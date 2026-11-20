"""sop project clone <所有者/项目名>（设计书 4.6、4.7、7.2 末尾；3-25）：换了电脑、继续旧项目。

做这几件事，顺序就是下面的顺序：
1. 克隆：经接入层 wtx.init 调 `wt init <所有者/项目名> --url <地址> --no-hook`（不加 --create，就是取下已有的仓库），
   带 WT_TEMPLATE 指向工具包的模板，所以 wt 钩子 .shared/hooks/ 装的是工具包的那三个（「项目的 wt 钩子：工具包自带，克隆时安装」），
   wt 自带的装依赖脚本不会被执行。项目根是 ~/Project/<项目名>，和建项目的那台电脑同一个位置。
2. 装主线 sop.json 声明的工具包版本：装到 ~/tools/sop/versions/<提交编号>/（和启动器同一个装法），装完核对就是那个提交、没被改过。
3. 重新生成 .shared/.env：按仓库主线上的清单 .env.example（3-25 定的名字，留给 3-48 写进设计书）原样写出；值空着的几项是
   第三方测试密钥，列出来让小白按引导自己填。仓库里没有清单就不生成。已经有 .shared/.env 的不动。
   生成之后在 main/ 里执行一次 `wt hook`（工具包的准备脚本只做一件事：把 .env 链接进来）。
4. 出口检查：在项目根跑 wt doctor，没有失败项（和 I2 一样）。
5. 按远程分支和事件日志重建进行中的工作目录（4.7）：
   - 进行中的功能（日志里登记了、没结束也没放弃的那个；F1 做完才有分支）：`wt new feat/<功能>` 继续远程的分支。
   - 它的工单里，T1 做完了（日志里有「开了工单目录」的登记）、没做完、没放弃、没合进功能分支的：
     远程有这条分支（T4 通过后就推送了）就继续它；远程还没有（T4 之前，实现还没推送过），就从 T1 登记的起点重新开（丢的是那一步，重做）。
   - 每条分支的基准：wt 会按打开中的 PR 的目标分支补记（开了 PR 的）；还没开 PR 的（T10 之前的工单、F12 之前的功能），
     按事件日志里登记的那一份写回 wt 的登记（wtx.set_base）。wt 补记的和日志里的对不上就停下，不猜哪个对。
   - 工单目录照 T1 那样在本机登记一组端口（5.5）。
   已经建好的目录不再建：断了重跑接着做。

事件日志只读（取回、读），不往里写。特权侧调 wt、Git 之前照规矩先核对（wtx 里做）。

没做的：体检项目需要的运行时（档案还没有，第 2a 期）；重建出来的工单目录在受限侧补装依赖（拆成 3-58）；
克隆时由正在运行的这一份工具包重建目录，没有换成 sop.json 声明的那一份去做（第一版两者一样）。
"""
import os
import re
import sys

from . import paths, ports, projectgh, state, wtx
from .errors import SopError
from .gitx import Git
from .project import Project

ENV_MANIFEST = '.env.example'
SLUG = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def parse_slug(slug):
    if not SLUG.match(slug or ''):
        raise SopError(f'要写成「GitHub 账号名/项目名」，例如 zhangsan/jizhang：{slug!r}')
    name = slug.split('/')[1]
    try:
        paths.check_project_name(name)
    except ValueError:
        raise SopError(f'项目名 {name} 不合本工具包的规矩（只能用小写字母、数字和「-」），这个仓库不是用 sop project new 建的？')
    return name


# ---------- 1. 克隆 ----------
def _same_project(root, url):
    """项目根已经在了：是不是上次克隆到一半的这一个（裸仓库加 .shared，远程地址一样）。"""
    if not ((root / '.git').is_dir() and (root / '.shared').is_dir()):
        return False
    p = Git(root / '.git').run('remote', 'get-url', 'origin', check=False)
    return p.returncode == 0 and p.stdout.strip() == url


def fetch_project(name, slug, root, url):
    """把仓库取下来建好项目根。返回 True 是这次新建的，False 是上次已经建好（接着做）。"""
    if os.path.lexists(root):
        if _same_project(root, url):
            print(f'{root} 上次已经克隆过，接着做后面几步。')
            return False
        raise SopError(f'{root} 已经有东西了（不是这个项目上次克隆到一半的样子）。先把它挪走再执行。这次什么都没动。')
    if projectgh.gh('repo', 'view', slug, '--json', 'name', check=False).returncode:
        raise SopError(f'GitHub 上找不到仓库 {slug}，或者这台电脑上登录的账号看不到它（私有仓库要用有权限的账号登录）。'
                       '这次什么都没建。')
    print(f'从 GitHub 取下仓库 {slug}，建项目目录 {root}……')
    wtx.init(name, root, slug, url, hook=False)
    return True


# ---------- 2. 工具包版本 ----------
def install_toolkit(sop):
    tk = sop.get('toolkit') or {}
    repo, version = tk.get('repo'), tk.get('version')
    if not repo or not version:
        raise SopError('主线上的 sop.json 没写工具包的仓库和版本，不知道该装哪一份')
    from .version import install
    d = install(repo, version)
    g = Git(d / '.git', d)
    if g.rev('HEAD') != version or g('status', '--porcelain', '--untracked-files=no'):
        raise SopError(f'本机的工具包目录 {d} 和声明的版本 {version[:8]} 对不上（被改过）。请执行 sop repair。')
    print(f'工具包版本 {version[:8]} 已装好（{d}）')
    return d


# ---------- 3. .shared/.env ----------
def parse_manifest(text):
    """清单 .env.example：KEY=值 一行一项，# 开头是说明。.shared/.env 就是它原样一份（本机开发用的值本来就写在清单里）；
    值空着的是第三方测试密钥（6.3：只许放丢了不心疼的测试密钥），要小白按它上面的说明自己填。
    返回 (要写出的内容, [(要自己填的项, 它上面的说明)])。"""
    fill, notes = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            notes = []
        elif s.startswith('#'):
            notes.append(s.lstrip('#').strip())
        else:
            key, eq, val = s.removeprefix('export ').partition('=')
            if eq and not val.strip().strip('"\''):
                fill.append((key.strip(), '；'.join(n for n in notes if n)))
            notes = []
    return (text if text.endswith('\n') or not text else text + '\n'), fill


def regenerate_env(p):
    """按主线上的清单重新生成 .shared/.env。返回要自己填的项；没有清单返回 None。已经有的不动。"""
    f = p.root / '.shared' / '.env'
    if os.path.lexists(f):
        print(f'{f} 已经有了，不动')
        return []
    r = p.git.run('show', f'refs/remotes/origin/main:{ENV_MANIFEST}', check=False)
    if r.returncode:
        print(f'仓库里没有开发环境的清单 {ENV_MANIFEST}，.shared/.env 没有生成（项目还没用到时就是这样）')
        return None
    text, fill = parse_manifest(r.stdout)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print(f'按清单 {ENV_MANIFEST} 重新生成了 {f}')
    if fill:
        print('下面几项是第三方测试密钥，换了电脑要你自己重新填（打开上面那个文件，在等号后面填上）：')
        for k, why in fill:
            print(f'  · {k}' + (f'：{why}' if why else ''))
    wtx.call(p.name, p.root, 'hook', 'main', slug=p.slug())       # main/ 里也把 .env 链接进来（工具包的准备脚本只做这一件事）
    return fill


# ---------- 5. 进行中的工作目录 ----------
def _last_register(events, scope, what):
    regs = [e for e in events if e['scope'] == scope and e['type'] == 'register' and e.get('what') == what]
    return regs[-1] if regs else None


def in_progress(p):
    """按事件日志算出要重建的工作目录：[{branch, wt, base, start, ticket}]。base 是日志里登记的基准（origin 上的分支名）。"""
    p.journal.fetch()
    f = state.current_feature(p.journal.read(['project'], fetch=False))
    if not f:
        return []
    evs = p.journal.read([f'feature/{f.name}'], fetch=False)
    reg = _last_register(evs, f.scope, 'branch')
    if not reg:
        return []                     # F1 还没做完：功能分支还没有，接着做时 F1 会建
    if any(e['scope'] == f.scope and e.get('step') == 'F20' and e['type'] == 'done' for e in evs):
        return []                     # 已经合进主线（分支删了），剩下的清理、复盘、记录指标只用 main 目录
    out = [{'branch': f.branch, 'wt': f.wt, 'base': reg.get('base') or 'main', 'start': None, 'ticket': False}]
    _, ts = state.view(p.flows, f, evs)
    for t, pos in ts.values():
        if pos.status in ('done', 'dropped') or state.merged(pos):
            continue
        r = _last_register(evs, t.scope, 'worktree')
        if not r:
            continue                  # T1 还没做完：接着做时 T1 会开目录
        out.append({'branch': t.branch, 'wt': t.wt, 'base': r.get('base') or f.branch, 'start': r.get('base_commit'), 'ticket': True})
    return out


def rebuild(p, item):
    """重建一个工作目录，并让 wt 登记的基准和事件日志里的一致。返回一句说明。"""
    branch, base = item['branch'], item['base']
    on_remote = bool(p.git.rev(f'refs/remotes/origin/{branch}'))
    how = ''
    if (p.root / item['wt']).is_dir():
        how = '上次已经建好'
    elif on_remote:
        p.wt_new(branch)                                   # 继续远程已有的分支；开了 PR 的，wt 按 PR 的目标分支补记基准
        how = '继续远程的分支'
    elif item['ticket']:
        start = item['start'] if item['start'] and p.git.rev(item['start']) else f'origin/{base}'
        p.wt_new(branch, start)                            # 实现还没推送过：从 T1 的起点重新开，这一步接着做时重做
        how = '远程还没有这条分支（实现还没推送过），从开工单时的起点重新开'
    else:
        raise SopError(f'远程没有进行中的功能分支 {branch}，事件日志却说它已经开了。启动维修窗口（sop repair）看一下。')
    got, want = wtx.base(p.root, branch), f'origin/{base}'
    if got is None:
        p.wt_set_base(branch, base)
        how += f'；基准按事件日志写回 {want}'
    elif got != want:
        raise SopError(f'分支 {branch} 的基准对不上：wt 按 PR 补记的是 {got}，事件日志里登记的是 {want}。'
                       '启动维修窗口（sop repair）看一下。')
    else:
        how += f'；基准 {want}'
    if item['ticket']:
        ports.allocate(p.name, item['wt'])                 # 和 T1 一样在本机登记一组端口（5.5）
    return how


# ---------- 全过程 ----------
def clone_project(slug):
    name = parse_slug(slug)
    root = paths.projects_dir() / name
    url = projectgh.url_for(slug)
    fetch_project(name, slug, root, url)
    p = Project(root)
    try:
        sop = p.sop_json()
        if sop.get('project') != name:
            raise SopError(f'仓库主线上的 sop.json 写的项目名是 {sop.get("project")!r}，和仓库名 {name} 不一样。启动维修窗口（sop repair）看一下。')
        install_toolkit(sop)
        regenerate_env(p)
        projectgh.GitHub().doctor(name, root)
        items = in_progress(p)
        if not items:
            print('事件日志里没有进行中的功能，只建了 main 目录。')
        for it in items:
            print(f'  {it["wt"]}：{rebuild(p, it)}')
    finally:
        p.journal.close()
    print(f'项目已克隆好：{root}。进入这个目录执行 sop 接着做。')
    return root


def cli(argv):
    if len(argv) != 1 or argv[0].startswith('-'):
        print('用法：sop project clone <GitHub 账号名/项目名>')
        return 2
    try:
        parse_slug(argv[0])
    except SopError as e:
        print(str(e)); return 2
    clone_project(argv[0])
    return 0


if __name__ == '__main__':
    sys.exit(cli(sys.argv[1:]))
