#!/usr/bin/env python3
"""隔离自检（设计书 6.2 的四条要求、6.3 的表、16.2）。不需要管理员权限，不改这台电脑的任何东西：
在 /tmp 下造一个和 wt 一样结构的假项目，对每一种放法在受限环境里逐项试，和 6.3 那张表要求的对照。

用法：uv run python -m runner.selftest [--keep]
专用 Docker 那几项（三种挂法改 .shared/hooks、.git/config、.git/hooks；看不到 state 和通道文件）在 runner/docker/selftest_docker.py，
要在虚拟机里跑。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from kernel import paths  # noqa: E402
from runner import aistate, placement, sandbox  # noqa: E402

PROBE = pathlib.Path(__file__).resolve().parent / 'probe.py'
ID = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x.invalid', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x.invalid'}
SECRET_ENV = ('GH_TOKEN', 'GITHUB_TOKEN', 'SSH_AUTH_SOCK', 'DBUS_SESSION_BUS_ADDRESS', 'GNOME_KEYRING_CONTROL', 'XDG_RUNTIME_DIR')


def sh(*a, cwd=None):
    p = subprocess.run([str(x) for x in a], cwd=cwd, capture_output=True, text=True, env={**os.environ, **ID})
    if p.returncode:
        raise RuntimeError(f'{a}: {p.stderr}')
    return p.stdout.strip()


def make_fixture(tmp):
    """假项目：.git（裸仓库）、main、feat-a-1、ticket-a-1-01、别的功能的 feat-b-1；.shared（钩子、.env、cache）。"""
    tmp = pathlib.Path(tmp)
    seed = tmp / 'seed'
    sh('git', 'init', '-q', '-b', 'main', seed)
    (seed / 'README.md').write_text('x\n'); sh('git', 'add', '.', cwd=seed); sh('git', 'commit', '-qm', 'x', cwd=seed)
    R = tmp / 'Project' / 'demo'
    R.mkdir(parents=True)
    sh('git', 'clone', '-q', '--bare', seed, R / '.git')
    g = ['git', f'--git-dir={R / ".git"}']
    sh(*g, 'worktree', 'add', '-q', R / 'main', 'main')
    sh(*g, 'worktree', 'add', '-q', '-b', 'feat/a-1', R / 'feat-a-1', 'main')
    sh(*g, 'worktree', 'add', '-q', '-b', 'ticket/a-1/01', R / 'ticket-a-1-01', 'feat/a-1')
    sh(*g, 'worktree', 'add', '-q', '-b', 'feat/b-1', R / 'feat-b-1', 'main')
    hooks = R / '.shared' / 'hooks'
    hooks.mkdir(parents=True)
    for f in (pathlib.Path(__file__).resolve().parent.parent / 'templates' / 'wt' / 'hooks').iterdir():
        shutil.copy(f, hooks / f.name)
    (R / '.shared' / '.env').write_text('DB_PASSWORD=本机开发用\n')
    (R / '.shared' / 'cache').mkdir()
    other = tmp / 'Project' / 'other'
    other.mkdir(parents=True)
    return R, other


def probe(ctx, actions):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, dir='/tmp') as f:
        json.dump(actions, f)
    ctx.ro = list(ctx.ro) + [str(PROBE), f.name]
    p = sandbox.run(ctx, ['python3', str(PROBE), f.name], timeout=120)
    os.unlink(f.name)
    if p.returncode:
        raise RuntimeError(f'探针在受限环境里跑不起来：{p.stderr[-500:]}')
    return json.loads(p.stdout)


def git_in(wt_dir, *args):
    return {'op': 'run', 'argv': ['git', *args], 'cwd': str(wt_dir)}


def ok_rc(r):
    return isinstance(r, dict) and r['rc'] == 0


def check_kind(R, other, kind):
    """一种放法：逐项试，返回 [(项目, 期望, 实际)]。"""
    gd = R / '.git'
    home = pathlib.Path(os.environ['HOME'])
    runtime = paths.runtime_dir()
    out = pathlib.Path(tempfile.mkdtemp(prefix=f'selftest-out-{kind}-', dir='/tmp'))
    if kind == 'implement_spec':
        W, feat, wname = R / 'feat-a-1', 'a-1', None
    elif kind == 'ticket_impl':
        W, feat, wname = R / 'ticket-a-1-01', 'a-1', 'ticket-a-1-01'
    else:
        W, feat, wname = R / 'feat-a-1', 'a-1', 'feat-a-1'
    reg = gd / 'worktrees' / W.name
    ctx = placement.Ctx(root=R, kind=kind, worktree=wname, feature=feat, out_dir=out, chdir=W)
    can_write = kind != 'readonly'
    can_commit = kind in ('ticket_impl', 'implement_spec')
    rows = [
        # (说明, 动作, 期望结果)
        ('看不到 ~/.ssh', {'op': 'exists', 'path': str(home / '.ssh')}, False),
        ('看不到钥匙串的通道（/run/user/<编号>/bus、keyring）', {'op': 'exists', 'path': f'/run/user/{os.getuid()}/bus'}, False),
        ('看不到 SSH 代理的通道', {'op': 'exists', 'path': f'/run/user/{os.getuid()}/gcr'}, False),
        ('看不到复用 SSH 连接的通道目录', {'op': 'exists', 'path': str(runtime)}, False),
        ('看不到 ~/.config/gh（GitHub 登录）', {'op': 'exists', 'path': str(home / '.config' / 'gh')}, False),
        ('看不到 sop 的状态目录（AI 状态目录、锁、日志）', {'op': 'exists', 'path': str(paths.sop_home() / 'state')}, False),
        ('看不到机器级配置', {'op': 'exists', 'path': str(paths.config_dir())}, False),
        ('看不到别的项目', {'op': 'exists', 'path': str(other)}, False),
        ('写得了工作目录' if can_write else '写不了工作目录', {'op': 'write_dir', 'path': str(W)}, can_write),
        ('工作目录里指向 .git 的小文件只读', {'op': 'write_file', 'path': str(W / '.git')}, False),
        ('.git/config 只读', {'op': 'write_file', 'path': str(gd / 'config')}, False),
        ('.git/hooks 只读', {'op': 'write_dir', 'path': str(gd / 'hooks')}, False),
        ('登记里的 commondir 只读', {'op': 'write_file', 'path': str(reg / 'commondir')}, False),
        ('登记里的 gitdir 只读', {'op': 'write_file', 'path': str(reg / 'gitdir')}, False),
        ('别的工作目录的登记只读', {'op': 'write_dir', 'path': str(gd / 'worktrees' / 'feat-b-1')}, False),
        ('.shared/hooks 改不了', {'op': 'write_file', 'path': str(R / '.shared' / 'hooks' / 'post-create')}, False),
        ('.shared/.env 只读', {'op': 'write_file', 'path': str(R / '.shared' / '.env')}, False),
        ('移动不了 main 的指针', git_in(W, 'update-ref', 'refs/heads/main', 'HEAD'), False),
        ('移得动别的功能的分支指针（7.6 已知的弱点，靠推送前核对「是远程的延续」）' if kind == 'implement_spec' else '移动不了别的功能的分支指针',
         git_in(W, 'update-ref', 'refs/heads/feat/b-1', 'HEAD'), kind == 'implement_spec'),
        ('提交得了' if can_commit else '提交不了（由流程命令提交）',
         git_in(W, 'commit', '--allow-empty', '-qm', '自检'), can_commit),
        ('移得动本功能的工单分支指针' if can_commit else '移不动本功能的工单分支指针',
         git_in(W, 'update-ref', f'refs/heads/ticket/{feat}/99', 'HEAD'), can_commit),
        ('结果目录可写', {'op': 'write_dir', 'path': placement.OUT_MNT}, True),
    ]
    if kind == 'implement_spec':
        rows += [('main 目录只读', {'op': 'write_dir', 'path': str(R / 'main')}, False),
                 ('别的功能的目录只读', {'op': 'write_dir', 'path': str(R / 'feat-b-1')}, False),
                 ('移得动本功能的功能分支指针', git_in(W, 'update-ref', f'refs/heads/feat/{feat}', 'HEAD'), True)]
    else:
        rows += [('看不到别的工作目录', {'op': 'exists', 'path': str(R / 'feat-b-1')}, False)]
    if kind == 'ticket_impl':
        rows += [('移动不了本功能的功能分支指针', git_in(W, 'update-ref', f'refs/heads/feat/{feat}', 'HEAD'), False)]
    res = probe(ctx, [r[1] for r in rows] + [{'op': 'env'}])
    env = res.pop()
    table = []
    for (desc, act, want), got in zip(rows, res):
        actual = ok_rc(got) if act['op'] == 'run' else bool(got)
        table.append((f'{kind}：{desc}', want, actual, got if act['op'] == 'run' and actual != want else None))
    leaked = [k for k in env if k in SECRET_ENV or 'TOKEN' in k or 'SECRET' in k or k.startswith('ANTHROPIC')]
    table.append((f'{kind}：环境变量里没有密钥和通道', [], leaked, None))
    shutil.rmtree(out, ignore_errors=True)
    return table


def check_state_dirs(R):
    """前一个会话往状态目录里写的东西，后一个全新会话读不到（6.3 三、W35）。"""
    rows = []
    tmpl = lambda d: (d / 'settings.json').write_text('{}')   # noqa: E731
    a = aistate.fresh('demo', 'fake', 'T3', tmpl)
    ctx = placement.Ctx(root=R, kind='ticket_impl', worktree='ticket-a-1-01', feature='a-1', home_binds={'.fakeai': a})
    probe(ctx, [{'op': 'mkfile', 'path': os.path.join(os.environ['HOME'], '.fakeai', 'settings.local.json'),
                 'text': '{"hooks": "留话"}'}])
    rows.append(('状态目录：前一个会话确实写进去了（对照）', True, (a / 'settings.local.json').exists(), None))
    aistate.seal(a)
    rows.append(('状态目录：用完封存成只读', True, aistate.sealed(a), None))
    b = aistate.fresh('demo', 'fake', 'T9', tmpl)
    ctx = placement.Ctx(root=R, kind='readonly', worktree='ticket-a-1-01', feature='a-1', home_binds={'.fakeai': b})
    res = probe(ctx, [{'op': 'exists', 'path': os.path.join(os.environ['HOME'], '.fakeai', 'settings.local.json')},
                      {'op': 'exists', 'path': str(a)}])
    rows.append(('状态目录：后一个全新会话读不到前一个留的东西', False, bool(res[0]), None))
    rows.append(('状态目录：后一个会话看不到前一个的状态目录', False, bool(res[1]), None))
    rows.append(('状态目录：现建的不复用旧名字', True, a != b and b.name.startswith('T9-'), None))
    return rows


def check_machine(R):
    rows = [('内核已禁用往终端塞按键（对话步骤的前提）', True, sandbox.tiocsti_disabled(), None)]
    # 对照：这些东西在受限环境外面确实存在，「里面看不到」才有意义。外面也没有的，如实标出来
    home, uid = pathlib.Path(os.environ['HOME']), os.getuid()
    for desc, p in (('~/.ssh', home / '.ssh'), ('钥匙串的通道 /run/user/<编号>/bus', f'/run/user/{uid}/bus'),
                    ('SSH 代理的通道 /run/user/<编号>/gcr', f'/run/user/{uid}/gcr'), ('~/.config/gh', home / '.config' / 'gh'),
                    ('复用 SSH 连接的通道目录', paths.runtime_dir())):
        there = os.path.lexists(p)
        rows.append((f'对照：外面{"看得到" if there else "也没有（这一项在这台电脑上验不到）"} {desc}', there, there, None))
    cfg = subprocess.run(['git', f'--git-dir={R / ".git"}', 'config', '--get', 'extensions.worktreeConfig'], capture_output=True, text=True)
    rows.append(('仓库的公共配置里没开「工作目录专用配置」的扩展', '', cfg.stdout.strip(), None))
    return rows


def run_all(keep=False):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-selftest-', dir='/tmp'))
    old = {k: os.environ.get(k) for k in ('SOP_HOME',)}
    os.environ['SOP_HOME'] = str(tmp / 'sop-home')
    (tmp / 'sop-home' / 'config').mkdir(parents=True)
    try:
        R, other = make_fixture(tmp)
        rows = check_machine(R)
        for k in ('ticket_impl', 'planning', 'std_draft', 'readonly', 'restricted_script', 'implement_spec'):
            rows += check_kind(R, other, k)
        rows += check_state_dirs(R)
        return rows
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        if not keep:
            subprocess.run(['chmod', '-R', 'u+w', str(tmp)])
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    rows = run_all(keep='--keep' in sys.argv)
    bad = [r for r in rows if r[1] != r[2]]
    for desc, want, got, extra in rows:
        print(f'{"符合  " if want == got else "不符合"} {desc}' + ('' if want == got else f'（应为 {want}，实际 {got} {extra or ""}）'))
    print(f'隔离自检：{len(rows)} 项，{len(bad)} 项不符合')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
