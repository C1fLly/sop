"""流程引擎（设计书 8.4）：从当前位置连续执行，遇到下面任一情况停下：下一步的执行者是人或 AI 交互（又没人在答）；
某一步失败且自动处理的办法用完；达到轮数上限。每次停下打印四件事：现在在哪一步、刚才自动做了什么以及各自通过与否、
现在需要你做什么、做完后执行什么命令。

并行：一个 sop 进程里，F14 给所有不被阻塞的工单各开一个线程走工单流程（并行数有上限，7.5），事件由同一个写入线程合并推送（8.2）。
"""
import os
import shutil
import socket
import threading
import time
import traceback
from dataclasses import dataclass, field

from checks import lib as checklib
from checks.quota_scan.check import run as quota_scan

from . import cost, journal as J, state
from .errors import SopError, Tampered, ToolkitBug
from .locks import ProjectLock
from .replay import replay

PARALLEL = int(os.environ.get('SOP_PARALLEL', '3'))
MAX_STEPS = int(os.environ.get('SOP_MAX_STEPS_PER_RUN', '200'))   # 一轮里同一个范围最多走几步（防打转的总保险，8.4）


@dataclass
class StepResult:
    ok: bool
    reason: str = ''
    route: str | None = None          # 失败时去哪（覆盖流程定义的 on_fail）
    hold: bool = False                # 失败时停在这一步（等人、维修窗口、修补版）
    payload: dict = field(default_factory=dict)
    cost: float = 0.0
    reopen: list = field(default_factory=list)   # 要重新打开的确认步骤
    confirm: bool = False             # 人的确认：记成 confirm 而不是 done
    notes: list = field(default_factory=list)


class Stop(Exception):
    """这一轮到此为止（等人、额度报错暂停等）。"""


class Engine:
    def __init__(self, project, human, adapter, out=print):
        self.p, self.human, self.adapter = project, human, adapter
        self.out = out
        self.did = []                 # 这一轮自动做了什么（停下时打印）
        self.waiting = []             # 在等人做什么
        self.problems = []            # 停下的原因
        self.tried_blocked = set()
        self.over_limit = set()       # 这一轮走到步数上限的范围：不再接着走（3-29 发现原来工单会被反复重开、停不下来）
        self.counts = {}
        self.outlock = threading.Lock()
        self.poll = float(os.environ.get('SOP_POLL_SECONDS', '15'))
        self.dlock = threading.Lock()
        self.lease = None             # 这个 sop 进程在用的专用 Docker（3-18），退出时放开
        from . import steps
        self.steps = steps

    # ---------- 小工具 ----------
    def say(self, msg):
        with self.outlock:
            self.out(msg)

    def ev(self, scope, step, type_, **kw):
        return self.p.journal.append(J.event(scope, step, type_, **kw))

    def docker(self, prof=None):
        """专用 Docker（6.3 二，3-18 用时才起）：项目的技术栈档案要用 Docker（toolchain.toml 里有 [docker] 段）时，
        起好这个项目的专用 Docker、等它答话，返回通道；档案不用 Docker（或还没选档案）返回 None。
        一个 sop 进程里只起一次，拿着「在用」锁一直到退出（run() 收尾时放开）；退出后 15 分钟没有 sop 再用就由计时器停掉。
        上限取 [docker] 段的 memory、cpu（都可省，省了用默认：内存一半、一半的核）。档案在工具包里，受限侧改不了。"""
        prof = prof if prof is not None else self.p.profile()
        if not prof or 'docker' not in prof['toolchain']:
            return None
        with self.dlock:
            if self.lease is None:
                from runner.docker import service
                limits = service.check_limits(prof['toolchain']['docker'])
                self.lease = service.use(self.p.name, self.p.root, limits, service.proxy())
            else:
                self.lease.touch()
            return self.lease.sock

    def release_docker(self):
        with self.dlock:
            if self.lease is not None:
                self.lease.release()
                self.lease = None

    def events(self, feature):
        return self.p.journal.read(['project', f'feature/{feature.name}'], fetch=False)

    def scope_events(self, feature, scope):
        return [e for e in self.events(feature) if e.get('scope') == scope]

    # ---------- 主循环 ----------
    def run(self, wait_for_lock=False):
        try:
            lock = ProjectLock(self.p.name).acquire()
        except SopError as e:
            self.say(str(e)); return 'busy'
        try:
            self.p.journal.fetch()
            self.p.fetch()
            return self._loop()
        except Stop:
            return self.report('stopped' if self.problems else 'waiting')
        finally:
            self.release_docker()
            self.p.journal.close()
            lock.release()

    def _loop(self):
        proj_events = self.p.journal.read(['project'], fetch=False)
        f = state.current_feature(proj_events)
        if f is None:
            self.say('现在没有进行中的功能。开始一个新功能：sop feature new <名字>')
            return 'idle'
        flow = self.p.flows['feature']
        while True:
            evs = self.events(f)
            fpos, _ = state.view(self.p.flows, f, evs)
            if fpos.status == 'done':
                self.say(f'功能 {f.name} 已经做完并合进主线。')
                return self.report('done')
            if fpos.status == 'dropped':
                return self.report('done')
            if fpos.status in ('stopped',):
                self.problems.append(f'功能 {f.name} 停在了 {fpos.pos}：自动处理的办法用完了。请启动维修窗口（sop repair）。')
                raise Stop
            if fpos.status == 'blocked':
                if f.scope in self.tried_blocked:
                    self.problems.append(f'{fpos.pos} 没通过：{(fpos.last_fail or {}).get("reason", "")}')
                    raise Stop
                self.tried_blocked.add(f.scope)
            if fpos.status == 'interrupted':
                self.recover(f, f, fpos)
            step = flow[fpos.pos]
            if step['id'] == 'F14':
                self.run_tickets(f, fpos)
                continue
            self.do_step(f, f, step, fpos)

    # ---------- 一步 ----------
    def do_step(self, feature, sc, step, pos):
        sid = step['id']
        with self.outlock:
            self.counts[sc.scope] = self.counts.get(sc.scope, 0) + 1
            if self.counts[sc.scope] > MAX_STEPS:
                self.over_limit.add(sc.scope)
                self.problems.append(f'{sc.scope} 这一轮已经走了 {MAX_STEPS} 步还没走完，回头路走得太多了，先停下（8.4）。请启动维修窗口。')
                raise Stop
        if step['actor'] in ('human', 'ai_interactive') and not self.human.can(sc.scope, sid):
            if not (step.get('condition') and not self.steps.condition(self, step['condition'], feature, sc)):
                self.waiting.append((sc.scope, sid, step['name']))
                raise Stop
        attempt = pos.attempts.get(sid, 0) + 1
        if step.get('condition') and not self.steps.condition(self, step['condition'], feature, sc):
            self.ev(sc.scope, sid, 'skipped', reason=f'条件不满足：{step["condition"]}')
            self.did.append((sc.scope, sid, step['name'], '跳过'))
            return
        start = self.steps.before(self, feature, sc, step, attempt)
        self.ev(sc.scope, sid, 'start', attempt=attempt, **start)
        try:
            res = self.steps.dispatch(self, feature, sc, step, attempt, pos)
        except Tampered as e:
            res = StepResult(False, str(e), hold=True)
        except J.Offline:
            raise
        except ToolkitBug as e:
            res = StepResult(False, f'工具包自己的问题：{e}', hold=True, notes=[{'kind': '工具包问题', 'text': str(e)}])
        except SopError as e:
            res = StepResult(False, str(e), hold=True)
        except Exception as e:   # 工具包自己的代码出错：停下，交 sop self report（16.5）
            tb = traceback.format_exc()
            (self.p.state / 'runs').mkdir(parents=True, exist_ok=True)
            (self.p.state / 'runs' / f'error-{int(time.time())}.txt').write_text(tb)
            res = StepResult(False, f'工具包自己的代码出错（{type(e).__name__}: {e}）。这是工具包的问题，不是你的；'
                                    f'可以执行 sop self report 登记', hold=True, notes=[{'kind': '工具包问题', 'text': tb[-2000:]}])
        items = []
        if res.ok:
            items.append(J.event(sc.scope, sid, 'confirm' if res.confirm else 'done', **{**res.payload, 'attempt': attempt, 'cost': res.cost}))
        else:
            kw = {**res.payload, 'attempt': attempt, 'cost': res.cost, 'reason': res.reason}
            if res.route:
                kw['route'] = res.route
            if res.hold:
                kw['hold'] = True
            items.append(J.event(sc.scope, sid, 'failed', **kw))
        for t in res.reopen:
            items.append(J.event(sc.scope, sid, 'reopen', target=t))
        for n in res.notes:
            items.append(J.event(sc.scope, sid, 'note', **n))
        self.p.journal.append(*items)
        self.did.append((sc.scope, sid, step['name'], '通过' if res.ok else f'没通过：{res.reason[:200]}'))
        self.after_step(feature, res)
        if not res.ok and res.hold:
            self.tried_blocked.add(sc.scope)       # 这一轮不再重试它
            self.problems.append(f'{sc.scope} 的 {sid}（{step["name"]}）：{res.reason}')

    def after_step(self, feature, res):
        """花费提醒（8.4）：到了默认数提醒一次，不中断。"""
        for a in cost.alerts_due(feature.name, self.events(feature), self._all_events()):
            self.p.journal.append(J.event(feature.scope, None, 'note', **a))
            self.say('【花费提醒】' + a['text'])
            cost.notify(a['text'])

    def _all_events(self):
        tip = self.p.journal.tip()
        dirs = sorted({'/'.join(f.split('/')[1:3]) for f in self.p.git('ls-tree', '-r', '--name-only', tip, 'events/').splitlines()})
        return self.p.journal.read(dirs or ['project'], fetch=False)

    def quota(self, feature, sc, sid, logs):
        """每个 AI 步骤结束后扫描会话日志里的额度类报错（7.12、W29）。同一个功能里反复出现就暂停。"""
        if not logs:
            return []
        ok, line, rep = quota_scan(logs)
        if ok:
            return []
        before = [e for e in self.events(feature) if e.get('type') == 'note' and e.get('kind') == '额度报错']
        text = (f'{sc.scope} 的 {sid}：AI 服务报了 {len(rep["hits"])} 次额度类的错误（例如「{rep["hits"][0]["text"][:80]}」）。'
                '断掉的可能只是 AI 派出去的帮手，主会话自己接着做完了。请到 AI 服务的后台看一下余额，不够就充值。')
        self.say('【额度】' + text)
        cost.notify(text)
        note = {'kind': '额度报错', 'text': text, 'hits': rep['hits'][:5]}
        if before:
            self.problems.append('同一个功能里第二次碰到额度类的报错，先暂停。充好值以后再执行 sop。')
            note['paused'] = True
        return [note]

    # ---------- 被打断的步骤 ----------
    def recover(self, feature, sc, pos):
        """日志里有「步骤开始」而没有结束：列出这个工作目录里没提交的改动，丢弃，从上一次提交的状态重做这一步（7.12）。"""
        ev = pos.running_since or {}
        if ev.get('host') and ev['host'] != socket.gethostname() and not os.environ.get('SOP_SAME_MACHINE'):
            self.problems.append(f'{sc.scope} 的 {pos.pos} 是在另一台电脑（{ev["host"]}）上开始的，还没结束。'
                                 '那台电脑是不是还在跑？确认已经停了，再执行 SOP_SAME_MACHINE=1 sop。')
            raise Stop
        wt = self.steps.worktree_of(self, feature, sc, self.p.flows[sc.scope.split('/')[0]][pos.pos])
        if wt and (self.p.root / wt).is_dir():
            g = self.p.wgit(wt)
            lost = g('status', '--porcelain', '--untracked-files=all')
            ignored = [x for x in checklib.nul(g('ls-files', '-o', '-i', '--exclude-standard', '-z')) if checklib.match(x, checklib.AI_CONFIG)]
            if lost or ignored:
                self.say(f'{sc.scope} 的 {pos.pos} 上次被打断了。丢掉没提交的改动，从上一次提交重做：\n' + lost + ''.join(f'\n?? {x}（被忽略的 AI 设置文件）' for x in ignored))
            g('merge', '--abort', check=False)
            g('reset', '-q', '--hard')
            g('clean', '-q', '-fd')
            for x in ignored:
                p = self.p.root / wt / x
                shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
        self.ev(sc.scope, pos.pos, 'note', kind='中断后重做', text=f'{pos.pos} 上次被打断，丢掉没提交的改动后重做')

    # ---------- F14：工单并行 ----------
    def run_tickets(self, feature, fpos):
        f = feature
        if fpos.running != 'F14' and fpos.pos == 'F14':
            self.ev(f.scope, 'F14', 'start', attempt=fpos.attempts.get('F14', 0) + 1)
        running, stop_reasons = {}, []
        cv = threading.Condition()

        def worker(t):
            try:
                self.run_ticket(f, t)
            except Stop:
                pass
            except Exception as e:   # noqa: BLE001
                stop_reasons.append(f'{t.scope}：{e}')
                (self.p.state / 'runs').mkdir(parents=True, exist_ok=True)
                (self.p.state / 'runs' / f'error-{int(time.time())}.txt').write_text(traceback.format_exc())
            finally:
                with cv:
                    running.pop(t.id, None)
                    cv.notify_all()

        while True:
            evs = self.events(f)
            _, ts = state.view(self.p.flows, f, evs)
            plan_merged = {}
            for t, pos in ts.values():
                plan_merged[t.plan_id] = plan_merged.get(t.plan_id, False) or state.merged(pos)
            runnable, held, waiting_h, blocked = [], [], [], []
            for tid, (t, pos) in ts.items():
                if pos.status in ('done', 'dropped') or tid in running or t.scope in self.over_limit:
                    continue
                if pos.status == 'held':
                    held.append((t, pos)); continue
                if pos.status in ('stopped',) or (pos.status == 'blocked' and t.scope in self.tried_blocked):
                    blocked.append((t, pos)); continue
                if not all(plan_merged.get(d) for d in t.deps):
                    continue
                st = self.p.flows['ticket'][pos.pos]
                if st['actor'] == 'human' and not self.human.can(t.scope, pos.pos) and not \
                        (st.get('condition') and not self.steps.condition(self, st['condition'], f, t)):
                    waiting_h.append((t, pos)); continue
                runnable.append(t)
            with cv:
                for t in runnable:
                    if len(running) >= PARALLEL:
                        break
                    th = threading.Thread(target=worker, args=(t,), daemon=True, name=f'ticket-{t.id}')
                    running[t.id] = th
                    th.start()
                if running:
                    cv.wait(timeout=5)
                    continue
            if self.problems:
                raise Stop
            if held:
                for t, pos in held:
                    self.steps.handle_decision(self, f, t, pos)
                return
            if stop_reasons:
                self.problems += stop_reasons
                raise Stop
            if blocked:
                for t, pos in blocked:
                    self.problems.append(f'工单 {t.id} 停在 {pos.pos}：{(pos.last_fail or {}).get("reason", "")}')
                raise Stop
            if waiting_h:
                for t, pos in waiting_h:
                    self.waiting.append((t.scope, pos.pos, self.p.flows['ticket'][pos.pos]['name']))
                raise Stop
            live = [t for t, pos in ts.values() if pos.status not in ('dropped',)]
            if all(ts[t.id][1].status == 'done' for t in live):
                self.ev(f.scope, 'F14', 'done', tickets=[t.id for t in live])
                self.did.append((f.scope, 'F14', '实现', f'{len(live)} 张工单都合进了功能分支'))
                return
            # 剩下的都被依赖挡着（依赖的工单被放弃了）：停下说明
            self.problems.append('剩下的工单都在等别的工单，而那几张做不下去了：' +
                                 '、'.join(t.id for t, pos in ts.values() if pos.status not in ('done', 'dropped')))
            raise Stop

    def run_ticket(self, feature, t):
        flow = self.p.flows['ticket']
        while True:
            pos = replay(flow, self.scope_events(feature, t.scope))
            if pos.status in ('done', 'dropped', 'held', 'stopped'):
                return
            if pos.status == 'blocked':
                if t.scope in self.tried_blocked:
                    return
                self.tried_blocked.add(t.scope)
            if pos.status == 'interrupted':
                self.recover(feature, t, pos)
            step = flow[pos.pos]
            self.do_step(feature, t, step, pos)
            if self.problems:
                return

    # ---------- 停下时打印的四件事 ----------
    def report(self, status):
        lines = ['', '======== 现在在哪 ========']
        if status == 'done':
            self.waiting = []
        try:
            proj = self.p.journal.read(['project'], fetch=False)
            f = state.current_feature(proj)
            if f:
                fpos, ts = state.view(self.p.flows, f, self.events(f))
                lines.append(f'功能 {f.name}：{fpos.pos}（{"进行中" if fpos.pos == "F14" and fpos.status == "interrupted" else fpos.status}）')
                for tid, (t, pos) in ts.items():
                    lines.append(f'  工单 {tid}：{pos.pos}（{pos.status}）')
                # 在等人做什么：按现在的位置现算（早先记下的、后来已经答了的不算）
                now = {(f.scope, fpos.pos)} | {(t.scope, pos.pos) for t, pos in ts.values()}
                self.waiting = [w for w in self.waiting if (w[0], w[1]) in now and fpos.status != 'done']
        except Exception as e:   # noqa: BLE001
            lines.append(f'（读位置出错：{e}）')
        lines.append('======== 刚才自动做了什么 ========')
        lines += [f'  {sc} {sid} {name}：{r}' for sc, sid, name, r in self.did[-40:]] or ['  （没有）']
        lines.append('======== 现在需要你做什么 ========')
        if self.problems:
            lines += [f'  停下了：{x}' for x in dict.fromkeys(self.problems)]
        for sc, sid, name in dict.fromkeys(self.waiting):
            lines.append(f'  {sc} 的 {sid}（{name}）在等你')
        if not self.problems and not self.waiting:
            lines.append('  不需要你做什么' if status == 'done' else '  （无）')
        lines.append('======== 做完后执行 ========')
        if self.waiting:
            lines.append('  sop answer   （在终端里回答；AI 对话的步骤用 sop chat）')
        elif self.problems:
            lines.append('  看懂上面的原因后再执行 sop；看不懂就执行 sop repair 启动维修窗口')
        else:
            lines.append('  sop')
        self.say('\n'.join(lines))
        return status
