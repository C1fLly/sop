"""回放：按流程定义把一个范围（一个功能或一张工单）的事件走一遍，得出现在在哪一步（设计书 8.2、8.3）。

只看事件，不看文件内容：记录不因为文件变了而失效，只有「重新打开」事件才让确认失效（8.3）。
回头路（T6 回 T4、T14 回 T4、F17 回 F14）在回放里是同一步骤的又一次尝试。
流程定义里没有的步骤编号不猜，只记下个数（S6）。
"""
from dataclasses import dataclass, field


@dataclass
class Position:
    pos: str
    status: str = 'ready'          # ready / running / interrupted / done / dropped / held / stopped / blocked
    running: str | None = None
    running_since: dict | None = None
    attempts: dict = field(default_factory=dict)
    fails: dict = field(default_factory=dict)
    confirms: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)
    cost: float = 0.0
    unknown: int = 0
    last_fail: dict | None = None
    notes: list = field(default_factory=list)


def replay(flow, events):
    st = Position(pos=flow.order[0])

    def settle():
        # 确认过、没被重新打开的人的确认步骤，直接越过（8.3：记录不因为文件变了而失效）
        while st.pos in flow.steps and flow[st.pos].get('confirm') and st.pos in st.confirms:
            st.pos = flow.next_of(st.pos)

    for ev in events:
        t, sid = ev['type'], ev.get('step')
        st.cost += float(ev.get('cost') or 0)
        if t in ('register', 'release'):
            continue
        if t == 'note':
            st.notes.append(ev)
            continue
        if t == 'drop':
            st.status = 'dropped'
            continue
        if sid not in flow.steps:
            st.unknown += 1
            continue
        if t == 'start':
            st.running, st.running_since = sid, ev
            st.attempts[sid] = st.attempts.get(sid, 0) + 1
            st.pos = sid
        elif t == 'done':
            st.running = None
            st.pos = flow.next_of(sid)
        elif t == 'skipped':
            st.running = None
            st.skipped.append(sid)
            st.pos = flow.next_of(sid)
        elif t == 'confirm':
            st.running = None
            st.confirms[sid] = ev.get('commit')
            st.pos = flow.next_of(sid)
        elif t == 'failed':
            st.running = None
            st.fails[sid] = st.fails.get(sid, 0) + 1
            st.last_fail = ev
            s = flow[sid]
            if ev.get('route'):
                target = ev['route']                       # 处理函数指明去哪（例如有冲突去 T14）
            elif s.get('max_fails') and st.fails[sid] > s['max_fails']:
                target = s.get('on_fails_exhausted', 'STOP')
            else:
                target = s.get('on_fail') or sid           # 没写去哪：停在原地，等人或维修窗口
            seen = set()
            while target in flow.steps and flow[target].get('max_attempts') and \
                    st.attempts.get(target, 0) >= flow[target]['max_attempts'] and target not in seen:
                seen.add(target)
                target = flow[target].get('on_exhausted', 'STOP')
            st.pos = target
            if target == sid and not ev.get('route') and not s.get('on_fail'):
                st.status = 'blocked'
        elif t == 'reopen':
            st.confirms.pop(ev['target'], None)
            if ev.get('jump'):
                st.pos = ev['target']
        if t != 'failed':
            if st.status == 'blocked':
                st.status = 'ready'
        settle()
    if st.status == 'dropped':
        return st
    if st.running:
        st.status, st.pos = 'interrupted', st.running
    elif st.pos == 'END':
        st.status = 'done'
    elif st.pos == 'HOLD':
        st.status = 'held'
    elif st.pos == 'STOP':
        st.status = 'stopped'
    return st
