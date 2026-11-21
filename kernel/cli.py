"""流程命令 sop 的入口（设计书 8.5）。第二段做了推进流程要用的几条；其余（机器、项目、备份、维修……）第三段及以后。"""
import os
import re
import sys

from . import cost, journal as J, precheck, state
from .errors import SopError
from .human import NoHuman, ScriptedHuman, TtyHuman
from .project import Project, find_root


def adapter_name(p=None):
    """流程引擎用哪个 AI 工具适配器（3-29）：环境变量 SOP_AI（只给流程沙箱、自测用）→ 主线 sop.json 的 ai.tool（10.3 的角色配置，
    第 1 期所有角色用同一个工具）→ 默认 claude（第 1 期只有 Claude Code）。"""
    from adapters import ai
    name = os.environ.get('SOP_AI')
    if name:
        if name not in ai.ADAPTERS:
            raise SopError(f'环境变量 SOP_AI={name}：没有这个 AI 工具适配器（有：{"、".join(ai.ADAPTERS)}）')
        return name
    sop = {}
    if p is not None:
        try:
            sop = p.sop_json(fetch=False)
        except Exception:    # noqa: BLE001  主线还没有 sop.json（例如还没推送过）：按默认
            sop = {}
    want = (sop.get('ai') or {}).get('tool') if isinstance(sop.get('ai'), dict) else None
    if want is None:
        return ai.DEFAULT
    if want not in ai.REAL:
        raise SopError(f'主线 sop.json 里 ai.tool 写的是 {want!r}，第 1 期只能是：{"、".join(ai.REAL)}')
    return want


def adapter(p=None):
    from adapters import ai
    return ai.load(adapter_name(p))


def human(p, interactive):
    s = os.environ.get('SOP_HUMAN_SCRIPT')
    if s:
        return ScriptedHuman(p.name, s)
    return TtyHuman() if interactive and sys.stdin.isatty() else NoHuman()


def run_engine(p, interactive=False):
    from machine import syscheck
    if not syscheck.gate():        # 系统升级了先重跑隔离自检，没通过就停下（4.5，3-07）
        return 1
    from .engine import Engine
    a = adapter(p)
    remind = a.reminder()          # 版本和上次真实 AI 演练的不一样（或还没演练过）：每次启动都提醒，流程照常（10.1）
    if remind:
        print(f'提醒：{remind}')
    st = Engine(p, human(p, interactive), a).run()
    return 0 if st in ('done', 'waiting', 'idle') else (3 if st == 'busy' else 1)


def status(p):
    p.journal.fetch()
    f = state.current_feature(p.journal.read(['project'], fetch=False))
    if not f:
        print('现在没有进行中的功能'); return 0
    evs = p.journal.read(['project', f'feature/{f.name}'], fetch=False)
    fpos, ts = state.view(p.flows, f, evs)
    print(f'功能 {f.name}：在 {fpos.pos}（{fpos.status}），已花 {cost.total(evs):.2f} 美元（工具报告的金额）')
    for tid, (t, pos) in ts.items():
        print(f'  工单 {tid}：在 {pos.pos}（{pos.status}）')
    return 0


def show_cost(p):
    p.journal.fetch()
    tip = p.journal.tip()
    dirs = sorted({'/'.join(x.split('/')[1:3]) for x in p.git('ls-tree', '-r', '--name-only', tip, 'events/').splitlines()})
    evs = p.journal.read(dirs or ['project'], fetch=False)
    by = {}
    for e in evs:
        if e.get('cost'):
            by[e['scope']] = by.get(e['scope'], 0) + float(e['cost'])
    for k, v in sorted(by.items()):
        print(f'{k}：{v:.2f} 美元')
    print(f'合计：{cost.total(evs):.2f} 美元（工具报告的金额，不是服务后台实际扣的钱）')
    for e in evs:
        if e.get('kind') == '花费提醒':
            print('提醒过：' + e['text'])
    return 0


def feature_new(p, name):
    """开始一个功能：名字带序号，开分支之前查日志分支，确认这个名字从来没用过（6.4，v0.9）。"""
    if not re.match(r'^[a-z0-9][a-z0-9-]{0,40}$', name):
        raise SopError('功能名只能用小写字母、数字和「-」')
    from .locks import ProjectLock
    with ProjectLock(p.name):
        p.journal.fetch()
        if state.current_feature(p.journal.read(['project'], fetch=False)):
            raise SopError('已经有一个进行中的功能。第一版一个项目一次只做一个功能（1.2）。')
        for n in range(1, 1000):
            full = f'{name}-{n}'
            try:
                p.journal.append(J.register_name(f'feat/{full}', kind='feature'),
                                 J.event('project', None, 'register', what='feature', feature=full))
                break
            except J.NameTaken:
                continue
        p.journal.close()
    print(f'开始功能 {full}（分支 feat/{full}）。执行 sop 开始。')
    return 0


def feature_drop(p, yes):
    from .engine import Engine
    from .locks import ProjectLock
    from . import steps
    with ProjectLock(p.name):
        p.journal.fetch()
        f = state.current_feature(p.journal.read(['project'], fetch=False))
        if not f:
            raise SopError('现在没有进行中的功能')
        if not yes:
            raise SopError(f'放弃功能 {f.name} 会关掉它的 PR、删掉它的目录和分支，做到现在的内容全部丢掉。确认就执行 sop feature drop --yes')
        eng = Engine(p, NoHuman(), adapter(p))
        _, ts = state.view(p.flows, f, eng.events(f))
        for t, pos in ts.values():
            if pos.status not in ('done', 'dropped'):
                steps.drop_ticket(eng, f, t, '功能放弃')
        n = steps.feature_pr(eng, f)
        if n and steps.pr_view(eng, n)['state'] == 'OPEN':
            p.gh('pr', 'close', str(n), '--delete-branch')
        if (p.root / f.wt).is_dir():
            p.wt_remove(f.branch, done=False)
        p.journal.append(J.event(f.scope, None, 'drop', reason='小白放弃了这个功能'),
                         J.event('project', None, 'note', kind='功能放弃', feature=f.name))
        p.journal.close()
    print(f'功能 {f.name} 已放弃')
    return 0


def init_project(p):
    """项目初始化里特权侧的两样（I6 建日志分支；登记 .git/config 的指纹）。正式的 sop project new 在第三段。"""
    p.journal.init_branch()
    precheck.record(p.name, p.root)
    print('日志分支已建，.git/config 的指纹已记下')
    return 0


def main(argv):
    try:
        if argv[:2] == ['self', 'bootstrap'] or argv[:2] == ['self', 'install']:
            from . import version
            return version.cli(argv[1:])
        if argv[:1] == ['machine']:
            from machine.cli import main as machine_main
            return machine_main(argv[1:])
        if argv[:2] == ['project', 'new']:      # 不在项目里也能用（7.2）
            from . import projectnew
            return projectnew.cli(argv[2:])
        if argv[:2] == ['project', 'clone']:    # 换了电脑、继续旧项目（4.6、4.7）
            from . import projectclone
            return projectclone.cli(argv[2:])
        p = Project(find_root(os.getcwd()))
        if not argv:
            return run_engine(p)
        cmd = argv[0]
        if cmd in ('answer', 'chat'):
            return run_engine(p, interactive=True)
        if cmd == 'status':
            return status(p)
        if cmd == 'cost':
            return show_cost(p)
        if argv[:2] == ['feature', 'new'] and len(argv) == 3:
            return feature_new(p, argv[2])
        if argv[:2] == ['feature', 'drop']:
            return feature_drop(p, '--yes' in argv)
        if cmd == 'init-project':
            return init_project(p)
        if cmd == 'self':
            from . import version
            return version.cli(argv[1:], p)
        print(f'不认识的命令：sop {" ".join(argv)}')
        return 2
    except SopError as e:
        print(str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
