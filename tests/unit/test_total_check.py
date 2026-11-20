"""总检查本身：坏的检查必须被判不合格（16.1）。"""
import os
import pathlib
import subprocess
import sys

from tests.helpers import REPO, TempHome

ALWAYS_PASS = '''import sys, os
sys.path.insert(0, os.environ["TOOLKIT"])
from checks import lib
sys.exit(lib.cli(lambda **kw: (True, "什么都放过", {})))
'''


class TestTotalCheck(TempHome):
    def make(self, name, samples):
        d = self.tmp / 'checks' / name
        (d / 'samples').mkdir(parents=True)
        (d / 'check.py').write_text(ALWAYS_PASS)
        for s in samples:
            (d / 'samples' / s).mkdir()
            (d / 'samples' / s / 'args.json').write_text('{}')

    def run_total(self):
        return subprocess.run([sys.executable, str(REPO / 'checks' / 'total_check.py')], capture_output=True, text=True,
                              env={**os.environ, 'SOP_CHECKS_DIR': str(self.tmp / 'checks'), 'SOP_TEST_TMP': str(self.tmp)})

    def test_never_fails_is_caught(self):
        self.make('lazy', ['pass-a', 'fail-b'])
        p = self.run_total()
        self.assertEqual(p.returncode, 1)
        self.assertIn('不符合 lazy/fail-b', p.stdout)

    def test_missing_fail_sample_is_caught(self):
        self.make('nofail', ['pass-a'])
        p = self.run_total()
        self.assertEqual(p.returncode, 1)
        self.assertIn('缺', p.stdout)

    def test_good_is_ok(self):
        self.make('fine', ['pass-a'])
        (self.tmp / 'checks' / 'fine' / 'samples' / 'fail-b').mkdir()
        (self.tmp / 'checks' / 'fine' / 'samples' / 'fail-b' / 'args.json').write_text('{}')
        (self.tmp / 'checks' / 'fine' / 'check.py').write_text(ALWAYS_PASS.replace(
            'lambda **kw: (True, "什么都放过", {})', 'lambda **kw: (os.path.basename(os.environ["CASE"]).split("-")[1] == "pass", "按样例名判", {})'))
        p = self.run_total()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    # 3-57：「应报错」必须看到检查自己写出的结论，光退出码 1 不算（Python 没兜住的错退出码也是 1）
    def test_import_crash_is_not_a_finding(self):
        self.make('crash', ['pass-a', 'fail-b'])
        (self.tmp / 'checks' / 'crash' / 'check.py').write_text('import no_such_module_for_3_57\n')
        p = self.run_total()
        self.assertEqual(p.returncode, 1)
        self.assertIn('不符合 crash/fail-b', p.stdout)
        self.assertIn('检查自己崩了', p.stdout)

    def test_crash_after_verdict_is_caught(self):
        # 只在报错那条路上、打印完结论写报告时才崩：改之前总检查整体是「全部符合」
        self.make('late', ['pass-a', 'fail-b'])
        (self.tmp / 'checks' / 'late' / 'check.py').write_text(ALWAYS_PASS.replace(
            'lambda **kw: (True, "什么都放过", {})',
            'lambda **kw: (lambda bad: (not bad, "按样例名判", {"x": {1}} if bad else {}))('
            'os.path.basename(os.environ["CASE"]).split("-")[1] == "fail")'))
        p = self.run_total()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('不符合 late/fail-b', p.stdout)
        self.assertIn('符合   late/pass-a', p.stdout)

    def test_verdict_must_be_this_run(self):
        # 样例里自带一份报告、或者检查写完结论又换了退出码，都不算
        self.make('fake', ['pass-a', 'fail-b'])
        (self.tmp / 'checks' / 'fake' / 'check.py').write_text('import sys\nsys.exit(1)\n')
        (self.tmp / 'checks' / 'fake' / 'samples' / 'fail-b' / 'report.json').write_text('{"退出码": 1}')
        self.make('switch', ['pass-a', 'fail-b'])
        (self.tmp / 'checks' / 'switch' / 'check.py').write_text(ALWAYS_PASS.replace(
            'sys.exit(lib.cli(', 'lib.cli(').rstrip().removesuffix(')') + '\nsys.exit(1)\n')
        p = self.run_total()
        self.assertIn('不符合 fake/fail-b', p.stdout)
        self.assertIn('不符合 switch/fail-b', p.stdout)
