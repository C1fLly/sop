#!/usr/bin/env python3
"""3-29 的真实调用（花 AI 的钱，不在全部自测里，手动跑）：真实 AI 演练（16.2），再让流程引擎按配置用 Claude Code 适配器真跑两步。

- 一切都在 /tmp 下新建的临时目录里：流程沙箱的「世界」（本机假远程加假 gh、假门禁、临时 SOP_HOME），用完整个删掉；
  tests 包一导入就换成假主目录（3-59 的保险），所以开头先记下终端里 ANTHROPIC_ 开头的变量和 claude 的位置；
  Claude Code 只在受限环境里跑（主目录是空的、状态目录从模板现建）；密钥只作为环境变量给进去，不写进任何文件。
- 一、演练（adapters/ai/claude/drill.py）：交互（打开对话窗口不出首次启动的几屏；开场内容是点名了技能的任务包）、
  自动调用（点名技能、写结果文件）、反着试（没有副本的技能不调用）；都过了记下演练过的版本（记在这个世界的 SOP_HOME 里）。
- 二、流程引擎：项目主线上装好技能（和 sop project new 的 I4 一样）；一张带风险标记的工单。
  1. 假 AI（SOP_AI=fake）走到 F8（验收包）开始就掐断；
  2. 换成按配置选的 Claude Code（不设 SOP_AI，主线 sop.json 也没写，走默认），SOP_MAX_STEPS_PER_RUN=1：只真跑 F8，
     要求通过出口检查 cards_cover、提交到功能分支，屏幕上没有「还没演练」的提醒（一里刚记下）；
  3. 假 AI 接着走到 T9（工单复查）开始就掐断；
  4. 再换成 Claude Code 只真跑 T9（点名技能 code-review、只读、结果文件）。
- 每次真调用一结束就记账：docs/第三段/记账.json（只记增量）；碰到余额不足、额度类的错就停下，不重试。
用法：uv run python tests/real_ai/claude_engine.py
     加 --fake：先用假的 claude 把脚本自己走一遍（不花钱、记账写在临时目录；假的 claude 不会写验收卡，F8 应当没通过）。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
FAKE = '--fake' in sys.argv
KEYS = {k: v for k, v in os.environ.items() if k.startswith('ANTHROPIC_')}          # tests 包一导入就去掉了，先记下
REAL_CLAUDE = os.path.realpath(shutil.which('claude') or os.path.expanduser('~/.local/bin/claude'))
TERM = os.environ.get('TERM') if os.environ.get('TERM') not in (None, '', 'dumb') else 'xterm-256color'

from tests.sandbox import plans                      # noqa: E402  （导入 tests 包：换成假主目录）
from tests.sandbox.world import World                # noqa: E402

LEDGER = REPO / 'docs' / '第三段' / '记账.json'
F = 'jz-1'
FS, T1 = f'feature/{F}', f'ticket/{F}/01'


def book(what, ver, cost, basis, secs, rc):
    led = json.loads(LEDGER.read_text()) if LEDGER.exists() else {'entries': []}
    led['entries'].append({'what': what, 'tool': f'claude {ver}', 'cost': cost, 'basis': basis, 'secs': secs, 'rc': rc,
                           'date': time.strftime('%Y-%m-%d')})
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n')
    print(f'  记账：{cost:.4f} 美元（{basis}）；第三段合计 {sum(e["cost"] for e in led["entries"]):.4f} 美元', flush=True)


class RealWorld(World):
    extra = {}

    def env(self):
        e = {**super().env(), **{k: v for k, v in self.extra.items() if k != 'PATH_FIRST'}}
        if self.extra.get('PATH_FIRST'):
            e['PATH'] = f'{self.extra["PATH_FIRST"]}:{e["PATH"]}'
        for k, v in list(e.items()):
            if v is None:
                del e[k]
        return e


def step_events(w, scope, sid):
    return [e for e in w.events(f'feature/{F}') if e.get('scope') == scope and e.get('step') == sid]


def started(scope, sid, attempt=None):
    return lambda w: any(e['type'] == 'start' and (attempt is None or e.get('attempt') == attempt) for e in step_events(w, scope, sid))


def main():
    global LEDGER
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-3-29-', dir='/tmp'))
    if FAKE:
        LEDGER = tmp / '记账-假的.json'
    try:
        bindir = tmp / 'claude-bin'
        bindir.mkdir()
        if FAKE:
            shutil.copy(REPO / 'tests' / 'fakes' / 'claude' / 'claude', bindir / 'claude')
            (bindir / 'claude').chmod(0o755)
            keys = {'ANTHROPIC_BASE_URL': 'fake://ok', 'ANTHROPIC_AUTH_TOKEN': 'fake-token-3-29-xxxxxxxx'}
        else:
            if not os.path.isfile(REAL_CLAUDE):
                print('没找到 claude'); return 1
            os.symlink(REAL_CLAUDE, bindir / 'claude')
            keys = KEYS
        w = RealWorld(tmp / 'w')
        # 项目主线装上技能（sop project new 的 I4 做的那样），之后的功能分支、工单目录里都有 .claude/skills/
        from kernel import projectnew
        work = tmp / 'skills-work'
        e = {**os.environ, **w.git_env()}
        subprocess.run(['git', 'clone', '-q', str(w.remote), str(work)], env=e, check=True)
        installed = projectnew.install_skills(work, toolkit=REPO)
        subprocess.run(['git', '-C', str(work), 'add', '-A'], env=e, check=True)
        subprocess.run(['git', '-C', str(work), 'commit', '-qm', 'chore: 装技能（I4）'], env=e, check=True)
        subprocess.run(['git', '-C', str(work), 'push', '-q', 'origin', 'HEAD:main'], env=e, check=True)
        print(f'主线装了 {len(installed)} 个技能', flush=True)

        # ---------- 一、演练 ----------
        os.environ.update({'SOP_HOME': str(w.home), 'SOP_RUNTIME_DIR': str(w.tmp / 'run'), 'TERM': TERM})
        from adapters.ai.claude import adapter as C
        from adapters.ai.claude import drill
        a = C.ClaudeAdapter(exe=bindir / 'claude', environ=keys)
        ver = a.version()
        print(f'Claude Code {ver}（{REAL_CLAUDE if not FAKE else "假的"}）；演练前的提醒：{a.reminder()!r}', flush=True)
        t0 = time.time()
        r = drill.run(adapter=a, say=lambda s: print('  ' + s, flush=True), wait=120)
        for c in r.calls:
            book('3-29 ' + c['what'], ver, c['cost'], c['basis'], c['secs'], c['rc'])
        print(f'演练：{r.message}（{round(time.time() - t0)} 秒）；演练后的提醒：{a.reminder()!r}', flush=True)
        if r.quota:
            print('服务报了余额不足或额度类的错：停下，不重试。'); return 2
        if not r.ok:
            return 1

        # ---------- 二、流程引擎 ----------
        w.extra = {'SOP_AI': 'fake'}
        r0 = w.sop('feature', 'new', 'jz')
        assert r0.returncode == 0, r0.stdout + r0.stderr
        ai, human = plans.happy(F, [('01', [], '数据：改了账目的算法')])
        w.script.update(ai); w.human.update(human)
        w.script[f'{FS}:F8:1'] = {'sleep': 600}
        w.script[f'{T1}:T9:1'] = {'sleep': 600}
        w.save_scripts()
        real_env = {'SOP_AI': None, 'SOP_MAX_STEPS_PER_RUN': '1', 'PATH_FIRST': str(bindir), 'TERM': TERM, **keys}

        def real_step(scope, sid, label):
            hit, out = w.sop_until(started(scope, sid, 1))
            assert hit, out[-3000:]
            print(f'假 AI 走到 {sid} 开始，掐断', flush=True)
            w.extra = real_env
            t0 = time.time()
            res = w.sop(timeout=1800)
            secs = round(time.time() - t0)
            w.extra = {'SOP_AI': 'fake'}
            print(f'--- 换成 Claude Code 跑 {sid}：退出码 {res.returncode}，{secs} 秒；屏幕：\n{res.stdout[-2500:]}\n{res.stderr[-1500:]}', flush=True)
            evs = step_events(w, scope, sid)
            end = [x for x in evs if x['type'] in ('done', 'failed')]
            if not end:
                print(f'{sid} 没有结束事件', evs[-3:]); return None, res
            ev = end[-1]
            book(f'3-29 流程引擎按配置用 Claude Code 真跑 {sid}（{label}）', ver, float(ev.get('cost') or 0.0), '工具报告（流程引擎记进事件）',
                 secs, 0 if ev['type'] == 'done' else 1)
            return ev, res

        ev8, res8 = real_step(FS, 'F8', '验收包，出口检查 cards_cover')
        if ev8 is None:
            return 1
        print(f'F8：{ev8["type"]}，{ev8.get("reason", "")[:300]}', flush=True)
        if '提醒：' in res8.stdout:
            print('不对：演练刚做过，屏幕上还有提醒')
        q = [x for x in step_events(w, FS, 'F8') if x['type'] == 'note' and '额度' in json.dumps(x, ensure_ascii=False)]
        if q:
            print('碰到额度类的报错：停下，不重试。', q); return 2
        if ev8['type'] == 'done':
            files = w.rgit('ls-tree', '-r', '--name-only', f'feat/{F}', f'.scratch/{F}/cards/', f'.scratch/{F}/summary.md')
            print(f'功能分支上的验收卡和摘要：{files.split()}；提交 {ev8.get("commit")}', flush=True)
            print('验收卡 01：\n' + w.rgit('show', f'feat/{F}:.scratch/{F}/cards/01.md', check=False)[:1500], flush=True)
        elif not FAKE:
            return 1

        if ev8['type'] != 'done':      # 只在 --fake 时到这里：让假 AI 把 F8 补上，好接着走到 T9
            w.script[f'{FS}:F8'] = ai[f'{FS}:F8']
            w.save_scripts()
        ev9, res9 = real_step(T1, 'T9', '工单复查，点名技能 code-review')
        if ev9 is None:
            return 1
        print(f'T9：{ev9["type"]}，{ev9.get("reason", "")[:300]}；发现 {ev9.get("findings")} 条', flush=True)
        st = sorted((w.home / 'state' / w.name / 'ai-state' / 'claude').glob('ticket_*T9*')) if (w.home / 'state').is_dir() else []
        st = [d for d in st if d.is_dir()]
        for d in st:
            sids = [f.stem for f in d.rglob('*.jsonl')]
            print(f'  状态目录 {d.name}：会话 {sids}，加载过的技能 {[C.skill_loads(d, s) for s in sids]}', flush=True)
        res_json = sorted((w.home / 'state' / w.name / 'runs').rglob('T9-*/out/result.json'))
        for f in res_json:
            print(f'  {f.parent.parent.name} 的结果文件：{f.read_text()[:1500]}', flush=True)
        good = ev8['type'] == 'done' and ev9['type'] == 'done'
        print('结论：', '都对' if good else '有不对的', flush=True)
        return 0 if good else 1
    finally:
        subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
        subprocess.run(['rm', '-rf', str(tmp)])


if __name__ == '__main__':
    sys.exit(main())
