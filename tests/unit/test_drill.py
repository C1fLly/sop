"""3-47：破坏演练脚本 tests/drill.py 自己（设计书 16.3）。

- 怎么判：用假的小场景（几行代码的「检查」和「破坏」）核对拦住了 / 没拦住 / 演不下去三种结果、退出码、每一项都先还原；
- 安全：现场不在 /tmp、当前目录或主目录不在现场里、和本机真的主目录沾边，一律拒绝；写文件之前核对目标在现场里；
- 拷副本：只读开发目录（Git 记着的文件，含没提交的改动），不写它的索引；
- 真演一份快的（自测里只放这一份）：在 /tmp 的副本里把「特权侧用之前核对」比 wt 钩子那一条去掉，
  只演 wt-hook 和 git-hook 两项：wt-hook 必须变成「没拦住」、git-hook 照样拦住、退出码 1，演完 /tmp 里不留现场。
  和 sop self check（3-44）一样在副本目录里执行 python3 tests/drill.py。整套演练和反着试是手动的：tests/drill.py、tests/drill_reverse.py。
"""
import glob
import os
import pathlib
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest

from kernel import selfcheck
from tests.helpers import REPO, TempHome, sh

sys.path.insert(0, str(REPO / 'tests'))
import drill  # noqa: E402


class Fake:
    """一个假场景：state 是「被检查的东西」，check 看它，brk 改坏它，restore 改回去。"""

    def __init__(self, blocks=True, base_ok=True, reason='坏了：x', restore_ok=True, brk_error=False, check_raises=False):
        self.state, self.calls = 'good', []
        self.blocks, self.base_ok, self.reason = blocks, base_ok, reason
        self.restore_ok, self.brk_error, self.check_raises = restore_ok, brk_error, check_raises

    def check(self, ctx):
        self.calls.append(('check', self.state))
        if self.state == 'good':
            return self.base_ok, '' if self.base_ok else '本来就坏：y'
        if self.check_raises:
            raise RuntimeError('检查崩了')
        return (False, f'一些输出\n{self.reason}\n') if self.blocks else (True, '都好')

    def brk(self, ctx):
        self.calls.append('brk')
        if self.brk_error:
            raise drill.DrillError('找不到要改的地方')
        self.state = 'bad'

    def restore(self, ctx):
        self.calls.append('restore')
        if self.restore_ok:
            self.state = 'good'

    def item(self, name='fake'):
        return drill.Item(name, '把 x 改坏', '假检查', self.check, self.brk, self.restore, ['坏了', 'x'])


class Ctx:
    state = {}


def run(f):
    out = []
    res, why = drill.run_item(f.item(), Ctx(), out.append)
    return res, why, out


class TestJudge(unittest.TestCase):
    def test_blocked(self):
        f = Fake()
        res, why, out = run(f)
        self.assertEqual(res, drill.BLOCKED)
        self.assertEqual(f.calls, [('check', 'good'), 'brk', ('check', 'bad'), 'restore', ('check', 'good')])
        self.assertTrue(any(x.startswith('  破坏之后：检查失败（假检查拦住了）：坏了：x') for x in out), out)
        self.assertIn('  还原之后：假检查又通过了', out)

    def test_not_blocked(self):
        f = Fake(blocks=False)
        res, why, out = run(f)
        self.assertEqual(res, drill.NOT_BLOCKED)
        self.assertIn('restore', f.calls)
        self.assertTrue(any('没拦住' in x for x in out))

    def test_base_fails(self):
        f = Fake(base_ok=False)
        res, why, _ = run(f)
        self.assertEqual(res, drill.BROKEN)
        self.assertIn('没破坏时', why)
        self.assertNotIn('brk', f.calls)              # 没破坏时就没过：不破坏

    def test_fails_for_another_reason(self):
        res, why, _ = run(Fake(reason='别的毛病'))
        self.assertEqual(res, drill.BROKEN)
        self.assertIn('不是这次破坏', why)

    def test_markers_must_be_on_one_line(self):
        res, _, _ = run(Fake(reason='坏了\nx'))          # 两个标记分在两行：不算
        self.assertEqual(res, drill.BROKEN)

    def test_check_crash_is_not_blocked(self):
        res, why, _ = run(Fake(check_raises=True))
        self.assertEqual(res, drill.BROKEN)
        self.assertIn('检查自己出错', why)

    def test_restore_not_back(self):
        f = Fake(restore_ok=False)
        res, why, _ = run(f)
        self.assertEqual(res, drill.BROKEN)
        self.assertIn('还原之后', why)

    def test_break_error_still_restores(self):
        f = Fake(brk_error=True)
        res, why, _ = run(f)
        self.assertEqual(res, drill.BROKEN)
        self.assertIn('找不到要改的地方', why)
        self.assertIn('restore', f.calls)

    def test_summary_exit_code(self):
        quiet = [].append
        ok = drill.run_items([Fake().item('a'), Fake().item('b')], Ctx(), quiet)
        self.assertEqual(drill.summary(ok, quiet), 0)
        for bad in (Fake(blocks=False), Fake(base_ok=False), Fake(reason='别的')):
            with self.subTest(bad=bad.__dict__):
                rs = drill.run_items([Fake().item('a'), bad.item('b')], Ctx(), quiet)
                out = []
                self.assertEqual(drill.summary(rs, out.append), 1)
                self.assertTrue(any(x.startswith('破坏演练没过') and 'b ' in x for x in out), out)
        self.assertEqual(drill.summary([], quiet), 1)   # 一项都没演不算过

    def test_items_listed(self):
        its = drill.items()
        names = [it.name for it in its]
        self.assertEqual(len(names), len(set(names)))
        for need in ('test-expect', 'guard-rules', 'wt-hook'):   # 任务清单点名的三样
            self.assertIn(need, names)
        for it in its:
            self.assertTrue(it.marker and all(it.marker), it.name)
        p = subprocess.run([sys.executable, str(REPO / 'tests' / 'drill.py'), '--only', 'nope'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_selfcheck_finds_it(self):
        self.assertEqual(selfcheck.DRILL, 'tests/drill.py')
        self.assertTrue((REPO / selfcheck.DRILL).is_file())


class TestSafety(TempHome):
    def setUp(self):
        super().setUp()
        self.work = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-t-', dir='/tmp'))
        (self.work / 'home').mkdir()
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_ok(self):
        drill.assert_safe(self.work, cwd=self.work, home=self.work / 'home')

    def test_refuses(self):
        acct = pwd.getpwuid(os.getuid()).pw_dir
        cases = {
            '当前目录在开发目录': dict(cwd=REPO, home=self.work / 'home'),
            '主目录是真的': dict(cwd=self.work, home=acct),
            '主目录没设': dict(cwd=self.work, home=''),
            '主目录在现场外的 /tmp': dict(cwd=self.work, home=self.tmp),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                with self.assertRaises(drill.Refuse):
                    drill.assert_safe(self.work, **kw)
        with self.assertRaises(drill.Refuse):            # 现场本身不在 /tmp
            drill.assert_safe(REPO, cwd=REPO, home=REPO)
        with self.assertRaises(drill.Refuse):            # 现场就是 /tmp
            drill.assert_safe('/tmp', cwd='/tmp', home='/tmp')

    def test_inside(self):
        drill.inside(self.work, self.work / 'a' / 'b')
        for p in (REPO / 'README.md', self.work, self.work / '..' / 'x', '/tmp/x'):
            with self.subTest(p=str(p)):
                with self.assertRaises(drill.Refuse):
                    drill.inside(self.work, p)
        os.symlink(REPO, self.work / 'link')               # 经链接指到外面也不行
        with self.assertRaises(drill.Refuse):
            drill.inside(self.work, self.work / 'link' / 'README.md')

    def test_inner_refuses_outside_tmp_copy(self):
        p = subprocess.run([sys.executable, 'tests/drill.py', '--inner', str(self.work)], cwd=REPO, capture_output=True, text=True,
                           env={**os.environ, 'HOME': str(self.work / 'home')})
        self.assertEqual(p.returncode, 2)
        self.assertIn('拒绝执行', p.stdout)


class TestCopy(TempHome):
    def test_copy_reads_only(self):
        src = self.tmp / 'src'
        src.mkdir()
        sh('git', 'init', '-q', '-b', 'main', cwd=src)
        (src / '.gitignore').write_text('ign/\n')
        for f, t in (('a.txt', '一'), ('gone.txt', '删'), ('sub/b.txt', '二')):
            (src / f).parent.mkdir(exist_ok=True)
            (src / f).write_text(t)
        sh('git', 'add', '-A', cwd=src); sh('git', 'commit', '-qm', '起点', cwd=src)
        (src / 'a.txt').write_text('一（没提交的改动）')
        (src / 'gone.txt').unlink()
        (src / 'new.txt').write_text('新')
        (src / 'ign').mkdir(); (src / 'ign' / 'x').write_text('忽略')
        index = (src / '.git' / 'index').read_bytes()
        work = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-t-', dir='/tmp'))
        self.addCleanup(shutil.rmtree, work, True)
        (work / 'gitconfig').write_text(drill.GIT_ID)
        start, n = drill.copy_source(work, src, work / 'toolkit')
        dest = work / 'toolkit'
        self.assertEqual((dest / 'a.txt').read_text(), '一（没提交的改动）')
        self.assertEqual((dest / 'new.txt').read_text(), '新')
        self.assertTrue((dest / 'sub' / 'b.txt').is_file())
        self.assertFalse((dest / 'gone.txt').exists())
        self.assertFalse((dest / 'ign').exists())
        self.assertEqual(n, 4)
        self.assertEqual(drill.git(work, 'rev-parse', 'HEAD', cwd=dest), start)
        self.assertEqual(drill.git(work, 'status', '--porcelain', cwd=dest), '')
        self.assertEqual((src / '.git' / 'index').read_bytes(), index)      # 开发目录的索引一个字节没变
        with self.assertRaises(drill.Refuse):
            drill.copy_source(work, src, self.tmp / 'outside')


@unittest.skipUnless(shutil.which('wt'), '这台电脑上没有 wt')
class TestRealOne(TempHome):
    def test_weakened_precheck_is_caught(self):
        """把比 wt 钩子那一条去掉：wt-hook 没拦住、git-hook 照样拦住、退出码 1；/tmp 里不留现场；副本没被动。"""
        work = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-t-', dir='/tmp'))
        self.addCleanup(drill.rmtree, work)
        (work / 'gitconfig').write_text(drill.GIT_ID)
        src = work / 'src'
        drill.copy_source(work, REPO, src)
        f = src / 'checks' / 'precheck' / 'check.py'
        text = f.read_text(encoding='utf-8')
        old = '        elif sha(mine) != sha(want):'
        self.assertEqual(text.count(old), 1)
        f.write_text(text.replace(old, '        elif False:'), encoding='utf-8')
        drill.git(work, 'commit', '-qam', '改弱', cwd=src)
        before = set(glob.glob('/tmp/sop-drill-*'))
        p = subprocess.run([sys.executable, 'tests/drill.py', '--only', 'wt-hook,git-hook'], cwd=src, capture_output=True,
                           text=True, timeout=600)
        out = p.stdout + p.stderr
        self.assertEqual(p.returncode, 1, out)
        self.assertIn('没拦住  wt-hook：', out)
        self.assertIn('检查失败（拦住了）  git-hook：', out)
        self.assertIn('破坏之后：检查失败（特权侧用之前核对拦住了）：项目里有特权侧要用的文件被改过，不执行：.git/hooks/post-checkout', out)
        self.assertEqual(set(glob.glob('/tmp/sop-drill-*')) - before, set())
        self.assertEqual(drill.git(work, 'status', '--porcelain', cwd=src), '')


if __name__ == '__main__':
    unittest.main()
