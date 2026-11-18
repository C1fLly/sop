#!/usr/bin/env python3
"""窄接口的特权侧一头（S7 试验的最小实现）。在受限环境外面运行，手里有推送的权限。

只认三种请求：new-worktree、merged、done。逐个校验、执行、记入日志。
不运行任何项目代码：只调用 wt 和 git，git 一律明说仓库在哪、关掉钩子。
"""
import json, os, re, subprocess, sys, time, pathlib
ROOT = pathlib.Path('/tmp/sop-p1-lock/proj'); FEAT = 'demo'
GITDIR = str(ROOT / '.git'); FBR = f'feat/{FEAT}'; FWT = ROOT / f'feat-{FEAT}'
REQ = ROOT / '.shared/broker/requests'; RES = ROOT / '.shared/broker/responses'
LOG = pathlib.Path('/tmp/sop-p1-lock/broker.log'); STATE = pathlib.Path('/tmp/sop-p1-lock/broker-state.json')
STOP = pathlib.Path('/tmp/sop-p1-lock/broker.stop')
PROTECTED = ('CLAUDE.md', 'AGENTS.md', '.claude/', '.agents/', 'docs/agents/', 'sop.json', '.github/')
TICKET_RE = re.compile(r'^(0[1-9]|[1-9][0-9]|fix)$')
WTENV = {**os.environ, 'WT_TEMPLATE': '/home/sanchuanzl/tools/sop/docs/试验/脚本/S9/工具包模板'}
GIT = ['git', f'--git-dir={GITDIR}', '-c', 'core.hooksPath=/dev/null']

def log(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    with LOG.open('a') as f: f.write(line + '\n')
    print(line, flush=True)

def run(cmd, cwd=None, check=False):
    log('＋ ' + ' '.join(cmd) + (f'   （在 {cwd}）' if cwd else ''))
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=WTENV)
    if p.returncode != 0: log(f'   退出码 {p.returncode}：{(p.stderr or p.stdout).strip()[:400]}')
    if check and p.returncode != 0: raise RuntimeError((p.stderr or p.stdout).strip()[:400])
    return p

def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {'worktrees': {}, 'merged': [], 'pushes': [], 'rejected': [], 'done': False}

def save(s): STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1))

def known_tickets():
    # 工单清单取自已经推送到远程的规划（受限侧改不了远程），不看工作目录里的文件
    p = run(GIT + ['ls-tree', '--name-only', f'origin/{FBR}', f'.scratch/{FEAT}/issues/'])
    return {os.path.basename(x)[:2] for x in p.stdout.split('\n') if x.strip()}


def gitfiles_ok(path):
    """设计书 7.6（v0.6 加、第一段验证）：先核对这个工作目录的三个小文件内容符合预期，再去碰它。"""
    path = pathlib.Path(path); name = path.name
    want = {path / '.git': f'gitdir: {GITDIR}/worktrees/{name}',
            pathlib.Path(GITDIR) / 'worktrees' / name / 'commondir': '../..',
            pathlib.Path(GITDIR) / 'worktrees' / name / 'gitdir': f'{path}/.git'}
    for f, w in want.items():
        try: got = f.read_text().strip()
        except Exception as e: return False, f'{f} 读不了：{e}'
        if got != w: return False, f'{f} 的内容被改过（应为 {w!r}，实际 {got[:80]!r}）'
    if run(GIT + ['config', '--get', 'extensions.worktreeConfig']).stdout.strip():
        return False, '仓库的公共配置里被打开了「工作目录专用配置」的扩展'
    return True, ''

def verify_and_push(s, what):
    """核对集成分支，再推送。返回 (ok, 说明)。"""
    tip = run(GIT + ['rev-parse', FBR]).stdout.strip()
    remote = run(GIT + ['rev-parse', f'origin/{FBR}']).stdout.strip()
    # 一、历史延续：本地集成分支必须是远程那条的延续
    if run(GIT + ['merge-base', '--is-ancestor', remote, tip]).returncode != 0:
        return False, '集成分支不是远程分支的延续（历史被改写了），拒绝推送'
    # 二、没有改受保护路径
    changed = run(GIT + ['diff', '--name-only', f'{remote}..{tip}']).stdout.split('\n')
    bad = [c for c in changed if c and any(c == p or c.startswith(p) for p in PROTECTED)]
    if bad:
        return False, '改动了受保护路径，拒绝推送：' + '、'.join(bad[:5])
    if tip == remote:
        return True, f'ok（{what}；集成分支没有新提交，不用推送）'
    p = run(GIT + ['push', 'origin', f'{FBR}:{FBR}'])
    if p.returncode != 0:
        return False, '推送失败：' + (p.stderr or '').strip()[:200]
    s['pushes'].append({'what': what, 'sha': tip, 'time': time.strftime('%H:%M:%S')})
    return True, f'ok（{what}；已推送 {tip[:7]}）'

def handle(req, s):
    kind, t = req.get('kind'), req.get('ticket')
    if kind == 'new-worktree':
        if not isinstance(t, str) or not TICKET_RE.match(t): return False, f'工单编号不合规矩：{t!r}'
        if t != 'fix' and t not in known_tickets(): return False, f'规划里没有编号为 {t} 的工单'
        if t in s['worktrees']: return True, s['worktrees'][t]['path']      # 重复请求：给回同一个目录
        br = f'ticket/{FEAT}/{t}'; path = ROOT / f'ticket-{FEAT}-{t}'
        p = run(['wt', 'new', br, FBR, '--yes'], cwd=str(ROOT))
        if p.returncode != 0 or not path.is_dir(): return False, 'wt new 失败：' + (p.stderr or p.stdout).strip()[-200:]
        s['worktrees'][t] = {'path': str(path), 'branch': br, 'base': run(GIT + ['rev-parse', FBR]).stdout.strip()}
        return True, str(path)
    if kind == 'merged':
        if not isinstance(t, str) or t not in s['worktrees']: return False, f'编号 {t!r} 的工作目录不是经我建的，不认'
        br = s['worktrees'][t]['branch']
        for p in (s['worktrees'][t]['path'], str(FWT)):
            good, why = gitfiles_ok(p)
            if not good: return False, '核对小文件不通过，不碰这个目录：' + why
        btip = run(GIT + ['rev-parse', br]).stdout.strip()
        if btip == s['worktrees'][t]['base']: return False, f'{br} 上没有任何新提交，谈不上合并'
        if run(GIT + ['merge-base', '--is-ancestor', br, FBR]).returncode != 0: return False, f'{br} 还没有合入 {FBR}'
        ok, msg = verify_and_push(s, f'工单 {t} 已合入')
        if ok and t not in s['merged']: s['merged'].append(t)
        return ok, msg
    if kind == 'done':
        for p in [w['path'] for w in s['worktrees'].values()] + [str(FWT)]:
            good, why = gitfiles_ok(p)
            if not good: return False, '核对小文件不通过：' + why
        ok, msg = verify_and_push(s, '全部完成')
        if ok: s['done'] = True
        return ok, msg
    return False, f'不认识的请求种类：{kind!r}'

def main():
    log(f'特权侧开始值守。项目 {ROOT}，功能 {FEAT}')
    while not STOP.exists():
        for f in sorted(REQ.glob('*.json')):
            s = state()
            try:
                req = json.loads(f.read_text()); rid = req.get('id')
                if not isinstance(rid, str) or not re.match(r'^[0-9]+-[0-9a-f]{6}$', rid) or rid + '.json' != f.name:
                    raise ValueError('请求编号不合规矩')
                log(f'收到请求 {req.get("kind")} {req.get("ticket")}（来自 {req.get("cwd")}）')
                ok, msg = handle(req, s)
            except Exception as e:
                rid = f.stem; ok, msg = False, f'请求读不懂：{e}'
            if not ok: s['rejected'].append({'file': f.name, 'why': msg})
            save(s); log(f'回答：{"ok" if ok else "拒绝"} {msg}')
            if re.match(r'^[0-9]+-[0-9a-f]{6}$', rid or ''):
                (RES / (rid + '.json')).write_text(json.dumps({'ok': ok, 'message': msg}, ensure_ascii=False))
            f.rename(f.with_suffix('.handled'))
        time.sleep(0.3)
    log('特权侧停止值守')

if __name__ == '__main__': main()
