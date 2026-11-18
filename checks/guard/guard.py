#!/usr/bin/env python3
"""守门检查（设计书 6.4）。在 GitHub 上由 pull_request_target 触发；本机流程沙箱里由假的 gh 用同样的方式调用。

前提（由检查流程文件做好）：当前目录是主线的检出（有 origin）；本脚本所在的工具包，是主线 sop.json 声明的那个版本。
只把 PR 的提交当数据读：取它改了哪些文件、受保护文件现在的内容指纹；从不检出、不运行 PR 里的任何东西。
放行事件：日志分支 sop/journal 最新一份里的 releases/<归属>/...，同一归属同一路径只认序号最大的那条（只取最新一份，不取历史）。
受保护清单：只从主线 sop.json 声明的工具包版本里取（基础清单 + 声明的档案的清单）；PR 改了 sop.json 且新内容有放行时，
再并入新 sop.json 声明的档案（和工具包版本）的清单。"""
import json
import os
import subprocess
import sys
import tempfile
import time

TOOLKIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLKIT)
from checks import lib  # noqa: E402
from checks.protected import core  # noqa: E402

T0 = time.time()


def g(*a, **kw):
    return lib.git('.git', *a, **kw)


def fetch_toolkit(repo, version, into):
    subprocess.run(['git', 'init', '-q', into], check=True)
    subprocess.run(['git', '-C', into, 'fetch', '-q', '--depth', '1', repo, version], check=True)
    subprocess.run(['git', '-C', into, 'checkout', '-q', 'FETCH_HEAD'], check=True)
    return into


def releases_of(owner):
    g('fetch', '-q', '--no-tags', '--depth=1', 'origin', '+refs/heads/sop/journal:refs/sop/journal')
    key = owner.replace('/', '__')
    files = [f for f in g('ls-tree', '-r', '--name-only', 'refs/sop/journal', f'releases/{key}/').splitlines() if f.endswith('.json')]
    best = {}
    if files:
        out = g('cat-file', '--batch', input=''.join(f'refs/sop/journal:{f}\n' for f in files).encode(), binary=True)
        i = 0
        while i < len(out):   # 按字节切（W21 第一版按字符切，遇到中文就错位）
            j = out.index(b'\n', i); size = int(out[i:j].split()[2]); body = out[j + 1:j + 1 + size]; i = j + 2 + size
            r = json.loads(body.decode('utf-8'))
            if r.get('owner') == owner and (r['path'] not in best or r['seq'] > best[r['path']]['seq']):
                best[r['path']] = r
    return best


def main():
    ev = json.load(open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8'))
    pr = ev['pull_request']; num = pr['number']; base = pr['base']['ref']; head_ref = pr['head']['ref']
    owner = head_ref if base == 'main' else base          # 工单 PR 的归属是它的目标（功能分支）；目标是主线的归属是它自己
    g('fetch', '-q', '--no-tags', 'origin', f'+refs/pull/{num}/head:refs/sop/prhead', f'+refs/heads/{base}:refs/sop/base',
      '+refs/heads/main:refs/sop/main')
    here, main_tip = g('rev-parse', 'HEAD').strip(), g('rev-parse', 'refs/sop/main').strip()
    print(f'PR #{num}: {head_ref} -> {base}；归属 {owner}；检出的主线 {here[:12]}')
    if here != main_tip:   # 第一段结束审查的轻微 2：自查「检出的就是主线最新的那个提交」
        print(f'守门检查不通过：检出的不是主线最新的提交（主线是 {main_tip[:12]}）'); return 1
    sop = json.load(open('sop.json', encoding='utf-8'))
    pats = core.patterns_for(TOOLKIT, sop)
    chg = core.changes('.git', 'refs/sop/base', 'refs/sop/prhead')
    best = releases_of(owner)
    print(f'本归属的放行涉及 {len(best)} 个路径')
    for st, path in chg:     # PR 改了 sop.json：新内容有放行才算数，算数时并入新声明的清单
        if path == 'sop.json' and st != 'D':
            blob = core.blob_of('.git', 'refs/sop/prhead', path)
            if best.get(path, {}).get('blob') == blob:
                new = json.loads(g('show', 'refs/sop/prhead:sop.json'))
                tk = TOOLKIT
                if new.get('toolkit', {}).get('version') != sop.get('toolkit', {}).get('version'):
                    tk = fetch_toolkit(new['toolkit']['repo'], new['toolkit']['version'], tempfile.mkdtemp(prefix='sop-tk-'))
                pats += core.patterns_for(tk, new)
                print('PR 改了 sop.json 且有放行：并入新声明的清单')
    bad, ok = core.evaluate('.git', 'refs/sop/base', 'refs/sop/prhead', pats, best, chg=chg)
    for o in ok:
        print(f'  放行  {o["path"]}  {o["blob"][:12]}  序号 {o["seq"]}')
    print(f'改动 {len(chg)} 个文件；用时 {time.time() - T0:.2f} 秒')
    if bad:
        print('守门检查不通过：')
        for b in bad:
            print(f'  {b["path"]}：{b["why"]}')
        return 1
    print('守门检查通过')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:    # 出错一律按不通过算
        print(f'守门检查出错（按不通过算）：{e}'); sys.exit(1)
