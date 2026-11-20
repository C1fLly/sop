"""sop project clone 里不碰 Git、gh 的几小块（3-25）：开发环境清单怎么读、仓库名怎么认、按事件日志算要重建哪些目录。整条流程在 tests/sandbox/test_project_clone.py。"""
import types
import unittest

from kernel import flowdef, journal as J, projectclone as C
from kernel.errors import SopError
from tests.helpers import REPO


class TestManifest(unittest.TestCase):
    def test_values_kept_and_empty_ones_listed_with_their_notes(self):
        text = ('# 本机开发用的数据库\nDB_URL=postgres://localhost/dev\n\n'
                '# 短信服务的测试密钥\n# 在服务商的测试后台里取\nSMS_TEST_KEY=\n'
                'export MAP_TEST_KEY=""\n'
                '\n# 和下面没有关系的说明\n\nPORT=3000')
        out, fill = C.parse_manifest(text)
        self.assertEqual(out, text + '\n')                 # 原样一份，末尾补一个换行
        self.assertEqual(fill, [('SMS_TEST_KEY', '短信服务的测试密钥；在服务商的测试后台里取'), ('MAP_TEST_KEY', '')])

    def test_empty_manifest(self):
        self.assertEqual(C.parse_manifest(''), ('', []))


class FakeJournal:
    def __init__(self, evs):
        self.evs = evs

    def fetch(self):
        pass

    def read(self, dirs, fetch=True):
        return [e for e in self.evs if J.scope_dir(e['scope']) in dirs]


class TestInProgress(unittest.TestCase):
    """按事件日志算要重建哪些目录（整条在沙箱里演；这里补沙箱没演的几种）。"""

    def plan(self, evs):
        p = types.SimpleNamespace(journal=FakeJournal(evs), flows=flowdef.load_dir(REPO / 'flows'))
        return [(x['wt'], x['base']) for x in C.in_progress(p)]

    def test_cases(self):
        fs = 'feature/jz-1'
        reg = J.event('project', None, 'register', what='feature', feature='jz-1')
        f1 = J.event(fs, 'F1', 'register', what='branch', branch='feat/jz-1', base='main', worktree='feat-jz-1')
        self.assertEqual(self.plan([]), [])                                   # 没有功能：只有 main
        self.assertEqual(self.plan([reg]), [])                                # F1 还没做完
        self.assertEqual(self.plan([reg, f1]), [('feat-jz-1', 'main')])
        self.assertEqual(self.plan([reg, f1, J.event(fs, 'F20', 'done')]), [])   # 已经合进主线
        end = J.event('project', None, 'note', kind='功能结束', feature='jz-1')
        self.assertEqual(self.plan([reg, f1, end]), [])                       # 功能结束了


class TestSlug(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(C.parse_slug('tester/demo-2'), 'demo-2')
        for bad in ('demo', 'a/b/c', 'tester/Demo', 'tester/demo_x', '', 'tester/-x'):
            with self.assertRaises(SopError, msg=bad):
                C.parse_slug(bad)


if __name__ == '__main__':
    unittest.main()
