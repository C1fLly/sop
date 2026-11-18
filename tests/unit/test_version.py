"""工具包仓库自己的检查：版本的分类（7.11）。修补版的流程定义和技能副本和上一版逐字一致。"""
import pathlib
import shutil
import tempfile
import unittest

from kernel import version
from tests.helpers import REPO


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(dir='/tmp'))
        for n in ('a', 'b'):
            shutil.copytree(REPO / 'flows', self.d / n / 'flows')
            (self.d / n / 'checks').mkdir()
            (self.d / n / 'checks' / 'x.py').write_text(n)

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_patch(self):
        self.assertEqual(version.classify(self.d / 'a', self.d / 'b'), 'patch')

    def test_major_flow_changed(self):
        p = self.d / 'b' / 'flows' / 'ticket.toml'
        p.write_text(p.read_text() + '\n# 改了\n')
        self.assertEqual(version.classify(self.d / 'a', self.d / 'b'), 'major')

    def test_major_skills_changed(self):
        (self.d / 'b' / 'skills').mkdir()
        (self.d / 'b' / 'skills' / 'SKILL.md').write_text('新版本的技能')
        self.assertEqual(version.classify(self.d / 'a', self.d / 'b'), 'major')
