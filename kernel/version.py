"""工具包的版本（设计书 3.2、7.11、16.5）：安装、启动器、修补版和大版本、升级。

- 版本用提交编号标识。修补版只改脚本、检查、任务包模板，流程定义和技能副本不变；大版本改了流程定义或技能版本。
- 判断「能不能在功能进行中换上」不靠版本自己的声明，按实际内容比：flows/ 和 skills/ 两个版本逐字一致才算修补版。
- 有进行中的功能（或还没合并的产品规划）时不升级大版本；修补版可以换上：升级 PR 合进主线后，特权侧把主线合进功能分支（只做合并，
  不运行代码），再让进行中的工单分支跟上（wt sync --merge）。步骤编号没变，事件日志照样回放。
- 退回上一个版本（sop self rollback，7.11、16.5 第 2 条，3-43）：在项目里走和升级同一条路（改主线 sop.json 的声明、走 PR），
  有进行中的功能时只能退到修补版；不在项目里换 versions/latest（项目外面的命令用它）。退回去的版本只从本机已装好的里找，不联网下。
"""
import filecmp
import json
import os
import pathlib
import shutil
import subprocess
import sys

from . import journal as J, paths, state
from .errors import SopError
from .project import TOOLKIT

FLOW_DIRS = ('flows', 'skills')


def install(repo, version):
    from .launcher import install as _install
    return _install(repo, version, paths.versions_dir())


# 启动器 ~/tools/sop/sop（3.2）。内核用 uv 执行（3.3），用规定位置那份 uv（~/tools/uv/bin/uv；第零步刚装好时它还不在 PATH 里，
# 电脑上另有一份旧 uv 时 PATH 里先找到的可能是旧的），没有才用 PATH 里的；uv 的缓存放 ~/tools/cache/uv（4.3）。
# SOP_PYTHON 只在自测里用
LAUNCHER_SH = '''#!/bin/sh
# SOP 工具包的启动器（设计书 3.2）。由 sop self install 和第零步（bootstrap.sh）写，不要手改
here=$(cd "$(dirname "$0")" && pwd)
tools=${SOP_TOOLS_DIR:-$(dirname "$here")}
if [ -n "${SOP_PYTHON:-}" ]; then exec "$SOP_PYTHON" -I "$here/launcher.py" "$@"; fi
uv=$tools/uv/bin/uv
[ -x "$uv" ] || uv=uv
export UV_CACHE_DIR="$tools/cache/uv" UV_PYTHON_INSTALL_DIR="$tools/uv/python"
exec "$uv" run -q --no-project --python 3.14 python -I "$here/launcher.py" "$@"
'''


def write_launcher(version):
    """写启动器、把项目外面用的版本（versions/latest）换成 version。

    每个文件都先写临时文件再一下换名（os.replace），中途断了要么是旧的、要么是新的，不会只写了一半。
    latest 最后换：换之前先确认那个版本的目录在（launcher.py 读得到），所以不会指向不存在的版本。
    换了之后在 versions/history 末尾记一行（sop self rollback 按它找上一个）。"""
    home = paths.sop_home()
    launcher = (paths.versions_dir() / version / 'kernel' / 'launcher.py').read_text()
    old = current_latest()
    _write_if_changed(home / 'launcher.py', launcher)
    _write_if_changed(home / 'sop', LAUNCHER_SH, 0o755)
    _write_if_changed(paths.versions_dir() / 'latest', version)
    _record_history(old, version)


def _write_if_changed(f, text, mode=0o644):
    """内容没变就不写（第零步可以重复跑，修改时间也不动）。要写时先写同目录的临时文件，再一下换名。"""
    try:
        if f.read_text() == text and (f.stat().st_mode & 0o777) == mode:
            return False
    except FileNotFoundError:
        pass
    tmp = f.with_name(f'.{f.name}.tmp')
    try:
        with open(tmp, 'w') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, f)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


# ---------- 项目外面用的版本：versions/latest 和它的历史 ----------
def current_latest():
    f = paths.versions_dir() / 'latest'
    try:
        return f.read_text().strip() or None
    except FileNotFoundError:
        return None


def stack(seq):
    """一串先后用过的版本 -> 现在还算数的「版本栈」：回到栈里已经有的版本，就当作退回到它，把它上面的弹掉
    （A→B→退回 A 之后，A 的上一个不再是 B，B 正是因为有毛病才退掉的）。连续重复的只算一个。"""
    out = []
    for v in seq:
        if not v:
            continue
        if v in out:
            del out[out.index(v) + 1:]
        else:
            out.append(v)
    return out


def _history_file():
    return paths.versions_dir() / 'history'


def latest_stack():
    """项目外面用过的版本栈；最后一个是 versions/latest 现在记的（历史没跟上时以 latest 为准）。"""
    try:
        seq = _history_file().read_text().split()
    except FileNotFoundError:
        seq = []
    cur = current_latest()
    st = stack(seq + [cur] if cur else seq)
    return st


def _record_history(old, new):
    if old == new and _history_file().exists():
        return
    try:
        seq = _history_file().read_text().split()
    except FileNotFoundError:
        seq = []
    if not seq and old and old != new:
        seq.append(old)          # 有历史之前就装着的那个版本也记上，才退得回去
    if seq and seq[-1] == new:
        return
    seq.append(new)
    _write_if_changed(_history_file(), '\n'.join(seq) + '\n')


def installed_ok(version):
    """本机 versions/<提交编号>/ 装着这个版本、没被改过、启动要用的文件都在。是就返回目录，否则返回 (None, 原因)。"""
    d = paths.versions_dir() / version
    if not d.is_dir():
        return None, f'本机没有装这个版本（{d} 不存在）'
    for f in ('kernel/main.py', 'kernel/launcher.py'):
        if not (d / f).is_file():
            return None, f'{d} 不完整（缺 {f}）'

    def git(*a):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(d), *a], capture_output=True, text=True,
                              env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
    head = git('rev-parse', 'HEAD')
    dirty = git('status', '--porcelain', '--untracked-files=no')
    if head.returncode or head.stdout.strip() != version:
        return None, f'{d} 不是这个版本（Git 记的是 {head.stdout.strip()[:8] or "看不出来"}）'
    if dirty.returncode or dirty.stdout.strip():
        return None, f'{d} 里的文件被改过'
    return d, None


def same_tree(a, b, sub):
    pa, pb = pathlib.Path(a) / sub, pathlib.Path(b) / sub
    if not pa.exists() and not pb.exists():
        return True
    if not pa.exists() or not pb.exists():
        return False
    cmp = filecmp.dircmp(pa, pb)

    def clean(c):
        if c.left_only or c.right_only or c.diff_files or c.funny_files:
            return False
        return all(clean(s) for s in c.subdirs.values())
    return clean(cmp) and all(filecmp.cmp(pa / f, pb / f, shallow=False) for f in cmp.same_files)


def classify(old_dir, new_dir):
    """patch：流程定义和技能副本逐字一致；否则 major。"""
    return 'patch' if all(same_tree(old_dir, new_dir, d) for d in FLOW_DIRS) else 'major'


def in_progress(p):
    """有进行中的功能（或还没合并的产品规划）。"""
    p.journal.fetch()
    return state.current_feature(p.journal.read(['project'], fetch=False))


def _cur_dir(cur):
    d = paths.versions_dir() / cur
    return d if d.exists() else TOOLKIT


def upgrade(p, target, human):
    """sop self upgrade <提交编号>。"""
    sop = p.sop_json()
    cur = sop['toolkit']['version']
    if target == cur:
        print('已经是这个版本'); return 0
    new_dir = install(sop['toolkit']['repo'], target)
    kind = classify(_cur_dir(cur), new_dir)
    f = in_progress(p)
    if kind == 'major' and f:
        raise SopError(f'新版本改了流程定义或技能（大版本）。功能 {f.name} 还在进行中，不能换大版本（7.11）。'
                       '先把这个功能做完，或者放弃它（sop feature drop），再升级。')
    return switch(p, sop, target, new_dir, kind, f, human)


def project_versions(p):
    """这个项目先后用过、现在还算数的工具包版本栈（按主线上 sop.json 的历史，退回过的弹掉，见 stack）。
    最后一个就是主线现在声明的；倒数第二个是「上一个版本」。调之前先取回主线。"""
    g = p.git
    seq = []
    for c in g('log', '--first-parent', '--reverse', '--format=%H', 'refs/remotes/origin/main', '--', 'sop.json').splitlines():
        r = g.run('show', f'{c}:sop.json', check=False)
        if r.returncode:
            continue           # 这个提交删了 sop.json
        try:
            seq.append(json.loads(r.stdout)['toolkit']['version'])
        except (ValueError, KeyError, TypeError):
            continue
    return stack(seq)


def rollback_project(p, human):
    """在项目里的 sop self rollback：把主线 sop.json 声明的版本退回上一个（7.11：和升级走同一条路）。"""
    sop = p.sop_json()
    cur = sop['toolkit']['version']
    st = project_versions(p)
    if not st or st[-1] != cur:
        st = [*st, cur]
    if len(st) < 2:
        raise SopError(f'没有上一个版本可以退：项目 {p.name} 一直用的就是现在这个工具包版本 {cur[:8]}'
                       '（或者之前用过的都已经退回过了）。可以停下等修好的版本出来，修好后用 sop self upgrade <提交编号> 换上。')
    prev = st[-2]
    prev_dir, why = installed_ok(prev)
    if not prev_dir:
        raise SopError(f'上一个版本是 {prev[:8]}，可是{why}，退不回去。工具包只从本机已经装好的版本里退，不联网下载。'
                       '可以停下等修好的版本出来，修好后用 sop self upgrade <提交编号> 换上。')
    kind = classify(_cur_dir(cur), prev_dir)
    f = in_progress(p)
    if kind == 'major' and f:
        raise SopError(f'上一个版本 {prev[:8]} 和现在的 {cur[:8]} 流程定义或技能不一样（大版本），'
                       f'功能 {f.name} 还在进行中，不能退（7.11：功能做到一半时只能在修补版之间换）。什么都没改。'
                       '可以：停下等修好的修补版出来，用 sop self upgrade <提交编号> 换上；'
                       '或者放弃这个功能（sop feature drop，做到现在的内容全部丢掉），再退回。')
    print(f'项目 {p.name} 的工具包版本：现在 {cur[:8]}，上一个 {prev[:8]}（{"修补版" if kind == "patch" else "大版本"}）。'
          '退回去：和升级一样改主线上 sop.json 的声明、走 PR 和检查。')
    return switch(p, sop, prev, prev_dir, kind, f, human, back=True)


def switch(p, sop, target, new_dir, kind, f, human, back=False):
    """把主线 sop.json 声明的版本换成 target（升级和退回共用，7.11）：开 upgrade/<版本>-<序号> 分支、写放行、走 PR 和检查、合并；
    有进行中的功能（只可能是修补版）时把主线合进功能分支、进行中的工单分支跟上。"""
    from . import steps
    from .engine import Engine
    verb = '退回' if back else '升级'
    eng = Engine(p, human, None)
    name = None
    for n in range(1, 1000):
        cand = f'upgrade/{target[:8]}-{n}'
        try:
            p.journal.append(J.register_name(cand, kind='upgrade'), J.event('project', None, 'register', what='upgrade', branch=cand,
                                                                            to=target, kind=kind, back=back))
            name = cand
            break
        except J.NameTaken:
            continue
    wt = name.replace('/', '-')
    p.fetch('main')
    if not (p.root / wt).is_dir():
        p.wt_new(name, 'origin/main')
    w = p.root / wt
    # 特权侧自己生成的内容：新的 sop.json；同步检查流程（和新版本工具包里的逐字一致）
    sop2 = dict(sop, toolkit={**sop['toolkit'], 'version': target})
    (w / 'sop.json').write_text(json.dumps(sop2, ensure_ascii=False, indent=1) + '\n')
    src = new_dir / 'templates' / 'project' / '.github' / 'workflows'
    for fn in os.listdir(src):
        shutil.copy(src / fn, w / '.github' / 'workflows' / fn)
    g = p.wgit(wt)
    g('add', '-A')
    changed = [x for x in g('diff', '--cached', '--name-only').splitlines() if x]
    rel = []
    for path in changed:
        blob = g('rev-parse', f':{path}')
        if path.startswith('.github/workflows/') and steps.blob_of_file(src / os.path.basename(path)) != blob:
            raise SopError(f'{path} 和新版本工具包里的不一样，不写放行')
        rel.append(J.release(name, path, blob, f'工具包{verb}'))
    p.journal.append(*rel)                        # 先写放行，再推送（6.4）
    g('commit', '-q', '-m', f'chore: 工具包{verb}到 {target[:8]}（{ "修补版" if kind == "patch" else "大版本"}）')
    steps.push(eng, name)
    p.wt('pr', '--draft', '--base', 'main', '--title', f'chore: 工具包{verb}到 {target[:8]}', cwd=w)   # 先草稿再转正式，F19 才认（6.4）
    n = steps.gh_json(eng, 'pr', 'list', '--state', 'open', '--head', name, '--json', 'number')[0]['number']
    p.gh('pr', 'ready', str(n), check=False)
    st, line, head = steps.wait_checks(eng, n, steps.NAMES, True)
    if st != 'ok':
        raise SopError(f'{verb}的 PR 没过 GitHub 检查：{line}')
    if sop.get('visibility') == 'public':
        p.gh('pr', 'merge', str(n), '--squash')
    else:
        ans = human.ask('project', 'upgrade', f'{verb}的 PR 检查都过了，请到网页上点合并：{steps.pr_view(eng, n)["url"]}', {'choices': ['点好了']})
        if ans.get('answer') != '点好了':
            raise SopError('还没在网页上点合并')
    p.wt_remove(name)
    if f and not p.git.ok('ls-remote', '--exit-code', '--heads', 'origin', f.branch):
        f = None    # 功能刚开、F1 还没建功能分支（3-43 碰到的）：没有要跟上的，F1 以后从新的主线建
    if f:   # 修补版在功能进行中换上：主线合进功能分支，进行中的工单分支跟上
        p.fetch('main', f.branch)
        steps.ff_feature(eng, f)
        fg = p.wgit(f.wt)
        with p.gitlock:
            r = fg.run('merge', '--no-edit', '-q', 'refs/remotes/origin/main', check=False)
            if r.returncode:
                fg('merge', '--abort', check=False)
                raise SopError('把主线合进功能分支时有冲突，已停下。请启动维修窗口。')
        steps.push(eng, f.branch)
        _, ts = state.view(p.flows, f, eng.events(f))
        for t, pos in ts.values():
            if pos.status not in ('done', 'dropped') and (p.root / t.wt).is_dir():
                p.wt('sync', '--merge', cwd=p.root / t.wt)
    p.journal.append(J.event('project', None, 'note', kind=f'工具包{verb}', to=target, change=kind))
    p.journal.close()
    print(f'工具包已{verb}到 {target[:8]}（{"修补版" if kind == "patch" else "大版本"}）。执行 sop 接着做。')
    return 0


def rollback_machine():
    """不在项目里的 sop self rollback：项目外面的命令（sop machine …、sop project new/clone、sop self report）用的版本
    （versions/latest）退回上一个。项目里用哪个版本由主线 sop.json 定，这里不管。"""
    st = latest_stack()
    if not st:
        raise SopError('还没有安装任何工具包版本，没有可以退的。')
    cur = st[-1]
    if len(st) < 2:
        raise SopError(f'没有上一个版本可以退：项目外面一直用的就是现在这个工具包版本 {cur[:8]}'
                       '（或者之前用过的都已经退回过了）。')
    prev = st[-2]
    prev_dir, why = installed_ok(prev)
    if not prev_dir:
        raise SopError(f'上一个版本是 {prev[:8]}，可是{why}，退不回去。什么都没改。工具包只从本机已经装好的版本里退，不联网下载。')
    write_launcher(prev)
    print(f'项目外面用的工具包版本已从 {cur[:8]} 退回到 {prev[:8]}（{prev_dir}）。'
          '项目里用哪个版本由项目主线上的 sop.json 定，要退项目的版本，到项目目录里再执行一次 sop self rollback。')
    return 0


def rollback(argv, cwd):
    """sop self rollback：在项目里退项目的版本，不在项目里退项目外面用的版本。"""
    if argv:
        print('用法：sop self rollback（在项目目录里退这个项目用的工具包版本；在项目外面退项目外面用的版本）')
        return 2
    from .project import Project, find_root
    try:
        root = find_root(cwd)
    except SopError:
        return rollback_machine()
    p = Project(root)
    from .cli import human
    from .locks import ProjectLock
    with ProjectLock(p.name):
        return rollback_project(p, human(p, True))


def cli(argv, p=None):
    if argv[:1] in (['bootstrap'], ['install']) and len(argv) == 3:
        d = install(argv[1], argv[2])
        write_launcher(argv[2])
        print(f'已安装工具包版本 {argv[2][:8]} 到 {d}')
        return 0
    if argv[:1] == ['upgrade'] and len(argv) == 2 and p:
        from .cli import human
        from .locks import ProjectLock
        with ProjectLock(p.name):
            return upgrade(p, argv[1], human(p, True))
    print('用法：sop self upgrade <提交编号>')
    return 2
