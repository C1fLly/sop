"""3-21：wt 接入层（kernel/wtx.py）。用本机的 wt（只用不改）在 /tmp 的本地假远程上测：
建项目、建目录、删目录、登记基准正常能用；准备脚本、.git/config、Git 钩子被改过时拒绝执行，wt 一条命令都不跑。
主目录、TMPDIR 都指到临时目录里，gh 换成一个只记账、什么都不做的假的（不碰真的 GitHub 和登录）。"""
import os
import pathlib
import shutil
import unittest

from kernel import paths, precheck, wtx
from kernel.errors import SopError, Tampered
from tests.helpers import REPO, TempHome, mock_env, sh

WT = shutil.which('wt')
FAKE_GH = '#!/bin/sh\necho "$*" >> "$FAKEGH_LOG"\nexit 0\n'


@unittest.skipUnless(WT, '本机没有 wt')
class TestWtLayer(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.user_home = t / 'home'
        for d in (self.user_home, t / 'tmpdir', t / 'bin'):
            d.mkdir()
        (t / 'bin' / 'gh').write_text(FAKE_GH)
        (t / 'bin' / 'gh').chmod(0o755)
        self.ghlog = t / 'gh.log'
        # 外面带进来的 WT_ 变量（指向 wt 自带的模板、往文件里写目录）应当被接入层去掉
        self._env2 = mock_env({'HOME': str(self.user_home), 'TMPDIR': str(t / 'tmpdir'), 'PATH': f'{t / "bin"}:{os.environ["PATH"]}',
                               'FAKEGH_LOG': str(self.ghlog), 'SOP_TOOLS_DIR': str(t / 'tools'),
                               'WT_TEMPLATE': str(pathlib.Path(WT).resolve().parent / 'template'), 'WT_CD_FILE': str(t / 'cd-file')})
        self._env2.__enter__()
        # 假远程：main 上一个提交；另有功能分支 feat/f 和它下面一张还没开 PR 的工单分支 ticket/f-1
        self.remote = t / 'github' / 'demo.git'
        seed = t / 'seed'
        sh('git', 'init', '-q', '--bare', '-b', 'main', self.remote)
        sh('git', 'init', '-q', '-b', 'main', seed)
        (seed / 'README.md').write_text('# demo\n')
        sh('git', '-C', seed, 'add', '-A'); sh('git', '-C', seed, 'commit', '-qm', 'chore: init')
        sh('git', '-C', seed, 'push', '-q', self.remote, 'HEAD:main', 'HEAD:feat/f')
        (seed / 'a.txt').write_text('工单\n')
        sh('git', '-C', seed, 'add', '-A'); sh('git', '-C', seed, 'commit', '-qm', 'feat: 工单')
        sh('git', '-C', seed, 'push', '-q', self.remote, 'HEAD:ticket/f-1')
        self.root = t / 'Project' / 'demo'

    def tearDown(self):
        self._env2.__exit__(None, None, None)
        super().tearDown()

    def make(self, **kw):
        wtx.init('demo', self.root, 'tester/demo', self.remote, **kw)

    def cfg(self, key):
        return sh('git', '--git-dir', self.root / '.git', 'config', '--get', key, check=False)

    # ---------- 正常能用 ----------
    def test_init_uses_toolkit_template(self):
        self.make()
        self.assertTrue((self.root / '.git' / 'HEAD').is_file())
        self.assertEqual(wtx.worktrees(self.root), ['main'])
        for f in ('README.md', 'hooks/post-create', 'hooks/pre-remove', 'hooks/ignore-ok'):   # 是工具包的模板，不是 wt 自带的
            self.assertEqual((self.root / '.shared' / f).read_bytes(), (REPO / 'templates' / 'wt' / f).read_bytes(), f)
        self.assertEqual(sorted(os.listdir(self.root / '.shared')), ['README.md', 'hooks'])
        self.assertIsNotNone(precheck.recorded('demo'))                 # 建完就记下了 .git/config 的指纹
        precheck.verify('demo', self.root, ['main'])
        self.assertFalse((self.tmp / 'cd-file').exists())               # 外面带进来的 WT_CD_FILE 没有用上
        self.assertEqual(os.listdir(self.user_home), [])                # 没往主目录写东西
        self.assertEqual(os.listdir(self.tmp / 'tmpdir'), [])           # wt 的临时文件也收拾了

    def test_init_refuses_non_empty(self):
        self.root.mkdir(parents=True)
        (self.root / 'x').write_text('')
        with self.assertRaises(SopError):
            self.make()

    def test_new_remove_and_registry(self):
        self.make()
        wtx.new('demo', self.root, 'feat/g', 'origin/main')
        d = self.root / 'feat-g'
        self.assertTrue((d / '.git').is_file())
        self.assertEqual(wtx.base(self.root, 'feat/g'), 'origin/main')   # wt 把起点记成了基准
        precheck.verify('demo', self.root, wtx.worktrees(self.root))      # 指纹跟着 wt 的改动重记了
        (self.root / '.shared' / '.env').write_text('A=1\n')
        wtx.new('demo', self.root, 'feat/h', 'origin/main')
        self.assertEqual(os.readlink(self.root / 'feat-h' / '.env'), '../.shared/.env')   # 工具包的准备脚本：只链接 .env
        wtx.remove('demo', self.root, 'feat/g', done=False)
        self.assertFalse(d.exists())
        self.assertEqual(wtx.worktrees(self.root), ['feat-h', 'main'])
        wtx.call('demo', self.root, 'ls', '--no-gh')
        self.assertFalse(self.ghlog.exists())                             # 这几样都不找 gh
        self.assertEqual(os.listdir(self.user_home), [])

    def test_set_base_for_ticket_without_pr(self):
        """4.7：换了电脑、还没开 PR 的工单，按事件日志里记的基准写回 wt 的登记；之后 wt sync 就以它为基准。"""
        self.make()
        wtx.new('demo', self.root, 'ticket/f-1')                          # 继续远程已有的分支，不写起点
        self.assertIsNone(wtx.base(self.root, 'ticket/f-1'))              # 没有 PR，wt 补记不了
        wtx.set_base('demo', self.root, 'ticket/f-1', 'feat/f')
        self.assertEqual(wtx.base(self.root, 'ticket/f-1'), 'origin/feat/f')
        p = wtx.call('demo', self.root, 'sync', '--merge', '--dry-run', cwd=self.root / 'ticket-f-1')
        self.assertIn('origin/feat/f', p.stdout + p.stderr)
        self.assertNotIn('origin/main', p.stdout + p.stderr)
        before = self.cfg('branch.ticket/f-1.wtBase')
        for bad_branch, target in (('ticket/f-1', 'feat/nope'), ('ticket/nope', 'feat/f'), ('a..b', 'feat/f')):
            with self.assertRaises(SopError):
                wtx.set_base('demo', self.root, bad_branch, target)
        self.assertEqual(self.cfg('branch.ticket/f-1.wtBase'), before)
        precheck.verify('demo', self.root, wtx.worktrees(self.root))

    # ---------- 被改过就不执行 ----------
    def assert_refused(self, what):
        marker = self.tmp / 'ran'
        n = wtx.worktrees(self.root)
        cfg = (self.root / '.git' / 'config').read_bytes()
        for act in (lambda: wtx.new('demo', self.root, 'feat/x', 'origin/main'),
                    lambda: wtx.remove('demo', self.root, 'feat/g', done=False),
                    lambda: wtx.set_base('demo', self.root, 'feat/g', 'feat/f'),
                    lambda: wtx.call('demo', self.root, 'ls', '--no-gh')):
            with self.assertRaises(Tampered, msg=what):
                act()
        self.assertFalse(marker.exists(), what)                           # 改过的准备脚本、钩子没有被执行
        self.assertEqual(wtx.worktrees(self.root), n, what)              # 没建也没删目录
        self.assertEqual((self.root / '.git' / 'config').read_bytes(), cfg, what)   # 登记没被写

    def prepared(self):
        self.make()
        wtx.new('demo', self.root, 'feat/g', 'origin/main')
        return self.tmp / 'ran'

    def test_refuse_changed_post_create(self):
        marker = self.prepared()
        h = self.root / '.shared' / 'hooks' / 'post-create'
        h.write_text(h.read_text() + f'touch {marker}\n')
        self.assert_refused('post-create')

    def test_refuse_changed_pre_remove(self):
        marker = self.prepared()
        (self.root / '.shared' / 'hooks' / 'pre-remove').write_text(f'#!/bin/sh\ntouch {marker}\n')
        self.assert_refused('pre-remove')

    def test_refuse_changed_git_config(self):
        """受限侧往 .git/config 里加一条（比如把钩子目录指到自己写的地方），特权侧下次用之前就发现。"""
        marker = self.prepared()
        hooks = self.tmp / 'evil-hooks'
        hooks.mkdir()
        (hooks / 'post-checkout').write_text(f'#!/bin/sh\ntouch {marker}\n')
        (hooks / 'post-checkout').chmod(0o755)
        with open(self.root / '.git' / 'config', 'a') as f:
            f.write(f'[core]\n\thooksPath = {hooks}\n')
        self.assert_refused('.git/config')

    def test_refuse_git_hook(self):
        marker = self.prepared()
        h = self.root / '.git' / 'hooks' / 'post-checkout'
        h.parent.mkdir(exist_ok=True)
        h.write_text(f'#!/bin/sh\ntouch {marker}\n')
        h.chmod(0o755)
        self.assert_refused('.git/hooks')

    def test_refuse_worktree_gitfile(self):
        self.prepared()
        (self.root / 'feat-g' / '.git').write_text(f'gitdir: {self.tmp}/elsewhere\n')
        self.assert_refused('工作目录的小文件')

    def test_refuse_worktree_gitfile_replaced_by_dir(self):
        """把工作目录里的小文件换成一个目录（里面放自己的配置），这个工作目录也照样要核对，不能因为「不是小文件」就漏掉。"""
        self.prepared()
        g = self.root / 'feat-g' / '.git'
        g.unlink()
        sh('git', 'init', '-q', g.parent)
        self.assertTrue(g.is_dir())
        self.assert_refused('小文件换成了目录')

    def test_refuse_worktree_gitfile_deleted(self):
        self.prepared()
        (self.root / 'feat-g' / '.git').unlink()
        self.assert_refused('小文件删了')

    def test_no_fingerprint_refused(self):
        self.prepared()
        (paths.state_dir('demo') / 'git-config.sha256').unlink()
        self.assert_refused('没有指纹')


if __name__ == '__main__':
    unittest.main()
