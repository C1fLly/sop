"""流程沙箱：中断恢复（设计书 7.12）和「sop 在推送前被强制结束」（8.2）。"""
import os

from tests.sandbox.base import F, FB, FS, SandboxCase

T1 = f'ticket/{F}/01'


def started(step, scope):
    def pred(w):
        return any(e.get('scope') == scope and e.get('step') == step and e['type'] == 'start' for e in w.events(f'feature/{F}'))
    return pred


class TestInterrupt(SandboxCase):
    kill_at = '25'
    def test_killed_during_ai_step(self):
        """AI 步骤做到一半 sop 被强制结束（断电）：下次 sop 列出没提交的改动、丢掉、从上一次提交重做这一步，最后做完。"""
        self.start([('01', [], '无')])
        w = self.w
        w.script[f'{T1}:T3:1'] = {'pre_files': {'src/半截.py': '写到一半'}, 'sleep': 600}
        w.save_scripts()
        w.sop('status')    # 先装好启动器
        hit, out = w.sop_until(lambda w: started('T3', T1)(w) and (w.root / 'ticket-jz-1-01' / 'src' / '半截.py').exists())
        self.assertTrue(hit, out[-2000:])
        r = self.go()
        self.assertIn('上次被打断', r.stdout)
        self.assertIn('半截.py', r.stdout)
        self.assertFeatureDone(r)
        s = self.steps(T1)
        self.assertEqual([t for st, t in s if st == 'T3'][:3], ['start', 'note', 'start'])
        self.assertEqual(self.main_file('src/半截.py'), '')

    def test_killed_before_push(self):
        """sop 在推送事件之前被强制结束：重来之后，回放和推上去的一致（没推上去的那一步还停在原地，重做）。"""
        self.start([('01', [], '无')])
        w = self.w
        for k in list(w.human):       # 对话和人的步骤被打断了要重来一次（对话不在远程，4.7），剧本多备一次回答
            w.human[k] = w.human[k] * 2
        w.save_scripts()
        w.sop('status')
        r1 = w.sop(env={'SOP_TEST_DIE_BEFORE_PUSH': self.kill_at})
        self.assertEqual(r1.returncode, 137, r1.stdout[-2000:])
        before = self.evs()
        last = before[-1]
        # 本机的回放只看推上去的事件：最后一条推上去的是什么，就接着从那里走
        st = self.w.sop('status')
        self.assertIn(f'功能 {F}', st.stdout)
        r = self.go()
        self.assertFeatureDone(r)
        after = self.evs()
        self.assertEqual(after[:len(before)], before)             # 推上去的事件一条没丢、没变
        # 被打断的那一步（有「开始」、没有结束就断了）重做了一次，而且做的事没有重复（例如没开出第二个 PR）
        starts = {}
        for e in after:
            if e['type'] == 'start':
                starts[(e['scope'], e['step'])] = starts.get((e['scope'], e['step']), 0) + 1
        twice = [k for k, n in starts.items() if n > 1]
        self.assertLessEqual(len(twice), 1, starts)   # 「开始」已经推上去的那一步重做一次；「开始」没推上去的，那一步本来就没开始过
        self.assertEqual(len(self.prs()), 2)          # 功能 PR 一个、工单 PR 一个


class TestKilledEarly(TestInterrupt):
    """在规划对话步骤中间被打断。"""
    kill_at = '12'
    test_killed_during_ai_step = None


class TestKilledAtTicketStart(TestInterrupt):
    """在工单开始之前被打断。"""
    kill_at = '40'
    test_killed_during_ai_step = None


class TestKilledLate(TestInterrupt):
    """在合并、清理那几步被打断。"""
    kill_at = '60'
    test_killed_during_ai_step = None
