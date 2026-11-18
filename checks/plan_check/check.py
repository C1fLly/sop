#!/usr/bin/env python3
"""检查「规格格式、工单格式和关系、故事覆盖」（设计书 7.4 的 F7、14.2）。在哪运行：本机。
参数：worktree、fdir（.scratch/<功能>）。格式见 checks/README.md。
通过：规格有用户故事；每张工单有状态、依赖、覆盖、风险行和至少一条验收标准；依赖的工单都存在、没有环；
每条用户故事至少被一张工单的覆盖行引用；覆盖行引用的故事都存在。"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

STORY = re.compile(r'^- (S\d+)[：:]')
AC = re.compile(r'^- \[[ xX]\] (AC\d+)[：:]')


def ids(text):
    return [] if text.strip() in ('', '无') else [x.strip() for x in re.split(r'[、,，\s]+', text.strip()) if x.strip()]


def parse_ticket(text):
    t = {'title': None, 'fields': {}, 'acs': []}
    sec = None
    for line in text.splitlines():
        if line.startswith('# ') and t['title'] is None:
            t['title'] = line[2:].strip()
        elif line.startswith('## '):
            sec = line[3:].strip()
        elif sec is None and re.match(r'^(状态|依赖|覆盖|风险)：', line):
            k, v = line.split('：', 1); t['fields'][k] = v.strip()
        elif sec == '验收标准' and AC.match(line):
            t['acs'].append(AC.match(line).group(1))
    return t


def load(worktree, fdir):
    spec_p = os.path.join(worktree, fdir, 'spec.md')
    spec = open(spec_p, encoding='utf-8').read() if os.path.exists(spec_p) else None
    idir = os.path.join(worktree, fdir, 'issues')
    tickets = {}
    for f in sorted(os.listdir(idir)) if os.path.isdir(idir) else []:
        m = re.match(r'^(\d\d)-.+\.md$', f)
        if m:
            tickets[m.group(1)] = parse_ticket(open(os.path.join(idir, f), encoding='utf-8').read()) | {'file': f}
    return spec, tickets


def run(worktree, fdir, part='all'):
    """part='spec' 时只查规格（F5 的出口检查）。"""
    spec, tickets = load(worktree, fdir)
    errs = []
    stories = []
    if spec is None:
        errs.append('没有 spec.md')
    else:
        sec = None
        for line in spec.splitlines():
            if line.startswith('## '):
                sec = line[3:].strip()
            elif sec == '用户故事' and STORY.match(line):
                stories.append(STORY.match(line).group(1))
        if not spec.lstrip().startswith('# '):
            errs.append('spec.md 第一行要是标题')
        if not stories:
            errs.append('spec.md 的「## 用户故事」里没有故事（- S1：……）')
    if part == 'spec':
        rep = {'errors': errs, 'stories': stories}
        return (not errs), ('规格格式不对：' + '；'.join(errs) if errs else f'规格格式正确：{len(stories)} 条用户故事'), rep
    if not tickets:
        errs.append('没有工单（issues/NN-短名.md）')
    covered = set()
    for n, t in tickets.items():
        if not t['title'] or not t['title'].startswith(n):
            errs.append(f'工单 {t["file"]} 的标题要以编号开头')
        for k in ('状态', '依赖', '覆盖', '风险'):
            if k not in t['fields']:
                errs.append(f'工单 {n} 少了「{k}：」这一行')
        if not t['acs']:
            errs.append(f'工单 {n} 没有验收标准（- [ ] AC1：……）')
        for d in ids(t['fields'].get('依赖', '')):
            if d not in tickets:
                errs.append(f'工单 {n} 依赖的 {d} 不存在')
        cov = ids(t['fields'].get('覆盖', ''))
        if not cov:
            errs.append(f'工单 {n} 的覆盖行是空的')
        for s in cov:
            if s not in stories:
                errs.append(f'工单 {n} 覆盖的故事 {s} 在规格里没有')
            covered.add(s)
    for s in stories:
        if s not in covered:
            errs.append(f'用户故事 {s} 没有任何工单覆盖')
    state = {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            errs.append('工单之间的依赖有环：' + ' → '.join(path + [n])); return
        state[n] = 1
        for d in ids(tickets[n]['fields'].get('依赖', '')):
            if d in tickets:
                visit(d, path + [n])
        state[n] = 2
    for n in tickets:
        visit(n, [])
    rep = {'errors': errs, 'stories': stories, 'tickets': {n: {'deps': ids(t['fields'].get('依赖', '')),
                                                               'risk': t['fields'].get('风险', ''), 'acs': t['acs']}
                                                           for n, t in tickets.items()}}
    if errs:
        return False, '规划校验不通过：' + '；'.join(errs[:6]), rep
    return True, f'规划校验通过：{len(stories)} 条用户故事，{len(tickets)} 张工单', rep


if __name__ == '__main__':
    sys.exit(lib.cli(run))
