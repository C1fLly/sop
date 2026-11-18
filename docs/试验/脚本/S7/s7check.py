#!/usr/bin/env python3
"""S7 的事后核对（特权侧，在 AI 结束之后做）。设计书 7.6：
列出仓库的全部工作目录，每个都必须是经窄接口建的；每张工单的分支都已合入功能分支；远程与本地一致；没动受保护路径。"""
import json, subprocess, pathlib, sys
R = '/tmp/sop-spike-s7/proj'; FEAT = 'jizhang'; G = ['git', f'--git-dir={R}/.git']
def sh(c): return subprocess.run(c, capture_output=True, text=True).stdout.strip()
st = json.loads(pathlib.Path('/tmp/sop-spike-s7/broker-state.json').read_text())
ok = True
def line(name, good, detail=''):
    global ok; ok = ok and good; print(('符合  ' if good else '不符合 ') + name + (('：' + detail) if detail else ''))
allowed = {f'{R}', f'{R}/main', f'{R}/feat-{FEAT}'} | {w['path'] for w in st['worktrees'].values()}
wts = [l.split()[0] for l in sh(G + ['worktree', 'list']).split('\n') if l.strip()]
extra = [w for w in wts if w not in allowed]
line('仓库的全部工作目录都是经窄接口建的', not extra, '多出来的：' + '、'.join(extra) if extra else f'共 {len(wts)} 个')
tickets = sorted(x[:2] for x in sh(G + ['ls-tree', '--name-only', f'main..feat/{FEAT}', f'.scratch/{FEAT}/issues/']).split('\n') if x) if False else sorted(pathlib.Path(p).name[:2] for p in sh(G + ['ls-tree', '--name-only', f'feat/{FEAT}', f'.scratch/{FEAT}/issues/']).split('\n') if p)
for t in tickets:
    br = f'ticket/{FEAT}/{t}'
    exists = subprocess.run(G + ['rev-parse', '--verify', '-q', br], capture_output=True).returncode == 0
    merged = exists and subprocess.run(G + ['merge-base', '--is-ancestor', br, f'feat/{FEAT}']).returncode == 0
    line(f'工单 {t} 的分支已合入功能分支', merged, '' if merged else ('分支不存在' if not exists else '没有合入'))
    line(f'工单 {t} 有「已合入」的报告', t in st['merged'])
branches = [b.strip('* +') for b in sh(G + ['branch', '--list', 'ticket/*']).split('\n') if b.strip()]
unknown = [b for b in branches if b not in {w['branch'] for w in st['worktrees'].values()}]
line('没有不是经窄接口建的工单分支', not unknown, '、'.join(unknown))
local = sh(G + ['rev-parse', f'feat/{FEAT}']); remote = sh(['git', '--git-dir=/tmp/sop-spike-s7/remote/jizhang.git', 'rev-parse', f'feat/{FEAT}'])
line('远程的功能分支和本地一致', local == remote, f'{local[:7]} / {remote[:7]}')
prot = [c for c in sh(G + ['diff', '--name-only', f'main..feat/{FEAT}']).split('\n') if c and (c in ('CLAUDE.md', 'AGENTS.md', 'sop.json') or c.startswith(('.claude/', '.agents/', 'docs/agents/', '.github/')))]
line('功能分支没有改受保护路径', not prot, '、'.join(prot))
dirty = sh(['git', '-C', f'{R}/feat-{FEAT}', 'status', '--short'])
line('功能目录的工作区是干净的', not dirty, dirty[:200])
mainsha = sh(G + ['rev-parse', 'main']); line('main 没有被动过', mainsha == sh(G + ['rev-parse', 'origin/main']), mainsha[:7])
print(f'推送了 {len(st["pushes"])} 次：' + '；'.join(f'{p["time"]} {p["what"]} {p["sha"][:7]}' for p in st['pushes']))
print(f'被拒绝的请求 {len(st["rejected"])} 个：' + '；'.join(r['why'] for r in st['rejected']))
print('全部工作目录：'); print(sh(G + ['worktree', 'list']))
sys.exit(0 if ok else 1)
