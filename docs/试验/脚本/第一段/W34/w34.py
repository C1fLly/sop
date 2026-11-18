import sys, subprocess, json, pathlib, re
sys.path.insert(0, '/tmp/sop-spike-ai'); import ai
P = '/tmp/sop-p1-w34'; R = f'{P}/proj'; F = f'{R}/feat-qingjia'; REG = f'{R}/.git/worktrees/feat-qingjia'
run = sys.argv[1]          # A 或 B
BINDS = f'ro:{R}/.git rw:{REG} ro:{REG}/commondir ro:{REG}/gitdir ro:{F}/.git'   # 提交内容也只读；不放开任何分支指针
ENV = {'EXTRA_BINDS': BINDS, 'CHDIR': F}
common = ('/to-tickets 规格在 .scratch/请假登记/spec.md。补充说明（和技能原文不一样的地方以这里为准）：'
          '1. 拆工单时本该问用户的问题（拆多细、先后顺序），按你的推荐决定，不要停下来等；在最后的回答里列出你替用户定了哪些。'
          '2. 工单文件写在 .scratch/请假登记/issues/ 下。')
last = {'A': '3. 不要提交、不要建分支、不要推送。这一步结束后由流程命令统一提交。',
        'B': '3. 完成后请把你的改动提交到当前分支。'}[run]
state = f'{P}/state-{run}'
r = ai.claude('第一段', f'W34-{run}', F, common + last, state, max_usd=3.0, timeout=1500, env=ENV)
print('=== AI 的最后回答 ===\n' + (r['result'] or '')[:3000])
print('=== ok', r['ok'], 'subtype', r.get('subtype'), '花费', r['cost'], '用时', round(r['secs']))
# 从会话记录里找它执行过的 git 命令
cmds = []
for f in pathlib.Path(state).rglob('*.jsonl'):
    for line in f.read_text(errors='replace').splitlines():
        try: j = json.loads(line)
        except Exception: continue
        for c in (j.get('message') or {}).get('content') or []:
            if isinstance(c, dict) and c.get('type') == 'tool_use' and c.get('name') == 'Bash':
                cmd = c['input'].get('command', '')
                if 'git' in cmd: cmds.append(cmd[:200])
print('=== 会话里执行过的 git 命令 ===\n' + ('\n'.join(cmds) or '（没有）'))
