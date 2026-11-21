"""3-59：自测的保险。

一、测试这一侧（tests/safehome.py）：整个测试进程的主目录是 /tmp 下公用的假主目录，AI、GitHub、Docker 一类的变量去掉了，
   PATH 里没有本机主目录下的目录；每个 TempHome 测试另有自己的临时主目录。
二、工具包这一侧（kernel/paths.guard_home）：会写主目录的入口，主目录是公用的假主目录（测试漏设了 HOME），
   或者是这个账号真的主目录、环境却像在自测里，都停下不做，一个字都不写。

「真的主目录」那几种情况一律换成 /tmp 下的一个「装作是真的」的目录（把 paths.account_home 换掉），不拿本机真的主目录试。"""
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from kernel import paths
from machine import aisetup, catalog, ghsetup, globalrules, install, setup, shellenv, wtsetup
from tests import safehome
from tests.helpers import REPO, TMP_ROOT, TempHome


@contextlib.contextmanager
def environ(**values):
    """临时改环境变量；值是 None 的去掉。"""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def tree(d):
    """目录下每一样的（相对路径, 大小, 修改时间）。"""
    d = pathlib.Path(d)
    return sorted((str(p.relative_to(d)), p.lstat().st_size, p.lstat().st_mtime_ns) for p in d.rglob('*'))


class TestTestProcess(unittest.TestCase):
    """测试进程本身：主目录、变量、PATH 都换过了。"""

    def test_home_is_shared_fake(self):
        home = pathlib.Path(os.environ['HOME'])
        self.assertEqual(home, safehome.SHARED_HOME)
        self.assertEqual(os.environ[paths.TEST_MARK], str(home))
        self.assertTrue(str(home).startswith(str(TMP_ROOT) + '/'))
        self.assertNotEqual(home.resolve(), paths.account_home().resolve())
        self.assertEqual(pathlib.Path.home(), home)
        for k in safehome.XDG:
            self.assertTrue(os.environ[k].startswith(str(home) + '/'), k)

    def test_no_secrets_or_real_tools(self):
        bad = [k for k in os.environ if k.startswith(('ANTHROPIC_', 'CLAUDE', 'OPENAI_', 'GH_', 'GITHUB_', 'DOCKER_', 'SSH_AUTH_SOCK'))]
        self.assertEqual(bad, [])
        for d in os.environ['PATH'].split(os.pathsep):
            real = os.path.realpath(d)
            under_home = real.startswith(str(safehome.REAL_HOME) + '/')
            self.assertFalse(under_home and not real.startswith(str(REPO) + '/'), d)
        for name in ('claude', 'codex', 'pi', 'opencode'):
            exe = shutil.which(name)
            self.assertFalse(exe and os.path.realpath(exe).startswith(str(safehome.REAL_HOME) + '/'), (name, exe))

    def test_child_process_inherits_fake_home(self):
        out = subprocess.run([sys.executable, '-c', 'import os, pathlib; print(pathlib.Path.home())'],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, str(safehome.SHARED_HOME))


class TestTempHomeDefault(TempHome):
    def test_each_test_has_own_home(self):
        self.assertEqual(pathlib.Path.home(), self.test_home)
        self.assertTrue(self.test_home.is_dir())
        self.assertEqual(os.environ['XDG_CONFIG_HOME'], str(self.test_home / '.config'))
        paths.guard_home('试一下')         # 自己的临时主目录：不挡


class TestSharedHomeRefused(unittest.TestCase):
    """测试没给自己设 HOME（用的是公用的假主目录）时，每个会写主目录的入口都停下，公用的假主目录一样都没变。
    这些测试故意不用 TempHome、不设 HOME：就是「漏设 HOME」的那种测试。"""

    def setUp(self):
        self.tmp = pathlib.Path(TMP_ROOT / f'shared-{os.getpid()}')
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._e = environ(SOP_HOME=self.tmp / 'sop-home', SOP_TOOLS_DIR=self.tmp / 'tools',
                          SOP_TOOLS_TOML=REPO / 'tests' / 'fakes' / 'machine' / 'tools.toml')
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.assertEqual(pathlib.Path.home(), safehome.SHARED_HOME)
        self.before = tree(safehome.SHARED_HOME)

    def assert_nothing_written(self):
        self.assertEqual(tree(safehome.SHARED_HOME), self.before)
        self.assertFalse((self.tmp / 'sop-home').exists())       # 连进度、锁都没写
        self.assertFalse((self.tmp / 'tools').exists())

    def assert_refused(self, fn, *args, **kw):
        with self.assertRaises(paths.HomeGuard) as e:
            fn(*args, **kw)
        self.assertIn('自测的保险', str(e.exception))
        self.assertIn('公用的假主目录', str(e.exception))
        self.assert_nothing_written()

    def test_setup(self):
        called = []
        self.assert_refused(setup.run, steps=(('M2', '安装工具', lambda ctx: called.append(1)),), say=lambda *a: None)
        self.assertEqual(called, [])

    def test_each_entry(self):
        self.assert_refused(install.install, ('uv',))
        self.assert_refused(install.install_tool, catalog.find('uv'), out=subprocess.DEVNULL)
        self.assert_refused(shellenv.install_block)
        self.assert_refused(ghsetup.setup, say=lambda *a: None)
        self.assert_refused(globalrules.install, out=lambda *a: None)
        self.assert_refused(aisetup.setup, ask=lambda *a: self.fail('不该问'), secret=lambda *a: self.fail('不该问'),
                            say=lambda *a: None)
        self.assert_refused(wtsetup.install, out=subprocess.DEVNULL)

    def test_explicit_file_is_callers_choice(self):
        """shellenv 给了别的文件（不是主目录里的 ~/.bashrc）就照写：那是调用的人自己定的。"""
        rc = self.tmp / 'rc'
        rc.write_text('')
        self.assertTrue(shellenv.install_block(rc=rc, tools_dir=self.tmp / 't'))

    def test_sop_machine_setup_subprocess(self):
        """3-12 出事的那个测试原样再来一次：用测试进程的整套环境（没设 HOME）执行 sop machine setup。被挡住，什么都没写。"""
        cwd = self.tmp / 'not-a-project'
        cwd.mkdir()
        p = subprocess.run([sys.executable, str(REPO / 'kernel' / 'main.py'), 'machine', 'setup'], cwd=cwd,
                           capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': ''}, timeout=120)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('自测的保险：sop machine setup', p.stdout)
        self.assertNotIn('【第 1 步', p.stdout)
        self.assertEqual(os.listdir(cwd), [])
        self.assert_nothing_written()


class TestRealHome(TempHome):
    """主目录是「这个账号真的主目录」时。真的主目录换成 /tmp 下装作是真的一个目录。"""

    def setUp(self):
        super().setUp()
        self.real = self.tmp / 'pretend-real-home'
        self.real.mkdir()
        p = mock.patch.object(paths, 'account_home', return_value=self.real)
        p.start()
        self.addCleanup(p.stop)
        # 平常用户自己执行时的样子：HOME 是真的，自测的变量一个都没有
        self._plain = environ(HOME=self.real, SOP_HOME=None, SOP_RUNTIME_DIR=None, SOP_TOOLS_DIR=None, SOP_PROJECTS_DIR=None,
                              SOP_TOOLS_TOML=None, SOP_UNDER_TEST=None, XDG_CONFIG_HOME=None)
        self._plain.__enter__()

    def tearDown(self):
        self._plain.__exit__(None, None, None)     # 先恢复，再让 TempHome 恢复它自己设的（cleanup 在 tearDown 之后才跑，顺序会反）
        super().tearDown()

    def refused(self, **env):
        with environ(**env):
            with self.assertRaises(paths.HomeGuard) as e:
                paths.guard_home('试一下')
        self.assertIn('真的主目录', str(e.exception))
        return str(e.exception)

    def test_plain_use_not_refused(self):
        paths.guard_home('试一下')
        with environ(SOP_HOME=self.real / 'tools' / 'sop', SOP_TOOLS_DIR=self.real / 'tools', SOP_PROJECTS_DIR='~/Project'):
            paths.guard_home('试一下')        # 写的就是默认的位置：照样是平常用
        with environ(HOME=str(self.real) + '/'):
            paths.guard_home('试一下')

    def test_test_signs_refused(self):
        self.assertIn('SOP_HOME', self.refused(SOP_HOME=self.tmp / 'sop-home'))      # 3-12 出事时就是这样
        self.assertIn('SOP_TOOLS_DIR', self.refused(SOP_TOOLS_DIR=self.tmp / 'tools'))
        self.assertIn('SOP_PROJECTS_DIR', self.refused(SOP_PROJECTS_DIR=self.tmp / 'Project'))
        self.assertIn('SOP_TOOLS_TOML', self.refused(SOP_TOOLS_TOML='/x/tools.toml'))
        self.assertIn('SOP_RUNTIME_DIR', self.refused(SOP_RUNTIME_DIR=self.tmp / 'run'))
        self.assertIn('SOP_UNDER_TEST', self.refused(SOP_UNDER_TEST=self.tmp / 'other'))

    def test_home_missing_refused(self):
        """HOME 没设时 Python 会退回去用账号真的主目录：一律挡。"""
        self.assertIn('HOME 没设', self.refused(HOME=None))
        self.assertIn('HOME 没设', self.refused(HOME=''))

    def test_symlink_to_real_home_refused(self):
        link = self.tmp / 'link-home'
        link.symlink_to(self.real)
        self.refused(HOME=link, SOP_HOME=self.tmp / 'sop-home')

    def test_entry_writes_nothing(self):
        """整条入口：主目录装作是真的、SOP_HOME 是临时的（3-12 出事时的样子），往 ~/.bashrc 写那一段被挡住，文件一个字没变。"""
        rc = self.real / '.bashrc'
        rc.write_text('# 用户原来的\n')
        before = tree(self.real)
        with environ(SOP_HOME=self.tmp / 'sop-home'):
            with self.assertRaises(paths.HomeGuard):
                shellenv.install_block()
            with self.assertRaises(paths.HomeGuard):
                globalrules.install(out=lambda *a: None)
        self.assertEqual(tree(self.real), before)
        self.assertEqual(rc.read_text(), '# 用户原来的\n')
        # 没有保险时会写（演给自己看：只在这个装作是真的 /tmp 目录里）
        with mock.patch.object(paths, 'guard_home'):
            with environ(SOP_HOME=self.tmp / 'sop-home'):
                self.assertTrue(shellenv.install_block(tools_dir=self.tmp / 'tools'))
        self.assertIn('SOP 工具包', rc.read_text())

    def test_other_home_not_refused(self):
        """测试自己的临时主目录：带着自测的变量也不挡（这是测试的正常样子）。"""
        own = self.tmp / 'own-home'
        own.mkdir()
        with environ(HOME=own, SOP_HOME=self.tmp / 'sop-home', SOP_UNDER_TEST=self.tmp / 'shared'):
            paths.guard_home('试一下')


if __name__ == '__main__':
    unittest.main()
