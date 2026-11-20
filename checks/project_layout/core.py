"""新项目里该有什么（设计书 5.1、5.2、7.2 的 I3、I4，附录 B）。写的一方（kernel/projectnew.py）和查的一方（check.py）共用这一份。
只用标准库，不依赖内核：以后在 GitHub 上只带着工具包的检出也能跑。

技能：
- 装哪些：附录 B 直接列了用途的那几个（WANTED），再按「谁调用谁」把被依赖的技能一并装上，被依赖的从技能原文里查（附录 B 末尾那句），
  不靠手工维护名单。原文里调用别的技能只有两种写法：一行里写着「Skill tool」，被调用的名字放在引号或反引号里
  （Call the Skill tool with "tdd"）；或者写「the `x` skill」「the `/x` skill」。只认工具包副本里真有的技能名。
- `setup-matt-pocock-skills` 不算依赖：好几个技能都提到它，意思是「没配置就让用户去运行它」，不是调用；设计书定了不运行它，
  由 I4 的脚本直接写出它的产出（7.2）。`wizard` 第一版不用。
- 装到哪：`.claude/skills/<技能>/` 和 `.agents/skills/<技能>/` 两处（10.2 第 3 条），整个技能目录逐字复制（10.2 第 4 条），
  去掉副本里分类那一层（副本是 skills/mattpocock/skills/<分类>/<技能>/）。
- 许可：上游是 MIT，复制时要带上版权和许可声明。技能目录一个字不许改，所以许可文件原样放在技能目录之外：
  `.claude/LICENSE-mattpocock-skills`、`.agents/LICENSE-mattpocock-skills`（3-20、3-23 定的位置）。
技能的配置 `docs/agents/`：`setup-matt-pocock-skills` 要问的三个问题答案固定（工单存本地文件、默认标签、单一术语表，7.2），
它会拿自己目录里的几份种子文件当起点写出；这里原样用那几份种子文件。
"""
import os
import re

COPY = os.path.join('skills', 'mattpocock')
LICENSE_SRC = os.path.join(COPY, 'LICENSE')
LICENSE_DEST = ('.claude/LICENSE-mattpocock-skills', '.agents/LICENSE-mattpocock-skills')
SKILL_DIRS = ('.claude/skills', '.agents/skills')

# 附录 B 里直接列了用在哪一步的技能（被依赖的那几个不列，由 install_list 从原文里查出来）
WANTED = ('wayfinder', 'research', 'grill-with-docs', 'handoff', 'to-spec', 'to-tickets', 'implement', 'implement-spec',
          'code-review', 'pr', 'retro', 'diagnosing-bugs', 'prototype', 'triage', 'improve-codebase-architecture', 'wait-what')
NOT_DEPENDENCY = ('setup-matt-pocock-skills',)

# docs/agents/ 下的文件：(技能, 种子文件)。工单存本地文件、默认的五个标签（装了 triage）、单一术语表
AGENT_DOCS = {
    'docs/agents/issue-tracker.md': ('setup-matt-pocock-skills', 'issue-tracker-local.md'),
    'docs/agents/triage-labels.md': ('setup-matt-pocock-skills', 'triage-labels.md'),
    'docs/agents/domain.md': ('setup-matt-pocock-skills', 'domain.md'),
}

# 项目模板（templates/project/）里逐字照抄、之后只随工具包升级而变的文件；其余模板文件（GLOSSARY.md、检查流程、
# docs/standards/）之后会被技能或档案改（domain-modeling 写术语表，P2a 铺规范文件、改检查流程），只要求在
TEMPLATE_EXACT = ('AGENTS.md', 'CLAUDE.md')
REQUIRED = ('AGENTS.md', 'CLAUDE.md', 'GLOSSARY.md', 'sop.json', '.gitignore',
            '.github/workflows/sop-check.yml', '.github/workflows/sop-guard.yml')
GITIGNORE_MUST = ('.env',)          # 准备脚本把 .shared/.env 链接进每个工作目录，不能被提交
VISIBILITY = ('public', 'private')


def catalog(toolkit):
    """工具包副本里的技能：{技能名: 目录}。技能目录是 skills/mattpocock/skills/<分类>/<技能>/（里面有 SKILL.md）。"""
    top = os.path.join(toolkit, COPY, 'skills')
    out = {}
    for cat in sorted(os.listdir(top)):
        cd = os.path.join(top, cat)
        if not os.path.isdir(cd):
            continue
        for name in sorted(os.listdir(cd)):
            d = os.path.join(cd, name)
            if os.path.isfile(os.path.join(d, 'SKILL.md')):
                if name in out:
                    raise ValueError(f'技能副本里有两个同名的技能 {name}（{out[name]}、{d}），去掉分类那一层会撞名')
                out[name] = d
    return out


def _texts(d):
    for base, _, names in os.walk(d):
        for n in sorted(names):
            if n.endswith(('.md', '.yaml', '.yml')):
                with open(os.path.join(base, n), encoding='utf-8') as f:
                    yield f.read()


def calls(skill_dir, names):
    """一个技能原文里调用了哪些别的技能（只认 names 里有的）。"""
    alt = '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    quoted = re.compile(r'["`]/?(' + alt + r')["`]')
    the_skill = re.compile(r'`/?(' + alt + r')` skill')
    own = os.path.basename(skill_dir)
    found = set()
    for text in _texts(skill_dir):
        for line in text.splitlines():
            if 'Skill tool' in line:
                found.update(m.group(1) for m in quoted.finditer(line))
            found.update(m.group(1) for m in the_skill.finditer(line))
    return found - {own} - set(NOT_DEPENDENCY)


def install_list(toolkit):
    """要装的技能：WANTED 加上它们（一层层）调用到的。返回 {技能名: 副本里的目录}，按名字排。"""
    cat = catalog(toolkit)
    missing = [n for n in WANTED if n not in cat]
    if missing:
        raise ValueError(f'技能副本里没有这几个技能：{"、".join(missing)}')
    todo, seen = list(WANTED), set()
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo.extend(calls(cat[n], cat))
    return {n: cat[n] for n in sorted(seen)}


def agent_docs(toolkit):
    """{docs/agents/ 下的路径: 种子文件的位置}。"""
    cat = catalog(toolkit)
    return {dest: os.path.join(cat[skill], f) for dest, (skill, f) in AGENT_DOCS.items()}


def template_dir(toolkit):
    return os.path.join(toolkit, 'templates', 'project')
