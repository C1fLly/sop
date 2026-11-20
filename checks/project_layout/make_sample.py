#!/usr/bin/env python3
"""给总检查的样例造一个刚建好的项目工作目录（和 sop project new 的 I3、I4 写出的一样）。用法：make_sample.py <目录> [--root <项目根>]
--root：另造一个本机的项目根（裸仓库 .git、.shared/hooks/、main/ 里一个指向 .git 的小文件），工作目录就是它的 main/。"""
import os
import pathlib
import subprocess
import sys

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TOOLKIT))
from kernel import projectnew  # noqa: E402


def main(argv):
    if '--root' in argv:
        root = pathlib.Path(argv[argv.index('--root') + 1])
        subprocess.run(['git', 'init', '-q', '--bare', str(root / '.git')], check=True)
        (root / '.shared' / 'hooks').mkdir(parents=True)
        (root / 'main').mkdir()
        (root / 'main' / '.git').write_text(f'gitdir: {root / ".git" / "worktrees" / "main"}\n')
        dest = root / 'main'
        name = root.name
    else:
        dest, name = pathlib.Path(argv[0]), 'demo'
    projectnew.write_template(dest, name, 'private', 'https://example.invalid/sop.git', '0' * 40)
    projectnew.install_skills(dest)


if __name__ == '__main__':
    main(sys.argv[1:])
