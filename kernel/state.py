"""从事件得出：当前是哪个功能、它的工单有哪些、各自在哪一步（设计书 8.2：位置由事件按流程定义回放得出，Y3）。"""
from dataclasses import dataclass, field

from .replay import replay


@dataclass
class Feature:
    name: str                       # 带序号的功能名，例如 jizhang-1

    @property
    def scope(self):
        return f'feature/{self.name}'

    @property
    def branch(self):
        return f'feat/{self.name}'

    @property
    def wt(self):
        return f'feat-{self.name}'

    @property
    def fdir(self):
        return f'.scratch/{self.name}'


@dataclass
class Ticket:
    feature: Feature
    id: str                          # 这一轮的编号：01；被放弃后重做的是 01-2；修复工单是 x1
    plan_id: str                     # 工单文件的编号（依赖按它算）
    file: str                        # 相对 fdir 的工单文件
    risk: str = '无'
    deps: list = field(default_factory=list)
    fix: bool = False

    @property
    def scope(self):
        return f'ticket/{self.feature.name}/{self.id}'

    @property
    def branch(self):
        return f'ticket/{self.feature.name}/{self.id}'

    @property
    def wt(self):
        return f'ticket-{self.feature.name}-{self.id}'

    @property
    def risky(self):
        return self.fix or self.risk.strip() not in ('', '无')


def current_feature(project_events):
    """最后一个开了轮、还没结束也没放弃的功能（第一版一个项目一次只做一个功能，1.2）。"""
    names = [e['feature'] for e in project_events if e['type'] == 'register' and e.get('what') == 'feature']
    ended = {e['feature'] for e in project_events if e['type'] == 'note' and e.get('kind') in ('功能结束', '功能放弃')}
    for n in reversed(names):
        if n not in ended:
            return Feature(n)
    return None


def by_scope(events):
    out = {}
    for e in events:
        out.setdefault(e['scope'], []).append(e)
    return out


def regs(events, what):
    return [e for e in events if e['type'] == 'register' and e.get('what') == what]


def tickets(feature, feature_dir_events):
    """这个功能登记过的全部工单（按登记的先后）。"""
    out = {}
    for e in regs([x for x in feature_dir_events if x['scope'] == feature.scope], 'ticket'):
        out[e['id']] = Ticket(feature, e['id'], e['plan_id'], e['file'], e.get('risk', '无'), e.get('deps', []), e.get('fix', False))
    return out


def view(flows, feature, feature_dir_events):
    """返回 (功能的位置, {工单编号: (工单, 位置)})。"""
    sc = by_scope(feature_dir_events)
    fpos = replay(flows['feature'], sc.get(feature.scope, []))
    ts = {i: (t, replay(flows['ticket'], sc.get(t.scope, []))) for i, t in tickets(feature, feature_dir_events).items()}
    return fpos, ts


def last_payload(events, step, type_='done'):
    for e in reversed(events):
        if e.get('step') == step and e['type'] == type_:
            return e
    return None


def merged(pos):
    """工单已合进功能分支（T13 做完）。"""
    return pos.status == 'done' or pos.pos == 'T15' or (pos.status == 'interrupted' and pos.pos == 'T15')
