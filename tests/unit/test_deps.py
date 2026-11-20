"""这台电脑上工作目录装没装过依赖（3-58）：kernel/steps.ensure_deps 的记号什么时候算数、什么时候重装、装不好怎么办。
受限环境本身不起（sandbox.run 换成记一笔的假的）；整条流程（换电脑后接着做）在 tests/sandbox/test_project_clone.py。"""
import json
import types
from unittest import mock

from kernel import steps
from kernel.state import Feature
from tests.helpers import TempHome


class FakeProject:
    def __init__(self, tmp, setup=('python3', '{profile}/setup.py')):
        self.root = tmp / 'Project' / 'demo'
        self.state = tmp / 'state' / 'demo'
        self.setup = list(setup) if setup else None
        (self.root / 'feat-a').mkdir(parents=True)

    def profile(self):
        cmds = {'setup': self.setup} if self.setup else {}
        return {'name': 'fake', 'dir': '/档案', 'commands': cmds, 'toolchain': {'ro': ['{profile}']}}

    def expand(self, s, prof):
        return s.replace('{profile}', prof['dir'])

    def deps_mark(self, wt):
        return self.state / 'deps' / f'{wt}.json'


class TestEnsureDeps(TempHome):
    def setUp(self):
        super().setUp()
        self.p = FakeProject(self.tmp)
        self.eng = types.SimpleNamespace(p=self.p, did=[], docker=lambda prof=None: None)
        self.f = Feature('a')
        self.calls = []
        self.rc = 0

    def fake_run(self, ctx, cmd, timeout=None):
        self.calls.append((ctx.kind, ctx.worktree, cmd))
        return types.SimpleNamespace(returncode=self.rc, stdout='', stderr='装不上：网络不通' if self.rc else '')

    def ensure(self, sid='F15', wt='feat-a'):
        with mock.patch.object(steps.sandbox, 'run', self.fake_run):
            return steps.ensure_deps(self.eng, self.f, self.f, sid, wt)

    def test_installs_once_in_restricted_side_then_mark_counts(self):
        self.assertIsNone(self.ensure())
        self.assertEqual(self.calls, [('restricted_script', 'feat-a', ['python3', '/档案/setup.py'])])
        mark = json.loads(self.p.deps_mark('feat-a').read_text())
        self.assertEqual((mark['worktree'], mark['profile'], mark['setup'], mark['step']),
                         ('feat-a', 'fake', ['python3', '{profile}/setup.py'], 'feature/a:F15'))
        self.assertFalse((self.p.root / 'feat-a' / 'deps').exists())        # 记号不在项目根下
        self.assertEqual(len(self.eng.did), 1)
        self.assertIsNone(self.ensure())                                     # 第二次：记号对得上，不再装
        self.assertEqual(len(self.calls), 1)

    def test_t1_installs_without_extra_line_in_report(self):
        self.assertIsNone(self.ensure('T1'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.eng.did, [])                                   # T1 自己就是「开目录、装依赖」，不另报

    def test_directory_recreated_or_setup_changed_reinstalls(self):
        self.ensure()
        d = self.p.root / 'feat-a'
        d.rename(self.p.root / 'old')
        d.mkdir()                                                            # 删了重建（另一个 inode）：记号不算数
        self.ensure()
        self.assertEqual(len(self.calls), 2)
        self.p.setup = ['python3', '{profile}/setup.py', '--frozen']         # 档案换了装法：重装
        self.ensure()
        self.assertEqual(len(self.calls), 3)
        self.p.deps_mark('feat-a').write_text('不是 JSON')                    # 记号坏了：重装
        self.ensure()
        self.assertEqual(len(self.calls), 4)

    def test_failure_holds_and_leaves_no_mark(self):
        self.rc = 1
        r = self.ensure()
        self.assertFalse(r.ok)
        self.assertTrue(r.hold)
        self.assertIn('装依赖失败', r.reason)
        self.assertIn('网络不通', r.reason)
        self.assertFalse(self.p.deps_mark('feat-a').exists())
        self.rc = 0
        self.assertIsNone(self.ensure())                                     # 下一次接着装
        self.assertEqual(len(self.calls), 2)

    def test_nothing_to_do_without_setup_or_directory(self):
        self.p.setup = None
        self.assertIsNone(self.ensure())
        self.assertIsNone(steps.ensure_deps(types.SimpleNamespace(p=types.SimpleNamespace(profile=lambda: None)), self.f, self.f, 'F15', 'feat-a'))
        self.p.setup = ['true']
        self.assertIsNone(self.ensure(wt='ticket-a-01'))                     # 目录不在：交给这一步自己去报
        self.assertEqual(self.calls, [])

    def test_only_steps_that_run_project_code(self):
        """门禁和工单上的实现要装；复查、规划、人的步骤不跑项目代码，不装（和给专用 Docker 通道的划法一致，6.3 四）。"""
        from kernel import flowdef
        from tests.helpers import REPO
        flows = flowdef.load_dir(REPO / 'flows')
        need = sorted(f'{s["id"]}' for fl in flows.values() for s in fl.steps.values() if s.get('kind') in steps.DEPS_KINDS)
        self.assertEqual(need, ['F15', 'T14', 'T3', 'T5', 'T6', 'T7'])
