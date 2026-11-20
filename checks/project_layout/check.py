#!/usr/bin/env python3
"""检查「项目的目录结构对、技能文件与工具包一致」（设计书 14.2 第二行，7.2 的 I3、I4 的出口检查）。在哪运行：两处
（本机：sop project new 写完之后；GitHub 上的项目检查以后接，要带着 sop.json 声明的那个工具包版本的检出）。
参数：dir（项目的一个工作目录，或 GitHub 上的检出）、toolkit（sop.json 声明的那个工具包版本的目录）、
root（可选，本机的项目根：再看 5.1 的结构，裸仓库 .git、.shared/、默认分支目录 main/）。
看什么（应该有什么，见 core.py）：
- 5.2 的初始文件都在；AGENTS.md、CLAUDE.md 和工具包的模板逐字一致；.gitignore 里有 .env；sop.json 读得出、该有的几项都有。
- .claude/skills/、.agents/skills/ 两处各有且只有要装的那些技能，每个技能目录和工具包副本里的逐字一致（内容一个字节、换行、
  执行权限、多了少了都报）；两份许可文件和副本里的 LICENSE 逐字一致；docs/agents/ 下三份和种子文件逐字一致。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402
from checks.project_layout import core  # noqa: E402
from checks.skills_pristine.check import blob_id, scan  # noqa: E402


def _file_id(p):
    if os.path.islink(p) or not os.path.isfile(p):
        return None
    with open(p, 'rb') as f:
        return ('100755' if os.stat(p).st_mode & 0o100 else '100644', blob_id(f.read()))


def _same_file(problems, have, want, what):
    a, b = _file_id(have), _file_id(want)
    if a is None:
        problems.append(f'少了 {what}')
    elif a != b:
        problems.append(f'{what} 和工具包里的不一致' + ('（只是执行权限不同）' if a[1] == b[1] else ''))


def _skills(problems, dir, toolkit, wanted):
    for base in core.SKILL_DIRS:
        top = os.path.join(dir, base)
        if not os.path.isdir(top) or os.path.islink(top):
            problems.append(f'少了技能目录 {base}/'); continue
        have = sorted(os.listdir(top))
        for n in sorted(set(have) - set(wanted)):
            problems.append(f'{base}/ 里多了 {n}（不在要装的技能里）')
        for n, src in wanted.items():
            d = os.path.join(top, n)
            if not os.path.isdir(d) or os.path.islink(d):
                problems.append(f'{base}/ 里少了技能 {n}'); continue
            got, odd = scan(d)
            exp, _ = scan(src)
            diff = [f'{k}（内容改了）' if got[k][1] != exp[k][1] else f'{k}（执行权限变了）'
                    for k in sorted(exp) if k in got and got[k] != exp[k]]
            diff += [f'{k}（少了）' for k in sorted(exp) if k not in got]
            diff += [f'{k}（多了）' for k in sorted(got) if k not in exp] + odd
            if diff:
                problems.append(f'{base}/{n} 和工具包的技能副本不一致：' + '、'.join(diff[:4]) + ('等' if len(diff) > 4 else ''))


def _sop_json(problems, dir, root):
    try:
        sop = json.load(open(os.path.join(dir, 'sop.json'), encoding='utf-8'))
    except FileNotFoundError:
        return
    except ValueError as e:
        problems.append(f'sop.json 读不出来：{e}'); return
    tk = sop.get('toolkit') or {}
    prof = sop.get('profiles') or {}
    if not isinstance(sop.get('project'), str) or not sop['project']:
        problems.append('sop.json 没写项目名')
    elif root and sop['project'] != os.path.basename(os.path.normpath(root)):
        problems.append(f'sop.json 的项目名 {sop["project"]} 和项目根的名字对不上')
    if not tk.get('repo') or not tk.get('version'):
        problems.append('sop.json 没写工具包的仓库和版本')
    if not isinstance(prof.get('stack'), list) or not isinstance(prof.get('end'), list):
        problems.append('sop.json 的档案段不对（要有 stack、end 两个列表）')
    if sop.get('visibility') not in core.VISIBILITY:
        problems.append('sop.json 没写仓库公开还是私有')


def _root(problems, root):
    if not os.path.isfile(os.path.join(root, '.git', 'HEAD')) or not lib.git_ok(os.path.join(root, '.git'), 'rev-parse', '--is-bare-repository'):
        problems.append('项目根下没有裸仓库 .git'); return
    if lib.git(os.path.join(root, '.git'), 'rev-parse', '--is-bare-repository').strip() != 'true':
        problems.append('项目根下的 .git 不是裸仓库')
    if not os.path.isdir(os.path.join(root, '.shared', 'hooks')):
        problems.append('项目根下没有 .shared/hooks/')
    if not os.path.isfile(os.path.join(root, 'main', '.git')):
        problems.append('项目根下没有默认分支的工作目录 main/')


def run(dir, toolkit, root=None):
    problems = []
    if root:
        _root(problems, root)
    for f in core.REQUIRED:
        if not os.path.isfile(os.path.join(dir, f)):
            problems.append(f'少了 {f}')
    tpl = core.template_dir(toolkit)
    for f in core.TEMPLATE_EXACT:
        if os.path.isfile(os.path.join(dir, f)):
            _same_file(problems, os.path.join(dir, f), os.path.join(tpl, f), f)
    gi = os.path.join(dir, '.gitignore')
    if os.path.isfile(gi):
        lines = {l.strip() for l in open(gi, encoding='utf-8')}
        for need in core.GITIGNORE_MUST:
            if need not in lines and '/' + need not in lines:
                problems.append(f'.gitignore 里没有 {need}')
    _sop_json(problems, dir, root)
    wanted = core.install_list(toolkit)
    _skills(problems, dir, toolkit, wanted)
    for dest in core.LICENSE_DEST:
        _same_file(problems, os.path.join(dir, dest), os.path.join(toolkit, core.LICENSE_SRC), dest)
    for dest, src in core.agent_docs(toolkit).items():
        _same_file(problems, os.path.join(dir, dest), src, dest)
    report = {'problems': problems, 'skills': sorted(wanted)}
    if problems:
        return False, f'项目的目录结构或技能文件不对（{len(problems)} 处）：' + '；'.join(problems[:3]) + ('……' if len(problems) > 3 else ''), report
    return True, f'项目的目录结构对，{len(wanted)} 个技能在两处都和工具包逐字一致', report


if __name__ == '__main__':
    sys.exit(lib.cli(run))
