#!/usr/bin/env python3
"""S0 主链试走的驱动脚本。
干活的 AI（Claude Code + 技能）和扮演小白的 AI 都在受限环境里运行，本脚本在外面来回传话并记账。
用法: driver.py grill | spec | tickets | implement | report
"""
import glob, json, os, re, subprocess, sys, time

S = '/tmp/sop-spike-s0'; PROJ = S + '/proj'; LOG = S + '/log'; STATEF = S + '/state.json'
STOP_AT = 18.5   # 用户给的上限是 20 美元；到这个数就不再发起新的调用

IDEA = ('我开了一家 12 个人的小设计公司。现在大家请假都是在微信里跟我说一声，月底算考勤的时候很乱，经常对不上。'
        '我想要一个小工具：员工能登记请假，我来批准或者不批，月底我能看到每个人这个月请了几天假。先做一个最简单、能用的版本。')

PERSONA = '''你在扮演一位完全没有编程基础的小公司老板，正在回答一个 AI 开发助手的提问。你不是助手，你是被提问的人。

你的情况：公司 12 个人，做平面设计。请假只有三种：年假、病假、事假。只有你一个人审批。员工不多，彼此都认识。你只想要第一版最简单、能用的东西，可有可无的功能一律回答「第一版不要」。

回答规则：
1. 按题号逐条回答，每条一两句大白话。
2. 标着【业务】的问题，凭你的业务常识自己定。对方给了推荐答案而你没有不同想法时，回答「同意」。
3. 标着【技术】的问题，统一回答：技术题按你的推荐，并记入决策记录。
4. 没有标记的问题：看得懂、属于公司业务的就照第 2 条答；看不懂的就照第 3 条答。
5. 对方没有提问、只是在总结或者请你确认时，回答：确认，没有别的要补充了。
6. 不提新需求，不反问，不使用任何工具，不写代码。
7. 回答的最后另起一行，写「看不懂的题：」，后面列出你其实看不懂的题号；没有就写「无」。'''


def load():
    if os.path.exists(STATEF):
        return json.load(open(STATEF))
    return {'n': 0, 'total': 0.0, 'sess_cost': {}, 'worker_sid': None, 'novice_sid': None, 'calls': []}


def save(st):
    json.dump(st, open(STATEF, 'w'), ensure_ascii=False, indent=1)


def call(role, phase, prompt, resume=None, budget=1.0, timeout=900):
    st = load()
    if st['total'] >= STOP_AT:
        print(f'!! 花费已到 {st["total"]:.2f} 美元，停止发起新的调用'); sys.exit(3)
    wd = S + '/novice' if role == 'novice' else PROJ
    env = dict(os.environ, STATE=f'{S}/aistate/{"novice" if role == "novice" else "worker"}')
    cmd = [S + '/sbx.sh', wd]
    if resume:
        cmd += ['--resume', resume]
    cmd += ['-p', prompt, '--output-format', 'json', '--max-budget-usd', str(budget)]
    if role == 'novice':
        pass   # 普通调用。带自定义系统提示词的调用被这台电脑接的服务拒绝了（原因没有追查），所以人设放在第一句话里
    else:
        cmd += ['--dangerously-skip-permissions']
    st['n'] += 1; n = st['n']; save(st)
    base = f'{LOG}/{n:03d}-{role}-{phase}'
    open(base + '.prompt.txt', 'w').write(prompt)
    t = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, err, rc = (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or ''), '超时', -9
    secs = round(time.time() - t)
    open(base + '.raw.json', 'w').write(out); open(base + '.err.txt', 'w').write(err or '')
    try:
        d = json.loads(out)
    except Exception:
        d = {'result': '', 'is_error': True, 'parse_failed': True}
    result = d.get('result') or ''
    sid = d.get('session_id') or resume
    cost = d.get('total_cost_usd') or 0.0
    st = load()
    # 续接同一个会话时，工具报告的是这个会话的累计花费，所以只记增量
    prev = st['sess_cost'].get(sid, 0.0) if sid else 0.0
    delta = cost - prev if cost >= prev else cost
    if sid:
        st['sess_cost'][sid] = max(cost, prev)
    st['total'] = round(st['total'] + delta, 4)
    rec = {'n': n, 'role': role, 'phase': phase, 'secs': secs, 'cost': round(delta, 4), 'turns': d.get('num_turns'),
           'rc': rc, 'is_error': d.get('is_error'), 'sid': sid, 'q': len(re.findall('❓', result)),
           'biz': result.count('【业务】'), 'tech': result.count('【技术】'), 'chars': len(result),
           'subtype': d.get('subtype')}
    st['calls'].append(rec); save(st)
    open(base + '.result.txt', 'w').write(result)
    print(f'[{n:03d}] {role:6s} {phase:14s} {secs:4d}秒 花费{delta:6.3f} 累计{st["total"]:6.2f} | 问题{rec["q"]:2d} 业务{rec["biz"]:2d} 技术{rec["tech"]:2d} | '
          f'{"出错 " if rec["is_error"] else ""}{result[:70]!r}', flush=True)
    if rec['is_error'] or rc != 0 or not result:
        print(f'!! 第 {n} 次调用出错，停下，不把错误内容传给下一步。详见 {base}.*'); sys.exit(4)
    return result, sid


def has_q(text):
    return '❓' in text or bool(re.search(r'(?m)^\s*\**Q\d+', text))


def novice(phase, text):
    st = load()
    head = '' if st.get('novice_sid') else PERSONA + '\n\n在整个对话里你都要保持这个身份。\n\n=====\n\n'
    ans, sid = call('novice', phase, head + '开发助手对你说了下面这段话，请按规则回答：\n\n' + text, resume=st.get('novice_sid'), budget=1.0, timeout=300)
    st = load(); st['novice_sid'] = sid; save(st)
    m = re.search(r'看不懂的题[:：]\s*(.*)', ans)
    st = load(); st.setdefault('not_understood', []).append({'phase': phase, 'n': st['n'], 'text': m.group(1).strip() if m else '（没有按格式写）'}); save(st)
    return ans


def worker(phase, prompt, budget=1.5, timeout=900, new=False):
    st = load()
    out, sid = call('worker', phase, prompt, resume=None if new else st.get('worker_sid'), budget=budget, timeout=timeout)
    if not new:
        st = load(); st['worker_sid'] = sid; save(st)
    return out, sid


def sh(*cmd):
    """在受限环境里执行一条命令（git、测试），不带任何密钥。"""
    p = subprocess.run([S + '/sbx.sh', PROJ, *cmd], capture_output=True, text=True, env=dict(os.environ, RAW='1'))
    return p.returncode, (p.stdout + p.stderr).strip()


def grill():
    st = load()
    last = [c for c in st['calls'] if c['role'] == 'worker' and not c['is_error']]
    if st.get('worker_sid') and last:   # 接着上一次中断的地方做
        out = open(f"{LOG}/{last[-1]['n']:03d}-worker-{last[-1]['phase']}.result.txt").read(); r = len(last)
    else:
        out, _ = worker('追问1', '/grill-with-docs ' + IDEA, budget=2.0); r = 1
    while has_q(out) and r < 10:
        ans = novice(f'追问{r}', out)
        r += 1
        out, _ = worker(f'追问{r}', '我的回答：\n' + ans, budget=2.0)
    out, _ = worker('追问确认', '确认，我们已经达成共识，没有别的要补充了。请把该记的术语和决策记录写好。', budget=2.0)
    out, _ = worker('交接', '/handoff 之后在同一个项目里写规格、拆工单', budget=1.5)
    print('--- 追问阶段结束后项目里的文件:'); print(sh('git', 'status', '--short')[1][:600]); print('--- 临时目录里的文件:', os.listdir(S + '/ostmp'))


def until_files(phase, first_prompt, pattern, max_rounds, budget):
    out, _ = worker(f'{phase}1', first_prompt, budget=budget, timeout=1200)
    r = 1
    while not glob.glob(PROJ + '/' + pattern) and r < max_rounds:
        ans = novice(f'{phase}{r}', out)
        r += 1
        out, _ = worker(f'{phase}{r}', '我的回答：\n' + ans, budget=budget, timeout=1200)
    files = sorted(glob.glob(PROJ + '/' + pattern))
    print(f'--- {phase}阶段：{len(files)} 个文件:', [f.replace(PROJ + '/', '') for f in files])
    return out


def spec():
    until_files('规格', '/to-spec', '.scratch/*/spec.md', 5, 3.0)


def tickets():
    until_files('工单', '/to-tickets', '.scratch/*/issues/*.md', 6, 3.0)
    print(sh('bash', '-c', 'git add -A && git commit -q -m "规划：术语、决策记录、规格、工单" && git log --oneline | head -3')[1])


def implement():
    files = sorted(glob.glob(PROJ + '/.scratch/*/issues/*.md'))
    st = load(); done = st.setdefault('implemented', []); save(st)
    for f in files:
        rel = f.replace(PROJ + '/', '')
        if rel in done:
            continue
        before = sh('git', 'rev-parse', 'HEAD')[1]
        out, sid = worker('实现 ' + os.path.basename(rel)[:2], '/implement ' + rel, budget=5.0, timeout=2400, new=True)
        r = 0
        while sh('git', 'rev-parse', 'HEAD')[1] == before and r < 2:
            r += 1
            ans = novice('实现提问', out)
            out, _ = call('worker', '实现续 ' + os.path.basename(rel)[:2], '我的回答：\n' + ans, resume=sid, budget=5.0, timeout=2400)
        after = sh('git', 'rev-parse', 'HEAD')[1]
        ncommits = sh('git', 'rev-list', '--count', f'{before}..{after}')[1] if after != before else '0'
        dirty = sh('git', 'status', '--short')[1]
        trc, tout = sh('python3', '-m', 'unittest', 'discover', '-s', 'tests')
        st = load()
        st['implemented'].append(rel)
        st.setdefault('impl', []).append({'ticket': rel, 'sid': sid, 'commits': ncommits, 'asked_rounds': r, 'dirty': bool(dirty),
                                         'tests_rc': trc, 'tests_tail': tout[-200:]})
        save(st)
        print(f'--- {rel}: 新提交 {ncommits} 个，中途提问 {r} 轮，工作区{"不" if dirty else ""}干净，全部测试退出码 {trc}：{tout.splitlines()[-1] if tout else ""}', flush=True)


def report():
    st = load()
    print(f'调用 {st["n"]} 次，累计花费 {st["total"]:.2f} 美元，累计用时 {sum(c["secs"] for c in st["calls"]) / 60:.1f} 分钟')
    agg = {}
    for c in st['calls']:
        k = (c['role'], re.sub(r'[\d ].*$', '', c['phase']))
        a = agg.setdefault(k, [0, 0.0, 0, 0, 0, 0]); a[0] += 1; a[1] += c['cost']; a[2] += c['secs']; a[3] += c['q']; a[4] += c['biz']; a[5] += c['tech']
    for (role, ph), a in agg.items():
        print(f'  {role:6s} {ph:6s} 调用{a[0]:2d}次 花费{a[1]:6.2f} 用时{a[2] / 60:5.1f}分 问题{a[3]:3d} 业务{a[4]:3d} 技术{a[5]:3d}')
    print('看不懂的题:', json.dumps(st.get('not_understood', []), ensure_ascii=False))
    print('实现:', json.dumps(st.get('impl', []), ensure_ascii=False))


if __name__ == '__main__':
    {'grill': grill, 'spec': spec, 'tickets': tickets, 'implement': implement, 'report': report}[sys.argv[1]]()
