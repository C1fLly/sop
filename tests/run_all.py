#!/usr/bin/env python3
"""跑全部自测：单元测试、流程沙箱、总检查（设计书 16.1、16.2），加文档检查（16.2、16.4，3-40、3-62）。

用法：uv run python tests/run_all.py [--no-skip] [--pattern <文件名>] [unit|sandbox|checks|docs ...]
  不给部分就四样都跑。工具包仓库在 GitHub 上的检查（.github/workflows/check.yml）一样一样分开跑的就是这几条命令。
  --no-skip：有测试被跳过（例如这台电脑上没有 wt、内核没禁用往终端塞按键）就算没通过。
             GitHub 上加这一项：那里的电脑是现准备的，缺了东西要报出来，不能悄悄少测几项还显示通过。
  --pattern：单元测试、流程沙箱只跑文件名对得上的（例如 test_basics.py），默认 test*.py 全跑。
             破坏演练（tests/drill.py，3-47）用它只跑被改的那一个测试文件，判法（含 --no-skip）和全跑一样。
"""
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import tests  # noqa: E402,F401  自测的保险（3-59）：先换成假主目录，再跑任何测试（只跑总检查时也一样）

PARTS = ('unit', 'sandbox', 'checks', 'docs')
# 文档检查（16.2）两样：①设计书里的章节号、步骤编号等引用没有悬空（改设计书后要跑的那一个，见 docs/交接.md）；
# ②文档里写的 `sop …` 命令在命令表 kernel/commands.py 里、写的工具包仓库里的路径存在（checks/doc_refs，3-62）。
# 小白手册写出来以后（3-39）加进 DOCS。
DOCS = ['docs/设计书.md', 'README.md', 'checks/README.md', 'flows/README.md', 'prompts/README.md', 'skills/README.md']
DOC_CHECKS = [['docs/试验/脚本/文档核对/check_refs.py', 'docs/设计书.md'],
              ['checks/doc_refs/check.py', '--repo', '.', *DOCS]]


def run_suite(name, no_skip, pattern='test*.py'):
    suite = unittest.defaultTestLoader.discover(str(REPO / 'tests' / name), pattern=pattern, top_level_dir=str(REPO))
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    if no_skip and r.skipped:
        print(f'有 {len(r.skipped)} 项被跳过（--no-skip 算没通过）：', flush=True)
        for test, why in r.skipped:
            print(f'  跳过：{test.id()}：{why}', flush=True)
        return False
    return r.wasSuccessful()


def main(which, no_skip=False, pattern='test*.py'):
    ok = True
    for part in which:
        print(f'===== {part} =====', flush=True)
        if part == 'checks':
            ok &= subprocess.run([sys.executable, str(REPO / 'checks' / 'total_check.py')]).returncode == 0
        elif part == 'docs':
            for c in DOC_CHECKS:      # 两样都跑完再说结果，一样没过不挡另一样
                ok &= subprocess.run([sys.executable, *c], cwd=REPO).returncode == 0
        else:
            ok &= run_suite(part, no_skip, pattern)
    print('全部通过' if ok else '有没通过的', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    args = sys.argv[1:]
    no_skip = '--no-skip' in args
    pattern = 'test*.py'
    if '--pattern' in args:
        i = args.index('--pattern')
        if i + 1 >= len(args):
            sys.exit('--pattern 后面要写文件名（例如 test_basics.py）')
        pattern = args[i + 1]
        del args[i:i + 2]
    parts = [a for a in args if a != '--no-skip']
    bad = [p for p in parts if p not in PARTS]
    if bad:
        sys.exit(f'不认识的部分：{" ".join(bad)}（只有 {"、".join(PARTS)}）')
    parts = parts or list(PARTS)
    parts = [p for p in parts if p != 'checks' or (REPO / 'checks' / 'total_check.py').exists()]
    sys.exit(main(parts, no_skip, pattern))
