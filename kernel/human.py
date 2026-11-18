"""人的那几步（原型确认、确认规划、选实现方式、行为验收、私有仓库网页上点合并、业务问题）。

真用时：sop 走到人的步骤就停下，打印「现在需要你做什么、做完执行什么命令」（8.4）；小白执行 sop answer，在终端里一项一项回答。
流程沙箱里：照剧本回答（SOP_HUMAN_SCRIPT）。剧本：{"<范围>:<步骤>": [回答, ...], "*:<步骤>": [...]}，按顺序一条一条用；
回答里可以写 "wait_for": ["<范围>:<步骤>", ...]，表示要等那几条先答完才轮到它（让几张工单的先后确定下来）。
用到第几条记在 ~/tools/sop/state/<项目名>/human-used.json。
"""
import json
import os
import threading

from . import paths


class NoHuman:
    """不在终端前：走到人的步骤就停。"""
    interactive = False

    def can(self, scope, step):
        return False

    def ask(self, scope, step, question, info=None):
        raise RuntimeError('没有人回答')


class TtyHuman(NoHuman):
    interactive = True

    def can(self, scope, step):
        return True

    def ask(self, scope, step, question, info=None):
        print('\n' + question)
        for line in (info or {}).get('show', []):
            print('  ' + line)
        choices = (info or {}).get('choices')
        while True:
            a = input('你的回答' + (f'（{"/".join(choices)}）' if choices else '') + '：').strip()
            if not choices or a in choices:
                break
        ans = {'answer': a}
        if a in ('不通过', '不满意', '不对'):
            ans['note'] = input('请写一句现象（我做了什么、期望什么、实际什么）：').strip()
        return ans


class ScriptedHuman(NoHuman):
    def __init__(self, project, path):
        self.project, self.path = project, path
        self.lock = threading.Lock()

    def _load(self):
        script = json.load(open(self.path, encoding='utf-8')) if os.path.exists(self.path) else {}
        f = paths.state_dir(self.project) / 'human-used.json'
        used = json.load(open(f)) if f.exists() else {}
        return script, used, f

    def _next(self, scope, step):
        script, used, f = self._load()
        for key in (f'{scope}:{step}', f'*:{step}'):
            if key in script:
                i = used.get(key, 0)
                if i < len(script[key]):
                    a = script[key][i]
                    waits = a.get('wait_for', [])
                    if all(used.get(w, 0) > 0 for w in waits):
                        return key, a, used, f
                    return None
        return None

    def can(self, scope, step):
        with self.lock:
            return self._next(scope, step) is not None

    def ask(self, scope, step, question, info=None):
        with self.lock:
            nxt = self._next(scope, step)
            if nxt is None:
                raise RuntimeError(f'剧本里没有 {scope}:{step} 的回答')
            key, a, used, f = nxt
            used[key] = used.get(key, 0) + 1
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(used, ensure_ascii=False))
            used[f'{scope}:{step}'] = used.get(f'{scope}:{step}', 0) + (0 if key == f'{scope}:{step}' else 1)
            f.write_text(json.dumps(used, ensure_ascii=False))
            return {k: v for k, v in a.items() if k != 'wait_for'}
