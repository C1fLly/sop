"""流程沙箱：归属名不重复（6.4，v0.9）；同一个项目开两个 sop（8.4）；另一台电脑上开始、没结束的步骤先问（8.4）。"""
import json
import subprocess

from kernel import journal as J
from tests.sandbox.base import F, FB, FS, SandboxCase


class TestNames(SandboxCase):
    def test_feature_name_never_reused(self):
        self.start([('01', [], '无')])
        r = self.go()
        self.assertFeatureDone(r)
        # 同名的功能再开一次：自动用下一个序号，jz-1 从此不再用
        r = self.w.sop('feature', 'new', 'jz')
        self.assertIn('jz-2', r.stdout)
        # 直接登记一个用过的归属名（规划、规范变更、升级、紧急修复都走这一条）：被拒
        for name in ('feat/jz-1', 'feat/jz-2'):
            p = subprocess.run(['python3', '-c', 'import sys; from kernel import journal as J\n'
                                'try:\n    J.Journal(sys.argv[1]).append(J.register_name(sys.argv[2])); print("成功")\n'
                                'except J.NameTaken as e: print("被拒")', str(self.w.root / '.git'), name],
                               capture_output=True, text=True, env={**self.w.env(), 'PYTHONPATH': str(self.w.home / 'versions' / self.w.version)})
            self.assertEqual(p.stdout.strip(), '被拒', p.stderr)

    def test_upgrade_branch_name_never_reused(self):
        v2 = self.w.publish_toolkit('修补版 a')
        self.assertEqual(self.w.sop('self', 'upgrade', v2).returncode, 0)
        v3 = self.w.publish_toolkit('修补版 b')
        self.assertEqual(self.w.sop('self', 'upgrade', v3).returncode, 0)
        names = self.w.rgit('ls-tree', '--name-only', 'sop/journal', 'names/').splitlines()
        self.assertIn(f'names/upgrade__{v2[:8]}-1.json', names)
        self.assertIn(f'names/upgrade__{v3[:8]}-1.json', names)
        self.assertEqual(len(set(names)), len(names))


class TestTwoSop(SandboxCase):
    def test_second_sop_can_only_look(self):
        self.start([('01', [], '无')])
        self.w.script[f'ticket/{F}/01:T3'] = {'files': {'src/t01.py': '1'}, 'commit': 'feat: 01', 'sleep': 8}
        self.w.save_scripts()
        self.w.sop('status')
        import subprocess as sp
        p = sp.Popen([str(self.w.home / 'sop')], cwd=self.w.root, env=self.w.env(), stdout=sp.PIPE, stderr=sp.STDOUT, text=True)
        import time
        for _ in range(100):
            if any(e.get('step') == 'T3' and e['type'] == 'start' for e in self.evs()):
                break
            time.sleep(0.3)
        r2 = self.w.sop()
        self.assertEqual(r2.returncode, 3)
        self.assertIn('只能看', r2.stdout)
        st = self.w.sop('status')
        self.assertEqual(st.returncode, 0)
        self.assertIn('T3', st.stdout)
        p.communicate(timeout=300)


class TestOtherMachine(SandboxCase):
    def test_ask_before_redoing(self):
        """日志里有另一台电脑上「开始」、没结束的步骤：先问小白那台电脑是不是还在跑。"""
        self.start([('01', [], '无')])
        self.w.save_scripts()
        self.w.sop('status')
        r = subprocess.run(['python3', '-c', 'import sys; from kernel import journal as J\n'
                            'j = J.Journal(sys.argv[1]); j.host = "另一台电脑"\n'
                            'j.append(J.event("feature/jz-1", "F1", "start", attempt=1))', str(self.w.root / '.git')],
                           capture_output=True, text=True, env={**self.w.env(), 'PYTHONPATH': str(self.w.home / 'versions' / self.w.version)})
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.go(ok=False)
        self.assertIn('另一台电脑', r.stdout)
        self.assertIn('还在跑', r.stdout)
        self.assertEqual(self.steps(FS), [('F1', 'start')])
        self.w.sop(env={'SOP_SAME_MACHINE': '1'})
        self.assertIn(('F1', 'done'), self.steps(FS))
