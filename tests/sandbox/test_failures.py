"""流程沙箱：失败、修复、深入诊断、技术决策、重新确认、工单各步不通过时的回头路（设计书 7.4、7.5、8.3）。"""
from tests.sandbox import plans
from tests.sandbox.base import F, FB, FS, SandboxCase

T1, T2 = f'ticket/{F}/01', f'ticket/{F}/02'
FD = f'.scratch/{F}'


class TestFailures(SandboxCase):
    def test_fix_diagnose_decide_and_backtracks(self):
        self.start([('01', [], '无'), ('02', [], '数据访问：改账本文件')])
        w = self.w
        # ---- 01：门禁一直不过 → T6 三轮 → T7 → T8 决定改规格的技术部分 → 重规划 → 01-2 重做 ----
        w.gate[f'{T1}:T5'] = {'pass': False, 'why': '金额相加差了一分钱'}
        w.script[f'{T1}:T8'] = {'files': {'docs/adr/0001-金额.md': '# 金额改用十进制小数类型\n'},
                                'result': {'decision': 'tech', 'pr_body': '金额改用十进制小数类型'}}
        w.script[f'{FS}:F9fix'] = {'append': {f'{FD}/spec.md': '金额改用十进制小数类型（T8 的决定）\n'}}
        # ---- 02：留了一个被忽略的 AI 设置文件 → T4 抓到；复查有阻断问题；小白验收不通过 ----
        w.script[f'{T2}:T3'] = {'files': {'src/t02.py': '2', '.claude/settings.local.json': '{"hooks": "留话"}'}, 'commit': 'feat: 02'}
        w.script[f'{T2}:T6:1'] = {'delete': ['.claude/settings.local.json']}
        w.script[f'{T2}:T9:1'] = {'result': {'findings': [{'text': '读账本文件时没处理文件不存在', 'blocking': True}]}}
        w.script[f'{T2}:T6:2'] = {'files': {'src/t02.py': '2  # 处理了文件不存在'}, 'commit': 'fix: 02 文件不存在'}
        w.human[f'{T2}:T11'] = [{'answer': '不通过', 'note': '我点保存，期望提示已保存，实际没反应'}, {'answer': '通过'}]
        w.script[f'{T2}:T6:3'] = {'files': {'src/t02.py': '2  # 保存后提示'}, 'commit': 'fix: 02 保存提示'}
        r = self.go()
        self.assertFeatureDone(r)
        s1 = self.steps(T1)
        self.assertEqual(sum(1 for s, t in s1 if s == 'T6' and t == 'done'), 3)        # 修复 3 轮
        self.assertIn(('T7', 'done'), s1)                                               # 深入诊断
        self.assertIn(('T8', 'done'), s1)                                               # 技术决策
        self.assertEqual(s1[-1], (None, 'drop'))                                        # 这一轮放弃了
        self.assertIn(('T15', 'done'), self.steps(f'ticket/{F}/01-2'))                   # 重规划后用新编号重做完了
        fs = self.steps(FS)
        self.assertIn(('F9fix', 'done'), fs)
        self.assertEqual(sum(1 for s, t in fs if s == 'F7' and t == 'done'), 2)          # 重走 F7、F8、F9
        self.assertEqual(sum(1 for s, t in fs if s == 'F10' and t == 'confirm'), 1)      # 验收卡没变，小白不用重新确认
        self.assertIn('十进制', self.main_file(f'{FD}/spec.md'))
        s2 = self.steps(T2)
        t4 = [x for x in self.evs(T2) if x['step'] == 'T4' and x['type'] == 'failed']
        self.assertIn('.claude/settings.local.json', t4[0]['reason'])                    # 可改范围抓到了被忽略的 AI 设置文件
        self.assertIn(('T9', 'failed'), s2)
        self.assertIn(('T11', 'failed'), s2)
        self.assertEqual(sum(1 for s, t in s2 if s == 'T6' and t == 'done'), 3)
        self.assertIn(('T11', 'confirm'), s2)
        self.assertEqual(self.main_file('.claude/settings.local.json'), '')

    def test_split_needs_reconfirm(self):
        """技术决策是「拆工单」：拆出一张新工单、验收卡变了 → 重新打开 F10，小白再确认一次（8.3）。"""
        self.start([('01', [], '无')])
        w = self.w
        w.gate[f'{T1}:T5'] = {'pass': False}
        w.script[f'{T1}:T8'] = {'files': {'docs/adr/0001-拆.md': '# 拆成两张\n'}, 'result': {'decision': 'split', 'pr_body': '拆成两张'}}
        w.script[f'{FS}:F9fix'] = {'files': {f'{FD}/issues/03-t.md': plans.ticket('03', [], ['S1'])}}
        w.script[f'{FS}:F8:2'] = {'files': {f'{FD}/cards/01.md': plans.card('01'), f'{FD}/cards/03.md': plans.card('03'),
                                            f'{FD}/summary.md': '大白话摘要（拆成了两张）'}}
        w.human[f'{FS}:F10'] = [{'answer': '是'}, {'answer': '是'}]
        r = self.go()
        self.assertFeatureDone(r)
        fs = self.steps(FS)
        self.assertIn(('F8', 'reopen'), fs)
        self.assertEqual(sum(1 for s, t in fs if s == 'F10' and t == 'confirm'), 2)      # 小白重新确认了
        self.assertIn(('T15', 'done'), self.steps(f'ticket/{F}/03'))
        self.assertIn(('T15', 'done'), self.steps(f'ticket/{F}/01-2'))
