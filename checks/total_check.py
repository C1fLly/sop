#!/usr/bin/env python3
"""总检查（设计书 16.1）：逐个运行所有检查的样例。
- 没有「应通过」或「应报错」样例的检查不合格；
- 「应通过」的样例上没通过（退出码不是 0）、「应报错」的样例上没报错（退出码不是 1）的，不合格。
  （退出码 2「无法判断」在「应报错」的样例上也不算报对了：检查自己崩了不能冒充发现了问题。）
- 只看退出码不够：Python 没兜住的错（例如一导入就崩、写报告时崩）退出码也是 1。所以还要看到检查自己写出的结论：
  报告 JSON 读得出、是对象、里面记的「退出码」和进程的退出码一样（checks/lib.py 的 finish 写的）；不然算检查自己崩了，不符合。
每个样例在 /tmp 下的临时副本里跑；有 setup.sh 的先执行它造现场；args.json 里的 {CASE} 换成临时副本的位置。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECKS = pathlib.Path(os.environ.get('SOP_CHECKS_DIR') or HERE)   # 测试总检查本身时换成别的目录
GIT_ID = {'GIT_AUTHOR_NAME': 'sample', 'GIT_AUTHOR_EMAIL': 'sample@example.invalid', 'GIT_COMMITTER_NAME': 'sample',
          'GIT_COMMITTER_EMAIL': 'sample@example.invalid', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}


def run_sample(check_py, sample, tmp_root):
    case = pathlib.Path(tempfile.mkdtemp(prefix=f'{check_py.parent.name}-{sample.name}-', dir=tmp_root))
    shutil.copytree(sample, case, dirs_exist_ok=True)
    env = {**os.environ, **GIT_ID, 'CASE': str(case), 'TOOLKIT': str(HERE.parent)}
    if (case / 'setup.sh').exists():
        p = subprocess.run(['bash', '-euo', 'pipefail', str(case / 'setup.sh')], cwd=case, env=env, capture_output=True, text=True)
        if p.returncode:
            return None, f'造现场失败：{p.stderr.strip()[-400:]}'
    args = (case / 'args.json').read_text(encoding='utf-8').replace('{CASE}', str(case)).replace('{TOOLKIT}', str(HERE.parent))
    (case / 'args.run.json').write_text(args, encoding='utf-8')
    rp = case / 'report.json'
    rp.unlink(missing_ok=True)   # 样例里带的、造现场时写的都不算，只认这次检查自己写的
    p = subprocess.run([sys.executable, str(check_py), str(case / 'args.run.json'), '--report', str(rp)],
                       env=env, capture_output=True, text=True, timeout=120)
    try:
        said = json.loads(rp.read_text(encoding='utf-8')).get('退出码')
    except (OSError, ValueError, AttributeError):
        said = None
    if said != p.returncode or isinstance(said, bool):
        why = '没写出报告' if not rp.exists() else ('报告里记的退出码是 %r' % (said,) if said is not None else '报告读不出或没记退出码')
        return None, f'检查自己崩了（进程退出码 {p.returncode}，{why}）：' + (p.stderr.strip() or p.stdout.strip())[-300:]
    return p.returncode, (p.stdout.strip() or p.stderr.strip())[-300:]


def main():
    tmp_root = pathlib.Path(os.environ.get('SOP_TEST_TMP', '/tmp/sop-test')) / 'total-check'
    shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir(parents=True)
    bad, n = [], 0
    for d in sorted(p for p in CHECKS.iterdir() if (p / 'check.py').exists()):
        samples = sorted((d / 'samples').iterdir()) if (d / 'samples').is_dir() else []
        kinds = {s.name.split('-', 1)[0] for s in samples}
        if 'pass' not in kinds or 'fail' not in kinds:
            bad.append(f'{d.name}：缺「应通过」或「应报错」的样例'); print(f'不合格 {d.name}：缺样例'); continue
        for s in samples:
            want = 0 if s.name.startswith('pass-') else 1
            rc, line = run_sample(d / 'check.py', s, tmp_root)
            n += 1
            ok = rc == want
            print(f'{"符合  " if ok else "不符合"} {d.name}/{s.name}：退出码 {rc}（应为 {want}） {line}', flush=True)
            if not ok:
                bad.append(f'{d.name}/{s.name}')
    print(f'总检查：{n} 个样例，{len(bad)} 个不合格' + (('：' + '、'.join(bad)) if bad else ''))
    if not bad:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
