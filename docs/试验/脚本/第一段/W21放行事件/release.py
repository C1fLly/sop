#!/usr/bin/env python3
"""第一段 W21：特权侧写放行事件（试验版）。照 S6 的写法：不检出日志分支，直接造一个只多一个文件的提交接在远程最新的后面，不强制推送，被抢先就重来。
用法：release.py <本地仓库的 .git> <归属> <路径> <内容指纹|deleted> <情形>
序号：同一归属、同一路径从 1 递增；写的时候读出现有最大序号加一，重来时重新读。"""
import hashlib, json, os, subprocess, sys, tempfile, time

BR = 'refs/heads/sop/journal'; TRACK = 'refs/remotes/origin/sop/journal'
WHO = {'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@example.invalid', 'GIT_COMMITTER_NAME': 'sop', 'GIT_COMMITTER_EMAIL': 'sop@example.invalid'}

def git(gitdir, *a, inp=None, env=None, check=True):
    p = subprocess.run(['git', '--git-dir', gitdir, *a], input=inp, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and p.returncode:
        raise RuntimeError(f'git {" ".join(a)}: {p.stderr.strip()}')
    return p.stdout.strip() if check else p

def write(gitdir, owner, path, blob, case):
    d = f"releases/{owner.replace('/', '__')}/{hashlib.sha1(path.encode()).hexdigest()[:16]}"
    for retry in range(100):
        git(gitdir, 'fetch', '-q', '--no-write-fetch-head', 'origin', f'+{BR}:{TRACK}')
        tip = git(gitdir, 'rev-parse', TRACK)
        names = git(gitdir, 'ls-tree', '--name-only', tip, d + '/').splitlines()
        seq = max([int(n.rsplit('/', 1)[-1][:-5]) for n in names] or [0]) + 1
        ev = {'type': 'release', 'owner': owner, 'path': path, 'blob': blob, 'seq': seq, 'case': case, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        b = git(gitdir, 'hash-object', '-w', '--stdin', inp=json.dumps(ev, ensure_ascii=False, indent=1))
        with tempfile.TemporaryDirectory() as td:
            ix = {'GIT_INDEX_FILE': td + '/index'}
            git(gitdir, 'read-tree', tip, env=ix)
            git(gitdir, 'update-index', '--add', '--cacheinfo', f'100644,{b},{d}/{seq:06d}.json', env=ix)
            tree = git(gitdir, 'write-tree', env=ix)
        c = git(gitdir, 'commit-tree', tree, '-p', tip, '-m', f'release {owner} {path} #{seq}', env=WHO)
        if git(gitdir, 'push', '-q', 'origin', f'{c}:{BR}', check=False).returncode == 0:
            return seq, retry
        time.sleep(0.2)
    raise RuntimeError('推送一直被拒绝')

if __name__ == '__main__':
    _, gitdir, owner, path, blob, case = sys.argv
    seq, retry = write(gitdir, owner, path, blob, case)
    print(f'放行已写：{owner} {path} {blob[:12]} 序号 {seq}（重来 {retry} 次）')
