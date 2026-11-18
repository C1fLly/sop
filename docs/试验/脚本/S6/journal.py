#!/usr/bin/env python3
"""试验 S6：事件日志。只用标准库和 git 命令。
- 事件存在单独的分支 sop/journal 上，一个事件一个文件，一次提交只加一个文件。
- 写入时不需要把这条分支检出成目录：直接造一个提交，接在远程最新的提交后面，再推送；被别人抢先了就重来。
- 当前位置由「按提交顺序读出全部事件，再照流程定义走一遍」得出。
"""
import json, os, subprocess, sys, tempfile, time, tomllib, uuid

BR = 'refs/heads/sop/journal'; TRACK = 'refs/remotes/origin/sop/journal'


def git(gitdir, *a, inp=None, env=None, check=True):
    p = subprocess.run(['git', '--git-dir', gitdir, *a], input=inp, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and p.returncode:
        raise RuntimeError(f'git {" ".join(a)}: {p.stderr.strip()}')
    return p.stdout.strip() if check else p


def fetch(gitdir):
    for _ in range(50):
        p = git(gitdir, 'fetch', '-q', '--no-write-fetch-head', 'origin', f'+{BR}:{TRACK}', check=False)
        if p.returncode == 0:
            return
        time.sleep(0.02)   # 多半是另一个进程正好在更新同一个指针，稍等重试
    raise RuntimeError('fetch 一直失败: ' + p.stderr)


def append(gitdir, event):
    """写入一个事件并推送。返回 (文件名, 重试次数)。"""
    event = dict(event, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'), id=uuid.uuid4().hex)
    name = f"events/{event['scope'].replace('/', '_')}/{time.time_ns()}-{event['id'][:8]}.json"
    blob = git(gitdir, 'hash-object', '-w', '--stdin', inp=json.dumps(event, ensure_ascii=False, indent=1))
    who = {'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@example.invalid', 'GIT_COMMITTER_NAME': 'sop', 'GIT_COMMITTER_EMAIL': 'sop@example.invalid'}
    for retry in range(200):
        fetch(gitdir)
        tip = git(gitdir, 'rev-parse', TRACK)
        with tempfile.TemporaryDirectory() as td:
            ix = {'GIT_INDEX_FILE': td + '/index'}
            git(gitdir, 'read-tree', tip, env=ix)
            git(gitdir, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{name}', env=ix)
            tree = git(gitdir, 'write-tree', env=ix)
        commit = git(gitdir, 'commit-tree', tree, '-p', tip, '-m', f"{event['scope']} {event['step']} {event['type']}", env=who)
        p = git(gitdir, 'push', '-q', 'origin', f'{commit}:{BR}', check=False)   # 不是强制推送：别人抢先了就会被拒绝
        if p.returncode == 0:
            return name, retry
        time.sleep(0.01 * (1 + retry % 5))
    raise RuntimeError('推送一直被拒绝')


def read_events(gitdir, do_fetch=True):
    """按提交顺序读出全部事件。"""
    if do_fetch:
        fetch(gitdir)
    out = git(gitdir, 'log', '--reverse', '--format=%H', '--name-only', '--diff-filter=A', TRACK)
    events = []
    commit = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if '/' not in line and len(line) == 40:
            commit = line; continue
        if line.startswith('events/'):
            ev = json.loads(git(gitdir, 'show', f'{commit}:{line}'))
            ev['_commit'] = commit; ev['_file'] = line; events.append(ev)
    return events


def replay(flowdef, kind, events):
    """照流程定义把一个范围（一张工单或一个功能）的事件走一遍，得出现在在哪一步。"""
    steps = {s['id']: s for s in flowdef['flow'][kind]}
    main = [s['id'] for s in flowdef['flow'][kind] if not s.get('side')]

    def nxt(sid):
        s = steps[sid]
        if s.get('goto'):
            return s['goto']
        i = main.index(sid)
        return main[i + 1] if i + 1 < len(main) else 'END'

    pos = main[0]; running = None; attempts = {}; fails = {}; confirms = {}; skipped = []; status = 'ready'; cost = 0.0; unknown = 0
    for ev in events:
        t, sid = ev['type'], ev['step']
        cost += ev.get('cost', 0)
        if t == 'worktree':      # 登记类事件：只记事实，不改变位置
            continue
        if sid not in steps:     # 流程定义里没有的步骤：不猜，记下个数，位置不动
            unknown += 1; continue
        if t == 'start':
            running = sid; attempts[sid] = attempts.get(sid, 0) + 1
        elif t == 'done':
            running = None; pos = nxt(sid)
        elif t == 'skipped':
            skipped.append(sid); pos = nxt(sid)
        elif t == 'confirm':
            confirms[sid] = ev.get('commit'); pos = nxt(sid)
        elif t == 'failed':
            running = None; fails[sid] = fails.get(sid, 0) + 1
            target = steps[sid].get('on_fail')
            while target and attempts.get(target, 0) >= steps[target].get('max_attempts', 10**9):
                target = steps[target].get('on_exhausted')
            pos = target or sid
        elif t == 'reopen':
            confirms.pop(ev['target'], None); pos = ev['target']
        elif t == 'drop':
            status = 'dropped'
    if running:
        status = 'interrupted'; pos = running
    elif status != 'dropped':
        status = 'done' if pos == 'END' else ('stopped' if steps.get(pos, {}).get('stop') else 'ready')
    return {'pos': pos, 'status': status, 'attempts': attempts, 'fails': fails, 'confirms': confirms, 'skipped': skipped, 'cost': round(cost, 2), 'unknown': unknown}


def positions(gitdir, flowdef, do_fetch=True):
    by = {}
    for ev in read_events(gitdir, do_fetch):
        by.setdefault(ev['scope'], []).append(ev)
    return {sc: replay(flowdef, 'ticket' if sc.startswith('ticket/') else 'feature', evs) for sc, evs in sorted(by.items())}


if __name__ == '__main__':
    # 给并行测试用：journal.py burst <gitdir> <scope> <个数>
    _, cmd, gitdir, scope, n = sys.argv
    tot = 0
    for i in range(int(n)):
        _, r = append(gitdir, {'scope': scope, 'step': f'X{i}', 'type': 'done'}); tot += r
    print(tot)
