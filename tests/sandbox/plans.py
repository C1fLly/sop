"""流程沙箱的剧本辅助：生成符合格式的规划产出（checks/README.md 的格式），和一套「顺利的」假 AI、人的回答。"""


def spec(stories):
    return '# 记账\n## 用户故事\n' + ''.join(f'- {s}：作为用户我要做第 {s} 件事\n' for s in stories) + '## 技术\n金额用整数分\n'


def ticket(tid, deps, cover, risk='无'):
    return (f'# {tid} 工单{tid}\n状态：未开始\n依赖：{"、".join(deps) or "无"}\n覆盖：{"、".join(cover)}\n风险：{risk}\n'
            f'## 要做什么\n做第 {tid} 件事\n## 验收标准\n- [ ] AC1：第 {tid} 件事做得到\n## 评论\n')


def card(tid):
    return f'# 验收卡 {tid}\n1. [AC1] 打开页面；操作第 {tid} 件事；预期做得到\n'


def happy(feature, tickets, new_pages=False):
    """tickets：[(编号, 依赖, 风险)]。返回 (假 AI 剧本, 人的剧本)。"""
    fd = f'.scratch/{feature}'
    sc = f'feature/{feature}'
    stories = [f'S{i + 1}' for i in range(len(tickets))]
    ai = {
        f'{sc}:F2': {'files': {f'{fd}/handoff-plan.md': f'交接\n有新页面或改页面：{"是" if new_pages else "否"}\n',
                               'GLOSSARY.md': '# 术语表\n- 账：一笔收支\n'}, 'cost': 0.3},
        f'{sc}:F3': {'files': {'apps/web/proto.txt': '原型（假数据）'}, 'cost': 0.4},
        f'{sc}:F4a': {'files': {f'{fd}/handoff-prototype.md': '原型做成了这样'}, 'cost': 0.1},
        f'{sc}:F5': {'files': {f'{fd}/spec.md': spec(stories)}, 'cost': 0.4},
        f'{sc}:F6': {'files': {f'{fd}/issues/{tid}-t.md': ticket(tid, deps, [stories[i]], risk) for i, (tid, deps, risk) in enumerate(tickets)},
                     'cost': 0.5},
        f'{sc}:F8': {'files': {**{f'{fd}/cards/{tid}.md': card(tid) for tid, _, _ in tickets}, f'{fd}/summary.md': '大白话摘要'}, 'cost': 0.3},
        f'{sc}:F9': {'result': {'findings': [{'text': '用词一致', 'blocking': False}]}, 'cost': 0.5},
        f'{sc}:F16': {'result': {'findings': []}, 'cost': 1.2},
        f'{sc}:F22': {'result': {'findings': [], 'pr_body': '复盘'}, 'cost': 0.2},
    }
    ai['*:T3'] = {'files': {'src/t{ticket}.py': '# 工单 {ticket}\n'}, 'commit': 'feat: 工单 {ticket}', 'cost': 1.5}
    ai['*:T14'] = {'merge': f'refs/remotes/origin/feat/{feature}', 'merge_take': 'ours', 'cost': 0.6}
    for tid, _, _ in tickets:
        ai[f'ticket/{feature}/{tid}:T3'] = {'files': {f'src/t{tid}.py': f'# 工单 {tid}\n'}, 'commit': f'feat: 工单 {tid}', 'cost': 1.5}
        ai[f'ticket/{feature}/{tid}:T9'] = {'result': {'findings': []}, 'cost': 1.2}
        ai[f'ticket/{feature}/{tid}:T14'] = {'merge': f'refs/remotes/origin/feat/{feature}', 'merge_take': 'ours', 'cost': 0.6}
    human = {f'{sc}:F2': [{'answer': '是'}], f'{sc}:F5': [{'answer': '是'}], f'{sc}:F6': [{'answer': '是'}],
             f'{sc}:F4': [{'answer': '满意'}], f'{sc}:F10': [{'answer': '是'}], f'{sc}:F13': [{'answer': ''}],
             f'{sc}:F17': [{'answer': '通过'}], '*:T11': [{'answer': '通过'}] * 10}
    return ai, human
