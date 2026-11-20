"""流程沙箱：sop project clone（设计书 4.6、4.7、7.2 末尾；3-25）。两台「电脑」共用一个假的 GitHub。

- 电脑 A：World 建的项目，走到「功能做到一半」：功能分支和草稿 PR 都有；工单 01 开了 PR、停在逐张验收（等人）；
  工单 02 实现推送了、还没开 PR（复查时 AI 交回一个问题，停下）；工单 04 开了目录、实现还没推送过（实现时 AI 交回一个问题）；
  工单 03 依赖 01，还没开工。
- 电脑 B：另一套主目录、工具包根目录、项目目录、gh 配置目录，执行 sop project clone tester/demo。
  比：项目根同一个位置（<项目目录>/demo）、工作目录一个不多一个不少、每个目录的分支和提交、wt 登记的基准和 PR 号、
  .shared/hooks 和工具包模板一字不差；还没开 PR 的工单 02 的基准是按事件日志写回的；工具包版本装好了；
  .shared/.env 按仓库里的清单重新生成。最后在 B 上接着做，把这个功能做完。

防止调到真的 gh：PATH 里假的在最前面；两台电脑的主目录、GH_CONFIG_DIR 都是空的临时目录；开头先确认 PATH 里找到的 gh 就是假的那个。
不连网：仓库地址都是本机路径。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

from kernel import wtx
from machine import components
from tests.helpers import REPO, mock_env, sh
from tests.sandbox import plans
from tests.sandbox.base import F, FB, FS, SandboxCase
from tests.sandbox.world import FAKES, World

T1, T2, T3, T4 = (f'ticket/{F}/{n}' for n in ('01', '02', '03', '04'))
MANIFEST = ('# 本机开发用的数据库\nDB_URL=postgres://localhost:5432/dev\n\n'
            '# 短信服务的测试密钥（在短信服务商的测试后台里取）\nSMS_TEST_KEY=\n')
CLEAN = ('GIT_', 'GH_', 'GITHUB_', 'WT_')


class CloneWorld(World):
    """主目录、gh 配置目录换成空的临时目录（真的 gh 就算被调到也没登录），外面带进来的 GH_、WT_ 变量去掉。"""

    def env(self):
        e = {k: v for k, v in super().env().items() if not k.startswith(CLEAN) or k in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')}
        for d in ('home-a', 'ghcfg-a', 'tmpdir-a'):
            (self.tmp / d).mkdir(exist_ok=True)
        gc = self.tmp / 'home-a' / '.gitconfig'       # 特权侧的 Git 去掉了 GIT_ 变量，提交身份从主目录的配置里读
        if not gc.exists():
            gc.write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n[init]\n\tdefaultBranch = main\n')
        e.update(HOME=str(self.tmp / 'home-a'), GH_CONFIG_DIR=str(self.tmp / 'ghcfg-a'), TMPDIR=str(self.tmp / 'tmpdir-a'))
        return e


class TestProjectClone(SandboxCase):
    maxDiff = None

    def setUp(self):
        super(SandboxCase, self).setUp()
        self.w = CloneWorld(self.tmp, self.visibility)
        found = subprocess.run(['sh', '-c', 'command -v gh; gh --version'], env=self.w.env(), capture_output=True, text=True).stdout
        self.assertEqual(found.splitlines()[0], str(FAKES / 'gh' / 'gh'))     # 调到的一定是假的 gh
        self.assertIn('(fake)', found)
        # 电脑 B
        b = self.b = self.tmp / 'b'
        for d in ('home', 'ghcfg', 'tmpdir', 'sop-home', 'Project', 'tools', 'run'):
            (b / d).mkdir(parents=True)
        (b / 'home' / '.gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n[init]\n\tdefaultBranch = main\n')
        url = self.tmp / 'ghurl' / 'tester'          # 「GitHub」上 tester/demo 的地址：指向 World 的远程
        url.mkdir(parents=True)
        (url / 'demo.git').symlink_to(self.w.remote)
        self.root_b = b / 'Project' / 'demo'

    def add_manifest(self):
        """仓库里的开发环境清单（直接放进主线，像是项目早先就有的）。"""
        seed = self.tmp / 'seed2'
        sh('git', 'clone', '-q', self.w.remote, seed, env=self.w.git_env())
        (seed / '.env.example').write_text(MANIFEST)
        sh('git', '-C', seed, 'add', '.env.example', env=self.w.git_env())
        sh('git', '-C', seed, 'commit', '-qm', 'chore: 开发环境清单', env=self.w.git_env())
        sh('git', '-C', seed, 'push', '-q', 'origin', 'HEAD:main', env=self.w.git_env())
        ga = ('git', '--git-dir', self.w.root / '.git')                # 电脑 A 的 main 目录也跟上（平常 wt done 会让它跟上）
        sh(*ga, 'fetch', '-q', 'origin', env=self.w.git_env())
        sh('git', '--git-dir', self.w.root / '.git' / 'worktrees' / 'main', '--work-tree', self.w.root / 'main',
           'merge', '-q', '--ff-only', 'refs/remotes/origin/main', cwd=self.w.root / 'main', env=self.w.git_env())

    def env_b(self):
        e = self.w.env()
        e.update(HOME=str(self.b / 'home'), GH_CONFIG_DIR=str(self.b / 'ghcfg'), TMPDIR=str(self.b / 'tmpdir'),
                 SOP_HOME=str(self.b / 'sop-home'), SOP_RUNTIME_DIR=str(self.b / 'run'), SOP_PROJECTS_DIR=str(self.b / 'Project'),
                 SOP_TOOLS_DIR=str(self.b / 'tools'), GIT_CONFIG_GLOBAL=str(self.b / 'home' / '.gitconfig'),
                 SOP_GITHUB_URL_PREFIX=f'{self.tmp / "ghurl"}/', PYTHONPATH=str(REPO))
        return e

    def kernel_b(self, *args, cwd=None, toolkit=REPO):
        """在电脑 B 上执行 sop。克隆用正在用的这一份工具包（开发目录）；在项目里接着做，用 sop.json 声明的、克隆时装好的那一份
        （和启动器一样：versions/<提交编号>/，里面有测试用的档案 fake）。"""
        return subprocess.run([sys.executable, '-m', 'kernel.cli', *args], cwd=cwd or self.b, env={**self.env_b(), 'PYTHONPATH': str(toolkit)},
                              capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)

    def machine_a_half_done(self):
        self.add_manifest()
        self.start([('01', [], '无'), ('02', [], '数据访问：改账本文件'), ('03', ['01'], '无'), ('04', [], '无')])
        w = self.w
        w.human[f'{FS}:F13'] = [{'answer': '', 'per_ticket': ['01', '02']}]      # 01、02 逐张验收
        del w.human['*:T11']                                                      # 01 停在逐张验收，等人
        w.script[f'{T2}:T9:1'] = {'result': {'status': 'question', 'questions': [{'category': '业务', 'text': '账本文件不存在时怎么办？'}]}}
        w.script[f'{T4}:T3:1'] = {'result': {'status': 'question', 'questions': [{'category': '业务', 'text': '金额要不要四舍五入？'}]}}
        self.go(ok=False)
        steps = {sc: self.steps(sc) for sc in (T1, T2, T3, T4)}
        self.assertIn(('T10', 'done'), steps[T1])
        self.assertNotIn(('T11', 'start'), steps[T1])
        self.assertIn(('T4', 'done'), steps[T2])
        self.assertIn(('T9', 'failed'), steps[T2])
        self.assertNotIn(('T10', 'start'), steps[T2])
        self.assertIn(('T1', 'done'), steps[T4])
        self.assertIn(('T3', 'failed'), steps[T4])
        self.assertNotIn(('T4', 'done'), steps[T4])
        self.assertEqual(steps[T3], [])
        prs = self.prs()
        self.assertEqual(prs[FB]['state'], 'OPEN')
        self.assertEqual(prs[T1]['state'], 'OPEN')
        self.assertNotIn(T2, prs)
        self.assertTrue(self.w.rgit('rev-parse', '--verify', '--quiet', f'refs/heads/{T2}'))
        self.assertEqual(self.w.rgit('rev-parse', '--verify', '--quiet', f'refs/heads/{T4}', check=False), '')

    def snapshot(self, root):
        """一台电脑上项目的样子：工作目录、各自的分支和提交、wt 登记的基准和 PR 号、.shared/hooks。"""
        g = lambda *a: sh('git', '--git-dir', root / '.git', *a, check=False)     # noqa: E731
        out = {'worktrees': {}, 'hooks': {}}
        for d in wtx.worktrees(root):
            gd = root / '.git' / 'worktrees' / d
            br = sh('git', '--git-dir', gd, 'symbolic-ref', '--short', 'HEAD')
            out['worktrees'][d] = {'branch': br, 'head': sh('git', '--git-dir', gd, 'rev-parse', 'HEAD'),
                                   'base': g('config', '--get', f'branch.{br}.wtBase') or None,
                                   'pr': g('config', '--get', f'branch.{br}.wtPr') or None}
        for f in sorted((root / '.shared' / 'hooks').iterdir()):
            out['hooks'][f.name] = (f.read_bytes(), os.access(f, os.X_OK))
        return out

    def test_clone_on_another_machine(self):
        self.machine_a_half_done()
        a = self.snapshot(self.w.root)
        self.assertEqual(sorted(a['worktrees']), ['feat-jz-1', 'main', 'ticket-jz-1-01', 'ticket-jz-1-02', 'ticket-jz-1-04'])
        journal = self.w.journal_tip()
        db_before = self.w.db()

        r = self.kernel_b('project', 'clone', 'tester/demo')
        if os.environ.get('SOP_SHOW'):
            print(r.stdout, r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = self.snapshot(self.root_b)
        # 同样的位置、同样的目录
        self.assertEqual(self.root_b.relative_to(self.b / 'Project'), self.w.root.relative_to(self.w.root.parent))
        self.assertEqual(b['worktrees'], a['worktrees'])
        self.assertEqual(b['worktrees'][f'ticket-jz-1-02']['base'], f'origin/{FB}')    # 没开 PR 的工单：基准按事件日志写回
        self.assertIsNone(b['worktrees']['ticket-jz-1-02']['pr'])
        self.assertEqual(b['worktrees']['ticket-jz-1-01']['base'], f'origin/{FB}')     # 开了 PR 的：wt 按 PR 补记
        self.assertEqual(b['worktrees']['feat-jz-1']['base'], 'origin/main')
        self.assertIn('基准按事件日志写回 origin/feat/jz-1', r.stdout)
        self.assertIn('从开工单时的起点重新开', r.stdout)                            # 工单 04：实现还没推送过
        # wt 钩子：和电脑 A、和工具包模板一字不差
        self.assertEqual(b['hooks'], a['hooks'])
        for name, (data, x) in b['hooks'].items():
            self.assertEqual(data, (REPO / 'templates' / 'wt' / 'hooks' / name).read_bytes())
        # 工具包版本装好了
        d = self.b / 'sop-home' / 'versions' / self.w.version
        self.assertEqual(sh('git', '-C', d, 'rev-parse', 'HEAD'), self.w.version)
        # .shared/.env 按清单重新生成，要自己填的列出来；各工作目录里链接着它
        env = self.root_b / '.shared' / '.env'
        self.assertEqual(env.read_text(), MANIFEST)
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertIn('SMS_TEST_KEY：短信服务的测试密钥', r.stdout)
        for wt in b['worktrees']:
            self.assertEqual(os.readlink(self.root_b / wt / '.env'), '../.shared/.env', wt)
            self.assertEqual(sh('git', '--git-dir', self.root_b / '.git' / 'worktrees' / wt, '--work-tree', self.root_b / wt,
                                'status', '--porcelain'), '', wt)
        # 工单目录在 B 上登记了端口；事件日志、假 GitHub 一点没变
        with mock_env({'SOP_HOME': str(self.b / 'sop-home')}):
            from kernel import ports
            self.assertEqual(sorted(ports.all_allocations()), [f'demo/ticket-jz-1-0{n}' for n in (1, 2, 4)])
        self.assertEqual(self.w.journal_tip(), journal)
        self.assertEqual({k: v for k, v in self.w.db().items() if k != 'clock'}, {k: v for k, v in db_before.items() if k != 'clock'})
        # 主目录、TMPDIR、gh 配置目录里什么都没留
        self.assertEqual(os.listdir(self.b / 'ghcfg'), [])
        self.assertEqual(os.listdir(self.b / 'tmpdir'), [])
        self.assertEqual(os.listdir(self.b / 'home'), ['.gitconfig'])

        # 再执行一次：接着做的样子，什么都不变
        r2 = self.kernel_b('project', 'clone', 'tester/demo')
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn('上次已经克隆过', r2.stdout)
        self.assertEqual(r2.stdout.count('上次已经建好'), 4)
        self.assertEqual(self.snapshot(self.root_b), b)

        # 在 B 上接着做：工单 01 验收通过，02 的复查、04 的实现重来，把功能做完
        with mock_env({'SOP_HOME': str(self.b / 'sop-home')}):
            components.record()          # B 的隔离自检通过过（机器准备时）
        self.w.human['*:T11'] = [{'answer': '通过'}] * 10
        self.w.save_scripts()
        r3 = self.kernel_b(cwd=self.root_b, toolkit=d)
        self.assertEqual(r3.returncode, 0, r3.stdout[-4000:] + r3.stderr[-2000:])
        self.assertFeatureDone(r3)
        for sc in (T1, T2, T3, T4):
            self.assertIn(('T15', 'done'), self.steps(sc), sc)

    def test_nothing_in_progress_no_manifest(self):
        """没有进行中的功能、仓库里没有开发环境清单：只建 main 目录，不生成 .shared/.env。"""
        r = self.kernel_b('project', 'clone', 'tester/demo')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('没有进行中的功能，只建了 main 目录', r.stdout)
        self.assertIn('仓库里没有开发环境的清单', r.stdout)
        self.assertEqual(wtx.worktrees(self.root_b), ['main'])
        self.assertFalse(os.path.lexists(self.root_b / '.shared' / '.env'))
        self.assertEqual(sh('git', '--git-dir', self.root_b / '.git', 'rev-parse', 'refs/heads/main'), self.w.rgit('rev-parse', 'main'))

    def test_refuses_and_leaves_nothing(self):
        """仓库在 GitHub 上找不到、项目目录已经有别的东西、名字不合规矩：停下，什么都没建。"""
        r = self.kernel_b('project', 'clone', 'tester/nope')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('GitHub 上找不到仓库 tester/nope', r.stdout)
        self.assertEqual(os.listdir(self.b / 'Project'), [])
        self.root_b.mkdir()
        (self.root_b / '别的东西.txt').write_text('x')
        r = self.kernel_b('project', 'clone', 'tester/demo')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('已经有东西了', r.stdout)
        self.assertEqual(os.listdir(self.root_b), ['别的东西.txt'])
        r = self.kernel_b('project', 'clone', 'Tester/Demo')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.w.db()['prs'], {})
