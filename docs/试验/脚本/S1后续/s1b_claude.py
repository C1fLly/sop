import sys, ai
B='/tmp/sop-spike-s1b'
T={'research':(f'{B}/research','/research Python 标准库 json.dump 的 ensure_ascii 参数默认值是什么？设成 False 有什么效果？以官方文档为准。',1.5),
   'codereview':(f'{B}/codereview','/code-review',1.8),
   'tdd':(f'{B}/tdd','/tdd 给这个项目加一个函数 slugify(text)，放在 textkit 里：把一句话变成网址里能用的小写短横线形式，比如 "Hello World" 变成 "hello-world"。',1.8)}
name=sys.argv[1]; wd,prompt,cap=T[name]
resume=sys.argv[2] if len(sys.argv)>2 else None
if resume: prompt=sys.argv[3]
r=ai.claude('S1b',f'claude-{name}'+('-resume' if resume else ''),wd,prompt,f'{B}/state-{name}',max_usd=cap,timeout=900,resume=resume)
print('=== 最后的回答 ===\n'+(r['result'] or '')[:3000]); print('=== ok',r['ok'],'subtype',r['subtype'],'花费',r['cost'],'用时',round(r['secs']),'会话',r['session'])
