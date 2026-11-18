"""读流程定义（设计书 8.1）。工具包自带的 TOML，只读。"""
import pathlib
import tomllib

ACTORS = ('script', 'restricted_script', 'ai_headless', 'ai_interactive', 'human')
KINDS = ('ticket_impl', 'planning', 'std_draft', 'readonly', 'restricted_script', 'implement_spec')
SPECIAL = ('STOP', 'END')
FIELDS = {'id', 'name', 'actor', 'kind', 'action', 'skill', 'session', 'condition', 'confirm', 'changes_confirmed', 'on_fail',
          'max_attempts', 'on_exhausted', 'max_fails', 'on_fails_exhausted', 'goto', 'side', 'hold', 'allowed', 'checks',
          'timeout_min', 'budget_usd', 'inputs', 'outputs'}


class FlowError(ValueError):
    pass


class Flow:
    def __init__(self, data, source=''):
        self.id = data['flow']['id']
        self.scope = data['flow']['scope']
        self.steps = {}
        self.order = []
        for s in data['step']:
            extra = set(s) - FIELDS
            if extra:
                raise FlowError(f'{source} 步骤 {s.get("id")} 有不认识的字段：{sorted(extra)}')
            if s['id'] in self.steps:
                raise FlowError(f'{source} 步骤编号重复：{s["id"]}')
            if s.get('actor') not in ACTORS:
                raise FlowError(f'{source} 步骤 {s["id"]} 的执行者不对：{s.get("actor")}')
            if s['actor'] in ('ai_headless', 'ai_interactive', 'restricted_script') and s.get('kind') not in KINDS:
                raise FlowError(f'{source} 步骤 {s["id"]} 要写受限环境的放法（kind）')
            self.steps[s['id']] = s
            if not s.get('side'):
                self.order.append(s['id'])
        for s in self.steps.values():
            for k in ('on_fail', 'on_exhausted', 'on_fails_exhausted', 'goto'):
                t = s.get(k)
                if t and t not in self.steps and t not in SPECIAL:
                    raise FlowError(f'{source} 步骤 {s["id"]} 的 {k} 指向不存在的步骤 {t}')

    def __getitem__(self, sid):
        return self.steps[sid]

    def __contains__(self, sid):
        return sid in self.steps

    def next_of(self, sid):
        s = self.steps[sid]
        if s.get('goto'):
            return s['goto']
        if s.get('hold'):
            return 'HOLD'
        i = self.order.index(sid)
        return self.order[i + 1] if i + 1 < len(self.order) else 'END'


def load(path):
    path = pathlib.Path(path)
    with open(path, 'rb') as f:
        return Flow(tomllib.load(f), source=path.name)


def load_dir(d):
    return {f.id: f for f in (load(p) for p in sorted(pathlib.Path(d).glob('*.toml')))}
