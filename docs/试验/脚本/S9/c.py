import sys
sys.path.insert(0,'/tmp/sop-spike-ai'); import ai
B='/tmp/sop-spike-s9'
r=ai.claude('S9','真实结构-implement-01','ticket-stack-1','/implement .scratch/stack/issues/01-按说明查找.md',f'{B}/state-c',max_usd=3.5,timeout=2400,sbx=f'{B}/s9env.sh')
print('=== 汇报 ===\n'+(r['result'] or '')[:3500]); print('=== ok',r['ok'],'subtype',r['subtype'],'花费',r['cost'],'用时',round(r['secs']))
