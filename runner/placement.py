"""按步骤的种类搭受限环境（设计书 6.3 的表）。只决定「放进去什么、哪些可写」，不在这里写死任何工具。

六种放法：
  ticket_impl      工单上的实现（T3、T6、T7、T14）：工单目录可写；.git 只读，只放开提交内容、本目录的登记（commondir、gitdir 除外）、
                   本功能的工单分支指针和它的变更记录。AI 自己提交。
  planning         功能目录、规划目录里的 AI 步骤（F2、F3、F5、F6、F8、T8 等）：目录可写；.git 只放开本目录的登记
                   （两个小文件除外），提交内容也只读，不放开任何分支指针。AI 不提交。
  std_draft        起草规范变更（G1）：同上。
  readonly         只看不改的 AI 步骤（T9、F9、F16、F22 等）：工作目录只读，另给一个可写的结果目录。
  restricted_script 受限脚本（装依赖、门禁、验收环境）：工作目录可写，.git 全部只读。
  implement_spec   原样运行 implement-spec（7.6）：整个项目根，再把 .git、main 目录、.shared、别的功能的目录盖成只读，
                   放开提交内容、各工作目录的登记、本功能的工单分支指针、功能分支指针；窄接口的请求和笔记目录单独可写。

每种都有：系统目录只读；主目录、/tmp、/run 是空的；环境变量全部清空、只放回白名单；.shared/.env 只读（6.3）；
任务包目录只读放在 /sop/task，结果目录可写放在 /sop/out。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

TASK_MNT, OUT_MNT = '/sop/task', '/sop/out'
PROXY = ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')


@dataclass
class Ctx:
    root: Path                       # 项目根
    kind: str
    worktree: str | None = None      # 工作目录名（项目根下的第一层目录名）
    feature: str | None = None       # 功能名（ticket_impl、implement_spec 放开分支指针用）
    task_dir: Path | None = None
    out_dir: Path | None = None
    home_binds: dict = field(default_factory=dict)    # {受限环境里主目录下的相对路径: 外面的目录}（AI 的状态目录等），可写
    ro: list = field(default_factory=list)            # 另外只读放进去的（程序、运行时）
    rw: list = field(default_factory=list)            # 另外可写放进去的（依赖缓存、窄接口的目录）
    env: dict = field(default_factory=dict)           # 另外放回的环境变量（值）
    pass_env: tuple = ()                              # 从外面原样带进去的环境变量名（例如 AI 服务的地址和密钥）
    net_proxy: bool = True                            # 带上代理的环境变量
    docker_sock: Path | None = None                   # 专用 Docker 的通道
    interactive: bool = False                         # 对话方式：不脱离终端（6.3 三，前提是内核禁用了往终端塞按键）
    chdir: Path | None = None
    other_worktrees_ro: bool = True                   # implement_spec：别的功能的目录盖成只读


def _home():
    return Path(os.environ.get('HOME', '/root'))


def _base(ctx):
    h = _home()
    a = ['--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
         '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/sbin', '/sbin', '--ro-bind', '/etc', '/etc',
         '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run', '--tmpfs', str(h)]
    if os.path.isdir('/run/systemd/resolve'):
        a += ['--ro-bind', '/run/systemd/resolve', '/run/systemd/resolve']
    return a


def _ensure(p):
    Path(p).mkdir(parents=True, exist_ok=True)
    return str(p)


def _git_binds(ctx):
    """.git 的放法。返回 bwrap 参数（按先后，后面的盖住前面的）。"""
    R, k = Path(ctx.root), ctx.kind
    gd = R / '.git'
    a = ['--ro-bind', str(gd), str(gd)]
    if k == 'readonly' or k == 'restricted_script':
        return a
    if k == 'implement_spec':
        a += ['--bind', str(gd / 'objects'), str(gd / 'objects'), '--bind', str(gd / 'worktrees'), str(gd / 'worktrees')]
        for d in ('refs/heads/feat', f'refs/heads/ticket/{ctx.feature}', 'logs/refs/heads/feat', f'logs/refs/heads/ticket/{ctx.feature}'):
            a += ['--bind', _ensure(gd / d), str(gd / d)]
        for n in sorted(os.listdir(gd / 'worktrees')):
            reg = gd / 'worktrees' / n
            if n == 'main' or (ctx.other_worktrees_ro and n != f'feat-{ctx.feature}' and not n.startswith(f'ticket-{ctx.feature}-')):
                a += ['--ro-bind', str(reg), str(reg)]
            else:
                a += ['--ro-bind', str(reg / 'commondir'), str(reg / 'commondir'), '--ro-bind', str(reg / 'gitdir'), str(reg / 'gitdir')]
        return a
    reg = gd / 'worktrees' / ctx.worktree
    a += ['--bind', str(reg), str(reg), '--ro-bind', str(reg / 'commondir'), str(reg / 'commondir'),
          '--ro-bind', str(reg / 'gitdir'), str(reg / 'gitdir')]
    if k == 'ticket_impl':
        a += ['--bind', str(gd / 'objects'), str(gd / 'objects')]
        for d in (f'refs/heads/ticket/{ctx.feature}', f'logs/refs/heads/ticket/{ctx.feature}'):
            a += ['--bind', _ensure(gd / d), str(gd / d)]   # 最后一条工单分支删掉后 Git 会把空目录删掉，先建好（S7）
    return a


def build(ctx):
    """返回 bwrap 的参数（不含要执行的命令）。"""
    R = Path(ctx.root)
    a = _base(ctx)
    if ctx.kind == 'implement_spec':
        a += ['--bind', str(R), str(R)]
        a += _git_binds(ctx)
        a += ['--ro-bind', str(R / 'main'), str(R / 'main'), '--ro-bind', str(R / '.shared'), str(R / '.shared')]
        if ctx.other_worktrees_ro:
            for n in sorted(os.listdir(R)):
                p = R / n
                if p.is_dir() and n not in ('.git', '.shared', 'main') and n != f'feat-{ctx.feature}' \
                        and not n.startswith(f'ticket-{ctx.feature}-'):
                    a += ['--ro-bind', str(p), str(p)]
        for n in sorted(os.listdir(R)):
            if (R / n / '.git').is_file() and n in (f'feat-{ctx.feature}', 'main'):
                a += ['--ro-bind', str(R / n / '.git'), str(R / n / '.git')]
    else:
        W = R / ctx.worktree
        a += ['--ro-bind' if ctx.kind == 'readonly' else '--bind', str(W), str(W)]
        a += ['--ro-bind', str(W / '.git'), str(W / '.git')]
        a += _git_binds(ctx)
    env_file = R / '.shared' / '.env'
    if env_file.exists() and ctx.kind != 'implement_spec':
        a += ['--ro-bind', str(env_file), str(env_file)]
    for p in ctx.ro:
        a += ['--ro-bind', str(p), str(p)]
    for p in ctx.rw:
        a += ['--bind', str(p), str(p)]
    h = _home()
    for rel, outside in ctx.home_binds.items():
        a += ['--bind', str(outside), str(h / rel)]
    a += ['--dir', '/sop']
    if ctx.task_dir:
        a += ['--ro-bind', str(ctx.task_dir), TASK_MNT]
    if ctx.out_dir:
        a += ['--bind', str(ctx.out_dir), OUT_MNT]
    if ctx.docker_sock:
        a += ['--bind', str(ctx.docker_sock), '/run/sop-docker.sock']
    # 环境变量：全部清空，只放回白名单
    a += ['--clearenv']
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(h), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
           'TERM': os.environ.get('TERM', 'xterm-256color') if ctx.interactive else 'dumb',
           'GIT_AUTHOR_NAME': 'sop-ai', 'GIT_AUTHOR_EMAIL': 'ai@sop.invalid', 'GIT_COMMITTER_NAME': 'sop-ai',
           'GIT_COMMITTER_EMAIL': 'ai@sop.invalid', 'TMPDIR': '/tmp'}
    if ctx.net_proxy:
        env.update({k: os.environ[k] for k in PROXY if k in os.environ})
    env.update({k: os.environ[k] for k in ctx.pass_env if k in os.environ})
    if ctx.docker_sock:
        env['DOCKER_HOST'] = 'unix:///run/sop-docker.sock'
        env['TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE'] = '/run/sop-docker.sock'
    env.update(ctx.env)
    for k, v in env.items():
        a += ['--setenv', k, str(v)]
    a += ['--unshare-pid', '--unshare-ipc', '--unshare-uts', '--die-with-parent']
    if not ctx.interactive:
        a += ['--new-session']
    a += ['--chdir', str(ctx.chdir or (R / ctx.worktree if ctx.worktree else R))]
    return a
