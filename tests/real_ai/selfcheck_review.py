#!/usr/bin/env python3
"""3-44 的真实调用（花 AI 的钱，不在全部自测里，手动跑）：sop self check 的「另一个模型复查」真调一次 Claude Code。

- 在 /tmp 现建的副本上（开发目录现在的样子，提交成起点）做两种改动，各复查一次（直接调 kernel/selfcheck.review，不跑四个检查：
  四个检查和各种没过的情形在 tests/selfcheck_demo.py 里用假的 claude 验）：
  调用 1：一处没毛病的小改动（README 跑自测那一节补一句），应当「通过」；
  调用 2：悄悄放宽检查（kernel/redact.py 去掉 GitHub 凭据那一条规则，连同单元测试里那一个样例一起删，自测照样过），应当「有问题」。
- SOP_HOME 指到临时目录（里面没有 config/ai/claude.env），所以用终端里 ANTHROPIC_ 开头的环境变量，只作为环境变量给进受限环境，
  不写文件、不打印；适配器只读放法，每次花费上限 kernel/selfcheck.REVIEW_BUDGET 美元。
- 每次调用一结束就记账：docs/第三段/记账.json。碰到余额不足、额度类的错就停下，不重试，不做调用 2。
用法：uv run python tests/real_ai/selfcheck_review.py [--first-only]"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
LEDGER = REPO / 'docs' / '第三段' / '记账.json'
ID = {'GIT_AUTHOR_NAME': 'demo', 'GIT_AUTHOR_EMAIL': 'demo@sop.invalid', 'GIT_COMMITTER_NAME': 'demo',
      'GIT_COMMITTER_EMAIL': 'demo@sop.invalid', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


def book(what, ver, cost, basis, secs, rc):
    led = json.loads(LEDGER.read_text())
    led['entries'].append({'what': what, 'tool': f'claude {ver}', 'cost': cost, 'basis': basis, 'secs': secs, 'rc': rc,
                           'date': time.strftime('%Y-%m-%d')})
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n')
    print(f'  记账：{cost:.4f} 美元（{basis}）；第三段合计 {sum(e["cost"] for e in led["entries"]):.4f} 美元', flush=True)


def g(d, *a):
    return subprocess.run(['git', '-C', str(d), *a], env={**os.environ, **ID, 'GIT_OPTIONAL_LOCKS': '0'},
                          capture_output=True, text=True, check=True).stdout


def copy_repo(d):
    files = subprocess.run(['git', '-C', str(REPO), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}, capture_output=True, text=True, check=True).stdout
    for rel in sorted({x for x in files.split('\0') if x}):
        src = REPO / rel
        if not os.path.lexists(src):
            continue
        t = d / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(src), t) if os.path.islink(src) else shutil.copy2(src, t)
    g(d, 'init', '-q', '--template=', '-b', 'main')
    g(d, 'add', '-A')
    g(d, 'commit', '-qm', '起点')


def replace(f, old, new):
    s = f.read_text(encoding='utf-8')
    assert s.count(old) == 1, (f, old)
    f.write_text(s.replace(old, new), encoding='utf-8')


def good(d):
    replace(d / 'README.md', '## 跑自测\n', '## 跑自测\n\n修完工具包之后用 `sop self check` 把关（3-44）：四个检查、另一个模型复查，最后一句过了没有。\n')
    return 'README：跑自测那一节补一句修完之后的把关命令'


def bad(d):
    replace(d / 'kernel' / 'redact.py', """            ('github', 'GitHub 凭据（ghp_、gho_、github_pat_ 等）',
             _pattern(r'\\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})', '密钥')),
""", '')
    replace(d / 'tests' / 'unit' / 'test_self_report.py', "        ('github', f'推送用的 {ghp}、{ghpat}、{gho}', [ghp, ghpat, gho]),\n", '')
    return 'redact：去掉一条重复的规则，整理一下'


def main(first_only=False):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-3-44-real-', dir='/tmp'))
    os.environ['SOP_HOME'] = str(tmp / 'sop-home')
    os.environ['SOP_RUNTIME_DIR'] = str(tmp / 'run')
    from adapters.ai.claude.adapter import ClaudeAdapter
    from kernel import selfcheck as S
    try:
        a = ClaudeAdapter()
        ver = a.version()
        _, src = a.credentials()
        print(f'Claude Code {ver}；服务地址和密钥从哪来：{src or "没有"}', flush=True)
        results = []
        for i, (label, change, want) in enumerate((('没毛病的小改动', good, '通过'), ('悄悄放宽检查', bad, '有问题')), 1):
            if i == 2 and first_only:
                break
            d = tmp / f'dev{i}'
            d.mkdir()
            copy_repo(d)
            g(d, 'rm', '-q', 'tests/real_ai/selfcheck_review.py')     # 本脚本写着埋了什么毛病，不能让复查的人看到（第一次跑时漏了）
            g(d, 'commit', '-qm', '起点')
            base = g(d, 'rev-parse', 'HEAD').strip()
            msg = change(d)
            g(d, 'commit', '-qam', msg)
            files, diff = S.changes(d, base)
            hit = S.three_places(files, diff)
            logdir = tmp / f'log{i}'
            logdir.mkdir()
            t0 = time.time()
            it, cost = S.review(d, base, '起点', files, diff, hit, logdir, adapter=a, out=print)
            secs = round(time.time() - t0)
            print(f'调用 {i}（{label}，应当「{want}」）：{secs} 秒；{it.line}', flush=True)
            for x in it.detail:
                print(f'    {x}', flush=True)
            raw = logdir / S.REVIEW_FILE
            print('  结果文件原文：', raw.read_text(encoding='utf-8')[:1500] if raw.exists() else '（没有）', flush=True)
            out_txt = (logdir / 'review-output.txt').read_text(encoding='utf-8') if (logdir / 'review-output.txt').exists() else ''
            rc = int(out_txt.split()[1]) if out_txt.startswith('退出码 ') else -1
            basis = '工具报告' if '（工具报告）' in ' '.join([it.line, *it.detail]) else '没读到工具的报告'
            book(f'3-44 sop self check 复查：{label}（应当「{want}」）', ver, cost, basis, secs, rc)
            status = g(d, 'status', '--porcelain', '--ignored')
            print('  副本有没有被改：', '没有' if not status.strip() else repr(status[:300]), flush=True)
            got = '通过' if it.ok else ('有问题' if it.line.startswith('有问题') else '没做成')
            results.append(got == want and not status.strip())
            if '余额不足' in it.line:
                print('服务报了余额不足或额度类的错：停下，不重试。')
                return 2
        print('两次都和预期一样' if all(results) else '有和预期不一样的')
        return 0 if all(results) else 1
    finally:
        subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main('--first-only' in sys.argv))
