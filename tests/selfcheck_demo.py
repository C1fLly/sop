#!/usr/bin/env python3
"""3-44 的验证（手动跑，不在全部自测里，不花钱）：在 /tmp 的临时副本上造几种没过的改动，看 sop self check 说不说「没过，卡在哪」。

每一种情形一份自己的副本（/tmp/sscd/c<序号>/dev，从开发目录现在的样子拷出来、提交成起点），在上面改一处，
用副本里的 kernel/selfcheck.py 真跑四个检查（全部自测，一份七八分钟，一份一份跑：两份同时跑会互相干扰，把关脚本自己也拿锁）；复查用假的 claude（不花钱，fake://ok 或 fake://reject）；
动了三处的那一种加 --isolation 时，隔离自检只真跑本机那份（runner/selftest.py，只在 /tmp 里造假项目），
专用 Docker 那份不跑（会在这台电脑上起专用 Docker），这一点如实打在结果里。
主目录、SOP_HOME、自测的临时目录都指到这一份自己的 /tmp 目录；去掉 ANTHROPIC_ 开头的变量（不会真调 AI）。

用法：uv run python tests/selfcheck_demo.py [情形 …]      不给情形就全跑；跑完删副本（--keep 留着）
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROOT = pathlib.Path('/tmp/sscd')   # 路径要短：自测里专用 Docker 的通道路径不能超过 107 个字符
FAKE_CLAUDE = REPO / 'tests' / 'fakes' / 'claude' / 'claude'
ID = {'GIT_AUTHOR_NAME': 'demo', 'GIT_AUTHOR_EMAIL': 'demo@sop.invalid', 'GIT_COMMITTER_NAME': 'demo',
      'GIT_COMMITTER_EMAIL': 'demo@sop.invalid', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


def edit(rel, old, new):
    def f(d):
        p = d / rel
        s = p.read_text(encoding='utf-8')
        assert s.count(old) == 1, (rel, old)
        p.write_text(s.replace(old, new), encoding='utf-8')
    return f


def good(d):
    p = d / 'README.md'
    p.write_text(p.read_text(encoding='utf-8') + '\n修完工具包之后的把关：`sop self check`（3-44）。\n', encoding='utf-8')


def drop_fail_samples(d):
    for s in (d / 'checks' / 'scope' / 'samples').glob('fail-*'):
        shutil.rmtree(s)


# 情形：(改什么, 复查的假 claude 怎么表现, 加不加 --isolation, 最后那一句要有的字)
CASES = {
    '全好': ([good], 'ok', False, '过了'),
    '单元测试失败': ([good, edit('tests/unit/test_commands.py', "self.assertEqual(commands.words(''), ())",
                                "self.assertEqual(commands.words(''), ('x',))")], 'ok', False, '单元测试没过'),
    '总检查失败': ([good, drop_fail_samples], 'ok', False, '总检查没过'),
    '文档检查失败': ([edit('README.md', '## 跑自测', '## 跑自测\n\n见 `kernel/没有这个文件.py`。')], 'ok', False, '文档检查没过'),
    '复查有问题': ([good], 'reject', False, '复查有问题'),
    '动了隔离没加isolation': ([good, edit('runner/selftest.py', '用法：uv run python -m runner.selftest [--keep]',
                                       '用法：uv run python -m runner.selftest [--keep]（3-44 演示改的一行）')],
                          'ok', False, '--isolation'),
    '动了隔离加了isolation': ([good, edit('runner/selftest.py', '用法：uv run python -m runner.selftest [--keep]',
                                       '用法：uv run python -m runner.selftest [--keep]（3-44 演示改的一行）')],
                          'ok', True, '破坏演练：还没有（3-47 还没做'),
}


def g(d, *a):
    return subprocess.run(['git', '-C', str(d), *a], env={**os.environ, **ID, 'GIT_OPTIONAL_LOCKS': '0'},
                          capture_output=True, text=True, check=True).stdout


def prepare(name):
    """一份自己的副本：开发目录现在的样子（跟踪的加没被忽略的新文件），提交成起点。"""
    base = ROOT / f'c{list(CASES).index(name)}'     # 目录名只用英文：专用 Docker 的登记文件不收带中文的路径（自测里有一项会因此不过）
    if base.exists():
        subprocess.run(['chmod', '-R', 'u+w', str(base)], capture_output=True)
        shutil.rmtree(base)
    d = base / 'dev'
    d.mkdir(parents=True)
    files = subprocess.run(['git', '-C', str(REPO), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}, capture_output=True, text=True, check=True).stdout
    for rel in sorted({x for x in files.split('\0') if x}):
        src = REPO / rel
        if not os.path.lexists(src):
            continue
        t = d / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), t)
        else:
            shutil.copy2(src, t)
    g(d, 'init', '-q', '--template=', '-b', 'main')
    g(d, 'add', '-A')
    g(d, 'commit', '-qm', '起点：开发目录现在的样子')
    return base, d


def one(name, keep=False):
    changes, mode, isolation, want = CASES[name]
    base, d = prepare(name)
    for f in changes:
        f(d)
    home, sop_home = base / 'home', base / 'sop-home'
    (sop_home / 'config' / 'ai').mkdir(parents=True)
    home.mkdir()
    env_file = sop_home / 'config' / 'ai' / 'claude.env'
    env_file.write_text(f'ANTHROPIC_BASE_URL="fake://{mode}"\nANTHROPIC_AUTH_TOKEN=fake-token-3-44-demo\n')
    os.chmod(env_file, 0o600)
    (base / 'bin').mkdir()
    shutil.copy(FAKE_CLAUDE, base / 'bin' / 'claude')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ANTHROPIC_', 'CLAUDE'))}
    # GIT_ 那几样只给上面造副本的 git 用，不带进把关（带进去会改变自测里 git 的行为，第一次跑时 3 项单元测试因此没过）
    env.update(HOME=str(home), SOP_HOME=str(sop_home), SOP_RUNTIME_DIR=str(base / 'run'), SOP_TEST_TMP=str(base / 't'))
    code = f'''
import json, pathlib, sys
sys.path.insert(0, {str(d)!r})
from adapters.ai.claude.adapter import ClaudeAdapter
from kernel import selfcheck
from machine import syscheck

def local_selftest(repo):
    ok, lines = syscheck.run_selftest([[sys.executable, '-I', str(repo / 'runner' / 'selftest.py')]])
    return ok, lines + ['（演示：专用 Docker 那份没跑，会在这台电脑上起专用 Docker）']

r = selfcheck.run(pathlib.Path({str(d)!r}), base='HEAD', isolation={isolation!r},
                  adapter=ClaudeAdapter(exe={str(base / "bin" / "claude")!r}), selftest=local_selftest)
print('最后一句：' + r['verdict'])
json.dump(r, open({str(base / "report.json")!r}, 'w'), ensure_ascii=False, indent=1)
'''
    p = subprocess.run([sys.executable, '-c', code], cwd=str(d), env=env, capture_output=True, text=True)
    out = p.stdout + p.stderr
    (base / 'output.txt').write_text(out, encoding='utf-8')
    last = next((x for x in reversed(out.splitlines()) if x.startswith('最后一句：')), '（没跑完）' + out[-300:])
    ok = want in last and (last == '最后一句：过了') == (want == '过了')
    try:
        logdir = json.loads((base / 'report.json').read_text())['logdir']
        if ok:          # 和预期不一样的留着记录目录看
            shutil.rmtree(logdir, ignore_errors=True)
        else:
            out += f'\n（和预期不一样，记录目录留着：{logdir}）'
    except (OSError, ValueError, KeyError):
        pass
    if not keep:
        subprocess.run(['chmod', '-R', 'u+w', str(base)], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)
    return name, ok, last, out


def main(argv):
    keep = '--keep' in argv
    names = [a for a in argv if a in CASES] or list(CASES)
    results = {}
    for n in names:
        name, ok, last, out = one(n, keep)
        results[name] = ok
        print(f'===== {name}：{"对" if ok else "不对"} =====', flush=True)
        print('\n'.join(x for x in out.splitlines() if not x.startswith(('....', 'Ran ')))[-3000:], flush=True)
    print('\n'.join(f'{"对  " if ok else "不对"} {n}' for n, ok in results.items()))
    print('全部对' if all(results.values()) else '有不对的')
    if not keep and ROOT.exists() and not any(ROOT.iterdir()):
        ROOT.rmdir()
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
