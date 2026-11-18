#!/usr/bin/env python3
"""检查「交接文件存在」（设计书 7.4 的 F2、F4a）。在哪运行：本机。参数：worktree、fdir、name（文件名，例如 handoff-plan.md）。
handoff 技能把文件写到系统临时目录，由流程命令搬进 .scratch/<功能>/（附录 B）；这里核对搬进来了、不是空的。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402



def run(worktree, fdir, name):
    p = os.path.join(worktree, fdir, name)
    if not os.path.isfile(p) or not open(p, encoding='utf-8').read().strip():
        return False, f'没有交接文件 {fdir}/{name}', {'path': p}
    return True, f'交接文件 {fdir}/{name} 已在仓库里', {'path': p}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
