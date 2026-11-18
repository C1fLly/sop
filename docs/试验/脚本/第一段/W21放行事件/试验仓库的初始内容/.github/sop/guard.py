#!/usr/bin/env python3
"""第一段 W21：守门检查。定义取自主线（工作目录里检出的就是主线）。
只把 PR 的提交当数据读：取它改了哪些文件、受保护文件现在的内容指纹；从不检出、不运行 PR 里的任何东西。
放行事件：日志分支 sop/journal 最新一份里的 releases/<归属>/<路径的散列>/<序号>.json，同一归属同一路径只认序号最大的那条。
受保护清单：只从主线取（工具包基础清单 + 主线 sop.json 声明的档案的清单）；PR 改了 sop.json 且新内容有放行时，再并入新 sop.json 声明的档案的清单。"""
import fnmatch, hashlib, json, os, subprocess, sys, time

T0 = time.time()
def git(*a):
    p = subprocess.run(['git', *a], capture_output=True, text=True)
    if p.returncode:
        sys.exit(f'守门检查出错（按不通过算）：git {" ".join(a)}: {p.stderr.strip()}')
    return p.stdout

ev = json.load(open(os.environ['GITHUB_EVENT_PATH']))
pr = ev['pull_request']; num = pr['number']; base = pr['base']['ref']; head_ref = pr['head']['ref']
owner = head_ref if base == 'main' else base          # 工单 PR 的归属是它的目标（功能分支）；目标是主线的归属是它自己
print(f'PR #{num}: {head_ref} -> {base}；归属 {owner}；主线检出 {git("rev-parse", "HEAD").strip()[:12]}')

git('fetch', '-q', '--no-tags', '--filter=blob:none', 'origin', f'+refs/pull/{num}/head:refs/sop/prhead', f'+refs/heads/{base}:refs/sop/base')
mb = git('merge-base', 'refs/sop/base', 'refs/sop/prhead').strip()
changes = [l.split('\t', 1) for l in git('diff', '--name-status', '--no-renames', mb, 'refs/sop/prhead').splitlines() if l]

t1 = time.time()
git('fetch', '-q', '--no-tags', '--depth=1', 'origin', '+refs/heads/sop/journal:refs/sop/journal')   # 只取最新一份，不取历史
key = owner.replace('/', '__')
files = [f for f in git('ls-tree', '-r', '--name-only', 'refs/sop/journal', f'releases/{key}/').splitlines() if f.endswith('.json')]
best = {}
if files:
    out = subprocess.run(['git', 'cat-file', '--batch'], input=''.join(f'refs/sop/journal:{f}\n' for f in files).encode(), capture_output=True).stdout
    i = 0
    while i < len(out):   # 按字节切：cat-file 给的大小是字节数（v1 按字符切，遇到中文就错位）
        hdr_end = out.index(b'\n', i); size = int(out[i:hdr_end].split()[2]); body = out[hdr_end + 1: hdr_end + 1 + size]; i = hdr_end + 2 + size
        r = json.loads(body.decode('utf-8'))
        if r.get('owner') == owner and (r['path'] not in best or r['seq'] > best[r['path']]['seq']):
            best[r['path']] = r
n_all = len(git('ls-tree', '-r', '--name-only', 'refs/sop/journal').splitlines())
print(f'日志分支最新一份共 {n_all} 个文件；本归属的放行 {len(files)} 条，涉及 {len(best)} 个路径；读日志用时 {time.time() - t1:.2f} 秒')

def load(p):
    return [l.strip() for l in open(p, encoding='utf-8') if l.strip() and not l.startswith('#')] if os.path.exists(p) else []
pats = load('.github/sop/protected-base.txt')
main_prof = json.load(open('sop.json')).get('profile', 'none')
pats += load(f'.github/sop/profiles/{main_prof}.txt')

def protected(path, pats):
    for p in pats:
        if p.endswith('/**'):
            if path.startswith(p[:-2]): return True
        elif '/' in p:
            if fnmatch.fnmatchcase(path, p): return True
        elif fnmatch.fnmatchcase(path.rsplit('/', 1)[-1], p):
            return True
    return False

def now_blob(st, path):
    return 'deleted' if st == 'D' else git('rev-parse', f'refs/sop/prhead:{path}').strip()

def released(path, blob):
    r = best.get(path)
    return r is not None and r['blob'] == blob, r

# PR 改了 sop.json：新内容有放行才算数，算数时并入新档案的清单
for st, path in changes:
    if path == 'sop.json' and st != 'D':
        ok, _ = released(path, now_blob(st, path))
        if ok:
            new_prof = json.loads(git('show', 'refs/sop/prhead:sop.json')).get('profile', 'none')
            if new_prof != main_prof:
                pats += load(f'.github/sop/profiles/{new_prof}.txt')
                print(f'PR 改了 sop.json 且有放行：并入档案 {new_prof} 的清单')

bad = []
for st, path in changes:
    if not protected(path, pats):
        continue
    blob = now_blob(st, path)
    ok, r = released(path, blob)
    if ok:
        print(f'  放行  {path}  {blob[:12]}  序号 {r["seq"]}（{r.get("case", "")}）')
    else:
        why = '没有放行' if r is None else f'指纹对不上最后一条放行（最后一条序号 {r["seq"]}，放行的是 {r["blob"][:12]}，现在是 {blob[:12]}）'
        bad.append(f'{path}：{why}')
print(f'改动 {len(changes)} 个文件，受保护的 {sum(protected(p, pats) for _, p in changes)} 个；总用时 {time.time() - T0:.2f} 秒')
if bad:
    print('守门检查不通过：'); [print('  ' + b) for b in bad]; sys.exit(1)
print('守门检查通过')
