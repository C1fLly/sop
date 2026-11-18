#!/usr/bin/env python3
"""S5、S7、S1 后续共用：在受限环境里调用 AI 工具，并记账。

规矩（用户定的）：
- 三项合计上限 30 美元；每次调用前先看累计数，到 28 美元就不再发起新的调用。
- 一步出错就停，不把报错当结果往下传。
- Claude Code 续接会话时报告的是会话累计数，这里只记增量。
- Codex、OpenCode、Pi 不报告金额：能读到词元数的按保守单价估，读不到的按每次 0.30 美元记。
"""
import json, os, subprocess, sys, time, re, pathlib

ROOT = pathlib.Path('/tmp/sop-spike-ai')
LEDGER = ROOT / 'ledger.json'
LOG = ROOT / 'log'
SBX = str(ROOT / 'sbx.sh')
STOP_AT = 28.0      # 到这个数不再发起新的调用
HARD = 30.0         # 用户给的上限
EST_IN, EST_OUT = 5.0 / 1e6, 25.0 / 1e6   # 另外三个工具的保守估价（美元/词元）
FLAT = 0.30         # 读不到词元数时每次记这么多


class Stop(Exception):
    pass


def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {'entries': [], 'sessions': {}}


def save(d):
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def spent(d=None):
    d = d or load()
    return round(sum(e['cost'] for e in d['entries']), 4)


def by_exp():
    d = load(); out = {}
    for e in d['entries']:
        out[e['exp']] = round(out.get(e['exp'], 0) + e['cost'], 4)
    return out


def guard():
    s = spent()
    if s >= STOP_AT:
        raise Stop(f'累计 {s:.2f} 美元，已到 {STOP_AT} 美元，不再发起新的调用')
    return s


def _run(env_extra, args, timeout):
    env = dict(os.environ); env.update(env_extra)
    t0 = time.time()
    try:
        p = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr, time.time() - t0, False
    except subprocess.TimeoutExpired as e:
        so = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or '')
        se = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or '')
        return -9, so, se, time.time() - t0, True


def _logname(d, exp, label):
    n = len(d['entries']) + 1
    return LOG / f'{n:03d}-{exp}-{label}'


def claude(exp, label, wd, prompt, state, resume=None, max_usd=1.0, timeout=1800, rw='', ro='', extra_args=(), env=None, sbx=None):
    """调用 Claude Code。返回 dict：ok、result、session、cost（本次增量）、secs、raw。"""
    s = guard(); d = load()
    cap = round(min(max_usd, HARD - s - 0.3), 2)
    if cap <= 0.05:
        raise Stop(f'累计 {s:.2f} 美元，剩余额度不够再发起一次调用')
    args = [sbx or SBX, wd, '-p', prompt, '--output-format', 'json', '--dangerously-skip-permissions', '--max-budget-usd', str(cap)]
    if resume:
        args += ['--resume', resume]
    args += list(extra_args)
    base = _logname(d, exp, label)
    pathlib.Path(str(base) + '.prompt.txt').write_text(prompt)
    e = {'TOOL': 'claude', 'STATE': state, 'EXTRA_RW': rw, 'EXTRA_RO': ro}; e.update(env or {})
    rc, out, err, secs, to = _run(e, args, timeout)
    pathlib.Path(str(base) + '.out.json').write_text(out)
    d = load()   # 重新读一遍账本：调用期间别的调用可能已经记过账
    pathlib.Path(str(base) + '.err.txt').write_text(err)
    j = None
    try:
        j = json.loads(out)
        if isinstance(j, list):   # 有的版本输出一个数组，最后一项是结果
            j = [x for x in j if isinstance(x, dict) and x.get('type') == 'result'][-1]
    except Exception:
        j = None
    total = float(j.get('total_cost_usd', 0) or 0) if j else 0.0
    sid = j.get('session_id') if j else None
    prev = d['sessions'].get(sid, 0.0) if (resume and sid) else 0.0
    inc = round(max(total - prev, 0.0), 4)
    basis = '工具报告'
    if j is None:
        # 读不到报告：超时或崩溃。按这次调用的上限记，宁多勿少。
        inc = cap; basis = '没读到报告，按本次上限记'
    if sid:
        d['sessions'][sid] = total
    ok = bool(j) and not j.get('is_error') and rc == 0 and not to
    d['entries'].append({'n': len(d['entries']) + 1, 'exp': exp, 'label': label, 'tool': 'claude', 'cost': inc,
                         'basis': basis, 'secs': round(secs), 'ok': ok, 'session': sid, 'resumed': bool(resume),
                         'turns': j.get('num_turns') if j else None, 'timeout': to, 'rc': rc})
    save(d)
    res = {'ok': ok, 'result': (j or {}).get('result', ''), 'session': sid, 'cost': inc, 'secs': secs, 'raw': j,
           'rc': rc, 'timeout': to, 'subtype': (j or {}).get('subtype'), 'log': str(base)}
    print(f'[{exp}/{label}] claude ok={ok} 花费+{inc:.3f} 累计={spent(d):.2f} 用时={secs:.0f}s 轮数={res["raw"].get("num_turns") if j else "?"}', flush=True)
    return res


OTHER_CMD = {
    'codex': lambda p: ['exec', '--dangerously-bypass-approvals-and-sandbox', '--skip-git-repo-check', '--ephemeral', '--json', p],
    'opencode': lambda p: ['run', '--auto', '--format', 'json', p],
    'pi': lambda p: ['-p', '--mode', 'json', '--no-session', '-a', p],
}


def _tokens(out):
    """从输出里尽量找词元数。返回 (输入, 输出, 工具自己报的金额或 None)。"""
    tin = tout = 0; cost = None; found = False
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        stack = [o]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
                keys = set(x.keys())
                if keys & {'input_tokens', 'output_tokens'}:
                    found = True
                    tin = max(tin, int(x.get('input_tokens') or 0)); tout = max(tout, int(x.get('output_tokens') or 0) + int(x.get('reasoning_output_tokens') or 0))
                if 'tokens' in x and isinstance(x['tokens'], dict):
                    t = x['tokens']; found = True
                    tin += int(t.get('input') or 0); tout += int(t.get('output') or 0) + int(t.get('reasoning') or 0)
                if 'usage' in x and isinstance(x['usage'], dict):
                    u = x['usage']
                    if 'input' in u or 'output' in u:
                        found = True
                        tin = max(tin, int(u.get('input') or 0) + int(u.get('cacheRead') or 0)); tout = max(tout, int(u.get('output') or 0))
                    c = u.get('cost')
                    if isinstance(c, dict) and isinstance(c.get('total'), (int, float)):
                        cost = max(cost or 0, float(c['total']))
                if isinstance(x.get('cost'), (int, float)) and x.get('cost'):
                    cost = (cost or 0) + float(x['cost'])
            elif isinstance(x, list):
                stack.extend(x)
    return (tin, tout, cost) if found or cost is not None else (None, None, None)


def other(exp, label, tool, wd, prompt, timeout=600, rw='', ro=''):
    """调用 Codex、OpenCode 或 Pi。返回 dict：ok、out（原始输出）、cost（估算）、secs。"""
    guard(); d = load()
    base = _logname(d, exp, label)
    pathlib.Path(str(base) + '.prompt.txt').write_text(prompt)
    rc, out, err, secs, to = _run({'TOOL': tool, 'EXTRA_RW': rw, 'EXTRA_RO': ro}, [SBX, wd] + OTHER_CMD[tool](prompt), timeout)
    pathlib.Path(str(base) + '.out.txt').write_text(out)
    d = load()   # 重新读一遍账本
    pathlib.Path(str(base) + '.err.txt').write_text(err)
    tin, tout, c = _tokens(out)
    if tin is None:
        cost = FLAT; basis = f'没有词元数，按每次 {FLAT} 记'
    else:
        est = tin * EST_IN + tout * EST_OUT
        cost = round(max(est, c or 0), 4)
        basis = f'估算：输入 {tin} 输出 {tout} 词元，按每百万 5 和 25 美元' + (f'；工具自报 {c:.4f}' if c is not None else '')
    ok = rc == 0 and not to
    d['entries'].append({'n': len(d['entries']) + 1, 'exp': exp, 'label': label, 'tool': tool, 'cost': cost, 'basis': basis,
                         'secs': round(secs), 'ok': ok, 'timeout': to, 'rc': rc})
    save(d)
    print(f'[{exp}/{label}] {tool} ok={ok} rc={rc} 花费+{cost:.3f}（{basis}） 累计={spent(d):.2f} 用时={secs:.0f}s', flush=True)
    return {'ok': ok, 'out': out, 'err': err, 'cost': cost, 'secs': secs, 'rc': rc, 'timeout': to, 'log': str(base)}


def text_of(tool, out):
    """从另外三个工具的 JSON 输出里拼出 AI 说的话，供人看和做关键字判断。"""
    parts = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        stack = [o]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k in ('text', 'delta', 'content', 'message', 'output', 'aggregated_output', 'command'):
                    v = x.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                    elif isinstance(v, (dict, list)):
                        stack.append(v)
                for k, v in x.items():
                    if k not in ('text', 'delta', 'content', 'message', 'output', 'aggregated_output', 'command') and isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(x, list):
                stack.extend(x)
    return '\n'.join(parts) if parts else out


if __name__ == '__main__':
    d = load()
    print(f'累计 {spent(d):.2f} 美元；分项 {by_exp()}；调用 {len(d["entries"])} 次')
