"""Claude Code 的真实 AI 演练（设计书 16.2、10.1；3-29）。花 AI 的钱（几美分），不在全部自测里。

在 /tmp 现建的一次性小项目里（工作目录里放一个技能副本 wait-what：原文标着只允许人触发、内容很短），用真的 Claude Code 跑：

1. 交互：打开一次对话窗口、不发消息，看首次启动的那几屏出没出（check_screens）；再在模拟终端里用 start_interactive 打开，
   开场内容是点名了技能的任务包，等它回答、/exit。要：直接是输入框、没出那几屏、退出码 0、它回答了、技能加载了。
2. 自动调用、技能触发、结果文件：run_headless 执行点名了技能的任务包。要：退出码 0、技能加载了、结果文件过结果文件检查、
   工作目录没被改。
3. 反着试（不花钱）：任务包点名一个工作目录里没有副本的技能，适配器不调用、说清楚。

都过了才调 mark_drilled 记下演练过的版本（之后 probe 和 sop 启动时不再提醒，直到版本又变了）。碰到余额不足、额度类的报错就停、不重试。
每次真的调用记一笔 calls（给调用方记账）。小白真用时对话窗口开在他自己的终端里，不经过模拟终端；这里的模拟终端只给演练用。

用法：python3 -m adapters.ai.claude.drill（工具包目录里执行；结果打印出来，记进 config/tools.json）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

from adapters.ai import ptyscreen
from adapters.ai.base import mark_drilled
from adapters.ai.claude import adapter as C
from checks.project_layout import core as layout
from checks.quota_scan.check import run as quota_scan
from checks.result_file.check import run as check_result
from kernel.project import TOOLKIT
from runner import placement, sandbox

SKILL = 'wait-what'          # 原文标着只允许人触发（disable-model-invocation），正文一段话，演练花得少
MISSING = 'no-such-skill-sop-drill'
CODE = '青石七三'


@dataclass
class Drill:
    ok: bool = False
    version: str = ''
    parts: list = field(default_factory=list)      # [(哪一样, 过没过, 给人看的话)]
    calls: list = field(default_factory=list)      # [{what, cost, basis, secs, rc}]：真的调用过的，给调用方记账
    quota: bool = False
    message: str = ''


def _task(d, n, body, skill=None, budget=1.0):
    t = pathlib.Path(d) / f'run-{n}'
    (t / 'task').mkdir(parents=True)
    (t / 'out').mkdir()
    (t / 'task' / 'task.md').write_text(body, encoding='utf-8')
    (t / 'task' / 'task.json').write_text(json.dumps({'scope': 'drill', 'step': 'drill', 'attempt': n, 'skill': skill,
                                                      'result_path': f'{placement.OUT_MNT}/result.json', 'budget_usd': budget,
                                                      'kind': 'review'}, ensure_ascii=False))
    return t


def _pack(goal, skill):
    return (f'# 任务包：演练（SOP 工具包的真实 AI 演练，16.2）\n\n## 目标\n{goal}\n\n'
            f'## 技能\n{f"调用 `{skill}`。" if skill else "无。"}\n\n'
            '## 禁止\n- 不改工作目录里的任何文件，不执行任何命令\n\n'
            '## 不确定时\n不猜，照常结束。\n')


HEADLESS_GOAL = ('这是一次演练，只检查点名的技能能不能加载。技能加载以后不要照它的流程做，只做下面这件事：'
                 f'写一份 JSON 结果文件到 {placement.OUT_MNT}/result.json，内容是 '
                 '{"status": "done", "commits": [], "commands": [], "deviations": [], "questions": [], '
                 '"findings": [{"text": "<用一句中文说这个技能要你做什么>", "blocking": false}]}。写好就结束。')
CHAT_GOAL = f'这是一次演练，只检查对话窗口和点名的技能。技能加载以后不要照它的流程做：请记住暗号「{CODE}」，只回答三个字：记好了'


def run(adapter=None, record=True, say=print, wait=120):
    """跑演练，返回 Drill。record：都过了就 mark_drilled。"""
    a = adapter or C.ClaudeAdapter()
    res = Drill()
    path, _ = a.location()
    if not path:
        res.message = '没找到 Claude Code（官方装法的默认位置是 ~/.local/bin/claude）'
        return res
    res.version = a.version()
    env, src = a.credentials()
    if not res.version or not env:
        res.message = 'Claude Code 查不出版本，或者没找到服务地址和密钥（先跑 sop machine setup 的「登录 AI 工具」）'
        return res
    if not sandbox.tiocsti_disabled():
        res.message = '这台电脑的内核没有禁用「往终端里塞按键」，对话步骤不能启动，演练不了交互那一样'
        return res

    def book(what, out, secs):
        res.calls.append({'what': what, 'cost': float(out.get('cost') or 0.0), 'basis': out.get('cost_basis', ''),
                          'secs': secs, 'rc': out.get('rc')})

    def quota(logs):
        ok_q, _, rep = quota_scan(logs or [])
        if not ok_q:
            res.quota = True
            res.message = ('AI 服务报了余额不足或额度用完一类的错（例如「' + rep['hits'][0]['text'][:80] + '」）。'
                           '先暂停：请到 AI 服务的后台看一下余额，不够就充值，充好以后再演练一次（这次没有重试）')
        return ok_q

    def part(name, ok, line):
        res.parts.append((name, bool(ok), line))
        say(f'{"过" if ok else "没过"}：{name}：{line}')
        return ok

    # ---- 1a. 打开对话窗口不出首次启动的那几屏（不发消息） ----
    t0 = time.time()
    ok_s, line_s, det = a.check_screens(wait=wait)
    book('演练：打开一次对话窗口、不发消息（check_screens）', {'cost': det.get('cost', 0.0), 'cost_basis': det.get('cost_basis', ''),
                                                     'rc': 0}, round(time.time() - t0))
    if not part('交互：打开对话窗口直接是输入框', ok_s is True, line_s):
        return _end(res)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-', dir='/tmp'))
    try:
        R, W = tmp / 'p', tmp / 'p' / 'drill'
        C._mini_project(R, W, skills={SKILL: layout.catalog(str(TOOLKIT))[SKILL]})

        def ctx(t, interactive=False):
            st = tmp / f'state-{t.name}'
            st.mkdir(mode=0o700)
            a.template(st, W)
            return st, placement.Ctx(root=R, kind='readonly', worktree=W.name, feature='drill', task_dir=t / 'task',
                                     out_dir=t / 'out', chdir=W, interactive=interactive)

        # ---- 1b. 对话窗口：开场内容是点名了技能的任务包 ----
        t = _task(tmp, 1, _pack(CHAT_GOAL, SKILL), SKILL)
        st, c = ctx(t, interactive=True)
        t0 = time.time()

        def answered(_screen):
            sid = C._newest_session(st, t0)
            return bool(sid and C._last_answer(st, sid))
        term = os.environ.get('TERM') if os.environ.get('TERM') not in (None, '', 'dumb') else 'xterm-256color'
        with ptyscreen.Pty(lambda: a.start_interactive(c, t / 'task', st), env={**os.environ, 'TERM': term}) as p:
            ready = p.wait_for(ptyscreen.is_ready, wait)
            got = p.wait_for(answered, 300) if ready else False
            p.pump(2)
            screens = ptyscreen.first_run_screens(p.text)
            p.type_line('/exit')
            p.close(wait=30)
        out = (p.result or {}).get('value') or {}
        book('演练：对话窗口，开场内容是点名了技能的任务包（start_interactive）', out, round(time.time() - t0))
        if not quota(out.get('logs')):
            return _end(res)
        ok = ready and got and not screens and out.get('rc') == 0 and out.get('skill_loaded') is True
        line = (f'输入框 {"出来了" if ready else "没出来"}，首次启动的几屏 {"、".join(screens) or "没有"}，退出码 {out.get("rc")}，'
                f'技能 {SKILL} {"加载了" if out.get("skill_loaded") else "没加载"}，它回答「{(out.get("text") or "")[:60]}」')
        if p.result and 'error' in p.result:
            line += '；出错：' + p.result['error'][-300:]
        if not part('交互：开场内容是任务包、点名的技能加载了', ok, line):
            return _end(res)

        # ---- 2. 自动调用、技能触发、结果文件 ----
        t = _task(tmp, 2, _pack(HEADLESS_GOAL, SKILL), SKILL)
        st, c = ctx(t)
        head = _git(W, 'rev-parse', 'HEAD')
        t0 = time.time()
        o = a.run_headless(c, t / 'task', st, timeout=600)
        book('演练：自动调用，点名技能、写结果文件（run_headless）', o.__dict__, round(time.time() - t0))
        if not quota(o.logs):
            return _end(res)
        ok_r, line_r, _ = check_result(str(t / 'out' / 'result.json'), str(R / '.git'), head, _git(W, 'rev-parse', 'HEAD'), 'review')
        changed = _git(W, 'status', '--porcelain', '--ignored')
        ok = o.rc == 0 and o.skill_loaded is True and ok_r and not changed and _git(W, 'rev-parse', 'HEAD') == head
        line = (f'退出码 {o.rc}，技能 {SKILL} {"加载了" if o.skill_loaded else "没加载"}，{line_r}，'
                f'工作目录{"被改了：" + changed[:200] if changed else "没被改"}')
        if not part('自动调用：点名的技能加载了、结果文件过检查', ok, line):
            return _end(res)

        # ---- 3. 反着试：点名一个工作目录里没有副本的技能（适配器不调用，不花钱） ----
        t = _task(tmp, 3, _pack('这一步不该被执行。', MISSING), MISSING)
        st, c = ctx(t)
        o = a.run_headless(c, t / 'task', st, timeout=60)
        logs = list((st / 'projects').rglob('*.jsonl')) if (st / 'projects').is_dir() else []
        ok = o.rc != 0 and o.cost_basis == '没有调用' and not logs and o.skill_loaded is False
        if not part('反着试：没有副本的技能不调用', ok, o.text[:200]):
            return _end(res)
    finally:
        subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    res.ok = True
    res.message = f'Claude Code {res.version} 的真实 AI 演练通过：交互、自动调用、技能触发、结果文件都对'
    if record:
        mark_drilled(C.NAME, res.version)
        res.message += '；已记下演练过的版本'
    return res


def _end(res):
    if not res.message:
        bad = next((p for p in res.parts if not p[1]), None)
        res.message = f'演练没通过：{bad[0]}（{bad[2]}）' if bad else '演练没做完'
    return res


def _git(W, *a):
    return subprocess.run(['git', '-C', str(W), *a], capture_output=True, text=True,
                          env={'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_OPTIONAL_LOCKS': '0',
                               'PATH': '/usr/bin:/bin'}).stdout.strip()


def main():
    r = run()
    for c in r.calls:
        print(f'  花了 {c["cost"]:.4f} 美元（{c["basis"]}）：{c["what"]}')
    print(r.message)
    print(f'合计 {sum(c["cost"] for c in r.calls):.4f} 美元（工具报告的金额）')
    return 0 if r.ok else (2 if r.quota else 1)


if __name__ == '__main__':
    sys.exit(main())
