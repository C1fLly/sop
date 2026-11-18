"""流程沙箱：额度类报错的扫描（7.12、W29），花费提醒（8.4）。"""
import json

from tests.sandbox.base import F, FS, SandboxCase

T1 = f'ticket/{F}/01'
BAL = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'Agent failed: API Error: 403 insufficient balance'}]}}


class TestQuota(SandboxCase):
    def test_once_warns_twice_pauses(self):
        """帮手报了余额不足、主会话照常结束：第一次提示去看余额、流程照常；同一个功能里第二次就暂停（7.12）。"""
        self.start([('01', [], '无'), ('02', ['01'], '无')])
        w = self.w
        w.script[f'{T1}:T3'] = {'files': {'src/t01.py': '1'}, 'commit': 'feat: 01', 'log': [json.dumps(BAL)]}
        w.script[f'ticket/{F}/02:T3'] = {'files': {'src/t02.py': '2'}, 'commit': 'feat: 02', 'log': [json.dumps(BAL)]}
        r = self.go(ok=False)
        notes = [e for e in self.evs() if e['type'] == 'note' and e.get('kind') == '额度报错']
        self.assertEqual(len(notes), 2)
        self.assertIn('后台看一下余额', notes[0]['text'])
        self.assertTrue(notes[1].get('paused'))
        self.assertIn(('T3', 'done'), self.steps(T1))               # 第一次没有中断流程
        self.assertIn(('T13', 'done'), self.steps(T1))
        self.assertIn('第二次碰到额度类的报错，先暂停', r.stdout)
        self.assertNotIn(('T4', 'start'), self.steps(f'ticket/{F}/02'))   # 第二次暂停了


class TestCostAlert(SandboxCase):
    def test_alert_does_not_stop(self):
        """花费到了默认数（一个功能 50 美元）时提醒一次，流程不停。"""
        self.start([('01', [], '无')])
        self.w.script[f'{FS}:F16'] = {'result': {'findings': []}, 'cost': 55.0}
        r = self.go()
        self.assertFeatureDone(r)
        alerts = [e for e in self.evs() if e.get('kind') == '花费提醒']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['what'], 'feature')
        self.assertIn('【花费提醒】', r.stdout)
        self.assertIn('工具报告的金额', alerts[0]['text'])
        order = [(x['step'], x['type']) for x in self.evs(FS)]
        self.assertGreater(order.index(('F23', 'done')), order.index(('F16', 'done')))     # 提醒之后照常走完
        c = self.w.sop('cost')
        self.assertIn('提醒过', c.stdout)
