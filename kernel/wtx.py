"""wt 接入层：特权侧调用 wt 的唯一入口（设计书 5.4、5.6、6.4 第四层、4.7）。

包住四件事：建项目 init()、建目录 new()、删目录 remove()（wt done 或 wt rm）、登记基准 set_base()；
开 PR、同步这类其余的命令走 call()。规矩：
- 每次调用 wt 之前先做「特权侧用之前核对」（kernel/precheck.py，6.4 第四层）：.shared/hooks/ 三个文件和工具包模板逐字一致、
  .git/config 和上次记下的指纹一致、没有会被执行的 Git 钩子和工作目录专用配置、每个工作目录的三个小文件对。
  对不上抛 Tampered，wt 一条命令都不执行。调完重新记下 .git/config 的指纹（wt 会往里写基准、PR 号）。
- 一律带 WT_TEMPLATE 指向工具包自己的模板（5.6），不用 wt 自带的那一份（它的准备脚本会装依赖）；
  从外面带进来的 WT_ 开头的变量（WT_TEMPLATE、WT_CD_FILE、WT_GITHUB_URL_PREFIX 等）一律去掉，只给自己的。
- 用环境变量把 Git 钩子再关一次（wt 自己调 git 时也生效）；加 --yes、标准输入接空，不停下来问。
- wt 用规定位置那一份（<工具目录>/wt/wt，4.3）；那里没有时用 PATH 里的。
wt 的登记（基准 branch.<分支>.wtBase、PR 号 branch.<分支>.wtPr）都在项目的 .git/config 里，不往主目录写。
"""
import os
import pathlib
import subprocess

from . import paths, precheck
from .errors import SopError
from .gitx import Git, clean_env

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = TOOLKIT / 'templates' / 'wt'


def executable():
    p = paths.tools_dir() / 'wt' / 'wt'
    return str(p) if p.is_file() and os.access(p, os.X_OK) else 'wt'


def env(slug=None):
    e = {k: v for k, v in clean_env().items() if not k.startswith('WT_')}
    e.update({'WT_TEMPLATE': str(TEMPLATE), 'GIT_CONFIG_COUNT': '1',
              'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/dev/null'})
    if slug:
        e['GH_REPO'] = slug
    else:
        e.pop('GH_REPO', None)
    return e


def dirname(branch):
    """wt 给分支建的目录名：斜杠换成「-」。"""
    return branch.replace('/', '-')


def worktrees(root):
    """要核对的工作目录：项目根下 Git 登记过的（.git/worktrees/<名>），加上凡是里面有 .git 的目录（文件、目录、链接都算）。
    以前只认「里面有 .git 小文件」的：受限侧把小文件换成一个目录（里面放自己的配置）或者删掉，这个目录就躲过了核对，
    而 wt pr、wt sync 是在工作目录里执行的，会照着那份配置做（3-21 发现的）。"""
    root = pathlib.Path(root)
    reg = root / '.git' / 'worktrees'
    registered = {p.name for p in reg.iterdir() if p.is_dir()} if reg.is_dir() else set()
    return sorted(p.name for p in root.iterdir()
                  if p.name not in ('.git', '.shared') and p.is_dir() and (p.name in registered or os.path.lexists(p / '.git')))


def _run(args, cwd, slug):
    return subprocess.run([executable(), *args, '--yes'], cwd=str(cwd), env=env(slug), capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def _fail(args, p):
    return SopError(f'wt {" ".join(args)} 失败：{(p.stderr or p.stdout).strip()[-600:]}')


def call(project, root, *args, cwd=None, slug=None, check=True):
    """核对 → 调 wt → 重记 .git/config 的指纹。project 是项目名（指纹记在 ~/tools/sop/state/<项目名>/）。"""
    root = pathlib.Path(root)
    precheck.verify(project, root, worktrees(root))
    try:
        p = _run(args, cwd or root, slug)
    finally:
        precheck.record(project, root)
    if check and p.returncode:
        raise _fail(args, p)
    return p


def init(project, root, slug, url, *, create=False, public=False, hook=True, settings=False):
    """建项目（I2，或克隆时建本机的项目根）：裸仓库 .git、.shared/（工具包的模板）、默认分支目录。
    create：先在 GitHub 上建仓库（wt 同时设好只允许压成一次提交的合并、合并后删分支）；
    settings：仓库已经有了（例如 I2 建完仓库就断了、重跑时），只设那几项合并的设置。
    建之前项目根还不存在，没有东西可核对；建完记下 .git/config 的指纹，再整个核对一遍。"""
    root = pathlib.Path(root)
    paths.check_project_name(project)
    if (root / '.git').exists() or (root.is_dir() and any(root.iterdir())):
        raise SopError(f'{root} 已经有东西了，不在上面建项目')
    root.parent.mkdir(parents=True, exist_ok=True)
    args = ['init', slug, '--url', str(url), '--dir', str(root)]
    if create:
        args += ['--create', '--public' if public else '--private']
    elif settings:
        args.append('--settings')
    if not hook:
        args.append('--no-hook')
    p = _run(args, root.parent, slug)
    if p.returncode:
        raise _fail(args, p)
    precheck.record(project, root)
    precheck.verify(project, root, worktrees(root))
    return p


def new(project, root, branch, start=None, *, slug=None):
    """建目录：wt new <分支> [起点]。起点写 origin 上的分支时 wt 把它记成基准。建完再核对新目录的三个小文件。"""
    args = ['new', branch] + ([start] if start else [])
    p = call(project, root, *args, slug=slug)
    d = pathlib.Path(root) / dirname(branch)
    if not (d / '.git').is_file():
        raise SopError(f'wt new {branch} 说成功了，但没有建出目录 {d.name}')
    precheck.verify(project, root, [d.name])
    return p


def remove(project, root, branch, *, done=True, slug=None):
    """删目录：done=True 用 wt done（核对 PR 已合并、都推送了才删，也删分支）；False 用 wt rm（丢弃）。"""
    p = call(project, root, 'done' if done else 'rm', branch, slug=slug)
    if (pathlib.Path(root) / dirname(branch)).exists():
        raise SopError(f'wt {"done" if done else "rm"} {branch} 之后目录还在')
    return p


def base(root, branch):
    """wt 登记的基准（origin/<分支>），没登记时 None。"""
    p = Git(pathlib.Path(root) / '.git').run('config', '--get', f'branch.{branch}.wtBase', check=False)
    return p.stdout.strip() or None


def set_base(project, root, branch, target):
    """登记基准：把分支的基准写回 wt 的登记（4.7：换了电脑、还没开 PR 的工单，按事件日志里记的那一份写回）。
    target 写 origin 上的分支名（feat/x 或 origin/feat/x）；本地没有这条分支、远程没有这个基准时不写。"""
    root = pathlib.Path(root)
    target = target.removeprefix('origin/')
    g = Git(root / '.git')
    precheck.verify(project, root, worktrees(root))
    if not g.ok('check-ref-format', '--branch', branch) or not g.rev(f'refs/heads/{branch}'):
        raise SopError(f'本机没有分支 {branch}，登记不了它的基准')
    if not g.rev(f'refs/remotes/origin/{target}'):
        raise SopError(f'远程没有分支 {target}（先拉取一次？），不能把它登记成 {branch} 的基准')
    try:
        g('config', f'branch.{branch}.wtBase', f'origin/{target}')
    finally:
        precheck.record(project, root)
