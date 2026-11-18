#!/usr/bin/env python3
"""检查「结果文件」（设计书 9.2、14.2）。在哪运行：本机。
参数：path（结果文件）、gitdir、base（这一步开始时的提交）、head（现在的提交）、kind（impl / planning / review）。
格式对；声称的提交都存在、都在这一步新加的那一段里（base 之后、head 之前）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

STATUS = ('done', 'partial', 'question')


def run(path, gitdir, base, head, kind):
    errs = []
    try:
        r = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        return False, '没有交回结果文件', {'errors': ['没有结果文件']}
    except ValueError as e:
        return False, f'结果文件不是合法的 JSON：{e}', {'errors': [str(e)]}
    if not isinstance(r, dict):
        return False, '结果文件不是一个对象', {'errors': ['不是对象']}
    if r.get('status') not in STATUS:
        errs.append(f'status 必须是 {"/".join(STATUS)} 之一')
    for k, t in (('commits', list), ('commands', list), ('deviations', list), ('questions', list), ('findings', list)):
        if not isinstance(r.get(k, []), t):
            errs.append(f'{k} 必须是列表')
    for q in r.get('questions', []) or []:
        if not isinstance(q, dict) or q.get('category') not in ('业务', '技术') or not q.get('text'):
            errs.append('每个问题要有 text，category 是「业务」或「技术」')
    for f in r.get('findings', []) or []:
        if not isinstance(f, dict) or not isinstance(f.get('blocking'), bool) or not f.get('text'):
            errs.append('每条发现要有 text 和 blocking（是否阻断）')
    for c in r.get('commands', []) or []:
        if not isinstance(c, dict) or 'cmd' not in c or not isinstance(c.get('rc'), int):
            errs.append('每条命令要有 cmd 和 rc')
    if kind == 'impl' and r.get('status') == 'done' and not isinstance(r.get('pr_body'), str):
        errs.append('实现类步骤要有 pr_body（PR 说明）')
    new = set(lib.git(gitdir, 'rev-list', f'{base}..{head}').split()) if base and head else set()
    for c in r.get('commits', []) or []:
        full = lib.git(gitdir, 'rev-parse', '--verify', '--quiet', f'{c}^{{commit}}', check=False).strip()
        if not full:
            errs.append(f'声称的提交 {c} 不存在')
        elif full not in new:
            errs.append(f'声称的提交 {c} 不是这一步新加的')
    if kind in ('planning', 'review') and r.get('commits'):
        errs.append('这一步不该有提交（由流程命令提交）')
    if errs:
        return False, '结果文件不对：' + '；'.join(errs[:6]), {'errors': errs}
    return True, f'结果文件格式正确（状态 {r["status"]}）', {'errors': [], 'status': r['status']}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
