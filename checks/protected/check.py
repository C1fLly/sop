#!/usr/bin/env python3
"""检查「受保护路径」（设计书 14.2）。在哪运行：两处——本机这一份（T4、F18 之前的兜底），GitHub 上是守门检查（checks/guard）。
参数：gitdir、base（目标分支）、head、patterns（受保护路径的清单）、releases（{路径: {blob, seq}}，本归属每个路径最后一条放行）。
通过：改了的受保护路径，现在的内容都是本归属最后一条放行的那一份。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402
from checks.protected import core  # noqa: E402


def run(gitdir, base, head, patterns, releases):
    bad, ok = core.evaluate(gitdir, base, head, patterns, releases)
    if bad:
        return False, '受保护的文件有改动没有放行：' + '；'.join(f'{b["path"]}（{b["why"]}）' for b in bad), {'bad': bad, 'released': ok}
    return True, f'受保护路径：改了 {len(ok)} 个，都有放行', {'bad': [], 'released': ok}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
