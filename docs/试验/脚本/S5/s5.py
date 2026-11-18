import sys, json, ai
P='/tmp/sop-spike-s5/proj'
Q1='不要执行任何命令，不要读任何文件。请列出你现在能用的全部技能（skill）的名字，每行一个，只列名字，不要解释。如果同一个名字出现了不止一次，就照实列多次。'
Q2='S5 的暗号是什么？'
EXPL={'claude':'/sop-canary-human','codex':'$sop-canary-human','opencode':'@sop-canary-human','pi':'/skill:sop-canary-human'}
NONE={'claude':'/no-such-skill-xyz 你好','codex':'$no-such-skill-xyz 你好','opencode':'@no-such-skill-xyz 你好','pi':'/skill:no-such-skill-xyz 你好'}
def ask(tool,label,prompt):
    if tool=='claude':
        r=ai.claude('S5',f'{tool}-{label}',P,prompt,f'/tmp/sop-spike-s5/state-claude',max_usd=0.6,timeout=300)
        txt=r['result']
    else:
        r=ai.other('S5',f'{tool}-{label}',tool,P,prompt,timeout=300)
        txt=ai.text_of(tool,r['out'])
    print(f'----- {tool} {label} ok={r["ok"]}\n{txt[:1500]}\n-----',flush=True)
    if not r['ok']:
        print('出错，停下。stderr 末尾：', (r.get('err') or '')[-600:]); sys.exit(2)
    return txt
tools=sys.argv[1].split(','); which=sys.argv[2].split(',')
for t in tools:
    if 'list' in which: ask(t,'list',Q1)
    if 'auto' in which: ask(t,'auto',Q2)
    if 'explicit' in which: ask(t,'explicit',EXPL[t])
    if 'none' in which: ask(t,'none',NONE[t])
