"""特权侧执行 Git 的唯一入口。

规矩（设计书 6.2、6.3、6.4、5.6）：
- 总是明说仓库在哪（--git-dir），不靠工作目录里指向 .git 的那个小文件；
- 关掉钩子（core.hooksPath=/dev/null），不运行任何项目代码；
- 路径不转义（core.quotePath=false），中文文件名按原样比；
- 推送、取回复用同一条 SSH 连接，通道文件放在只有用户自己能进的运行时目录里。
"""
import os
import subprocess

from . import paths

BASE_CONFIG = ('-c', 'core.hooksPath=/dev/null', '-c', 'core.quotePath=false', '-c', 'core.fsmonitor=false',
               '-c', 'advice.detachedHead=false')


class GitError(RuntimeError):
    def __init__(self, args, rc, stderr):
        super().__init__(f'git {" ".join(args)} 失败（退出码 {rc}）：{stderr.strip()[:500]}')
        self.rc = rc
        self.stderr = stderr


def clean_env(extra=None):
    """去掉会把 Git 引到别处的环境变量（GIT_DIR 等），加上复用连接的设置。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    ctl = paths.runtime_dir() / 'ssh-%C'
    env['GIT_SSH_COMMAND'] = f'ssh -o ControlMaster=auto -o ControlPath={ctl} -o ControlPersist=120'
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['LC_ALL'] = 'C.UTF-8'
    if extra:
        env.update(extra)
    return env


class Git:
    def __init__(self, gitdir, worktree=None):
        self.gitdir = str(gitdir)
        self.worktree = str(worktree) if worktree else None

    def argv(self, *args):
        a = ['git', f'--git-dir={self.gitdir}', *BASE_CONFIG]
        if self.worktree:
            a += [f'--work-tree={self.worktree}']
        return a + [str(x) for x in args]

    def run(self, *args, input=None, env=None, check=True, binary=False, cwd=None):
        p = subprocess.run(self.argv(*args), input=input, capture_output=True, text=not binary,
                           env=clean_env(env), cwd=cwd or self.worktree or None, stdin=None if input is not None else subprocess.DEVNULL)
        if check and p.returncode != 0:
            raise GitError(args, p.returncode, p.stderr if not binary else p.stderr.decode(errors='replace'))
        return p

    def __call__(self, *args, **kw):
        """执行并返回去掉首尾空白的标准输出。"""
        return self.run(*args, **kw).stdout.strip()

    def ok(self, *args, **kw):
        return self.run(*args, check=False, **kw).returncode == 0

    def rev(self, ref):
        p = self.run('rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}', check=False)
        return p.stdout.strip() if p.returncode == 0 else None

    def blob_of(self, rev, path):
        """某个提交里某个文件的内容指纹；不存在时返回 None。"""
        p = self.run('rev-parse', '--verify', '--quiet', f'{rev}:{path}', check=False)
        return p.stdout.strip() if p.returncode == 0 else None
