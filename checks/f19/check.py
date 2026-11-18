#!/usr/bin/env python3
"""检查「F19：GitHub 上的三项」（设计书 6.4、7.4）。在哪运行：本机（读 GitHub 的检查记录接口）。
参数：head（PR 当前最新的提交）、ready_at（转正式的时间，ISO 格式）、runs（检查记录：name、head_sha、status、conclusion、
      started_at）、names（{"fast": 快档名, "full": 全档名, "guard": 守门名}）。
三项都要过：全档、快档在最新的提交上、转正式之后真正跑完并且成功；守门在最新的提交上真正跑完并且成功（它转正式时不重跑）。
被跳过的、不在最新提交上的、还没跑完的，一律不算；不看 GitHub 的「可以合并」状态（第一段实测有空当）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402



def latest(runs, name, head, after=None):
    c = [r for r in runs if r['name'] == name and r['head_sha'] == head and (after is None or r['started_at'] >= after)]
    return max(c, key=lambda r: r['started_at']) if c else None


def run(head, ready_at, runs, names):
    rep, bad = {}, []
    for key, after in (('full', ready_at), ('fast', ready_at), ('guard', None)):
        r = latest(runs, names[key], head, after)
        label = {'full': '全档', 'fast': '快档', 'guard': '守门检查'}[key]
        if r is None:
            why = '在最新的提交上' + ('、转正式之后' if after else '') + '还没有跑'
        elif r['status'] != 'completed':
            why = '还没跑完'
        elif r['conclusion'] == 'skipped':
            why = '被跳过（跳过不算通过）'
        elif r['conclusion'] != 'success':
            why = f'结论是 {r["conclusion"]}'
        else:
            why = None
        rep[key] = {'run': r, 'why': why}
        if why:
            bad.append(f'{label}{why}')
    if bad:
        return False, 'GitHub 检查没过：' + '；'.join(bad), rep
    return True, 'GitHub 检查三项都过了（全档、快档、守门）', rep


if __name__ == '__main__':
    sys.exit(lib.cli(run))
