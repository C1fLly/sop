import sys, json, glob, os
sys.path.insert(0, '/tmp/sop-spike-ai'); import ai
W = '/tmp/sop-spike-s7/w15'; which = sys.argv[1]
r = ai.claude('S7', f'w15-{which}-implement-09', f'{W}/{which}', '/implement .scratch/请假登记/issues/09-已离职.md', f'{W}/state-{which}', max_usd=4.0, timeout=2400)
print('=== 汇报 ===\n' + (r['result'] or '')[:2500]); print('=== ok', r['ok'], '花费', r['cost'], '用时', round(r['secs']), '轮数', (r['raw'] or {}).get('num_turns'))
