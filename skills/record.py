#!/usr/bin/env python3
"""把 mattpocock/skills 某个提交的 skills/ 和 LICENSE 原样放进工具包的 skills/mattpocock/，并写版本记录 skills/source.json。
用法（在能上网的电脑上，先在 /tmp 新建的空目录里克隆上游、不检出）：
  git clone --no-checkout https://github.com/mattpocock/skills.git /tmp/<空目录>/src
  uv run python skills/record.py /tmp/<空目录>/src <提交编号>
只从克隆的 Git 数据里按指纹取文件原样写出（不检出、不经过换行或其它转换、不运行克隆里的任何东西）；写完用 checks/skills_pristine 核对一遍。
换技能版本一律算工具包的大版本（设计书 7.11、W12）。"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from checks.skills_pristine import check  # noqa: E402

REPO_URL = 'https://github.com/mattpocock/skills'
PATHS = ('LICENSE', 'skills')


def git(gitdir, *args, binary=False):
    p = subprocess.run(['git', f'--git-dir={gitdir}', '-c', 'core.hooksPath=/dev/null', *args],
                       capture_output=True, text=not binary, check=True)
    return p.stdout


def main(clone, rev):
    gitdir = os.path.join(clone, '.git') if os.path.isdir(os.path.join(clone, '.git')) else clone
    commit = git(gitdir, 'rev-parse', '--verify', rev + '^{commit}').strip()
    date = git(gitdir, 'show', '-s', '--format=%cs', commit).strip()
    files = {}
    for line in git(gitdir, 'ls-tree', '-r', '-z', commit, '--', *PATHS).split('\0'):
        if not line:
            continue
        meta, path = line.split('\t', 1)
        mode, kind, oid = meta.split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            sys.exit(f'{path} 不是普通文件（{mode} {kind}），这个脚本不处理')
        files[path] = (mode, oid)
    out = HERE / check.COPY
    shutil.rmtree(out, ignore_errors=True)
    for path, (mode, oid) in sorted(files.items()):
        p = out / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(git(gitdir, 'cat-file', 'blob', oid, binary=True))
        p.chmod(0o755 if mode == '100755' else 0o644)
    trees = {'skills': git(gitdir, 'rev-parse', f'{commit}:skills').strip()}
    rec = {'repo': REPO_URL, 'commit': commit, 'commit_date': date, 'license': 'MIT（见 mattpocock/LICENSE）',
           'trees': trees, 'files': {k: list(v) for k, v in sorted(files.items())}}
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    text = re.sub(r'\[\n\s+("\d+"),\n\s+("[0-9a-f]+")\n\s+\]', r'[\1, \2]', text)   # 每个文件一行
    (HERE / 'source.json').write_text(text + '\n', encoding='utf-8')
    ok, line, _ = check.run(str(HERE))
    print(line)
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
