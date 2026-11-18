"""第 3 步：流程定义和回放（设计书 7.4、7.5、8.1 到 8.3）。"""
import pathlib
import tempfile
import unittest

from kernel import flowdef
from kernel.replay import replay
from tests.helpers import REPO

FLOWS = flowdef.load_dir(REPO / 'flows')
T, F = FLOWS['ticket'], FLOWS['feature']


def ev(step, type, **kw):
    return {'step': step, 'type': type, **kw}


def run(*steps):
    """简写：('T1',) 表示开始并做完；('T5', 'failed') 表示开始并失败。"""
    out = []
    for s in steps:
        if isinstance(s, str):
            out += [ev(s, 'start'), ev(s, 'done')]
        else:
            sid, t, *rest = s
            kw = rest[0] if rest else {}
            out += ([ev(sid, 'start')] if t in ('done', 'failed') else []) + [ev(sid, t, **kw)]
    return out


class TestFlowFiles(unittest.TestCase):
    def test_load(self):
        self.assertEqual(T.order[:3], ['T1', 'T2', 'T3'])
        self.assertNotIn('T6', T.order)
        self.assertEqual(F.next_of('F9fix'), 'F7')
        self.assertEqual(T.next_of('T8'), 'HOLD')

    def test_bad_target_rejected(self):
        d = tempfile.mkdtemp()
        p = pathlib.Path(d) / 'x.toml'
        p.write_text('[flow]\nid="x"\nscope="x"\n[[step]]\nid="A"\nactor="script"\non_fail="Z"\n')
        with self.assertRaises(flowdef.FlowError):
            flowdef.load(p)
        p.write_text('[flow]\nid="x"\nscope="x"\n[[step]]\nid="A"\nactor="ai_headless"\n')
        with self.assertRaises(flowdef.FlowError):
            flowdef.load(p)


class TestTicketReplay(unittest.TestCase):
    def test_happy(self):
        self.assertEqual(replay(T, run('T1', 'T2', 'T3')).pos, 'T4')

    def test_fix_loop_then_diagnose_then_decide(self):
        evs = run('T1', 'T2', 'T3', 'T4', ('T5', 'failed'))
        self.assertEqual(replay(T, evs).pos, 'T6')
        evs += run('T6')
        self.assertEqual(replay(T, evs).pos, 'T4')           # 回头路
        for _ in range(2):
            evs += run('T4', ('T5', 'failed'), 'T6')
        p = replay(T, evs)
        self.assertEqual((p.attempts['T6'], p.fails['T5']), (3, 3))
        evs += run('T4', ('T5', 'failed'))
        self.assertEqual(replay(T, evs).pos, 'T7')           # T6 用完了
        evs += run('T7', 'T4', ('T5', 'failed'))
        self.assertEqual(replay(T, evs).pos, 'T8')           # T7 也不成
        evs += run('T8')
        self.assertEqual(replay(T, evs).status, 'held')      # 技术决策之后停下，等功能那一级处理

    def test_review_bounce_limit(self):
        evs = run('T1', 'T2', 'T3', 'T4', 'T5', ('T9', 'failed'))
        self.assertEqual(replay(T, evs).pos, 'T6')
        evs += run('T6', 'T4', 'T5', ('T9', 'failed'), 'T6', 'T4', 'T5', ('T9', 'failed'))
        self.assertEqual(replay(T, evs).pos, 'T8')           # 复查打回超过 2 轮

    def test_condition_skip(self):
        evs = run('T1', 'T2', 'T3', 'T4', 'T5', ('T9', 'skipped', {'reason': '没有风险标记'}))
        p = replay(T, evs)
        self.assertEqual((p.pos, p.skipped), ('T10', ['T9']))

    def test_conflict_goes_t14_then_t4(self):
        evs = run('T1', 'T2', 'T3', 'T4', 'T5', 'T9', ('T10', 'failed', {'route': 'T14', 'reason': '有冲突'}))
        self.assertEqual(replay(T, evs).pos, 'T14')
        evs += run('T14')
        self.assertEqual(replay(T, evs).pos, 'T4')           # v0.7 改的：回 T4，不是 T5

    def test_confirm_survives_until_reopen(self):
        base = run('T1', 'T2', 'T3', 'T4', 'T5', 'T9', 'T10', ('T11', 'confirm', {'commit': 'abc'}))
        self.assertEqual(replay(T, base).pos, 'T12')
        # T12 有冲突 → T14（验收之后，发重新打开）→ T4 … T10 → 又到 T11，要重新验收
        evs = base + run(('T12', 'failed', {'route': 'T14'}), 'T14') + [ev('T14', 'reopen', target='T11')] + \
            run('T4', 'T5', 'T9', 'T10')
        self.assertEqual(replay(T, evs).pos, 'T11')
        # 没有重新打开时，回头路再经过 T11 直接越过
        evs2 = base + run(('T12', 'failed', {'route': 'T6'}), 'T6', 'T4', 'T5', 'T9', 'T10')
        self.assertEqual(replay(T, evs2).pos, 'T12')

    def test_interrupted(self):
        evs = run('T1', 'T2') + [ev('T3', 'start')]
        p = replay(T, evs)
        self.assertEqual((p.status, p.pos), ('interrupted', 'T3'))

    def test_drop_unknown_and_cost(self):
        evs = run('T1') + [ev('T99', 'done'), ev('T2', 'start'), ev('T2', 'done', cost=0.5), ev(None, 'note', kind='额度'),
                           ev('T3', 'start'), ev('T3', 'failed', cost=1.25)]
        p = replay(T, evs)
        self.assertEqual((p.unknown, round(p.cost, 2), len(p.notes)), (1, 1.75, 1))
        self.assertEqual(replay(T, evs + [ev(None, 'drop')]).status, 'dropped')

    def test_done(self):
        p = replay(T, run('T1', 'T2', 'T3', 'T4', 'T5', 'T9', 'T10', ('T11', 'skipped'), 'T12', 'T13', 'T15'))
        self.assertEqual(p.status, 'done')


class TestFeatureReplay(unittest.TestCase):
    def test_plan_check_retry_limit(self):
        evs = run('F1', 'F2', ('F3', 'skipped'), ('F4', 'skipped'), ('F4a', 'skipped'), 'F5', 'F6', ('F7', 'failed'))
        self.assertEqual(replay(F, evs).pos, 'F7fix')
        evs += run('F7fix', ('F7', 'failed'), 'F7fix', ('F7', 'failed'))
        self.assertEqual(replay(F, evs).status, 'stopped')   # 最多 2 轮

    def test_accept_fail_goes_fix_ticket(self):
        evs = run('F1', 'F2', ('F3', 'skipped'), ('F4', 'skipped'), ('F4a', 'skipped'), 'F5', 'F6', 'F7', 'F8', 'F9',
                  ('F10', 'confirm'), 'F11', 'F12', ('F13', 'confirm'), 'F14', 'F15', 'F16', ('F17', 'failed'))
        self.assertEqual(replay(F, evs).pos, 'F14fix')
        evs += run('F14fix')
        self.assertEqual(replay(F, evs).pos, 'F14')

    def test_prototype_redo(self):
        evs = run('F1', 'F2', 'F3', ('F4', 'failed', {'reason': '按钮放左边'}))
        self.assertEqual(replay(F, evs).pos, 'F3')
        evs += run('F3', ('F4', 'confirm'))
        self.assertEqual(replay(F, evs).pos, 'F4a')

    def test_replan_after_decision(self):
        """T8 决定改规格的技术部分：F14 以「改去 F7」结束，重走 F7、F8、F9；验收卡变了才重新打开 F10（8.3）。"""
        head = run('F1', 'F2', ('F3', 'skipped'), ('F4', 'skipped'), ('F4a', 'skipped'), 'F5', 'F6', 'F7', 'F8', 'F9',
                   ('F10', 'confirm', {'commit': 'c1'}), 'F11', 'F12', ('F13', 'confirm'))
        evs = head + run(('F14', 'failed', {'route': 'F7', 'reason': '技术决策：改规格的技术部分'}))
        self.assertEqual(replay(F, evs).pos, 'F7')
        p = replay(F, evs + run('F7', 'F8', 'F9'))
        self.assertEqual(p.pos, 'F11')                   # 验收卡没变：F10 的确认仍然有效，直接越过
        evs2 = evs + [ev('F8', 'reopen', target='F10')] + run('F7', 'F8', 'F9')
        p2 = replay(F, evs2)
        self.assertEqual(p2.pos, 'F10')                  # 验收卡变了：要小白重新确认
        self.assertNotIn('F10', p2.confirms)
