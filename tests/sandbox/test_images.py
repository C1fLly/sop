"""流程沙箱：放行的新时机（设计书 6.4，v0.9）。两张工单改同一张图、按相反的顺序合并；验收之后有冲突，重新打开验收、重新确认。"""
from tests.sandbox.base import F, FB, FS, SandboxCase
from tests.sandbox.world import PNG_B, PNG_C

T1, T2 = f'ticket/{F}/01', f'ticket/{F}/02'


class TestImagesReverseOrder(SandboxCase):
    def test_last_merged_is_released_last(self):
        self.start([('01', [], '界面：改首页'), ('02', [], '界面：改首页')])
        w = self.w
        # 两张工单都改了首页（ui/screens/home.png 就是页面），门禁截图和基准不同 → 待验收的界面变化
        w.script[f'{T1}:T3'] = {'files': {'ui/screens/home.png': '@hex:' + PNG_B, 'src/t01.py': '1'}, 'commit': 'feat: 01'}
        w.script[f'{T2}:T3'] = {'files': {'ui/screens/home.png': '@hex:' + PNG_C, 'src/t02.py': '2'}, 'commit': 'feat: 02'}
        # T14：把功能分支合进来；页面冲突留自己的，视觉基准取功能分支的
        w.script[f'{T1}:T14'] = {'merge': f'refs/remotes/origin/{FB}', 'merge_take': 'ours'}
        # 小白先验收 01，再验收 02；01 被冲突打回后再验收一次
        w.human['*:T11'] = []
        w.human[f'{T1}:T11'] = [{'answer': '通过'}, {'answer': '通过'}]
        w.human[f'{T2}:T11'] = [{'answer': '通过', 'wait_for': [f'{T1}:T11']}]
        # 01 的快档检查一直「还在跑」，直到 02 合并了（合并的先后和验收的先后相反）
        w.rules = [{'name': 'fast', 'head': 'ticket/jz-1/01', 'until_merged': 'ticket/jz-1/02'}]
        r = self.go()
        self.assertFeatureDone(r)
        order = [(x['scope'], x['step'], x['type']) for x in self.evs()]
        acc1, acc2 = order.index((T1, 'T11', 'confirm')), order.index((T2, 'T11', 'confirm'))
        m1, m2 = order.index((T1, 'T13', 'done')), order.index((T2, 'T13', 'done'))
        self.assertLess(acc1, acc2)       # 先验收 01
        self.assertLess(m2, m1)           # 先合并 02
        # 01 合并前碰上冲突：去 T14，T14 重新打开了验收，01 又验收了一次
        self.assertIn((T1, 'T14', 'reopen'), order)
        self.assertEqual([s for s, t in self.steps(T1) if s == 'T11' and t == 'confirm'], ['T11', 'T11'])
        # 放行：都等合进功能分支之后才写；只认序号最大的那条，就是最后合进来的 01 的那张图（B）
        rel = sorted(self.w.releases(FB), key=lambda r: r['seq'])
        self.assertEqual([(r['ticket'], r['seq']) for r in rel], [('02', 1), ('01', 2)])
        self.assertEqual(rel[-1]['blob'], self.blob_main('docs/baseline/home.png'))
        # 放行写在合并之后（日志里的先后）
        ev_all = self.w.rgit('log', '--reverse', '--format=%s', 'sop/journal').splitlines()
        self.assertTrue(any('T13 done' in x for x in ev_all))
