#!/usr/bin/env python3
"""数一个 Claude Code 状态目录里的会话记录：用了哪些工具、派了几个帮手、调用了哪些技能、有没有越界的命令。
用法: transcript_stats.py <状态目录>   （只用于本试验自己启动的 Claude Code 会话）"""
import json, sys, pathlib, collections, re
root = pathlib.Path(sys.argv[1]); files = sorted(root.rglob('*.jsonl'))
tools = collections.Counter(); skills = collections.Counter(); agents = []; bad = []; sopreq = []
BAD = re.compile(r'git\s+(-C\s+\S+\s+)?(worktree\s+add|push|fetch|checkout\s+-b|switch\s+-c|branch\s+(?!--show|--contains|--merged|--no-merged|-a\b|-l\b|--list|-v|-r\b)\S|worktree\s+(remove|prune))|\bgh\s|isolation')
for f in files:
    sub = 'subagents' in str(f) or f.name.startswith('agent-')
    for line in f.open():
        try: o = json.loads(line)
        except Exception: continue
        m = o.get('message') or {}
        c = m.get('content') if isinstance(m, dict) else None
        if not isinstance(c, list): continue
        for b in c:
            if not isinstance(b, dict) or b.get('type') != 'tool_use': continue
            n = b.get('name'); i = b.get('input') or {}; tools[('帮手:' if sub else '主会话:') + n] += 1
            if n == 'Skill': skills[('帮手:' if sub else '主会话:') + str(i.get('skill'))] += 1
            if n in ('Agent', 'Task'): agents.append((i.get('description'), i.get('subagent_type'), i.get('isolation'), bool(i.get('run_in_background'))))
            if n == 'Bash':
                cmd = i.get('command', '')
                if 'sopreq' in cmd: sopreq.append(('帮手' if sub else '主会话', re.findall(r'sopreq [a-z-]+(?: \S+)?', cmd)))
                if BAD.search(cmd): bad.append(('帮手' if sub else '主会话', cmd[:160].replace('\n', ' ; ')))
            if n in ('Agent', 'Task') and i.get('isolation'): bad.append(('主会话', f'帮手用了自带的隔离：{i.get("isolation")}'))
print(f'会话记录文件 {len(files)} 个（其中帮手的 {sum(1 for f in files if "subagents" in str(f) or f.name.startswith("agent-"))} 个）')
print('工具调用：', dict(sorted(tools.items())))
print('技能调用：', dict(skills))
print(f'派出帮手 {len(agents)} 个：'); [print('   ', a) for a in agents]
print('谁执行了 sopreq：', sopreq)
print(f'越界的命令 {len(bad)} 条：'); [print('   ', b) for b in bad]
