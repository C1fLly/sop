#!/usr/bin/env python3
"""检查「可改范围」（设计书 14.2、5.6）。在哪运行：本机（依赖这一步的起点）。
参数：gitdir、worktree、base（这一步开始时的提交；AI 不提交的步骤也给，比较的就是工作区）、allowed（可改范围）、
      protected（受保护路径）、snapshot（这一步开始前，被 Git 忽略的 AI 设置和规则文件的指纹，{路径: 指纹}，可以不给）。
看的是：这一步提交了的改动、工作区里还没提交的改动、没被跟踪的新文件、**被 Git 忽略的文件**。
- 受保护路径（含任何层级的 CLAUDE*.md、AGENTS*.md、.claude/ 等）新出现或被改了，一律越界；
- 其余改动要在可改范围里；
- 被忽略的文件只看 AI 工具会自动读的那几类（构建产物、依赖目录本来就被忽略，不算）。
路径一律按不转义的原样比（中文文件名）。"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402


def ignored_ai_files(gitdir, worktree):
    """被忽略的文件里，AI 工具会自动读的那几类：{路径: 指纹}。"""
    out = {}
    for p in lib.nul(lib.git(gitdir, 'ls-files', '-o', '-i', '--exclude-standard', '-z', worktree=worktree)):
        if lib.match(p, lib.AI_CONFIG):
            fp = os.path.join(worktree, p)
            out[p] = hashlib.sha256(open(fp, 'rb').read()).hexdigest() if os.path.isfile(fp) else 'dir'
    return out


def run(gitdir, worktree, base, allowed, protected, snapshot=None):
    seen = {}
    if base:
        o = lib.nul(lib.git(gitdir, 'diff', '--name-status', '-z', '--no-renames', base, 'HEAD', worktree=worktree))
        for i in range(0, len(o), 2):
            seen[o[i + 1]] = '提交了的改动'
    o = lib.nul(lib.git(gitdir, 'diff', '--name-status', '-z', '--no-renames', 'HEAD', worktree=worktree))
    for i in range(0, len(o), 2):
        seen.setdefault(o[i + 1], '没提交的改动')
    for p in lib.nul(lib.git(gitdir, 'ls-files', '-o', '--exclude-standard', '-z', worktree=worktree)):
        seen.setdefault(p, '新文件')
    bad = []
    for path, how in sorted(seen.items()):
        if lib.match(path, list(protected) + list(lib.AI_CONFIG)):
            bad.append({'path': path, 'how': how, 'why': '受保护路径'})
        elif not lib.match(path, allowed):
            bad.append({'path': path, 'how': how, 'why': '不在可改范围'})
    before = snapshot or {}
    for path, fp in sorted(ignored_ai_files(gitdir, worktree).items()):
        if before.get(path) != fp:
            bad.append({'path': path, 'how': '被 Git 忽略的文件', 'why': 'AI 工具会自动读的设置或规则文件，新出现或被改了'})
    rep = {'changed': seen, 'bad': bad}
    if bad:
        return False, '越界：' + '；'.join(f'{b["path"]}（{b["how"]}，{b["why"]}）' for b in bad[:8]), rep
    return True, f'可改范围：{len(seen)} 处改动都在范围内', rep


if __name__ == '__main__':
    sys.exit(lib.cli(run))
