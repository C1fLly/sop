"""3-22：M5 安装 wt（machine/install/wt.sh、machine/wtsetup.py）。
都装到 /tmp 的临时工具目录，主目录 HOME 也是临时的；不连网、不碰本机的 ~/tools/wt：
- 安装脚本用测试现做的假 wt 仓库（几个版本标签，主线上还有没发布的改动，另一条分支上有个不在主线上的标签）；
- 出口检查要真的 wt doctor：从本机 ~/tools/wt 只读地克隆一份（--no-local，不建硬链接；GIT_OPTIONAL_LOCKS=0）当来源，
  gh、ssh 换成假的（不碰真的 GitHub 和登录）。本机没有 ~/tools/wt 时这几项跳过。"""
import os
import pathlib
import subprocess
import unittest

from machine import catalog, install, wtsetup
from tests.helpers import REPO, TMP_ROOT, TempHome, mock_env, rmtree, sh

WT_SH = REPO / 'machine' / 'install' / 'wt.sh'
LOCAL_WT = pathlib.Path.home() / 'tools' / 'wt'
FAKE_WT = '#!/bin/bash\nWT_VERSION="{v}"\ncase $1 in --version) printf "wt %s\\n" "$WT_VERSION" ;; *) exit 3 ;; esac\n'
FAKE_GH = ('#!/bin/sh\necho "$*" >> "$FAKEGH_LOG"\n'
           'case "$1" in --version) echo "gh version 2.83.0 (2025-11-01)" ;; auth) exit "${FAKEGH_AUTH:-0}" ;; esac\n')
FAKE_SSH_OK = ('#!/bin/sh\necho "$*" >> "$FAKESSH_LOG"\n'
               'echo "Hi tester! You have successfully authenticated, but GitHub does not provide shell access." >&2\nexit 1\n')
FAKE_SSH_DENIED = '#!/bin/sh\necho "$*" >> "$FAKESSH_LOG"\necho "git@github.com: Permission denied (publickey)." >&2\nexit 255\n'


def script(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def files_under(d):
    return sorted(str(p.relative_to(d)) for p in pathlib.Path(d).rglob('*'))


class WtBase(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.tools = t / 'tools'
        self.user_home = t / 'home'
        for d in (self.user_home, t / 'bin', t / 'tmpdir'):
            d.mkdir()
        self.sshlog = t / 'ssh.log'
        self._env2 = mock_env({'HOME': str(self.user_home), 'SOP_TOOLS_DIR': str(self.tools), 'TMPDIR': str(t / 'tmpdir'),
                               'PATH': f'{t / "bin"}:{os.environ["PATH"]}', 'FAKESSH_LOG': str(self.sshlog),
                               'FAKEGH_LOG': str(t / 'gh.log')})
        self._env2.__enter__()

    def tearDown(self):
        self._env2.__exit__(None, None, None)
        super().tearDown()

    def run_install(self, repo, **extra):
        env = {**install.script_env(net={}), 'SOP_WT_REPO': str(repo), **extra}
        return install.install_tool(catalog.find('wt'), env=env, out=subprocess.DEVNULL)

    def run_script(self, repo, **extra):
        env = {**install.script_env(net={}), 'SOP_WT_REPO': str(repo), **extra}
        return subprocess.run(['bash', str(WT_SH)], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def git(self, *args):
        return sh('git', '-C', self.tools / 'wt', *args)

    def assert_no_leftovers(self):
        self.assertEqual([p.name for p in self.tools.glob('.wt.new*')], [])
        self.assertEqual(list((self.tmp / 'tmpdir').iterdir()), [])


class TestInstallScript(WtBase):
    """安装脚本：用假 wt 仓库。"""

    def setUp(self):
        super().setUp()
        # 假 wt 仓库（当 GitHub 上的那个）：主线 v1.2.0 → v1.3.0 → 还没发布的改动；v1.1.0 的 wt 自己说的版本对不上；
        # 另一条分支上有 v9.9.9（不在主线上，不该被当成最新）
        self.src = self.tmp / 'github' / 'wt.git'
        seed = self.tmp / 'seed'
        sh('git', 'init', '-q', '--bare', '-b', 'main', self.src)
        sh('git', 'init', '-q', '-b', 'main', seed)
        for v, tag in (('1.0.9', 'v1.1.0'), ('1.2.0', 'v1.2.0'), ('1.3.0', 'v1.3.0'), ('1.4.0-dev', None)):
            script(seed / 'wt', FAKE_WT.format(v=v))
            sh('git', '-C', seed, 'add', '-A'); sh('git', '-C', seed, 'commit', '-qm', f'wt {v}')
            if tag:
                sh('git', '-C', seed, 'tag', '-a', tag, '-m', f'wt {tag}')
        sh('git', '-C', seed, 'checkout', '-qb', 'side')
        script(seed / 'wt', FAKE_WT.format(v='9.9.9'))
        sh('git', '-C', seed, 'commit', '-qam', 'side'); sh('git', '-C', seed, 'tag', '-a', 'v9.9.9', '-m', 'side')
        sh('git', '-C', seed, 'push', '-q', '--tags', self.src, 'main', 'side')

    def test_installs_latest_release_on_main(self):
        r, msg = self.run_install(self.src)
        self.assertTrue(r.ok, msg)
        self.assertEqual(r.version, (1, 3, 0))
        self.assertIn('装好了', msg)
        self.assertEqual(self.git('describe', '--tags', '--exact-match'), 'v1.3.0')
        self.assertEqual(sh('git', '-C', self.tools / 'wt', 'symbolic-ref', '-q', 'HEAD', check=False), '')   # 分离在标签上
        self.assertEqual(self.git('remote', 'get-url', 'origin'), str(self.src))     # 以后升级从同一个地方取
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('tag', '--list'), 'v1.1.0\nv1.2.0\nv1.3.0\nv9.9.9')
        self.assertFalse((self.tools / 'wt' / '.git' / 'hooks').exists())          # 没有从哪个模板复制钩子
        self.assertEqual(sorted(p.name for p in self.tools.iterdir()), ['wt'])
        self.assertEqual(list(self.user_home.iterdir()), [])                       # 主目录什么都没写
        self.assert_no_leftovers()
        r, msg = self.run_install(self.src)                                        # 再跑一次：合格就跳过
        self.assertIn('跳过', msg)

    def test_pinned_version(self):
        p = self.run_script(self.src, SOP_WT_VERSION='1.2.0')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('wt 1.2.0 装好了', p.stdout)
        self.assertEqual(self.git('describe', '--tags', '--exact-match'), 'v1.2.0')
        r = catalog.run_check(catalog.find('wt'))
        self.assertTrue(r.installed); self.assertFalse(r.ok)                       # 清单要 >=1.3

    def test_pinned_too_old_reports_not_enough(self):
        r, msg = self.run_install(self.src, SOP_WT_VERSION='v1.2.0')
        self.assertFalse(r.ok); self.assertIn('不够', msg)

    def test_refusals_leave_nothing(self):
        cases = [({'SOP_WT_VERSION': '1.9.9'}, '没有 v1.9.9 这个版本'),
                 ({'SOP_WT_VERSION': '1.1.0'}, '自己说的版本对不上'),
                 ({'SOP_WT_VERSION': 'main'}, '版本号看不懂')]
        for extra, want in cases:
            with self.subTest(extra):
                p = self.run_script(self.src, **extra)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn(want, p.stderr)
                self.assertFalse((self.tools / 'wt').exists())
                self.assert_no_leftovers()
        p = self.run_script(self.tmp / 'nowhere.git')
        self.assertNotEqual(p.returncode, 0); self.assertIn('取不下 wt', p.stderr)
        self.assertFalse((self.tools / 'wt').exists()); self.assert_no_leftovers()
        # GitHub 那种地址：SSH 不让进（还没登录 GitHub、密钥不对）。不停下来问，说清要先做 M3
        script(self.tmp / 'bin' / 'ssh', FAKE_SSH_DENIED)
        p = self.run_script('git@github.com:C1fLly/wt.git')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('要先登录 GitHub（M3）', p.stderr)
        self.assertIn('BatchMode=yes', self.sshlog.read_text())
        self.assertFalse((self.tools / 'wt').exists()); self.assert_no_leftovers()

    def test_existing_copy_untouched(self):
        for make in (lambda d: (d.mkdir(), (d / 'wt').write_text('#!/bin/sh\necho mine 0.9\n'), (d / 'mine.txt').write_text('我的改动\n')),
                     lambda d: d.symlink_to(self.tmp / 'missing')):
            with self.subTest(make=make):
                dest = self.tools / 'wt'
                self.tools.mkdir(exist_ok=True)
                make(dest)
                before = files_under(self.tools) if not dest.is_symlink() else None
                r, msg = self.run_install(self.src)
                self.assertFalse(r.ok)
                p = self.run_script(self.src)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('已经有东西了', p.stderr)
                self.assertIn('mv ', p.stderr)
                if before is not None:
                    self.assertEqual(files_under(self.tools), before)
                    self.assertEqual((dest / 'mine.txt').read_text(), '我的改动\n')
                    rmtree(dest)
                else:
                    self.assertTrue(dest.is_symlink())
                    dest.unlink()
                self.assert_no_leftovers()

    def test_hooks_and_outside_git_settings_ignored(self):
        """主目录的 Git 设置里指了钩子目录、模板目录，环境里带着 GIT_DIR：一个钩子都不执行，装的还是对的。"""
        mark = self.tmp / 'hook-ran'
        hooks = self.tmp / 'evil-hooks'
        for name in ('post-checkout', 'reference-transaction', 'post-index-change'):
            script(hooks / name, f'#!/bin/sh\necho {name} >> {mark}\n')
        other = self.tmp / 'other.git'
        sh('git', 'init', '-q', '--bare', other)
        tpl = self.tmp / 'evil-template'
        script(tpl / 'hooks' / 'post-checkout', f'#!/bin/sh\necho template >> {mark}\n')
        sh('git', 'config', '-f', self.user_home / '.gitconfig', 'core.hooksPath', hooks)
        sh('git', 'config', '-f', self.user_home / '.gitconfig', 'init.templateDir', tpl)
        r, msg = self.run_install(self.src, GIT_DIR=str(other), GIT_WORK_TREE=str(self.tmp))
        self.assertTrue(r.ok, msg)
        self.assertFalse(mark.exists(), mark.read_text() if mark.exists() else "")
        self.assertFalse((self.tools / 'wt' / '.git' / 'hooks').exists())
        self.assertEqual(self.git('describe', '--tags', '--exact-match'), 'v1.3.0')
        self.assertEqual(sh('git', '--git-dir', other, 'for-each-ref'), '')

    def test_listed_in_catalog(self):
        t = catalog.find('wt')
        self.assertEqual(t.install_kind(), ('script', WT_SH))
        self.assertEqual((t.step, t.admin, t.location), ('M5', False, '~/tools/wt'))
        self.assertEqual(subprocess.run(['bash', '-n', str(WT_SH)]).returncode, 0)
        text = WT_SH.read_text()
        for word in ('.bashrc', '.profile', '.local/bin', 'doctor --fix', 'config --global'):
            self.assertNotIn(word, text.replace('wt doctor --fix（', '').replace('wt install（往 ~/.local/bin', ''))
        p = subprocess.run(['bash', str(WT_SH)], capture_output=True, text=True, env={'PATH': os.environ['PATH'], 'HOME': str(self.tmp)})
        self.assertNotEqual(p.returncode, 0); self.assertIn('没给工具目录', p.stderr)


@unittest.skipUnless((LOCAL_WT / 'wt').is_file() and (LOCAL_WT / '.git').is_dir(), '本机没有 ~/tools/wt')
class TestExitCheck(WtBase):
    """出口检查：真的 wt（从本机 ~/tools/wt 只读地克隆一份来装），假 gh、假 ssh。"""

    @classmethod
    def setUpClass(cls):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.src_dir = pathlib.Path(subprocess.run(['mktemp', '-d', f'{TMP_ROOT}/wtsrc-XXXXXX'], capture_output=True, text=True,
                                                  check=True).stdout.strip())
        cls.src = cls.src_dir / 'wt.git'
        env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}
        subprocess.run(['git', 'clone', '-q', '--bare', '--no-local', str(LOCAL_WT), str(cls.src)], env=env, check=True,
                       capture_output=True)
        # 当成 GitHub 上那个：默认分支是 main（本机那份的 HEAD 分离在标签上，裸克隆照搬了它）
        subprocess.run(['git', '--git-dir', str(cls.src), 'symbolic-ref', 'HEAD', 'refs/heads/main'], check=True)

    @classmethod
    def tearDownClass(cls):
        rmtree(cls.src_dir)

    def setUp(self):
        super().setUp()
        script(self.tmp / 'bin' / 'ssh', FAKE_SSH_OK)
        r, msg = self.run_install(self.src)
        self.assertTrue(r.ok, msg)
        script(self.tools / 'gh' / 'bin' / 'gh', FAKE_GH)       # 规定位置的 gh（假的）

    def identity(self):
        sh('git', 'config', '-f', self.user_home / '.gitconfig', 'user.name', 'tester')
        sh('git', 'config', '-f', self.user_home / '.gitconfig', 'user.email', 'tester@example.invalid')

    def test_installed_release_version(self):
        want = sh('git', '--git-dir', self.src, 'describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*', 'main')
        self.assertEqual(self.git('describe', '--tags', '--exact-match'), want)
        r = catalog.run_check(catalog.find('wt'))
        self.assertTrue(r.ok, r.output)
        self.assertEqual('v' + r.version_text, want)

    def test_passes_with_identity_and_login(self):
        self.identity()
        before = files_under(self.user_home)
        with mock_env({'WT_TEMPLATE': str(self.tools / 'wt' / 'template'), 'WT_CD_FILE': str(self.tmp / 'cd'),
                       'GIT_DIR': str(self.tmp / 'nowhere')}):
            res = wtsetup.check()
        self.assertTrue(res.ok, res.output)
        self.assertEqual(res.failures, [])
        self.assertIn('── 环境', res.output)
        self.assertNotIn('── 项目', res.output)
        self.assertIn(f'.shared 模板：{wtsetup.wtx.TEMPLATE}', res.output)      # 用的是工具包的模板，不是外面带进来的
        self.assertIn('gh 已登录', res.output)
        self.assertTrue(any('全局配置缺少' in w for w in res.warnings))          # 只提醒；不加 --fix，不改全局配置
        self.assertEqual(files_under(self.user_home), before)
        self.assertFalse((self.tmp / 'cd').exists())
        self.assertIn('auth status', (self.tmp / 'gh.log').read_text())
        self.assertIn('通过', wtsetup.report(res)[0])
        self.assert_no_leftovers()                                                # wt 的临时文件、检查用的空目录都删了

    def test_fails_without_identity(self):
        res = wtsetup.check()
        self.assertFalse(res.ok)
        self.assertEqual(len(res.failures), 1)
        self.assertIn('提交身份', res.failures[0])
        self.assertIn('不通过', wtsetup.report(res)[0])
        self.assertEqual(list(self.user_home.iterdir()), [])

    def test_fails_when_gh_not_logged_in(self):
        self.identity()
        with mock_env({'FAKEGH_AUTH': '1'}):
            res = wtsetup.check()
        self.assertFalse(res.ok)
        self.assertTrue(any('gh 未登录' in f for f in res.failures), res.failures)

    def test_ssh_denied_is_only_a_warning(self):
        """wt doctor 把 SSH 连不上算「提醒」；M3 的出口检查才管 SSH。"""
        self.identity()
        script(self.tmp / 'bin' / 'ssh', FAKE_SSH_DENIED)
        res = wtsetup.check()
        self.assertTrue(res.ok, res.output)
        self.assertTrue(any('SSH 无法访问' in w for w in res.warnings))

    def test_not_installed_or_too_old(self):
        rmtree(self.tools / 'wt')
        res = wtsetup.check()
        self.assertFalse(res.ok); self.assertIn('还没有能运行的 wt', res.failures[0])
        script(self.tools / 'wt' / 'wt', FAKE_WT.format(v='1.2.3'))
        res = wtsetup.check()
        self.assertFalse(res.ok); self.assertIn('不够', res.failures[0])

    def test_runs_outside_any_project(self):
        """当前目录在一个 wt 项目里也只查环境。"""
        self.identity()
        proj = self.tmp / 'Project' / 'demo'
        proj.mkdir(parents=True)
        sh('git', 'init', '-q', '--bare', proj / '.git')
        old = os.getcwd()
        os.chdir(proj)
        try:
            res = wtsetup.check()
        finally:
            os.chdir(old)
        self.assertTrue(res.ok, res.output)
        self.assertNotIn('── 项目', res.output)


class TestParse(unittest.TestCase):
    def test_parse(self):
        out = ('wt: ── 环境\nwt: ✔ bash 5.3\nwt: ✖ 没设置提交身份（手册 A2）\nwt: ⚠ 没加载包装函数：x\n\n'
               'wt: ✖ 1 项失败，1 项提醒')
        self.assertEqual(wtsetup.parse(out), (['没设置提交身份（手册 A2）'], ['没加载包装函数：x']))


if __name__ == '__main__':
    unittest.main()
