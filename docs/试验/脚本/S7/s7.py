import sys, subprocess, time, json, os
sys.path.insert(0, '/tmp/sop-spike-ai'); import ai
R = '/tmp/sop-spike-s7/proj'
BINDS = ' '.join([f'ro:{R}/.git', f'rw:{R}/.git/objects', f'rw:{R}/.git/worktrees', f'ro:{R}/.git/worktrees/main',
    f'rw:{R}/.git/refs/heads/ticket/jizhang', f'rw:{R}/.git/refs/heads/feat', f'rw:{R}/.git/logs/refs/heads/ticket/jizhang',
    f'rw:{R}/.git/logs/refs/heads/feat', f'ro:{R}/main', f'ro:{R}/.shared', f'rw:{R}/.shared/notes',
    f'rw:{R}/.shared/broker/requests', f'ro:{R}/feat-jizhang/.git'])
ENV = {'EXTRA_BINDS': BINDS, 'CHDIR': f'{R}/feat-jizhang', 'EXTRA_PATH': f'{R}/.shared/bin'}
PROMPT = ('/implement-spec 规格在 .scratch/jizhang/spec.md，工单在 .scratch/jizhang/issues/ 下。'
          '补充说明：这个环境里 git 提交或合并时会打印一行「Unable to create …packed-refs.lock: Read-only file system」，'
          '这是正常的，提交和合并其实成功了，不用理会。')
broker = subprocess.Popen(['python3', '/tmp/sop-spike-s7/broker.py'], stdout=open('/tmp/sop-spike-s7/broker.out', 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
time.sleep(1)
try:
    r = ai.claude('S7', 'implement-spec', R, PROMPT, '/tmp/sop-spike-s7/state-claude', max_usd=float(sys.argv[1]) if len(sys.argv) > 1 else 10.0, timeout=2700, env=ENV)
    print('=== AI 的最后汇报 ===\n' + (r['result'] or '')[:4000])
    print('=== ok', r['ok'], 'subtype', r['subtype'], '花费', r['cost'], '用时', round(r['secs']))
finally:
    open('/tmp/sop-spike-s7/broker.stop', 'w').close(); time.sleep(1.5); broker.terminate()
