import sys, subprocess, time
sys.path.insert(0, '/tmp/sop-spike-ai'); import ai
B = '/tmp/sop-spike-s7b'; R = f'{B}/proj'
BINDS = ' '.join([f'ro:{R}/.git', f'rw:{R}/.git/objects', f'rw:{R}/.git/worktrees', f'ro:{R}/.git/worktrees/main',
    f'rw:{R}/.git/refs/heads/ticket/jizhang', f'rw:{R}/.git/refs/heads/feat', f'rw:{R}/.git/logs/refs/heads/ticket/jizhang',
    f'rw:{R}/.git/logs/refs/heads/feat', f'ro:{R}/main', f'ro:{R}/.shared', f'rw:{R}/.shared/notes',
    f'rw:{R}/.shared/broker/requests', f'ro:{R}/feat-jizhang/.git'])
ENV = {'EXTRA_BINDS': BINDS, 'CHDIR': f'{R}/feat-jizhang', 'EXTRA_PATH': f'{R}/.shared/bin'}
PROMPT = '/implement-spec ' + open(f'{B}/task.txt', encoding='utf-8').read()
broker = subprocess.Popen(['python3', f'{B}/broker.py'], stdout=open(f'{B}/broker.out', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
time.sleep(1)
try:
    r = ai.claude('S7b', 'implement-spec-原样技能', R, PROMPT, f'{B}/state-claude', max_usd=6.0, timeout=2700, env=ENV)
    print('=== AI 的最后汇报 ===\n' + (r['result'] or '')[:4000])
    print('=== ok', r['ok'], 'subtype', r['subtype'], '花费', r['cost'], '用时', round(r['secs']))
finally:
    open(f'{B}/broker.stop', 'w').close(); time.sleep(1.5); broker.terminate()
