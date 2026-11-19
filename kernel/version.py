"""工具包的版本（设计书 3.2、7.11、16.5）：安装、启动器、修补版和大版本、升级。

- 版本用提交编号标识。修补版只改脚本、检查、任务包模板，流程定义和技能副本不变；大版本改了流程定义或技能版本。
- 判断「能不能在功能进行中换上」不靠版本自己的声明，按实际内容比：flows/ 和 skills/ 两个版本逐字一致才算修补版。
- 有进行中的功能（或还没合并的产品规划）时不升级大版本；修补版可以换上：升级 PR 合进主线后，特权侧把主线合进功能分支（只做合并，
  不运行代码），再让进行中的工单分支跟上（wt sync --merge）。步骤编号没变，事件日志照样回放。
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
    home = paths.sop_home()
    _write_if_changed(home / 'launcher.py', (paths.versions_dir() / version / 'kernel' / 'launcher.py').read_text())
    _write_if_changed(home / 'sop', LAUNCHER_SH, 0o755)
    _write_if_changed(paths.versions_dir() / 'latest', version)


def _write_if_changed(f, text, mode=0o644):
    """内容没变就不写（第零步可以重复跑，修改时间也不动）。"""
    try:
        if f.read_text() == text and (f.stat().st_mode & 0o777) == mode:
            return
    except FileNotFoundError:
        pass
    f.write_text(text)
    os.chmod(f, mode)


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


def upgrade(p, target, human):
    """sop self upgrade <提交编号>。"""
    from . import steps
    from .engine import Engine
    sop = p.sop_json()
    cur = sop['toolkit']['version']
    if target == cur:
        print('已经是这个版本'); return 0
    new_dir = install(sop['toolkit']['repo'], target)
    cur_dir = paths.versions_dir() / cur if (paths.versions_dir() / cur).exists() else TOOLKIT
    kind = classify(cur_dir, new_dir)
    f = in_progress(p)
    if kind == 'major' and f:
        raise SopError(f'新版本改了流程定义或技能（大版本）。功能 {f.name} 还在进行中，不能换大版本（7.11）。'
                       '先把这个功能做完，或者放弃它（sop feature drop），再升级。')
    eng = Engine(p, human, None)
    name = None
    for n in range(1, 1000):
        cand = f'upgrade/{target[:8]}-{n}'
        try:
            p.journal.append(J.register_name(cand, kind='upgrade'), J.event('project', None, 'register', what='upgrade', branch=cand,
                                                                            to=target, kind=kind))
            name = cand
            break
        except J.NameTaken:
            continue
    wt = name.replace('/', '-')
    p.fetch('main')
    if not (p.root / wt).is_dir():
        p.wt('new', name, 'origin/main')
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
        rel.append(J.release(name, path, blob, '工具包升级'))
    p.journal.append(*rel)                        # 先写放行，再推送（6.4）
    g('commit', '-q', '-m', f'chore: 工具包升级到 {target[:8]}（{ "修补版" if kind == "patch" else "大版本"}）')
    steps.push(eng, name)
    p.wt('pr', '--draft', '--base', 'main', '--title', f'chore: 工具包升级到 {target[:8]}', cwd=w)   # 先草稿再转正式，F19 才认（6.4）
    n = steps.gh_json(eng, 'pr', 'list', '--state', 'open', '--head', name, '--json', 'number')[0]['number']
    p.gh('pr', 'ready', str(n), check=False)
    st, line, head = steps.wait_checks(eng, n, steps.NAMES, True)
    if st != 'ok':
        raise SopError(f'升级的 PR 没过 GitHub 检查：{line}')
    if sop.get('visibility') == 'public':
        p.gh('pr', 'merge', str(n), '--squash')
    else:
        ans = human.ask('project', 'upgrade', f'升级的 PR 检查都过了，请到网页上点合并：{steps.pr_view(eng, n)["url"]}', {'choices': ['点好了']})
        if ans.get('answer') != '点好了':
            raise SopError('还没在网页上点合并')
    p.wt('done', name)
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
    p.journal.append(J.event('project', None, 'note', kind='工具包升级', to=target, change=kind))
    p.journal.close()
    print(f'工具包已升级到 {target[:8]}（{"修补版" if kind == "patch" else "大版本"}）。执行 sop 接着做。')
    return 0


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
