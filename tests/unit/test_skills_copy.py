"""技能副本的核对（3-20）：自己算的目录指纹和 Git 算的一样（排序、执行权限这些细节容易错）。"""
import os

from checks.skills_pristine import check
from tests.helpers import TempHome, sh


class TestTreeId(TempHome):
    def test_same_as_git(self):
        d = self.tmp / 'r'
        # 「a.b」「a-b」和目录「a」的先后是 Git 排序里容易错的地方；再带一个可执行文件、一个中文名、一个 Windows 换行
        for rel, text in (('top/a.b', '1'), ('top/a-b', '2'), ('top/a/x', '3'), ('top/a/y/z.md', '4\r\n'),
                          ('top/技能/SKILL.md', '中文'), ('top/run.sh', '#!/bin/sh\n')):
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode())
        os.chmod(d / 'top/run.sh', 0o755)
        sh('git', 'init', '-q', str(d))
        sh('git', '-C', str(d), '-c', 'core.autocrlf=false', 'add', '-A')
        root = sh('git', '-C', str(d), 'write-tree')
        want = sh('git', '-C', str(d), 'rev-parse', f'{root}:top')
        files, odd = check.scan(str(d / 'top'))
        files = {'top/' + k: v for k, v in files.items()}
        self.assertEqual(odd, [])
        self.assertEqual(check.tree_id(files, 'top'), want)
        self.assertEqual(files['top/run.sh'][0], '100755')
