"""流程沙箱的「世界」（设计书 16.2）：离线的 GitHub（本机的假远程加假的 gh）、临时的工具包根目录、按工具包模板建好的项目。

- 工具包的「公开仓库」：一个本机裸仓库，提交的是当前开发目录的快照（不含 docs/），再把测试用的档案 fake 放进 profiles/。
  版本就是这个提交的编号；可以再提交几个变体（修补版、大版本），用来演工具包升级（W18）。
- 项目的远程：本机裸仓库，main 上是新项目的初始内容（templates/project 加 sop.json 等），另有日志分支。
- 项目根：经 wt 接入层（kernel/wtx.py）用 wt init --url 建（带 WT_TEMPLATE 指向工具包的模板），和真的一样是裸仓库加工作目录。
- 剧本：假 AI（SOP_FAKE_SCRIPT）、档案 fake 的门禁（SOP_FAKE_GATE）、人的回答（SOP_HUMAN_SCRIPT）、假 gh 的检查结果（rules.json）、
  假的隔离自检（SOP_FAKE_SELFTEST，3-07；没给剧本时一跑就报错）。
- 这台「电脑」的隔离自检已经通过过：系统组件现在的版本先记进登记（config/system.json），所以平常 sop 不会自检；
  要演系统升级，就把登记里的某一样改成旧的（set_registered）。
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys

from kernel import wtx
from machine import components, config
from tests.helpers import REPO, mock_env, sh

FAKES = REPO / 'tests' / 'fakes'
PNG_A = '89504e470d0a1a0a' + '00' * 8 + '41'     # 假的「图片」：只要内容不同就行
PNG_B = '89504e470d0a1a0a' + '00' * 8 + '42'
PNG_C = '89504e470d0a1a0a' + '00' * 8 + '43'


def snapshot_toolkit(dest, tweak=None):
    """把开发目录的当前样子（被 Git 跟踪的和没被忽略的新文件，不含 docs/）复制到 dest，再放进测试用的档案。"""
    files = sh('git', '-C', REPO, 'ls-files', '-co', '--exclude-standard', '-z').split('\0')
    for f in files:
        if not f or f.startswith('docs/') or not (REPO / f).is_file():
            continue
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / f, dest / f)
    shutil.copytree(FAKES / 'profiles' / 'stack' / 'fake', dest / 'profiles' / 'stack' / 'fake', dirs_exist_ok=True)
    if tweak:
        tweak(dest)


class World:
    def __init__(self, tmp, visibility='public', name='demo', tweak=None):
        self.tmp = pathlib.Path(tmp)
        self.name = name
        self.home = self.tmp / 'sop-home'
        self.github = self.tmp / 'github'
        self.fakegh = self.tmp / 'fakegh'
        self.scripts = self.tmp / 'scripts'
        for d in (self.home, self.github, self.fakegh, self.scripts):
            d.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp / 'Project' / name
        self.toolkit_remote = self.github / 'sop-toolkit.git'
        self.remote = self.github / f'{name}.git'
        self.visibility = visibility
        self.script = {}; self.gate = {}; self.human = {}; self.rules = []
        self.selftest = None                 # 假的隔离自检：None 是剧本没想到会自检；{'pass': True/False}
        self.selftest_log = self.scripts / 'selftest.log'
        self.save_scripts()
        self.version = self.publish_toolkit('初始版本', tweak)
        self._make_project()

    # ---------- 环境 ----------
    def env(self):
        return {**os.environ, 'SOP_HOME': str(self.home), 'SOP_RUNTIME_DIR': str(self.tmp / 'run'),
                'PATH': f'{FAKES / "gh"}:{os.environ["PATH"]}', 'FAKEGH_HOME': str(self.fakegh),
                'SOP_FAKE_SCRIPT': str(self.scripts / 'ai.json'), 'SOP_FAKE_GATE': str(self.scripts / 'gate.json'),
                'SOP_HUMAN_SCRIPT': str(self.scripts / 'human.json'), 'SOP_AI': 'fake', 'SOP_POLL_SECONDS': '0',
                'SOP_TOOLKIT_REPO': str(self.toolkit_remote), 'GIT_CONFIG_GLOBAL': str(self.tmp / 'gitconfig'),
                'GIT_CONFIG_NOSYSTEM': '1', 'SOP_NO_NOTIFY': '1', 'SOP_PYTHON': sys.executable, 'SOP_CHECK_DEADLINE': '60',
                'SOP_SELFTEST_CMD': str(FAKES / 'selftest' / 'selftest'), 'SOP_FAKE_SELFTEST': str(self.scripts / 'selftest.json')}

    def save_scripts(self):
        (self.scripts / 'ai.json').write_text(json.dumps(self.script, ensure_ascii=False, indent=1))
        (self.scripts / 'gate.json').write_text(json.dumps(self.gate, ensure_ascii=False, indent=1))
        (self.scripts / 'human.json').write_text(json.dumps(self.human, ensure_ascii=False, indent=1))
        (self.fakegh / 'rules.json').write_text(json.dumps(self.rules, ensure_ascii=False, indent=1))
        st = self.scripts / 'selftest.json'
        if self.selftest is None:
            st.unlink(missing_ok=True)
        else:
            st.write_text(json.dumps({**self.selftest, 'log': str(self.selftest_log), 'journal': str(self.remote)}))

    def git_env(self):
        return {'GIT_CONFIG_GLOBAL': str(self.tmp / 'gitconfig'), 'GIT_CONFIG_NOSYSTEM': '1'}

    # ---------- 工具包 ----------
    def publish_toolkit(self, message, tweak=None):
        """往工具包的「公开仓库」提交一个版本，返回提交编号。"""
        (self.tmp / 'gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n[init]\n\tdefaultBranch = main\n')
        if not self.toolkit_remote.exists():
            sh('git', 'init', '-q', '--bare', '-b', 'main', self.toolkit_remote, env=self.git_env())
        work = self.tmp / 'toolkit-work'
        shutil.rmtree(work, ignore_errors=True)
        if sh('git', '--git-dir', self.toolkit_remote, 'rev-parse', '--verify', '--quiet', 'main', check=False, env=self.git_env()):
            sh('git', 'clone', '-q', self.toolkit_remote, work, env=self.git_env())
            for p in work.iterdir():
                if p.name != '.git':
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
        else:
            work.mkdir(); sh('git', 'init', '-q', '-b', 'main', work, env=self.git_env())
            sh('git', '-C', work, 'remote', 'add', 'origin', self.toolkit_remote, env=self.git_env())
        snapshot_toolkit(work, tweak)
        sh('git', '-C', work, 'add', '-A', env=self.git_env())
        sh('git', '-C', work, 'commit', '-qm', message, '--allow-empty', env=self.git_env())
        sh('git', '-C', work, 'push', '-q', 'origin', 'HEAD:main', env=self.git_env())
        return sh('git', '-C', work, 'rev-parse', 'HEAD', env=self.git_env())

    # ---------- 项目 ----------
    def _make_project(self):
        e = self.git_env()
        sh('git', 'init', '-q', '--bare', '-b', 'main', self.remote, env=e)
        seed = self.tmp / 'seed'
        shutil.copytree(REPO / 'templates' / 'project', seed)
        (seed / 'sop.json').write_text(json.dumps({'project': self.name, 'toolkit': {'repo': str(self.toolkit_remote), 'version': self.version},
                                                   'profiles': {'stack': ['fake'], 'end': []}, 'visibility': self.visibility},
                                                  ensure_ascii=False, indent=1) + '\n')
        (seed / 'docs' / 'baseline').mkdir(parents=True)
        (seed / 'docs' / 'baseline' / 'home.png').write_bytes(bytes.fromhex(PNG_A))
        (seed / 'ui' / 'screens').mkdir(parents=True)
        (seed / 'ui' / 'screens' / 'home.png').write_bytes(bytes.fromhex(PNG_A))
        (seed / 'docs' / 'standards' / 'rules.md').write_text('规范第 1 版\n')
        (seed / 'src').mkdir()
        (seed / 'src' / 'app.py').write_text('print("记账")\n')
        (seed / '.gitignore').write_text('.env\n.claude/settings.local.json\n')
        sh('git', 'init', '-q', '-b', 'main', seed, env=e)
        sh('git', '-C', seed, 'add', '-A', env=e); sh('git', '-C', seed, 'commit', '-qm', 'chore: 项目初始内容', env=e)
        sh('git', '-C', seed, 'push', '-q', self.remote, 'HEAD:main', env=e)
        (self.fakegh / 'db.json').write_text(json.dumps({'clock': 0, 'remote': str(self.remote), 'slug': f'tester/{self.name}',
                                                         'visibility': self.visibility, 'prs': {}, 'runs': [], 'next_pr': 1, 'next_run': 1}))
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with mock_env(self.env()):     # 和真的一样经 wt 接入层建（带 WT_TEMPLATE 指向工具包的模板，建完记下 .git/config 的指纹，3-21）
            wtx.init(self.name, self.root, f'tester/{self.name}', self.remote, hook=False)
        (self.root / '.shared' / '.env').write_text('DB_URL=本机开发用\n')
        # 项目初始化里由特权侧做的几样（I6 建日志分支、记下 .git/config 的指纹）：第三段的 sop project new 正式做
        r = self.kernel('init-project')
        if r.returncode:
            raise RuntimeError(f'初始化失败：{r.stdout}\n{r.stderr}')
        # 机器准备（M6）时隔离自检通过过：记下这台电脑现在的系统组件版本（3-07）
        with self._sop_env():
            components.record()

    def _sop_env(self):
        return mock_env({'SOP_HOME': str(self.home), 'SOP_RUNTIME_DIR': str(self.tmp / 'run')})

    # ---------- 系统组件登记（3-07） ----------
    def registered(self):
        with self._sop_env():
            return config.system().get('components', {})

    def set_registered(self, **parts):
        """把登记里的几样改掉，演「上次自检通过之后系统升级了」。"""
        with self._sop_env():
            config.record_system({**config.system()['components'], **parts})

    def selftest_runs(self):
        if not self.selftest_log.exists():
            return []
        return [json.loads(x) for x in self.selftest_log.read_text().splitlines()]

    def journal_tip(self):
        return self.rgit('rev-parse', 'sop/journal')

    # ---------- 执行 sop ----------
    def kernel(self, *args, timeout=600, env=None):
        """直接用开发目录里的内核（不经启动器）。"""
        return subprocess.run([sys.executable, '-m', 'kernel.cli', *args], cwd=self.root, env={**self.env(), 'PYTHONPATH': str(REPO), **(env or {})},
                              capture_output=True, text=True, timeout=timeout)

    def sop(self, *args, timeout=900, env=None, kill_after=None):
        """经启动器执行 sop（按主线 sop.json 声明的版本找到安装的那一份）。kill_after：几秒后强制结束整组进程。"""
        launcher = self.home / 'sop'
        if not launcher.exists():
            self.kernel('self', 'bootstrap', str(self.toolkit_remote), self.version)
        cmd = [str(launcher), *args]
        if kill_after:
            p = subprocess.Popen(cmd, cwd=self.root, env={**self.env(), **(env or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True)
            try:
                out, err = p.communicate(timeout=kill_after)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                out, err = p.communicate()
            return subprocess.CompletedProcess(cmd, p.returncode, out, err)
        return subprocess.run(cmd, cwd=self.root, env={**self.env(), **(env or {})}, capture_output=True, text=True, timeout=timeout)

    def sop_until(self, predicate, timeout=300):
        """执行 sop，等 predicate(本世界) 成立时强制结束整组进程（模拟断电、被强制结束）。返回 (是否等到了, 输出)。"""
        import time
        launcher = self.home / 'sop'
        p = subprocess.Popen([str(launcher)], cwd=self.root, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True)
        t0, hit = time.time(), False
        while time.time() - t0 < timeout and p.poll() is None:
            try:
                if predicate(self):
                    hit = True
                    break
            except Exception:   # noqa: BLE001
                pass
            time.sleep(0.3)
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return hit, out

    # ---------- 看结果 ----------
    def gh(self, *args):
        return subprocess.run([str(FAKES / 'gh' / 'gh'), *args], env=self.env(), capture_output=True, text=True)

    def db(self):
        return json.loads((self.fakegh / 'db.json').read_text())

    def rgit(self, *args, check=True):
        return sh('git', '--git-dir', self.remote, *args, check=check, env=self.git_env())

    def events(self, d):
        files = self.rgit('ls-tree', '-r', '--name-only', 'sop/journal', f'events/{d}/').splitlines()
        out = []
        for c in self.rgit('log', '--reverse', '--format=%H', 'sop/journal').splitlines():
            for f in sorted(self.rgit('diff-tree', '--no-commit-id', '--name-only', '-r', '--diff-filter=A', c).splitlines()):
                if f in files:
                    out.append(json.loads(self.rgit('show', f'{c}:{f}')))
        return out

    def releases(self, owner):
        key = owner.replace('/', '__')
        fs = self.rgit('ls-tree', '-r', '--name-only', 'sop/journal', f'releases/{key}/').splitlines()
        return [json.loads(self.rgit('show', f'sop/journal:{f}')) for f in fs if f.endswith('.json')]
