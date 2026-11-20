#!/usr/bin/env python3
"""3-27 的真实调用（花 AI 的钱，不在全部自测里，手动跑）：Claude Code 适配器的 probe 和 run_headless。

- 一切都在 /tmp 下新建的临时目录里：SOP_HOME 指过去（机器级登记 config/tools.json 写在那里，不碰真的 ~/tools/sop/config），
  假项目用 runner/selftest.make_fixture 造（结构和 wt 的一样），用完整个删掉；
- 服务地址和密钥：临时 SOP_HOME 里没有 config/ai/claude.env，所以用终端里 ANTHROPIC_ 开头的环境变量（这台电脑就是这么配的），
  只作为环境变量给进受限环境，不写文件、不打印；
- 普通调用（适配器不加自定义系统提示词、不指定模型、不加钩子），每次花费上限 0.5 美元；
- 调用 1：probe，真发一次最短的调用；碰到余额不足、额度类的错就停下，不重试，不做调用 2；
- 调用 2：run_headless，在受限环境（readonly 放法）里执行一个最小的任务包：读 README.md、把第一行写进结果文件的一条发现；
  结果文件过 checks/result_file 的检查，内容和 README 对得上；
- 每次调用一结束就记账：docs/第三段/记账.json（接着第二段结束时的 21.29 美元，只记增量）。
用法：uv run python tests/real_ai/claude_adapter.py [--probe-only]"""
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
CARRIED = 21.29
TASK = '''# 任务包：T9（自检用，第 1 次）

这是一次测试。只读，不改任何文件、不提交。

## 目标
读当前目录下的 README.md，把它的第一行原样写进结果文件的一条发现里。

## 技能
无。

## 必读
- README.md

## 可改范围
- （只读，不改任何文件）

## 禁止
- 不改任何文件，不提交，不推送

## 完成标准
- 结果文件已写好

## 交回
结束时写一份 JSON 结果文件到 /sop/out/result.json，内容就是：
{"status": "done", "commits": [], "commands": [], "deviations": [], "questions": [], "findings": [{"text": "README 第一行：<第一行原文>", "blocking": false}]}

## 不确定时
不猜。把问题写进结果文件的 questions，category 写「业务」或「技术」，然后正常结束。
'''


def book(what, ver, cost, basis, secs, rc):
    led = json.loads(LEDGER.read_text()) if LEDGER.exists() else {'carried_from_phase2': CARRIED, 'entries': []}
    led['entries'].append({'what': what, 'tool': f'claude {ver}', 'cost': cost, 'basis': basis, 'secs': secs, 'rc': rc,
                           'date': time.strftime('%Y-%m-%d')})
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n')
    total = sum(e['cost'] for e in led['entries'])
    print(f'  记账：{cost:.4f} 美元（{basis}）；第三段合计 {total:.4f} 美元', flush=True)


def main(probe_only=False):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-3-27-', dir='/tmp'))
    os.environ['SOP_HOME'] = str(tmp / 'sop-home')
    os.environ['SOP_RUNTIME_DIR'] = str(tmp / 'run')
    from adapters.ai.claude.adapter import ClaudeAdapter
    from checks.quota_scan.check import run as quota_scan
    from checks.result_file.check import run as check_result
    from machine import config
    from runner import aistate, placement
    from runner.selftest import make_fixture
    try:
        a = ClaudeAdapter()
        ver = a.version()
        print(f'Claude Code {ver}，在 {a.location()[0]}', flush=True)
        _, src = a.credentials()
        print(f'服务地址和密钥从哪来：{src or "没有"}', flush=True)

        # ---- 调用 1：probe ----
        t0 = time.time()
        r = a.probe(timeout=300, budget=0.5)
        secs = round(time.time() - t0)
        called = 'rc' in r.details
        print(f'调用 1（probe）：{"能用" if r.ok else "不能用"}，{secs} 秒。{r.message}', flush=True)
        if called:
            book('3-27 probe：最短的一次调用', ver, r.cost, r.details.get('cost_basis', '工具报告'), secs, r.details['rc'])
        print('  提醒：', r.remind or '（无）')
        print('  登记：', json.dumps({k: v for k, v in config.tools().get('claude', {}).items()
                                      if k in ('version', 'probed_version', 'probe_ok', 'drilled_version')}, ensure_ascii=False))
        if r.quota:
            print('服务报了余额不足或额度类的错：停下，不重试，不做调用 2。')
            return 2
        if not r.ok or probe_only:
            return 0 if r.ok else 1

        # ---- 调用 2：run_headless ----
        R, _ = make_fixture(tmp)
        W = R / 'ticket-a-1-01'
        first = (W / 'README.md').read_text().splitlines()[0]
        d = tmp / 'run-T9'
        (d / 'task').mkdir(parents=True)
        (d / 'out').mkdir()
        (d / 'task' / 'task.md').write_text(TASK, encoding='utf-8')
        (d / 'task' / 'task.json').write_text(json.dumps({'scope': 'a-1/01', 'step': 'T9', 'attempt': 1,
                                                          'result_path': '/sop/out/result.json', 'kind': 'review'}))
        st = aistate.fresh('demo', a.name, 'a-1_01-T9', lambda x: a.template(x, W))
        ro, env, pass_env = a.sandbox_extras()
        ctx = placement.Ctx(root=R, kind='readonly', worktree=W.name, feature='a-1', task_dir=d / 'task', out_dir=d / 'out',
                            ro=ro, env=env, pass_env=pass_env, chdir=W)
        t0 = time.time()
        out = a.run_headless(ctx, d / 'task', st, timeout=300, budget=0.5)
        secs = round(time.time() - t0)
        aistate.seal(st)
        print(f'调用 2（run_headless）：退出码 {out.rc}{"，超时" if out.timeout else ""}，{secs} 秒，'
              f'花费 {out.cost:.4f} 美元（{out.cost_basis}），会话 {out.session}', flush=True)
        book('3-27 run_headless：最小任务包（读 README、写结果文件）', ver, out.cost, out.cost_basis, secs, out.rc)
        print('  它说：', out.text[:300])
        print('  会话日志：', [str(pathlib.Path(x).relative_to(st)) for x in out.logs])
        ok_q, line_q, _ = quota_scan(out.logs)
        print('  额度类报错：', line_q)
        rp = d / 'out' / 'result.json'
        ok_r, line_r, _ = check_result(str(rp), str(R / '.git' / 'worktrees' / W.name), None, None, 'review')
        print('  结果文件检查：', '通过' if ok_r else '不通过', '——', line_r)
        res = json.loads(rp.read_text()) if rp.exists() else {}
        hit = any(first in f.get('text', '') for f in res.get('findings', []))
        print(f'  结果文件里有 README 的第一行（{first!r}）：{hit}')
        status = subprocess.run(['git', '-C', str(W), 'status', '--porcelain', '--ignored'], capture_output=True, text=True).stdout
        print('  工作目录有没有被改：', '没有' if not status.strip() else repr(status))
        if not ok_q:
            print('服务报了余额不足或额度类的错：停下，不重试。')
            return 2
        return 0 if (out.rc == 0 and ok_r and hit and not status.strip()) else 1
    finally:
        subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
        subprocess.run(['rm', '-rf', str(tmp)])


if __name__ == '__main__':
    sys.exit(main('--probe-only' in sys.argv))
