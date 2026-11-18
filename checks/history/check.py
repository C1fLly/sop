#!/usr/bin/env python3
"""检查「历史延续」（设计书 6.4 第四层、14.2）。在哪运行：本机。
参数：gitdir、branch、local（本地这条分支现在的提交）。现场向远程取这条分支，核对本地是它的延续（没有改写历史）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402


def run(gitdir, branch, local):
    p = lib.git(gitdir, 'ls-remote', 'origin', f'refs/heads/{branch}')
    if not p.strip():
        return True, f'远程还没有 {branch}，不用比', {'remote': None}
    lib.git(gitdir, 'fetch', '-q', 'origin', f'+refs/heads/{branch}:refs/remotes/origin/{branch}')
    remote = lib.git(gitdir, 'rev-parse', f'refs/remotes/origin/{branch}').strip()
    ok = lib.git_ok(gitdir, 'merge-base', '--is-ancestor', remote, local)
    rep = {'remote': remote, 'local': local}
    if ok:
        return True, f'{branch}：本地是远程的延续', rep
    return False, f'{branch}：本地不是远程的延续（历史被改写了，或者远程有本地没有的提交）', rep


if __name__ == '__main__':
    sys.exit(lib.cli(run))
