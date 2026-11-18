#!/usr/bin/env python3
"""检查「特权侧用之前核对」（设计书 6.4 第四层，v0.9 加的）。在哪运行：本机，特权侧每次执行 wt、Git、gh 之前。
项目根下有几个文件会被特权侧执行、或会左右它怎么做，而经专用 Docker 改得了（6.3 二，实测）。逐个核对：
  1. .shared/hooks/ 里的三个文件和工具包模板逐字一致（wt new 会带着凭据执行 post-create）；
  2. .git/config 和特权侧上一次自己改完之后记下的指纹一致；
  3. .git/hooks/ 里没有会被执行的钩子（Git 只认确切的名字，.sample 不算）；没有「工作目录专用配置」的文件和扩展开关；
  4. 要碰的工作目录：里面指向 .git 的小文件、登记里的 commondir 和 gitdir 内容符合预期。
参数：root（项目根）、template（工具包模板的 hooks 目录）、config_sha（记下的 .git/config 指纹，没记过给 null）、worktrees（要核对的工作目录名）。"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

HOOKS = ('post-create', 'pre-remove', 'ignore-ok')
GIT_HOOKS = {'applypatch-msg', 'pre-applypatch', 'post-applypatch', 'pre-commit', 'pre-merge-commit', 'prepare-commit-msg',
             'commit-msg', 'post-commit', 'pre-rebase', 'post-checkout', 'post-merge', 'pre-push', 'pre-receive', 'update',
             'proc-receive', 'post-receive', 'post-update', 'reference-transaction', 'push-to-checkout', 'pre-auto-gc',
             'post-rewrite', 'sendemail-validate', 'fsmonitor-watchman', 'p4-changelist', 'p4-prepare-changelist',
             'p4-post-changelist', 'p4-pre-submit', 'post-index-change'}


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def read(path):
    try:
        return open(path, encoding='utf-8').read().strip()
    except OSError as e:
        return f'<读不了：{e.strerror}>'


def run(root, template, config_sha, worktrees):
    gd = os.path.join(root, '.git')
    bad = []
    for h in HOOKS:
        mine, want = os.path.join(root, '.shared', 'hooks', h), os.path.join(template, h)
        if not os.path.isfile(mine) or os.path.islink(mine):
            bad.append(f'.shared/hooks/{h} 不见了或被换成了链接')
        elif sha(mine) != sha(want):
            bad.append(f'.shared/hooks/{h} 和工具包模板不一样')
    cfg = os.path.join(gd, 'config')
    if config_sha is None:
        bad.append('没有记下 .git/config 的指纹（特权侧没有登记过这个项目）')
    elif sha(cfg) != config_sha:
        bad.append('.git/config 和特权侧上一次记下的不一样')
    if lib.git(gd, 'config', '--get', 'extensions.worktreeConfig', check=False).strip():
        bad.append('.git/config 里打开了「工作目录专用配置」的扩展')
    hd = os.path.join(gd, 'hooks')
    if os.path.isdir(hd):
        for n in sorted(os.listdir(hd)):
            if n in GIT_HOOKS:
                bad.append(f'.git/hooks/{n} 是一个会被 Git 执行的钩子')
    if os.path.exists(os.path.join(gd, 'config.worktree')):
        bad.append('.git/config.worktree 存在')
    wd = os.path.join(gd, 'worktrees')
    for n in (sorted(os.listdir(wd)) if os.path.isdir(wd) else []):
        if os.path.exists(os.path.join(wd, n, 'config.worktree')):
            bad.append(f'.git/worktrees/{n}/config.worktree 存在')
    for n in worktrees:
        want = {os.path.join(root, n, '.git'): f'gitdir: {gd}/worktrees/{n}',
                os.path.join(wd, n, 'commondir'): '../..',
                os.path.join(wd, n, 'gitdir'): os.path.join(root, n, '.git')}
        for f, w in want.items():
            if os.path.islink(f):
                bad.append(f'{os.path.relpath(f, root)} 被换成了链接')
            elif read(f) != w:
                bad.append(f'{os.path.relpath(f, root)} 的内容不对')
    if bad:
        return False, '项目里有特权侧要用的文件被改过，不执行：' + '；'.join(bad[:6]), {'bad': bad}
    return True, f'特权侧要用的文件都没被改过（核对了 {len(worktrees)} 个工作目录）', {'bad': []}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
