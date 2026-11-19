#!/usr/bin/env python3
"""启动器（设计书 3.2、7.11）：按项目主线上 sop.json 声明的工具包版本，找到 ~/tools/sop/versions/<提交编号>/ 并执行它。
不在项目里时（机器级命令）用已安装的最新版本。只用标准库，各版本之间这一份要稳定。

每次运行前核对：本机那个版本的目录就是声明的那个提交，没有被改过（6.4 第四层）。没装就从工具包仓库装。"""
import json
import os
import pathlib
import subprocess
import sys

HOME = pathlib.Path(os.environ.get('SOP_HOME') or '~/tools/sop').expanduser()
VERS = HOME / 'versions'


def die(msg):
    print(msg); sys.exit(1)


def git(*a, check=True):
    p = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *a], capture_output=True, text=True)
    if check and p.returncode:
        die(f'git {" ".join(a[:3])} 失败：{p.stderr.strip()[-300:]}')
    return p.stdout.strip()


def project_root(start):
    for d in [start, *start.parents]:
        if (d / '.git').is_dir() and (d / '.shared').is_dir():
            return d
    return None


def install(repo, version, vers=None):
    vers = vers or VERS
    d = vers / version
    if d.exists():
        return d
    tmp = vers / f'.{version}.tmp'
    subprocess.run(['rm', '-rf', str(tmp)])
    vers.mkdir(parents=True, exist_ok=True)
    git('init', '-q', str(tmp))
    git('-C', str(tmp), 'fetch', '-q', '--depth', '1', repo, version)
    git('-C', str(tmp), 'checkout', '-q', 'FETCH_HEAD')
    os.rename(tmp, d)
    return d


def verify(d, version):
    head = git('-C', str(d), 'rev-parse', 'HEAD', check=False)
    dirty = git('-C', str(d), 'status', '--porcelain', '--untracked-files=no', check=False)
    if head != version or dirty:
        die(f'本机的工具包目录 {d} 和声明的版本 {version[:8]} 对不上（被改过）。请执行 sop repair。')


def main():
    root = project_root(pathlib.Path.cwd())
    if root:
        gd = str(root / '.git')
        subprocess.run(['git', '--git-dir', gd, 'fetch', '-q', 'origin', '+refs/heads/main:refs/remotes/origin/main'], capture_output=True)
        sop = json.loads(git('--git-dir', gd, 'show', 'refs/remotes/origin/main:sop.json'))
        tk = sop['toolkit']
        d = install(tk['repo'], tk['version'])
        verify(d, tk['version'])
    else:
        latest = (HOME / 'versions' / 'latest').read_text().strip() if (HOME / 'versions' / 'latest').exists() else None
        if not latest:
            die('还没有安装任何工具包版本')
        d = VERS / latest
    py = os.environ.get('SOP_PYTHON')
    tools = pathlib.Path(os.environ.get('SOP_TOOLS_DIR') or HOME.parent).expanduser()
    uv = tools / 'uv' / 'bin' / 'uv'      # 规定位置那份 uv（4.3）；没有才用 PATH 里的
    cmd = [py] if py else [str(uv) if os.access(uv, os.X_OK) else 'uv', 'run', '-q', '--no-project', '--python', '3.14', 'python']
    os.execvp(cmd[0], [*cmd, '-I', str(d / 'kernel' / 'main.py'), *sys.argv[1:]])


if __name__ == '__main__':
    main()
