"""一个项目在本机的上下文（设计书 5.1、5.3）。"""
import json
import os
import pathlib
import subprocess
import threading
import tomllib

from checks.protected import core as protected_core

from . import flowdef, paths, precheck
from .errors import SopError
from .gitx import Git, clean_env
from .journal import Journal

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent


def find_root(start):
    """从当前目录向上找同时含有 .git（裸仓库）和 .shared 的目录（5.3）。"""
    p = pathlib.Path(start).resolve()
    for d in [p, *p.parents]:
        if (d / '.git').is_dir() and (d / '.shared').is_dir():
            return d
    raise SopError('当前目录不在一个 SOP 项目里（找不到同时含有 .git 和 .shared 的目录）。先 cd 到 ~/Project/<项目名>。')


class Project:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.name = paths.check_project_name(self.root.name)
        self.gitdir = self.root / '.git'
        self.git = Git(self.gitdir)
        self.toolkit = TOOLKIT
        self.journal = Journal(self.gitdir)
        self.flows = flowdef.load_dir(TOOLKIT / 'flows')
        self.gitlock = threading.RLock()        # 特权侧改公共 .git 的操作（wt、合并、推送）一次一个
        self.state = paths.state_dir(self.name)
        self.state.mkdir(parents=True, exist_ok=True)

    # ---------- 仓库 ----------
    def wgit(self, wt):
        """在某个工作目录里执行 Git：仓库写成它自己的登记目录，不靠目录里指向 .git 的小文件。"""
        return Git(self.gitdir / 'worktrees' / wt, self.root / wt)

    def fetch(self, *branches):
        specs = [f'+refs/heads/{b}:refs/remotes/origin/{b}' for b in branches] or ['+refs/heads/*:refs/remotes/origin/*']
        with self.gitlock:
            self.git('fetch', '-q', '--prune', 'origin', *specs)

    def sop_json(self, fetch=True):
        """主线上的 sop.json（一个项目同一时刻只用主线声明的那个工具包版本，7.11）。"""
        if fetch:
            self.fetch('main')
        return json.loads(self.git('show', 'refs/remotes/origin/main:sop.json'))

    def slug(self):
        url = self.git('remote', 'get-url', 'origin').rstrip('/')
        url = url[:-4] if url.endswith('.git') else url
        parts = url.replace(':', '/').split('/')
        return f'{parts[-2]}/{parts[-1]}'

    # ---------- 受保护路径 ----------
    def protected_patterns(self, sop=None):
        return protected_core.patterns_for(str(self.toolkit), sop or self.sop_json(fetch=False))

    # ---------- wt ----------
    def worktrees(self):
        return sorted(p.name for p in self.root.iterdir() if (p / '.git').is_file())

    def wt(self, *args, cwd=None, check=True):
        """调用 wt。之前核对特权侧要用的文件（6.4 第四层），之后重新记下 .git/config 的指纹。
        一律用工具包自己的模板（WT_TEMPLATE，5.6）；用环境变量再把 Git 钩子关一次（wt 自己调 git 时也生效）。"""
        with self.gitlock:
            precheck.verify(self.name, self.root, self.worktrees())
            env = clean_env({'WT_TEMPLATE': str(TOOLKIT / 'templates' / 'wt'), 'GIT_CONFIG_COUNT': '1',
                             'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/dev/null', 'GH_REPO': self.slug()})
            p = subprocess.run(['wt', *args, '--yes'], cwd=cwd or self.root, env=env, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
            precheck.record(self.name, self.root)
        if check and p.returncode:
            raise SopError(f'wt {" ".join(args)} 失败：{(p.stderr or p.stdout).strip()[-600:]}')
        return p

    # ---------- gh ----------
    def gh(self, *args, check=True, as_json=False):
        with self.gitlock:
            precheck.verify(self.name, self.root, self.worktrees())
        env = clean_env({'GH_REPO': self.slug(), 'GH_PROMPT_DISABLED': '1'})
        p = subprocess.run(['gh', *args], cwd=self.root, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if check and p.returncode:
            raise SopError(f'gh {" ".join(args[:3])} 失败：{p.stderr.strip()[-500:]}')
        return json.loads(p.stdout) if as_json and p.returncode == 0 else p

    # ---------- 档案 ----------
    def profile(self, sop=None):
        sop = sop or self.sop_json(fetch=False)
        stack = (sop.get('profiles') or {}).get('stack') or []
        if not stack:
            return None
        d = self.toolkit / 'profiles' / 'stack' / stack[0]
        load = lambda n: tomllib.load(open(d / n, 'rb')) if (d / n).exists() else {}   # noqa: E731
        return {'name': stack[0], 'dir': d, 'commands': load('commands.toml'), 'toolchain': load('toolchain.toml')}

    def expand(self, s, prof):
        s = s.replace('{profile}', str(prof['dir'])).replace('{toolkit}', str(self.toolkit))
        if s.startswith('$'):
            return os.environ.get(s[1:], '')
        return s
