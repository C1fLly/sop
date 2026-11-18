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
