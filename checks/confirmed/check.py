#!/usr/bin/env python3
"""检查「已确认内容」（设计书 14.2、7.5、7.6）。在哪运行：本机。
参数：gitdir、confirmed（小白在 F10 确认时的提交）、head、fdir（.scratch/<功能>）、mode：
  impl：规格、验收卡、大白话摘要逐字不变；工单文件只许勾选框、「状态：」那一行、「## 评论」那一节变；不许新加或删掉工单；
  t8：同上，但规格里以「## 技术」开头的节可以变（T8 之后只改规格的技术部分）。"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402



def files(gitdir, rev, d):
    out = lib.nul(lib.git(gitdir, 'ls-tree', '-r', '-z', '--name-only', rev, d + '/'))
    return {p: lib.git(gitdir, 'rev-parse', f'{rev}:{p}').strip() for p in out}


def show(gitdir, rev, p):
    return lib.git(gitdir, 'show', f'{rev}:{p}')


def norm_ticket(text):
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            skip = line.strip() == '## 评论'
            if skip:
                out.append(line); continue
        if skip or line.startswith('状态：'):
            continue
        out.append(re.sub(r'^(\s*- )\[[ xX]\]', r'\1[ ]', line))
    return '\n'.join(out).strip()


def non_tech(text):
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            skip = line.startswith('## 技术')
        if not skip:
            out.append(line)
    return '\n'.join(out).strip()


def run(gitdir, confirmed, head, fdir, mode='impl'):
    a, b = files(gitdir, confirmed, fdir), files(gitdir, head, fdir)
    bad = []
    for p in sorted(set(a) | set(b)):
        rel = p[len(fdir) + 1:]
        if not (rel == 'spec.md' or rel == 'summary.md' or rel.startswith('cards/') or rel.startswith('issues/')):
            continue
        if p not in b:
            bad.append(f'{rel} 被删掉了'); continue
        if p not in a:
            bad.append(f'{rel} 是新加的'); continue
        if a[p] == b[p]:
            continue
        if rel.startswith('issues/'):
            if norm_ticket(show(gitdir, confirmed, p)) != norm_ticket(show(gitdir, head, p)):
                bad.append(f'{rel} 除了勾选框、状态行、评论区，还有别的改动（验收标准等）')
        elif rel == 'spec.md' and mode == 't8':
            if non_tech(show(gitdir, confirmed, p)) != non_tech(show(gitdir, head, p)):
                bad.append('spec.md 技术部分以外的节变了')
        else:
            bad.append(f'{rel} 和确认时不一样')
    if bad:
        return False, '已确认的内容被改了：' + '；'.join(bad[:6]), {'bad': bad}
    return True, '已确认的内容没有被改', {'bad': []}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
