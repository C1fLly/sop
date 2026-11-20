"""检查共用的小工具。只用标准库，不依赖内核：守门检查在 GitHub 上只带着工具包的检出跑。"""
import functools
import json
import re
import subprocess
import sys

# 任何层级都受保护的 AI 工具设置和规则文件（设计书 5.6，v0.9）
AI_CONFIG = ('**/CLAUDE*.md', '**/AGENTS*.md', '**/.claude/**', '**/.agents/**', '**/.codex/**', '**/.opencode/**', '**/.pi/**')


@functools.lru_cache(maxsize=4096)
def _rx(pat):
    """把路径模式转成正则。`**` 任意层级（含零层），`*` 一层里的任意字符，`?` 一个字符；整条路径都要对上。
    不带「/」的模式（例如 `.eslintrc*`）在任何层级的文件名上都算（W21 守门脚本的规矩）；以「/」开头的只认根目录（例如 `/sop.json`）。"""
    if pat.startswith('/'):
        pat = pat[1:]
    elif '/' not in pat:
        pat = '**/' + pat
    out, i = '', 0
    while i < len(pat):
        if pat.startswith('**/', i):
            out += '(?:.*/)?'; i += 3
        elif pat.startswith('/**', i) and i + 3 == len(pat):
            out += '(?:/.*)?'; i += 3
        elif pat.startswith('**', i):
            out += '.*'; i += 2
        elif pat[i] == '*':
            out += '[^/]*'; i += 1
        elif pat[i] == '?':
            out += '[^/]'; i += 1
        else:
            out += re.escape(pat[i]); i += 1
    return re.compile(out + r'\Z')


def match(path, patterns):
    return any(_rx(p).match(path) for p in patterns)


def git(gitdir, *args, worktree=None, check=True, input=None, binary=False):
    a = ['git', f'--git-dir={gitdir}', '-c', 'core.hooksPath=/dev/null', '-c', 'core.quotePath=false']
    if worktree:
        a.append(f'--work-tree={worktree}')
    p = subprocess.run(a + [str(x) for x in args], capture_output=True, text=not binary, input=input,
                       cwd=worktree or None)
    if check and p.returncode:
        err = p.stderr if not binary else p.stderr.decode(errors='replace')
        raise RuntimeError(f'git {" ".join(map(str, args))}: {err.strip()[:400]}')
    return p.stdout if binary else p.stdout


def nul(s):
    return [x for x in s.split('\0') if x]


def finish(ok, line, report, report_path=None, unsure=False):
    """统一的收尾：一行结论、JSON 报告、退出码（14.1）。
    报告里写上这次的退出码和一行结论（「退出码」「结论」两项）：总检查只认检查自己写出的结论，
    光是退出码 1 可能是脚本崩了（Python 没兜住的错退出码也是 1），不能冒充发现了问题（16.1）。"""
    rc = 2 if unsure else (0 if ok else 1)
    print(line)
    if report_path:
        out = dict(report) if isinstance(report, dict) else {'报告': report}
        out['退出码'], out['结论'] = rc, line
        text = json.dumps(out, ensure_ascii=False, indent=1)   # 先整个转好再写：转不了就崩在写文件之前，不留半截报告
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(text)
    return rc


def cli(run):
    """check.py 的入口：读参数文件，调用 run(**参数) -> (ok, 一行结论, 报告)。"""
    if len(sys.argv) < 2:
        print('用法：check.py <参数.json> [--report <报告.json>]'); return 2
    rp = sys.argv[sys.argv.index('--report') + 1] if '--report' in sys.argv else None
    try:
        args = json.load(open(sys.argv[1], encoding='utf-8'))
        ok, line, report = run(**args)
    except Exception as e:   # 检查自己出错：无法判断，不当成通过
        return finish(False, f'无法判断：检查出错：{e}', {'error': repr(e)}, rp, unsure=True)
    return finish(ok, line, report, rp)


def git_ok(gitdir, *args):
    """只看 Git 的退出码是不是 0。"""
    return subprocess.run(['git', f'--git-dir={gitdir}', '-c', 'core.hooksPath=/dev/null', *map(str, args)],
                          capture_output=True).returncode == 0
