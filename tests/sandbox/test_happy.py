"""流程沙箱：顺利的路（设计书 7.4、7.5 全部步骤），两张工单、02 依赖 01，公开仓库。"""
from tests.sandbox.base import F, FB, FS, SandboxCase


class TestHappy(SandboxCase):
    def test_two_tickets_with_dependency(self):
        self.start([('01', [], '无'), ('02', ['01'], '无')])
        r = self.go()
        self.assertFeatureDone(r)
        # 02 依赖 01：02 的 T1 在 01 的 T13 之后
        order = [(x['scope'], x['step'], x['type']) for x in self.evs()]
        self.assertLess(order.index((f'ticket/{F}/01', 'T13', 'done')), order.index((f'ticket/{F}/02', 'T1', 'start')))
        # 主线上有两张工单的实现，没有动受保护路径
        self.assertTrue(self.main_file('src/t01.py') and self.main_file('src/t02.py'))
        self.assertEqual(self.w.releases(FB), [])
        # 功能 PR：草稿期间全档是「跳过」，转正式后真跑了；守门检查转正式时不重跑（W21）
        runs = [r for r in self.w.db()['runs'] if r['pr'] == self.prs()[FB]['number']]
        self.assertIn(('full', 'opened', 'skipped'), [(r['name'], r['event'], r['conclusion']) for r in runs])
        self.assertIn(('full', 'ready_for_review', 'success'), [(r['name'], r['event'], r['conclusion']) for r in runs])
        self.assertNotIn(('guard', 'ready_for_review'), [(r['name'], r['event']) for r in runs])
        # 分支、目录都清理了
        self.assertEqual(self.w.rgit('branch', '--list', 'feat/*', 'ticket/*'), '')
        self.assertEqual(sorted(p.name for p in self.w.root.iterdir()), ['.git', '.shared', 'main'])
        # 每个事件都推上去了：日志分支上的事件就是全部
        self.assertGreater(len(self.evs()), 60)
