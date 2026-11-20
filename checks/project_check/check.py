#!/usr/bin/env python3
"""项目检查（设计书 6.4 第三层的「项目检查」、14.2 的「快档、全档门禁」）。在哪运行：两处——GitHub 上由检查流程
sop-check.yml 的 fast、full 两个任务各跑一次（工具包取主线 sop.json 声明的那个版本，3-24）；本机的门禁另由流程命令在受限侧跑。
参数：dir（PR 的检出）、toolkit（sop.json 声明的那个工具包版本的目录）、tier（fast 或 full）、
profiles（可选，找档案的目录，默认是工具包里的 profiles/；样例用）。
看两样，都过才算通过：
1. 目录结构、技能文件与工具包一致（checks/project_layout，14.2「两处」那一行）。
2. 门禁（按 PR 里 sop.json 声明的档案，用户 2026-11-19 定的问题 6）：
   - 还没有声明任何档案（stack、end 都是空的）：明说「还没有技术栈档案，门禁暂不适用」，算通过（7.2：I7 时还没有档案）；
   - 声明了档案：每个档案在工具包这个版本里都要有，它的命令表（commands.toml）里要有这一档的门禁命令（gate-fast / gate-full），
     没有就算失败；有就在检出里逐条执行，全部退出码 0 才算通过。
   「跑了的测试数不是 0」等别的几项要等第 2a 期有了真的档案才接上（14.2）。"""
import json
import os
import subprocess
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402
from checks.project_layout import check as layout  # noqa: E402

TIERS = ('fast', 'full')
NOT_APPLICABLE = '还没有技术栈档案，门禁暂不适用'


def _expand(s, prof_dir, toolkit):
    s = s.replace('{profile}', prof_dir).replace('{toolkit}', toolkit)
    return os.environ.get(s[1:], '') if s.startswith('$') else s


def gate(dir, toolkit, tier, profiles=None):
    """返回 (通过, 一行说明, 报告)。"""
    profiles = profiles or os.path.join(toolkit, 'profiles')
    sop = json.load(open(os.path.join(dir, 'sop.json'), encoding='utf-8'))
    declared = [(kind, n) for kind in ('stack', 'end') for n in ((sop.get('profiles') or {}).get(kind) or [])]
    if not declared:
        return True, NOT_APPLICABLE, {'profiles': [], 'commands': []}
    ran, bad = [], []
    for kind, n in declared:
        d = os.path.join(profiles, kind, n)
        if not os.path.isdir(d):
            bad.append(f'声明的档案 {kind}/{n} 在工具包这个版本里没有'); continue
        f = os.path.join(d, 'commands.toml')
        cmds = tomllib.load(open(f, 'rb')) if os.path.isfile(f) else {}
        cmd = cmds.get(f'gate-{tier}')
        if not cmd or not isinstance(cmd, list):
            bad.append(f'声明了档案 {kind}/{n}，但它没有{"快档" if tier == "fast" else "全档"}门禁命令（gate-{tier}）'); continue
        argv = [_expand(str(x), d, toolkit) for x in cmd]
        p = subprocess.run(argv, cwd=dir, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        ran.append({'profile': f'{kind}/{n}', 'argv': argv, 'rc': p.returncode, 'tail': (p.stdout + p.stderr)[-1500:]})
        if p.returncode:
            bad.append(f'档案 {kind}/{n} 的门禁没通过（退出码 {p.returncode}）')
    rep = {'profiles': [f'{k}/{n}' for k, n in declared], 'commands': ran}
    if bad:
        return False, '；'.join(bad), rep
    return True, f'门禁通过（{len(ran)} 条命令）', rep


def run(dir, toolkit, tier, profiles=None):
    if tier not in TIERS:
        raise ValueError(f'tier 只能是 fast 或 full：{tier!r}')
    ok1, line1, rep1 = layout.run(dir, toolkit)
    ok2, line2, rep2 = gate(dir, toolkit, tier, profiles) if os.path.isfile(os.path.join(dir, 'sop.json')) else \
        (False, '没有 sop.json，不知道声明了哪些档案', {})
    label = '快档' if tier == 'fast' else '全档'
    report = {'tier': tier, 'layout': {'ok': ok1, 'line': line1, **rep1}, 'gate': {'ok': ok2, 'line': line2, **rep2}}
    if ok1 and ok2:
        return True, f'项目检查（{label}）通过：{line1}；{line2}', report
    bad = [x for ok, x in ((ok1, line1), (ok2, line2)) if not ok]
    return False, f'项目检查（{label}）不通过：' + '；'.join(bad), report


if __name__ == '__main__':
    sys.exit(lib.cli(run))
