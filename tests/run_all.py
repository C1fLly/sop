#!/usr/bin/env python3
"""跑全部自测：单元测试、流程沙箱、总检查（设计书 16.1、16.2）。用法：uv run python tests/run_all.py [unit|sandbox|checks]"""
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import tests  # noqa: E402,F401  自测的保险（3-59）：先换成假主目录，再跑任何测试（只跑总检查时也一样）


def run_suite(name):
    suite = unittest.defaultTestLoader.discover(str(REPO / 'tests' / name), top_level_dir=str(REPO))
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    return r.wasSuccessful()


def main(which):
    ok = True
    for part in which:
        print(f'===== {part} =====', flush=True)
        if part == 'checks':
            ok &= subprocess.run([sys.executable, str(REPO / 'checks' / 'total_check.py')]).returncode == 0
        else:
            ok &= run_suite(part)
    print('全部通过' if ok else '有没通过的', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    parts = sys.argv[1:] or ['unit', 'sandbox', 'checks']
    parts = [p for p in parts if p != 'checks' or (REPO / 'checks' / 'total_check.py').exists()]
    sys.exit(main(parts))
