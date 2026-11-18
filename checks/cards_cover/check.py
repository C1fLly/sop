#!/usr/bin/env python3
"""检查「验收卡格式」（设计书 7.4 的 F8、14.2）。在哪运行：本机。参数：worktree、fdir。
通过：每张工单有一张验收卡（cards/<编号>.md），工单里的每条验收标准至少对应验收卡上的一个步骤（步骤里写 [AC1]）；有大白话摘要 summary.md。"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

from checks.plan_check.check import load  # noqa: E402


def run(worktree, fdir):
    _, tickets = load(worktree, fdir)
    errs = []
    if not os.path.isfile(os.path.join(worktree, fdir, 'summary.md')):
        errs.append('没有大白话摘要 summary.md')
    for n, t in tickets.items():
        p = os.path.join(worktree, fdir, 'cards', f'{n}.md')
        if not os.path.isfile(p):
            errs.append(f'工单 {n} 没有验收卡'); continue
        refs = set(re.findall(r'\[(AC\d+)\]', open(p, encoding='utf-8').read()))
        for ac in t['acs']:
            if ac not in refs:
                errs.append(f'工单 {n} 的 {ac} 在验收卡上没有对应的步骤')
    if errs:
        return False, '验收包不全：' + '；'.join(errs[:6]), {'errors': errs}
    return True, f'验收包齐全：{len(tickets)} 张验收卡', {'errors': []}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
