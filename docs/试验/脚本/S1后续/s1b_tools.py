import sys, json, glob, ai
P='/tmp/sop-spike-s5/proj'; IDEA=' 我想做一个记录每天喝水量的小工具'
CALL={'codex':'$grill-me','opencode':'@grill-me','pi':'/skill:grill-me'}
def final_text(tool,out):
    last=''
    for line in out.splitlines():
        line=line.strip()
        if not line.startswith('{'): continue
        try: o=json.loads(line)
        except Exception: continue
        if tool=='codex':
            it=o.get('item') or {}
            if o.get('type')=='item.completed' and it.get('type') in ('agent_message','assistant_message'): last=it.get('text') or last
        elif tool=='opencode':
            p=o.get('part') or {}
            if isinstance(p,dict) and p.get('type')=='text': last=p.get('text') or last
        elif tool=='pi':
            m=o.get('message') or {}
            if o.get('type')=='message_end' and m.get('role')=='assistant':
                t=''.join(c.get('text','') for c in m.get('content',[]) if isinstance(c,dict) and c.get('type')=='text')
                if t: last=t
    return last
for t in sys.argv[1].split(','):
    r=ai.other('S1b',f'{t}-grill-me',t,P,CALL[t]+IDEA,timeout=240)
    txt=final_text(t,r['out'])
    used=[n for n in ('grilling','grill-me') if n in r['out']]
    print(f'----- {t} ok={r["ok"]} 输出里出现过的技能名={used}\n{txt[:1400]}\n-----',flush=True)
    if not r['ok']: print('出错，停下：',r['err'][-300:]); sys.exit(2)
