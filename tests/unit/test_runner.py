"""第 5 步：受限运行器按 6.3 的表放对；隔离自检（本机这一部分，16.2）。专用 Docker 那几项在虚拟机里跑（runner/docker/selftest_docker.py）。"""
import unittest

from runner import selftest


class TestIsolation(unittest.TestCase):
    def test_selftest_all_pass(self):
        rows = selftest.run_all()
        bad = [f'{d}（应为 {w}，实际 {g} {x or ""}）' for d, w, g, x in rows if w != g]
        self.assertEqual(bad, [])
        kinds = {d.split('：')[0] for d, *_ in rows}
        for k in ('ticket_impl', 'planning', 'std_draft', 'readonly', 'restricted_script', 'implement_spec'):
            self.assertIn(k, kinds)
