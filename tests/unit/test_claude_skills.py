"""3-29：Claude Code 适配器的技能触发、流程引擎按配置选适配器、真实 AI 演练（drill）记下演练过的版本。
全用假的 claude（tests/fakes/claude/claude），在真的受限环境（bubblewrap）和模拟终端里跑，不花钱、不连网。
真实调用在 tests/real_ai/claude_engine.py，手动跑。"""
import json
import os
import unittest

from adapters import ai
from adapters.ai import base, ptyscreen
from adapters.ai.base import Outcome
from adapters.ai.claude import adapter as C
from adapters.ai.claude import drill
from kernel import cli, steps
from kernel.errors import SopError
from machine import config
from runner import sandbox
from tests.helpers import mock_env
from tests.unit.test_claude_adapter import Base

WT = 'ticket-a-1-01'


class SkillBase(Base):
    def add_skill(self, name='demo-skill', wt=WT):
        d = self.R / wt / '.claude' / 'skills' / name
        d.mkdir(parents=True)
        (d / 'SKILL.md').write_text(f'---\nname: {name}\ndisable-model-invocation: true\n---\n演练用的技能 {name}\n', encoding='utf-8')
        return d

    def skilled_pack(self, skill, body='读 README.md。结束时写一份 JSON 结果文件到 /sop/out/result.json。'):
        d = self.taskpack(body=body)
        f = d / 'task' / 'task.json'
        tj = json.loads(f.read_text())
        tj['skill'] = skill
        f.write_text(json.dumps(tj))
        return d


class TestSkillHeadless(SkillBase):
    def test_skill_prefix_and_loaded(self):
        """点名的技能：/<技能名> 在提示词最前面；会话日志里认出它加载了；结果文件照常写。"""
        self.creds('ok')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual(out.rc, 0, out.text)
        self.assertIs(out.skill_loaded, True)
        rec = [x for x in self.seen(st) if x.get('type') == 'assistant'][0]
        self.assertTrue(rec['prompt'].startswith('/demo-skill 下面是这一步的任务包'), rec['prompt'][:80])
        self.assertEqual(C.skill_loads(st, out.session), ['demo-skill'])
        self.assertTrue((d / 'out' / 'result.json').exists())

    def test_no_skill_no_prefix(self):
        self.creds('ok')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.taskpack()
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual(out.rc, 0)
        self.assertIsNone(out.skill_loaded)
        self.assertTrue(self.seen(st)[0]['prompt'].startswith('下面是这一步的任务包'))

    def test_missing_copy_not_called(self):
        """工作目录里没有这个技能的副本：不调用（会话日志都没有），说清楚。"""
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual(out.rc, 1)
        self.assertEqual(out.cost_basis, '没有调用')
        self.assertIs(out.skill_loaded, False)
        self.assertIn('.claude/skills/demo-skill/SKILL.md', out.text)
        self.assertEqual(self.seen(st), [])
        self.assertIn('没有副本', steps.skill_problem({'skill': 'demo-skill'}, out))

    def test_bad_skill_name_not_called(self):
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('../坏 名字')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual((out.rc, out.cost_basis), (1, '没有调用'))
        self.assertEqual(self.seen(st), [])

    def test_log_changed_counts_as_not_loaded(self):
        """反着试：AI 工具升级后会话日志里不再有「加载了技能」那一条：认成没加载，流程引擎停在这一步。"""
        self.creds('noskill')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual(out.rc, 0)
        self.assertIs(out.skill_loaded, False)
        self.assertIn('没有它加载过的记录', steps.skill_problem({'skill': 'demo-skill'}, out))

    def test_builtin_skill_dir_not_counted(self):
        """只认项目里的副本（…/.claude/skills/<名字>）：别处的同名技能不算。"""
        st = self.tmp / 'st'
        d = st / 'projects' / 'x'
        d.mkdir(parents=True)
        lines = [{'type': 'user', 'message': {'content': [{'type': 'text', 'text': f'{C.SKILL_LOADED_HEAD} /opt/claude/skills/code-review\n\n正文'}]}},
                 {'type': 'user', 'message': {'content': f'{C.SKILL_LOADED_HEAD} /p/w/.claude/skills/code-review/\n\n正文'}},
                 {'type': 'assistant', 'message': {'content': f'{C.SKILL_LOADED_HEAD} /p/w/.claude/skills/tdd'}}]
        (d / 's1.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
        self.assertEqual(C.skill_loads(st, 's1'), ['code-review'])

    def test_resume_counts_only_this_call(self):
        """续接：只看这一次新加载的；同一个会话里前面加载过不算这一次的。"""
        self.creds('ok')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertIs(out.skill_loaded, True)
        d2 = self.skilled_pack('demo-skill', body='接着做')
        out2 = a.resume(self.ctx(d2), d2 / 'task', st, out.session, '补充说明')
        self.assertIs(out2.skill_loaded, True)
        last = [x for x in self.seen(st) if x.get('type') == 'assistant'][-1]
        self.assertTrue(last['prompt'].startswith('/demo-skill 补充说明'))
        self.assertEqual(C.skill_loads(st, out.session), ['demo-skill', 'demo-skill'])
        # 续接时这一步没点名技能：不加写法、不判
        d3 = self.taskpack(body='再接着做')
        out3 = a.resume(self.ctx(d3), d3 / 'task', st, out.session, '再补充')
        self.assertIsNone(out3.skill_loaded)


class TestSkillProblem(unittest.TestCase):
    def test_cases(self):
        sk = {'skill': 'implement'}
        self.assertEqual(steps.skill_problem({}, Outcome(rc=0, skill_loaded=False)), '')
        self.assertEqual(steps.skill_problem(sk, Outcome(rc=0, skill_loaded=None)), '')     # 假 AI 认不出：不管
        self.assertEqual(steps.skill_problem(sk, Outcome(rc=0, skill_loaded=True)), '')
        self.assertEqual(steps.skill_problem(sk, Outcome(rc=1, skill_loaded=False)), '')    # 调用本身出错：按原来的路走
        self.assertEqual(steps.skill_problem(sk, Outcome(rc=0, timeout=True, skill_loaded=False)), '')
        self.assertIn('sop repair', steps.skill_problem(sk, Outcome(rc=0, skill_loaded=False)))
        self.assertIn('sop repair', steps.skill_problem(sk, Outcome(rc=1, text='没有副本', cost_basis='没有调用', skill_loaded=False)))


@unittest.skipUnless(sandbox.tiocsti_disabled(), '内核没禁用往终端塞按键，对话步骤不启动')
class TestSkillInteractive(SkillBase):
    def test_opening_has_skill(self):
        self.creds('ok')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill', body='请记住暗号「青石七三」，只回答：记好了')
        c = self.ctx(d, WT)
        c.interactive = True
        with ptyscreen.Pty(lambda: a.start_interactive(c, d / 'task', st)) as t:
            self.assertTrue(t.wait_for(ptyscreen.is_ready, 30), t.text[-800:])
            t.type_line('/exit')
            t.close(wait=15)
        out = t.result['value']
        self.assertEqual(out['rc'], 0)
        self.assertIs(out['skill_loaded'], True)
        rec = [x for x in self.seen(st) if x.get('type') == 'assistant'][0]
        self.assertTrue(rec['prompt'].startswith('/demo-skill 下面是这一步的任务包'))

    def test_not_in_terminal_is_not_a_skill_problem(self):
        """对话步骤不在终端里（没调用）：不算「技能没触发」。"""
        self.creds('ok')
        self.add_skill()
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.skilled_pack('demo-skill')
        c = self.ctx(d, WT)
        c.interactive = False
        out = a.start_interactive(c, d / 'task', st)
        self.assertEqual(out.rc, 1)
        self.assertIsNone(out.skill_loaded)
        self.assertEqual(steps.skill_problem({'skill': 'demo-skill'}, out), '')


class FakeProject:
    def __init__(self, sop):
        self.sop = sop

    def sop_json(self, fetch=True):
        if isinstance(self.sop, Exception):
            raise self.sop
        return self.sop


class TestChooseAdapter(unittest.TestCase):
    def test_order(self):
        old = os.environ.pop('SOP_AI', None)
        self.addCleanup(lambda: old is not None and os.environ.__setitem__('SOP_AI', old))
        if True:
            self.assertEqual(cli.adapter_name(), 'claude')                               # 默认：Claude Code（原来默认是假 AI）
            self.assertEqual(cli.adapter_name(FakeProject({'project': 'x'})), 'claude')
            self.assertEqual(cli.adapter_name(FakeProject(RuntimeError('主线还没有 sop.json'))), 'claude')
            self.assertEqual(cli.adapter_name(FakeProject({'ai': {'tool': 'claude'}})), 'claude')
            for bad in ('fake', 'codex'):
                with self.assertRaises(SopError):
                    cli.adapter_name(FakeProject({'ai': {'tool': bad}}))               # 假 AI 不能写进项目
            self.assertIsInstance(cli.adapter(FakeProject({})), C.ClaudeAdapter)
        with mock_env({'SOP_AI': 'fake'}):
            self.assertEqual(cli.adapter_name(FakeProject({'ai': {'tool': 'claude'}})), 'fake')   # 流程沙箱、自测
            self.assertEqual(cli.adapter().name, 'fake')
        with mock_env({'SOP_AI': 'nope'}):
            with self.assertRaises(SopError):
                cli.adapter_name()

    def test_registry(self):
        self.assertEqual(set(ai.ADAPTERS), {'claude', 'fake'})
        self.assertEqual(ai.load('claude').name, 'claude')
        self.assertEqual(ai.load('fake').reminder(), '')


class TestReminder(SkillBase):
    def test_reminder_until_drilled(self):
        a = self.adapter()
        self.assertIn('还没做过真实 AI 演练', a.reminder())
        base.mark_drilled('claude', '9.9.9')
        self.assertEqual(a.reminder(), '')
        base.mark_drilled('claude', '9.9.8')
        self.assertIn('版本变了', a.reminder())

    def test_no_claude_no_reminder(self):
        a = C.ClaudeAdapter(exe=None)
        a.location = lambda: ('', '')
        self.assertEqual(a.reminder(), '')


@unittest.skipUnless(sandbox.tiocsti_disabled(), '内核没禁用往终端塞按键，对话步骤不启动')
class TestDrill(SkillBase):
    def test_drill_passes_and_records(self):
        self.creds('ok')
        a = self.adapter()
        r = drill.run(adapter=a, say=lambda *_: None, wait=30)
        self.assertTrue(r.ok, (r.message, r.parts))
        self.assertEqual([p[0] for p in r.parts], ['交互：打开对话窗口直接是输入框', '交互：开场内容是任务包、点名的技能加载了',
                                                   '自动调用：点名的技能加载了、结果文件过检查', '反着试：没有副本的技能不调用'])
        self.assertEqual(len(r.calls), 3)                     # 反着试那一次没有调用
        self.assertEqual(config.tools()['claude']['drilled_version'], '9.9.9')
        self.assertEqual(a.reminder(), '')

    def test_drill_fails_not_recorded(self):
        """反着试：会话日志里认不出技能加载了，演练不通过，不记版本。"""
        self.creds('noskill')
        a = self.adapter()
        r = drill.run(adapter=a, say=lambda *_: None, wait=30)
        self.assertFalse(r.ok)
        self.assertIn('没加载', r.message)
        self.assertNotIn('drilled_version', config.tools().get('claude', {}))

    def test_drill_quota_stops(self):
        self.creds('quota')
        r = drill.run(adapter=self.adapter(), say=lambda *_: None, wait=30)
        self.assertFalse(r.ok)
        self.assertTrue(r.quota, r.message)
        self.assertIn('充值', r.message)


if __name__ == '__main__':
    unittest.main()
