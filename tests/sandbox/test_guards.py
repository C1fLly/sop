"""流程沙箱：放行和合并前的几道关（设计书 6.4，v0.9）。"""
import json

from tests.sandbox.base import F, FB, FS, SandboxCase
from tests.sandbox.world import PNG_B

T1, T2 = f'ticket/{F}/01', f'ticket/{F}/02'


class TestDroppedTicketLeavesNoRelease(SandboxCase):
    def test_abandoned_accepted_ticket(self):
        """一张验收过、带截图改动的工单被放弃：功能 PR 照样是绿的，日志里没有它的放行。"""
        self.start([('01', [], '无'), ('02', [], '界面：改首页')])
        w = self.w
        w.script[f'{T2}:T3'] = {'files': {'ui/screens/home.png': '@hex:' + PNG_B, 'src/t02.py': '2'}, 'commit': 'feat: 02'}
        w.human['*:T11'] = []
        w.human[f'{T2}:T11'] = [{'answer': '通过'}] * 5     # T6 修复在验收之后，会重新打开验收（8.3），每轮都要再验
        w.human[f'{T2}:T8'] = [{'answer': '去掉'}]
        # 02 验收之后，GitHub 上的快档一直不过（本机门禁是过的）→ 重跑一次仍不过 → T6 … → T8 建议放弃 → 小白选去掉
        w.rules = [{'name': 'fast', 'head': 'ticket/jz-1/02', 'conclusion': 'failure'}]
        w.script[f'{T2}:T6'] = {'files': {'src/t02.py': '2 改了一版'}, 'commit': 'fix: 02'}
        w.script[f'{T2}:T7'] = {'files': {'src/t02.py': '2 又改了一版'}, 'commit': 'fix: 02 根因'}
        w.script[f'{T2}:T8'] = {'files': {'docs/adr/0001-放弃.md': '# 放弃首页改版\n'}, 'result': {'decision': 'abandon', 'pr_body': '首页改版做不了'}}
        w.script[f'{FS}:F9fix'] = {'append': {f'.scratch/{F}/spec.md': '首页改版去掉了\n'}}
        r = self.go()
        self.assertFeatureDone(r)
        self.assertEqual(self.steps(T2)[-1], (None, 'drop'))
        self.assertIn(('T11', 'confirm'), self.steps(T2))            # 它验收过
        self.assertEqual(self.w.releases(FB), [])                     # 可它从来没留下放行
        self.assertEqual(self.blob_main('docs/baseline/home.png'), self.w.rgit('rev-parse', 'HEAD~1:docs/baseline/home.png'))
        self.assertEqual(self.prs()['ticket/jz-1/02']['state'], 'CLOSED')


class TestF18Backstop(SandboxCase):
    def test_unreleased_protected_file_is_caught(self):
        """F18 之前的脚本兜底能发现一个故意没放行的受保护文件（这里由特权侧以外的路径塞进功能分支）。"""
        self.start([('01', [], '无')])
        w = self.w
        # 小白验收功能（F17）时，有人直接往功能分支推了一个改规范的提交（模拟 T4 漏判混进来的受保护改动）
        sneak = ('git -C {root}/feat-jz-1 -c core.hooksPath=/dev/null commit -q --allow-empty -m x && '
                 'echo 规范被放宽了 > {root}/feat-jz-1/docs/standards/rules.md && '
                 'git -C {root}/feat-jz-1 -c core.hooksPath=/dev/null commit -qam "放宽规范" && '
                 'git --git-dir {root}/.git push -q origin feat/jz-1').replace('{root}', str(w.root))
        w.human[f'{FS}:F17'] = [{'answer': '通过', 'do': [sneak]}]
        r = self.go(ok=False)
        self.assertIn('docs/standards/rules.md', r.stdout)
        self.assertIn('不自动补放行', r.stdout)
        f18 = [x for x in self.evs(FS) if x['step'] == 'F18' and x['type'] == 'failed']
        self.assertEqual([b['path'] for b in f18[0]['bad']], ['docs/standards/rules.md'])
        self.assertTrue(self.prs()[FB]['isDraft'])                    # 没转正式
        self.assertEqual(self.prs()[FB]['state'], 'OPEN')


class F19Case(SandboxCase):
    rule = None

    def run_one(self):
        self.start([('01', [], '无')])
        self.w.rules = [self.rule]
        r = self.go(ok=False)
        f19 = [x for x in self.evs(FS) if x['step'] == 'F19' and x['type'] == 'failed']
        self.assertTrue(f19, r.stdout[-3000:])
        self.assertEqual(self.prs()[FB]['state'], 'OPEN')             # 没合并
        self.assertNotIn(('F20', 'done'), self.steps(FS))
        return f19[0]['reason']


class TestF19OnlyFull(F19Case):
    rule = {'name': 'full', 'head': FB, 'conclusion': 'failure'}

    def test(self):
        self.assertIn('全档', self.run_one())


class TestF19OnlyFast(F19Case):
    rule = {'name': 'fast', 'head': FB, 'conclusion': 'failure'}

    def test(self):
        self.assertIn('快档', self.run_one())


class TestF19OnlyGuard(F19Case):
    rule = {'name': 'guard', 'head': FB, 'conclusion': 'failure'}

    def test(self):
        self.assertIn('守门', self.run_one())


class TestPrivateRepo(SandboxCase):
    visibility = 'private'

    def test_human_clicks_merge_after_f19(self):
        """私有仓库：F19 三项都过了才请小白去网页上点合并；点完核对合进去的就是查过的那一份。"""
        self.start([('01', [], '无')])
        w = self.w
        n_click = f'gh pr merge {{pr}} --squash'
        w.human[f'{FS}:F20'] = [{'answer': '点好了', 'do': [f'PATH={w.env()["PATH"]} FAKEGH_HOME={w.fakegh} ' + n_click]}]
        r = self.go()
        self.assertFeatureDone(r)
        f20 = [x for x in self.evs(FS) if x['step'] == 'F20' and x['type'] == 'done']
        self.assertTrue(f20[0]['merge_commit'])
        order = [(x['step'], x['type']) for x in self.evs(FS)]
        self.assertLess(order.index(('F19', 'done')), order.index(('F20', 'start')))
