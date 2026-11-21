#!/usr/bin/env python3
"""3-28 的真实调用（花 AI 的钱，不在全部自测里，手动跑）：Claude Code 适配器的对话方式和续接。

- 一切都在 /tmp 下新建的临时目录里：SOP_HOME 指过去（状态目录 state/<项目>/ai-state/ 在那里），假项目用
  runner/selftest.make_fixture 造，用完整个删掉；Claude Code 只在受限环境里跑（主目录是空的、状态目录从模板现建，
  看不到本机真的 ~/.claude、~/.claude.json）；
- 服务地址和密钥：临时 SOP_HOME 里没有 config/ai/claude.env，用终端里 ANTHROPIC_ 开头的环境变量，只作为环境变量给进去；
- 普通调用（不加自定义系统提示词、不指定模型、不加钩子）；对话窗口由这个脚本在模拟终端里替小白打字；
- 调用 A：check_screens，打开一次对话窗口、不发消息，看首次启动的那几屏出没出；
- 调用 B：start_interactive，开场内容是任务包（让它记住一个暗号）；看屏幕上有没有首次启动的那几屏，等它回答后 /exit；
- 调用 C：resume（对话方式），问暗号是什么，看它记不记得；
- 调用 D：resume（自动调用，-p），再问一遍，看记不记得、花费是不是只记了增量；
- 每次调用一结束就记账：docs/第三段/记账.json（只记增量）；碰到余额不足、额度类的错就停下，不重试。
用法：uv run python tests/real_ai/claude_interactive.py
     加 --fake：先用假的 claude（tests/fakes/claude/claude）把脚本自己走一遍，不花钱、记账写在临时目录里。"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

LEDGER = REPO / 'docs' / '第三段' / '记账.json'
CODE = '青石七三'
TASK = f'''# 任务包：F2（3-28 自检用，第 1 次）

这是一次测试。不读、不改任何文件，不执行任何命令。

请记住暗号「{CODE}」。这次只回答三个字：记好了
'''


def book(what, ver, cost, basis, secs, rc):
    led = json.loads(LEDGER.read_text()) if LEDGER.exists() else {'entries': []}
    led['entries'].append({'what': what, 'tool': f'claude {ver}', 'cost': cost, 'basis': basis, 'secs': secs, 'rc': rc,
                           'date': time.strftime('%Y-%m-%d')})
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n')
    total = sum(e['cost'] for e in led['entries'])
    print(f'  记账：{cost:.4f} 美元（{basis}）；第三段合计 {total:.4f} 美元', flush=True)


def main(fake=False):
    global LEDGER
    os.environ['TERM'] = 'xterm-256color'
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-3-28-', dir='/tmp'))
    if fake:
        LEDGER = tmp / '记账-假的.json'
    os.environ['SOP_HOME'] = str(tmp / 'sop-home')
    os.environ['SOP_RUNTIME_DIR'] = str(tmp / 'run')
    from adapters.ai import ptyscreen
    from adapters.ai.claude import adapter as C
    from checks.quota_scan.check import run as quota_scan
    from runner import aistate, placement, sandbox
    from runner.selftest import make_fixture
    if not sandbox.tiocsti_disabled():
        print('内核没禁用往终端塞按键，对话步骤不启动')
        return 1
    try:
        if fake:
            exe = tmp / 'bin' / 'claude'
            exe.parent.mkdir()
            exe.write_bytes((REPO / 'tests' / 'fakes' / 'claude' / 'claude').read_bytes())
            exe.chmod(0o755)
            a = C.ClaudeAdapter(exe=exe, environ={'ANTHROPIC_BASE_URL': 'fake://ok', 'ANTHROPIC_AUTH_TOKEN': 'fake-token-3-28-xxxxxxxx'})
        else:
            a = C.ClaudeAdapter()
        ver = a.version()
        print(f'Claude Code {ver}，在 {a.location()[0]}；密钥从：{a.credentials()[1] or "没有"}', flush=True)

        # ---- 调用 A：打开一次对话窗口，不发消息 ----
        t0 = time.time()
        ok, line, det = a.check_screens(wait=90)
        secs = round(time.time() - t0)
        print(f'调用 A（check_screens）：{ok}，{secs} 秒。{line}', flush=True)
        print('  屏幕最后几行：\n    ' + '\n    '.join(det.get('tail', '').splitlines()[-12:]))
        book('3-28 check_screens：打开一次对话窗口、不发消息', ver, det.get('cost', 0.0), '状态目录里工具记的数', secs, 0)
        if ok is not True:
            return 1

        R, _ = make_fixture(tmp)
        W = R / 'ticket-a-1-01'
        st = aistate.fresh('demo', a.name, 'a-1_01-F2', lambda x: a.template(x, W))

        def mkctx(n, body):
            d = tmp / f'run-{n}'
            (d / 'task').mkdir(parents=True)
            (d / 'out').mkdir()
            (d / 'task' / 'task.md').write_text(body, encoding='utf-8')
            (d / 'task' / 'task.json').write_text(json.dumps({'scope': 'a-1/01', 'step': 'F2', 'attempt': n, 'budget_usd': 0.5}))
            ro, env, pass_env = a.sandbox_extras()
            return d, placement.Ctx(root=R, kind='readonly', worktree=W.name, feature='a-1', task_dir=d / 'task',
                                    out_dir=d / 'out', ro=ro, env=env, pass_env=pass_env, chdir=W, interactive=True)

        def answered_since(t_start, want=None):
            def cond(_screen):
                sid = C._newest_session(st, t_start)
                ans = C._last_answer(st, sid) if sid else ''
                return bool(ans) and (want is None or want in ans or len(ans) > 200)
            return cond

        def window(label, fn, t_start, want=None):
            with ptyscreen.Pty(fn) as t:
                ready = t.wait_for(ptyscreen.is_ready, 90)
                got = t.wait_for(answered_since(t_start, want), 180) if ready else False
                t.pump(2)
                screens = ptyscreen.first_run_screens(t.text)
                t.type_line('/exit')
                t.close(wait=30)
            res = (t.result or {}).get('value') or {}
            print(f'{label}：输入框出来了 {ready}；等到回答 {got}；首次启动的几屏：{screens or "没有"}；'
                  f'退出码 {res.get("rc")}；会话 {res.get("session")}', flush=True)
            if t.result and 'error' in t.result:
                print('  出错：', t.result['error'][-800:])
            print('  屏幕上出现过的文字（最后 25 行）：\n    ' + '\n    '.join(t.text.splitlines()[-25:]))
            return res, t.text, screens

        # ---- 调用 B：start_interactive ----
        d, ctx = mkctx(1, TASK)
        t0 = time.time()
        out, screen, screens = window('调用 B（start_interactive）', lambda: a.start_interactive(ctx, d / 'task', st), t0, '记')
        secs = round(time.time() - t0)
        print(f'  它回答：{out.get("text", "")[:200]!r}；花费 {out.get("cost", 0):.4f}（{out.get("cost_basis")}）', flush=True)
        book('3-28 start_interactive：对话窗口，开场内容是任务包（记住暗号）', ver, out.get('cost', 0.0),
             out.get('cost_basis', ''), secs, out.get('rc'))
        proj = C._project_entry(st, str(W))
        print(f'  状态目录里工具记的：lastSessionId {proj.get("lastSessionId")}，lastCost {proj.get("lastCost")}；'
              f'会话日志里的 cost-state {C._cost_state(st, out.get("session"))}')
        ok_q, line_q, _ = quota_scan(out.get('logs') or [])
        print('  额度类报错：', line_q)
        if not ok_q:
            print('服务报了余额不足或额度类的错：停下，不重试。')
            return 2
        sid = out.get('session')
        if out.get('rc') != 0 or not sid or screens:
            return 1

        # ---- 调用 C：resume（对话方式） ----
        d, ctx = mkctx(2, '# 任务包：F2（3-28 自检用，第 2 次）\n\n这是一次测试。不读、不改任何文件，不执行任何命令。\n')
        t0 = time.time()
        out2, screen2, screens2 = window('调用 C（resume，对话方式）',
                                         lambda: a.resume(ctx, d / 'task', st, sid, '我刚才让你记住的暗号是什么？只回答暗号本身。'),
                                         t0, CODE)
        secs = round(time.time() - t0)
        print(f'  它回答：{out2.get("text", "")[:200]!r}；记得前文：{CODE in (out2.get("text") or "")}；'
              f'屏幕上有暗号：{CODE in screen2.split("只回答暗号本身")[-1]}', flush=True)
        print(f'  花费增量 {out2.get("cost", 0):.4f}（{out2.get("cost_basis")}）；会话编号没变：{out2.get("session") == sid}')
        proj = C._project_entry(st, str(W))
        print(f'  状态目录里工具记的：lastSessionId {proj.get("lastSessionId")}，lastCost {proj.get("lastCost")}；'
              f'会话日志里的 cost-state {C._cost_state(st, out2.get("session"))}；适配器记的累计 {C._read_json(C._cost_book(st))}')
        book('3-28 resume（对话方式）：问暗号', ver, out2.get('cost', 0.0), out2.get('cost_basis', ''), secs, out2.get('rc'))
        ok_q, line_q, _ = quota_scan(out2.get('logs') or [])
        print('  额度类报错：', line_q)
        if not ok_q:
            print('服务报了余额不足或额度类的错：停下，不重试。')
            return 2

        # ---- 调用 D：resume（自动调用） ----
        d, ctx = mkctx(3, '# 任务包：F2（3-28 自检用，第 3 次）\n\n这是一次测试。不读、不改任何文件，不执行任何命令。\n')
        ctx.interactive = False
        t0 = time.time()
        out3 = a.resume(ctx, d / 'task', st, out2.get('session') or sid, '我让你记住的暗号是什么？再说一遍，只回答暗号本身。', timeout=300)
        secs = round(time.time() - t0)
        print(f'调用 D（resume，自动调用）：退出码 {out3.rc}，{secs} 秒，会话 {out3.session}；它回答：{out3.text[:200]!r}；'
              f'记得前文：{CODE in out3.text}', flush=True)
        print(f'  花费增量 {out3.cost:.4f}（{out3.cost_basis}）；适配器记的累计 {C._read_json(C._cost_book(st))}')
        book('3-28 resume（自动调用 -p）：再问暗号', ver, out3.cost, out3.cost_basis, secs, out3.rc)
        ok_q, line_q, _ = quota_scan(out3.logs)
        print('  额度类报错：', line_q)
        aistate.seal(st)
        status = subprocess.run(['git', '-C', str(W), 'status', '--porcelain', '--ignored'], capture_output=True, text=True).stdout
        print('  工作目录有没有被改：', '没有' if not status.strip() else repr(status))
        if not ok_q:
            return 2
        good = (out2.get('rc') == 0 and CODE in (out2.get('text') or '') and not screens2
                and out3.rc == 0 and CODE in out3.text)
        print('结论：', '都对' if good else '有不对的')
        return 0 if good else 1
    finally:
        subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
        subprocess.run(['rm', '-rf', str(tmp)])


if __name__ == '__main__':
    sys.exit(main('--fake' in sys.argv))
