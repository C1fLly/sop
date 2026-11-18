#!/usr/bin/env python3
"""第一段 W17：一个进程替大家写事件，攒成一批，一次提交、一次推送。用法：batch.py <gitdir> <一批几个> <几批>"""
import json, os, subprocess, sys, tempfile, time, uuid
BR = 'refs/heads/sop/journal'; TRACK = 'refs/remotes/origin/sop/journal'
WHO = {'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@example.invalid', 'GIT_COMMITTER_NAME': 'sop', 'GIT_COMMITTER_EMAIL': 'sop@example.invalid'}
def git(g, *a, inp=None, env=None, check=True):
    p = subprocess.run(['git', '--git-dir', g, *a], input=inp, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and p.returncode: raise RuntimeError(p.stderr)
    return p.stdout.strip() if check else p
g, n, rounds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
for r in range(rounds):
    t0 = time.time(); evs = [{'scope': f'ticket/b{i}', 'step': 'T5', 'type': 'done', 'id': uuid.uuid4().hex} for i in range(n)]
    blobs = [(git(g, 'hash-object', '-w', '--stdin', inp=json.dumps(e)), f"events/{e['scope'].replace('/', '_')}/{time.time_ns()}-{e['id'][:8]}.json") for e in evs]
    for retry in range(50):
        git(g, 'fetch', '-q', '--no-write-fetch-head', 'origin', f'+{BR}:{TRACK}'); tip = git(g, 'rev-parse', TRACK)
        with tempfile.TemporaryDirectory() as td:
            ix = {'GIT_INDEX_FILE': td + '/i'}; git(g, 'read-tree', tip, env=ix)
            for b, name in blobs: git(g, 'update-index', '--add', '--cacheinfo', f'100644,{b},{name}', env=ix)
            tree = git(g, 'write-tree', env=ix)
        c = git(g, 'commit-tree', tree, '-p', tip, '-m', f'{n} 个事件', env=WHO)
        if git(g, 'push', '-q', 'origin', f'{c}:{BR}', check=False).returncode == 0: break
    print(f'一批 {n} 个：{time.time() - t0:.1f} 秒（重来 {retry} 次）', flush=True)
