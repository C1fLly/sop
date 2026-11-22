#!/usr/bin/env python3
"""反着试破坏演练（3-47，手动跑）：把某一道检查去掉或改弱，破坏演练里对应的那一项就必须变成「没拦住」、退出码非 0。

用法（在工具包开发目录里）：python3 tests/drill_reverse.py [改法的名字 ...]
每一种改法：把开发目录（Git 记着的文件，含没提交的改动）拷一份到 /tmp/sop-drill-rev-<随机>/src、提交成起点，在那份副本里把检查改弱，
再用副本里的 tests/drill.py 只演「应当变成没拦住的那几项」加一项对照（scope，应当照样拦住）。全部如预期才退出码 0。
开发目录只读；副本用完删。全跑一遍一两分钟。
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import drill  # noqa: E402

SRC = drill.HERE
CONTROL = 'scope'
PRE = 'checks/precheck/check.py'
# 名字：(应当变成没拦住的那几项, [(文件, 原来的一处, 改成) 或 (文件或目录, None) 表示整个删掉])
WEAKEN = {
    '单元测试不看失败': (['test-expect', 'ci-weaken'], [('tests/run_all.py', '    return r.wasSuccessful()', '    return True')]),
    '去掉 --no-skip 的判法': (['test-skip'], [('tests/run_all.py', '    if no_skip and r.skipped:', '    if False:')]),
    '不核对检查流程的 --no-skip': (['ci-weaken'], [('tests/unit/test_ci_workflow.py',
                                            "self.assertIn('--no-skip', args, f'{name} 在 GitHub 上不许悄悄跳过')", 'pass')]),
    '总检查不比预期': (['sample-expect', 'skill-edit'], [('checks/total_check.py', '            ok = rc == want', '            ok = True')]),
    '技能副本不比 LICENSE': (['skill-edit'], [('checks/skills_pristine/check.py',
                                          'have[k][1] != want[k][1])\n', "have[k][1] != want[k][1] and k != 'LICENSE')\n")]),
    '文档检查不看路径': (['doc-path'], [('checks/doc_refs/check.py', '            if r is not True:', '            if False:')]),
    '规范不在受保护清单里': (['guard-rules'], [('checks/protected/base.txt', 'docs/standards/**\n', '')]),
    '检查流程不在受保护清单里': (['guard-checkdef'], [('checks/protected/base.txt', '.github/workflows/**\n', '')]),
    '不比 wt 钩子': (['wt-hook'], [(PRE, '        elif sha(mine) != sha(want):', '        elif False:')]),
    '不比 .git/config 的指纹': (['git-config'], [(PRE, '    elif sha(cfg) != config_sha:', '    elif False:')]),
    '不看 .git/hooks': (['git-hook'], [(PRE, '            if n in GIT_HOOKS:', '            if False:')]),
    '不看工作目录专用配置': (['worktree-config'], [(PRE, "        if os.path.exists(os.path.join(wd, n, 'config.worktree')):",
                                             '        if False:')]),
    '不看指向 .git 的小文件': (['gitfile'], [(PRE, '            elif read(f) != w:', '            elif False:')]),
    '特权侧整个不核对': (['wt-hook', 'git-config', 'git-hook', 'worktree-config', 'gitfile'],
                  [('kernel/precheck.py', '    if not ok:\n        raise Tampered', '    if False:\n        raise Tampered')]),
    '可改范围不看范围': (['scope'], [('checks/scope/check.py', '        elif not lib.match(path, allowed):', '        elif False:')]),
}


def weaken(work, src, edits):
    for rel, old, *new in edits:
        f = drill.inside(work, src / rel)
        if old is None:
            shutil.rmtree(f) if f.is_dir() else f.unlink()
            continue
        text = f.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise drill.DrillError(f'{rel} 里「{old.strip()[:50]}」有 {text.count(old)} 处，不是正好一处（这个脚本要跟着改）')
        f.write_text(text.replace(old, new[0], 1), encoding='utf-8')


def one(name):
    targets, edits = WEAKEN[name]
    work = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-rev-', dir='/tmp'))
    try:
        (work / 'gitconfig').write_text(drill.GIT_ID)
        src = work / 'src'
        drill.copy_source(work, SRC, src)
        weaken(work, src, edits)
        only = targets + ([CONTROL] if CONTROL not in targets else [])
        p = subprocess.run([sys.executable, 'tests/drill.py', '--only', ','.join(only)], cwd=src, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=600)
        out = p.stdout + p.stderr
        lines = [x.strip() for x in out.splitlines()]
        miss = [t for t in targets if not any(x.startswith(f'没拦住  {t}：') for x in lines)]
        ctrl = CONTROL in targets or any(x.startswith(f'检查失败（拦住了）  {CONTROL}：') for x in lines)
        ok = p.returncode == 1 and not miss and ctrl
        why = [] if ok else [f'退出码 {p.returncode}'] + [f'{t} 没有变成没拦住' for t in miss] + ([] if ctrl else ['对照项不是拦住'])
        return ok, why, out
    finally:
        drill.rmtree(work)


def main(names):
    sys.stdout.reconfigure(line_buffering=True)
    bad = [n for n in names if n not in WEAKEN]
    if bad:
        print(f'没有这几种改法：{"、".join(bad)}；有：{"、".join(WEAKEN)}'); return 2
    failed = []
    for n in names or list(WEAKEN):
        t0 = time.time()
        try:
            ok, why, out = one(n)
        except drill.DrillError as e:
            ok, why, out = False, [str(e)], ''
        targets = '、'.join(WEAKEN[n][0])
        print(f'{"符合  " if ok else "不符合"} {n}：{targets} 应当没拦住 —— {"是，退出码 1" if ok else "；".join(why)}'
              f'（{round(time.time() - t0)} 秒）')
        if not ok:
            failed.append(n)
            print('\n'.join('    ' + x for x in out.splitlines()[-25:]))
    print(f'反着试：{len(names or WEAKEN)} 种改法，{len(failed)} 种不符合' + (f'：{"、".join(failed)}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
