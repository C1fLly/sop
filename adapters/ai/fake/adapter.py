"""「假 AI」适配器（设计书 16.2 的流程沙箱用）。在真的受限环境里运行 fakeai.py，按剧本产出文件。

剧本：环境变量 SOP_FAKE_SCRIPT 指向一个 JSON 文件，{"<范围>:<步骤>:<第几次>": 动作, "<范围>:<步骤>": 动作, ...}，
先找带次数的，没有再找不带次数的；都没有就用默认动作（什么都不改，正常交回）。动作的写法见 fakeai.py。
对话方式（start_interactive）在沙箱里不开终端，照剧本做完就结束（模拟小白和 AI 聊完）。"""
import json
import os
import pathlib
import shutil

from adapters.ai.base import Adapter, Outcome, ProbeResult
from runner import placement, sandbox

HERE = pathlib.Path(__file__).resolve().parent


class FakeAdapter(Adapter):
    name = 'fake'
    caps = {'interactive': True, 'headless': True, 'resume': True, 'subagents': True, 'budget_flag': False}
    state_home = '.fakeai'

    def template(self, state_dir, workdir):
        (state_dir / 'settings.json').write_text(json.dumps({'trusted': [str(workdir)]}))

    def probe(self):
        return ProbeResult(True, '假 AI：总是能用', version='fake')

    def _action(self, key_scope, step, attempt):
        f = os.environ.get('SOP_FAKE_SCRIPT')
        script = json.load(open(f, encoding='utf-8')) if f and os.path.exists(f) else {}
        for k in (f'{key_scope}:{step}:{attempt}', f'{key_scope}:{step}', f'*:{step}:{attempt}', f'*:{step}'):
            if k in script:
                return script[k]
        return {}

    def _run(self, ctx, taskpack, state_dir, extra=None, timeout=None):
        task = json.load(open(pathlib.Path(taskpack) / 'task.json', encoding='utf-8'))
        action = self._action(task['scope'], task['step'], task['attempt'])
        if extra:
            action = {**action, **extra}
        (pathlib.Path(taskpack) / 'fake-action.json').write_text(json.dumps(action, ensure_ascii=False))
        ctx.ro = list(ctx.ro) + [str(HERE / 'fakeai.py')]
        ctx.home_binds = {**ctx.home_binds, self.state_home: state_dir}
        p = sandbox.run(ctx, ['python3', str(HERE / 'fakeai.py'), f'{placement.TASK_MNT}/task.json',
                              f'{placement.TASK_MNT}/fake-action.json'], timeout=timeout)
        info = {}
        for line in p.stdout.splitlines():
            if line.startswith('FAKEAI '):
                info = json.loads(line[7:])
        logs = [str(x) for x in pathlib.Path(state_dir).glob('*.jsonl')]
        return Outcome(rc=p.returncode, cost=float(info.get('cost', 0)), session=info.get('session'), logs=logs,
                       text=info.get('text', '') or p.stderr[-500:])

    def run_headless(self, ctx, taskpack, state_dir, timeout=None):
        return self._run(ctx, taskpack, state_dir, timeout=timeout)

    def resume(self, ctx, taskpack, state_dir, session, text, timeout=None):
        return self._run(ctx, taskpack, state_dir, extra={'resumed': session}, timeout=timeout)

    def start_interactive(self, ctx, taskpack, state_dir):
        return self._run(ctx, taskpack, state_dir)
