#!/usr/bin/env python3
"""检查「文档里写的 `sop …` 命令和工具包仓库里的文件路径都存在」（设计书 16.2 的文档检查，3-62）。
在哪运行：工具包自己的自测（本机，和工具包仓库在 GitHub 上的 docs 检查：tests/run_all.py docs）。
章节号、步骤编号另由 docs/试验/脚本/文档核对/check_refs.py 查。

参数：repo（工具包仓库的根）、docs（要查的文档，相对 repo 的路径，也可以写绝对路径）；commands（命令表，默认 <repo>/kernel/commands.py）。

只看反引号里的（设计书、手册的写法：命令、路径一律放在反引号里），代码块（```）里的不看。
- 命令：以 `sop` 开头的。命令的词（到第一个 <…>、[…]、-- 为止）要正好是命令表里的一条：
  现在真有的（DONE）、内部用的（INTERNAL）、设计书里有还没做的（PLANNED，写着排在哪）。还没做的算通过，但在结论里列出来。
  命令后面还跟着别的词（例如 `sop feature new login`）只有那条命令要填参数时才行。`sop machine …` 这样以省略号结尾的，算一组命令的统称。
- 路径：不带空格、带「/」，第一段是工具包仓库最上一层的东西（3.2 那张目录，加上仓库里实际有的）的，算仓库内的路径，要存在：
  <…> 和 * 当通配，至少对上一个；以「/」结尾的要是目录。`~/tools/sop/dev/…` 是开发仓库里的，同样查；
  `~/tools/sop/…` 的第一段要是装好的目录里有的（sop、config、state、versions、dev）。
  项目仓库里也有同名的目录（docs/、.github/），项目仓库里才有的路径按 templates/project/ 和下面 PROJECT_ONLY 认，不算悬空。
  目录要里面有文件才算有：Git 不记空目录，本机多出来的空目录（例如现在的 profiles/、guide/）在 GitHub 上取出来就没有。
  还没有的路径（例如以后才放进来的目录）不要放进反引号，写明「还没有」；命令那边是 PLANNED，路径这边没有对应的表。
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

# 工具包仓库最上一层（设计书 3.2 的目录）。实际仓库里另有的（README.md、.github…）运行时加上
TOP = {'bootstrap.sh', 'kernel', 'runner', 'flows', 'checks', 'prompts', 'skills', 'adapters', 'profiles',
       'machine', 'templates', 'guide', 'tests', 'docs'}
NOT_TOP = {'.git', '.venv', '__pycache__'}
# 装到电脑上的 ~/tools/sop/ 下有什么（3.2；dev 是开发仓库）
INSTALLED = {'sop', 'config', 'state', 'versions', 'dev'}
# 项目仓库里才有、模板里还没有的路径（和工具包仓库的 docs/、.github/ 同名，不当成工具包的路径查）。写明谁建
PROJECT_ONLY = {
    'docs/agents/': '项目仓库：I4 放的 setup-matt-pocock-skills 的三份种子文件（3-23）',
    'docs/baseline/': '项目仓库：验收后的视觉基准（第 13 节，第 2a 期起）',
    'docs/notes/': '项目仓库：AI 的长期笔记（4.7，第 2a 期起）',
    'docs/product/risk.json': '项目仓库：P1 风险分级的结果（7.3，第 2a 期起）',
    '.github/sop/': '第一段 W21 试验仓库里放受保护清单的位置（6.4 写的是试验做法，不是工具包仓库的）',
}

CODE_SPAN = re.compile(r'`([^`\n]+)`')
ARG = re.compile(r'^(?:<|\[|-|…|\.\.\.)')
WORD = re.compile(r'^[a-z][a-z0-9-]*$')


def load_table(path):
    """命令表是一个只有数据的 Python 文件：执行它取 DONE、INTERNAL、PLANNED。"""
    ns = {}
    with open(path, encoding='utf-8') as f:
        exec(compile(f.read(), path, 'exec'), ns)  # noqa: S102  工具包自己的文件
    table = {}
    for kind in ('DONE', 'INTERNAL', 'PLANNED'):
        for usage, what in ns[kind].items():
            w = ns['words'](usage)
            if w in table:
                raise ValueError(f'命令表里 sop {" ".join(w)} 出现了两次（{table[w][0]}、{kind}）')
            table[w] = (kind, what, ns['takes_args'](usage))
    return table


def spans(text):
    """反引号里的内容和所在行号；代码块（```）里的不算。"""
    out, fenced = [], False
    for n, line in enumerate(text.split('\n'), 1):
        if line.lstrip().startswith('```'):
            fenced = not fenced
            continue
        if fenced:
            continue
        for m in CODE_SPAN.finditer(line):
            out.append((n, m.group(1).strip()))
    return out


def check_command(s, table):
    """s 以 sop 开头。返回 (种类, 说明, 对上的命令)：种类是 DONE / INTERNAL / PLANNED，或 None（悬空）。"""
    toks = s.split()[1:]
    ws = []
    for t in toks:
        if ARG.match(t) or not WORD.match(t):
            break
        ws.append(t)
    rest = toks[len(ws):]
    if rest and rest[0] in ('…', '...'):          # `sop machine …`：一组命令的统称
        if any(w[:len(ws)] == tuple(ws) and len(w) > len(ws) for w in table):
            return 'DONE', '一组命令', tuple(ws)
        return None, '没有以这几个词开头的命令', None
    for k in range(len(ws), -1, -1):              # 最长的那条命令，多出来的词只能是参数
        hit = table.get(tuple(ws[:k]))
        if hit and (k == len(ws) or hit[2]):
            return hit[0], hit[1], tuple(ws[:k])
    for k in range(len(ws) - 1, 0, -1):
        if tuple(ws[:k]) in table:
            return None, f'sop {" ".join(ws[:k])} 不带参数，命令表里也没有 sop {" ".join(ws[:k + 1])}', None
    return None, '命令表里没有', None


def as_glob(p):
    return re.sub(r'<[^<>/]*>', '*', p)


def has_files(d):
    """目录里（任何一层）有没有文件。Git 不记空目录：本机多一个空目录，GitHub 上取出来的就没有，不能本机过、GitHub 上不过。"""
    for _, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if x not in NOT_TOP]
        if names:
            return True
    return False


def exists(repo, rel):
    """仓库里有没有这个路径（<…>、* 当通配）。目录要里面有文件才算有。"""
    want_dir = rel.endswith('/')
    pat = os.path.join(repo, as_glob(rel.rstrip('/')))
    hits = glob.glob(pat, include_hidden=True) if any(c in pat for c in '*?[') else ([pat] if os.path.lexists(pat) else [])
    hits = [h for h in hits if not os.path.isdir(h) or has_files(h)]
    return any(os.path.isdir(h) for h in hits) if want_dir else bool(hits)


def check_path(s, repo, top):
    """返回 None（不是工具包仓库内的路径，不查）、True（存在）、或一句为什么悬空。"""
    if any(c.isspace() for c in s) or '://' in s or '/' not in s:
        return None
    s = re.sub(r':\d+(?:-\d+)?$', '', s.split('#', 1)[0])
    if s.startswith('~/tools/sop/'):
        rest = s[len('~/tools/sop/'):]
        first = rest.split('/', 1)[0]
        if first == 'dev':
            if rest in ('dev', 'dev/'):
                return True
            rel = rest[len('dev/'):]
            return True if exists(repo, rel) else '开发仓库里没有'
        if first not in INSTALLED and not first.startswith('<'):
            return f'装好的 ~/tools/sop/ 下只有 {"、".join(sorted(INSTALLED))}'
        return None
    first = s.split('/', 1)[0]
    if first not in top:
        return None
    if exists(repo, s):
        return True
    if s in PROJECT_ONLY or exists(os.path.join(repo, 'templates', 'project'), s):
        return None
    if s.endswith('/') and exists(repo, s.rstrip('/')):
        return '工具包仓库里有，但不是目录'
    return '工具包仓库里没有'


def run(repo, docs, commands=None):
    table = load_table(commands or os.path.join(repo, 'kernel', 'commands.py'))
    top = TOP | {n for n in os.listdir(repo) if n not in NOT_TOP}
    bad, planned, n_cmd, n_path = [], {}, 0, 0
    for d in docs:
        text = open(os.path.join(repo, d), encoding='utf-8').read()
        for line, s in spans(text):
            if s == 'sop' or s.startswith('sop '):
                n_cmd += 1
                kind, why, w = check_command(s, table)
                if kind is None:
                    bad.append(f'{d}:{line} 命令 `{s}`：{why}')
                elif kind == 'PLANNED':
                    planned.setdefault(' '.join(('sop',) + w), why)
                continue
            r = check_path(s, repo, top)
            if r is None:
                continue
            n_path += 1
            if r is not True:
                bad.append(f'{d}:{line} 路径 `{s}`：{r}')
    report = {'docs': docs, 'commands': n_cmd, 'paths': n_path, 'dangling': bad,
              'planned': [f'{k}：{v}' for k, v in sorted(planned.items())]}
    if bad:
        return False, f'文档里有 {len(bad)} 处命令或路径悬空：' + '；'.join(bad[:5]) + ('等' if len(bad) > 5 else ''), report
    tail = f'；其中 {len(planned)} 条命令还没做（命令表里写着排在哪）' if planned else ''
    return True, f'文档里的命令 {n_cmd} 处、仓库内路径 {n_path} 处都存在{tail}', report


def main_print(argv):
    """直接给人看：python3 checks/doc_refs/check.py --repo <根> <文档>…（run_all.py 用），逐条打印悬空的和还没做的。"""
    repo = argv[argv.index('--repo') + 1]
    docs = [a for i, a in enumerate(argv) if a != '--repo' and (i == 0 or argv[i - 1] != '--repo')]
    ok, line, rep = run(repo, docs)
    for b in rep['dangling']:
        print('  悬空：', b)
    for p in rep['planned']:
        print('  还没做：', p)
    return lib.finish(ok, line, rep)


if __name__ == '__main__':
    sys.exit(main_print(sys.argv[1:]) if '--repo' in sys.argv else lib.cli(run))
