"""各步的处理函数（设计书 7.4 功能流程、7.5 工单流程）。每个都写成「重做也安全」：被打断后重做时，已经做过的不再做。"""
import hashlib
import json
import os
import pathlib
import shutil
import time

from checks import lib as checklib
from checks.confirmed.check import run as check_confirmed
from checks.f19.check import run as check_f19
from checks.handoff_exists.check import run as check_handoff
from checks.history.check import run as check_history
from checks.plan_check.check import run as check_plan
from checks.cards_cover.check import run as check_cards
from checks.protected.check import run as check_protected
from checks.result_file.check import run as check_result
from checks.scope.check import ignored_ai_files, run as check_scope

from . import journal as J, ports, state, taskpack
from .errors import SopError, ToolkitBug
from .replay import replay
from runner import aistate, placement, sandbox

NAMES = {'fast': 'fast', 'full': 'full', 'guard': 'guard'}
RESULT_KIND = {'ticket_impl': 'impl', 'planning': 'planning', 'std_draft': 'planning', 'readonly': 'review'}
# 会运行项目代码的 AI 步骤（工单上的实现要跑测试，测试可能起容器）才给专用 Docker 的通道（6.3 四）；规划、只看不改的步骤不给
DOCKER_KINDS = ('ticket_impl', 'implement_spec')


def R(*a, **kw):
    from .engine import StepResult
    return StepResult(*a, **kw)


# ======================================================================
# 共用的小工具
# ======================================================================
def evs_of(eng, f, scope):
    return [e for e in eng.events(f) if e.get('scope') == scope]


def last(eng, f, scope, steps, type_='done'):
    for e in reversed(evs_of(eng, f, scope)):
        if e.get('step') in steps and e['type'] == type_:
            return e
    return None


def frozen_commit(eng, f):
    e = [x for x in evs_of(eng, f, f.scope) if x['type'] == 'register' and x.get('what') == 'plan']
    return e[-1]['frozen'] if e else None


def confirm_of(eng, f, scope, step):
    pos = replay(eng.p.flows[scope.split('/')[0]], evs_of(eng, f, scope))
    if step not in pos.confirms:
        return None
    return last(eng, f, scope, (step,), 'confirm')


def worktree_of(eng, f, sc, step):
    """这一步在哪个工作目录里做。工单上的实现、门禁、复查在工单目录；规划类的（含 T8 的决策记录）在功能目录。"""
    if step['id'] == 'F22':
        return 'main'          # 复盘在功能合进主线、清理之后做，只读地看 main 目录
    if isinstance(sc, state.Ticket) and step.get('kind') not in ('planning', 'std_draft'):
        return sc.wt
    if step['actor'] in ('script', 'human') and isinstance(sc, state.Ticket):
        return sc.wt
    return f.wt


def push(eng, branch):
    """推送一条分支。推之前现场取远程，核对本地是它的延续（6.4 第四层）。"""
    p = eng.p
    with p.gitlock:
        local = p.git('rev-parse', f'refs/heads/{branch}')
        ok, line, _ = check_history(str(p.gitdir), branch, local)
        if not ok:
            raise SopError(line)
        p.git('push', '-q', 'origin', f'refs/heads/{branch}:refs/heads/{branch}')
        p.git('update-ref', f'refs/remotes/origin/{branch}', local)
    return local


def ff_feature(eng, f):
    """把本机的功能目录快进到远程（工单 PR 合并后，wt done 只更新 main 目录，S3）。只做快进，不运行任何代码。"""
    p = eng.p
    p.fetch(f.branch)
    with p.gitlock:
        p.wgit(f.wt)('merge', '-q', '--ff-only', f'refs/remotes/origin/{f.branch}')


def commit_all(eng, wt, branch, message):
    """特权侧提交（规划类步骤 AI 不提交，6.3）：只做「登记文件、写提交」，关掉钩子，然后推送。"""
    g = eng.p.wgit(wt)
    with eng.p.gitlock:
        g('add', '-A')
        if g.ok('diff', '--cached', '--quiet'):
            return g('rev-parse', 'HEAD')
        g('commit', '-q', '-m', message)
    push(eng, branch)
    return g('rev-parse', 'HEAD')


def gh_json(eng, *args):
    p = eng.p.gh(*args)
    return json.loads(p.stdout)


def pr_view(eng, n):
    return gh_json(eng, 'pr', 'view', str(n), '--json', 'number,state,isDraft,headRefOid,mergeable,url')


def check_runs(eng, sha):
    return gh_json(eng, 'api', f'repos/{eng.p.slug()}/commits/{sha}/check-runs')['check_runs']


def rerun(eng, run_id):
    eng.p.gh('run', 'rerun', str(run_id))


def blob_of_file(path):
    data = pathlib.Path(path).read_bytes()
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()


def run_dir(eng, scope, sid, attempt):
    d = eng.p.state / 'runs' / scope.replace('/', '_') / f'{sid}-{attempt}'
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    (d / 'task').mkdir(parents=True)
    (d / 'out').mkdir()
    return d


def feature_pr(eng, f):
    e = last(eng, f, f.scope, ('F12',))
    return e['pr'] if e else None


def ticket_pr(eng, f, t):
    e = last(eng, f, t.scope, ('T10',))
    return e['pr'] if e else None


# ======================================================================
# 执行条件
# ======================================================================
def condition(eng, name, f, sc):
    if name == 'feature.has_new_pages':
        p = eng.p.root / f.wt / f.fdir / 'handoff-plan.md'
        return p.exists() and '有新页面或改页面：是' in p.read_text(encoding='utf-8')
    if name == 'ticket.risky':
        return sc.risky
    if name == 'ticket.per_ticket_accept':
        c = confirm_of(eng, f, f.scope, 'F13')
        per = (c or {}).get('per_ticket', [])
        return per == 'all' or sc.plan_id in per or (sc.fix and per != [])
    raise ToolkitBug(f'流程定义里有不认识的执行条件：{name}')


def before(eng, f, sc, step, attempt):
    return {}


def dispatch(eng, f, sc, step, attempt, pos):
    a = step['actor']
    if a in ('ai_headless', 'ai_interactive'):
        return ai_step(eng, f, sc, step, attempt, pos)
    if a == 'restricted_script':
        return gate_step(eng, f, sc, step, attempt)
    fn = HANDLERS.get(step['action'])
    if fn is None:
        raise ToolkitBug(f'步骤 {step["id"]} 的处理函数 {step["action"]} 不存在')
    return fn(eng, f, sc, step, attempt, pos)


# ======================================================================
# AI 步骤（6.3 的放法、9.1 的任务包、9.2 的结果文件、9.3 交回的问题、7.12 的额度报错）
# ======================================================================
def sessions_file(eng):
    return eng.p.state / 'sessions.json'


def session_for(eng, scope, step, flow, workdir):
    """全新会话的步骤每次现建状态目录；续接的几步共用一个（F2、F5、F6 是一组；F3、F4a 是一组）。"""
    group = step.get('session', 'new')
    tmpl = lambda d: eng.adapter.template(d, workdir)   # noqa: E731
    if group == 'new':
        return aistate.fresh(eng.p.name, eng.adapter.name, f'{scope.replace("/", "_")}-{step["id"]}', tmpl), None, True
    f = sessions_file(eng)
    data = json.loads(f.read_text()) if f.exists() else {}
    key = f'{scope}:{group}'
    members = [s['id'] for s in flow.steps.values() if s.get('session') == group]
    is_last = step['id'] == members[-1]
    if key in data and not aistate.sealed(data[key]['dir']):
        return pathlib.Path(data[key]['dir']), data[key].get('session'), is_last
    d = aistate.fresh(eng.p.name, eng.adapter.name, f'{scope.replace("/", "_")}-{group}', tmpl)
    data[key] = {'dir': str(d)}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return d, None, is_last


def remember_session(eng, scope, group, session):
    f = sessions_file(eng)
    data = json.loads(f.read_text()) if f.exists() else {}
    if f'{scope}:{group}' in data:
        data[f'{scope}:{group}']['session'] = session
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def ai_step(eng, f, sc, step, attempt, pos):
    p, sid, kind = eng.p, step['id'], step['kind']
    flow = p.flows[sc.scope.split('/')[0]]
    wt = worktree_of(eng, f, sc, step)
    wdir = p.root / wt
    if isinstance(sc, state.Ticket) and sid == 'T14':
        p.fetch(f.branch)
    d = run_dir(eng, sc.scope, sid, attempt)
    ticket_file = f'{f.fdir}/{sc.file}' if isinstance(sc, state.Ticket) else ''
    feedback = (pos.last_fail or {}).get('reason', '') or '（无）'
    if sid == 'F3':
        fb = last(eng, f, f.scope, ('F4',), 'failed')
        feedback = (fb or {}).get('note', '') or '（无）'
    allowed = [a.replace('{fdir}', f.fdir) for a in step.get('allowed', [])]
    must = ['AGENTS.md', 'GLOSSARY.md'] + ([f'{f.fdir}/spec.md'] if sid not in ('F2', 'F3', 'F5') else []) + ([ticket_file] if ticket_file else [])
    taskpack.build(d / 'task', scope=sc.scope, step=sid, attempt=attempt, action=step['action'], skill=step.get('skill'),
                   must_read=must, allowed=allowed or ['（只读，不改任何文件）'],
                   done_when=['结果文件已写好'] + ([f'出口检查：{c}' for c in step.get('checks', [])]),
                   fill={'feature': f.name, 'fdir': f.fdir, 'ticket_file': ticket_file, 'base': f'origin/{f.branch}' if isinstance(sc, state.Ticket) else 'origin/main',
                         'feedback': feedback}, result_kind=RESULT_KIND[kind])
    g = p.wgit(wt)
    head_before = g('rev-parse', 'HEAD')
    scope_base = p.git('rev-parse', f'refs/remotes/origin/{f.branch}') if sid == 'T14' else head_before
    snapshot = ignored_ai_files(str(g.gitdir), str(wdir))
    st_dir, session, is_last = session_for(eng, sc.scope, step, flow, wdir)
    ro, env, pass_env = eng.adapter.sandbox_extras()
    if sid == 'F22':
        ro = list(ro) + [str(p.state / 'ai-state')]
    ctx = placement.Ctx(root=p.root, kind=kind, worktree=wt, feature=f.name, task_dir=d / 'task', out_dir=d / 'out',
                        ro=ro, env=env, pass_env=pass_env, chdir=wdir,
                        docker_sock=eng.docker() if kind in DOCKER_KINDS else None,
                        interactive=step['actor'] == 'ai_interactive' and getattr(eng.human, 'interactive', False))
    if step['actor'] == 'ai_interactive':
        out = eng.adapter.resume(ctx, d / 'task', st_dir, session, '接着做下一步') if session else eng.adapter.start_interactive(ctx, d / 'task', st_dir)
    else:
        out = eng.adapter.resume(ctx, d / 'task', st_dir, session, '接着做') if session else eng.adapter.run_headless(ctx, d / 'task', st_dir)
    if step.get('session', 'new') != 'new' and out.session:
        remember_session(eng, sc.scope, step['session'], out.session)
    if step.get('session', 'new') == 'new' or is_last:
        aistate.seal(st_dir)
    notes = eng.quota(f, sc, sid, out.logs)
    base_res = dict(cost=out.cost, notes=notes)
    if any(n.get('paused') for n in notes):
        return R(False, '同一个功能里第二次碰到额度类的报错，暂停', hold=True, **base_res)
    if out.rc != 0 or out.timeout:
        return R(False, f'AI 工具没有正常结束（退出码 {out.rc}{"，超时" if out.timeout else ""}）：{out.text[-300:]}', **base_res)
    rpath = d / 'out' / 'result.json'
    result = json.loads(rpath.read_text()) if rpath.exists() else None
    if step['actor'] == 'ai_interactive':
        ans = eng.human.ask(sc.scope, sid, f'{step["name"]}：和 AI 聊完了吗？是不是已经达成共识？', {'choices': ['是', '还没有']})
        if ans.get('answer') not in ('是', True) and not ans.get('ok'):
            return R(False, '小白说还没有达成共识', hold=True, **base_res)
    elif result is None:
        return R(False, 'AI 没有交回结果文件（自动调用的 AI 说「做完了」不算数，Y6）', **base_res)
    if result:
        if kind == 'ticket_impl':
            ok_r, line, _ = True, '', None   # 结果文件和提交由 T4 核对
        else:
            ok_r, line, _ = check_result(str(rpath), str(g.gitdir), head_before, g('rev-parse', 'HEAD'), RESULT_KIND[kind])
        if not ok_r:
            return R(False, line, **base_res)
        if result.get('status') == 'question':   # 9.3：正常结束、什么都没做、交回一个问题
            qs = '；'.join(f'【{q.get("category")}】{q.get("text")}' for q in result.get('questions', []))
            return R(False, f'AI 交回了问题：{qs}', hold=True, payload={'questions': result.get('questions', [])}, **base_res)
    # ---- 按放法收尾 ----
    if kind in ('planning', 'std_draft'):
        ok_s, line, _ = check_scope(str(g.gitdir), str(wdir), head_before, allowed, p.protected_patterns(), snapshot)
        if not ok_s:
            return R(False, line, **base_res)
        for c in step.get('checks', []):
            ok_c, line = run_named_check(eng, f, c, wt)
            if not ok_c:
                return R(False, line, **base_res)
        commit = commit_all(eng, wt, f.branch, f'docs({f.name}): {step["name"]}（{sid}，由流程命令提交）')
        reopen = []
        if sid == 'F8':
            reopen = cards_changed_reopen(eng, f, commit)
        payload = {'commit': commit}
        if sid == 'T8':
            payload['decision'] = (result or {}).get('decision', 'tech')
            payload['decision_text'] = (result or {}).get('pr_body', '') or json.dumps(result or {}, ensure_ascii=False)[:500]
        return R(True, payload=payload, reopen=reopen, **base_res)
    if kind == 'readonly':
        blocking = [x['text'] for x in (result or {}).get('findings', []) if x.get('blocking')]
        if sid == 'F22':
            (p.state / 'runs' / f'retro-{f.name}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        if blocking:
            return R(False, '复查有阻断问题：' + '；'.join(blocking[:5]), payload={'findings': len(result.get('findings', []))}, **base_res)
        return R(True, payload={'findings': len((result or {}).get('findings', []))}, **base_res)
    # 工单上的实现（T3、T6、T7、T14）：AI 自己提交；结果文件、提交、可改范围由 T4 核对
    reopen = ['T11'] if step.get('changes_confirmed') and 'T11' in pos.confirms else []
    return R(True, payload={'run': str(d), 'base': scope_base, 'snapshot': snapshot}, reopen=reopen, **base_res)


def run_named_check(eng, f, name, wt):
    """流程定义里 checks = ["名字" 或 "名字:参数"]。"""
    n, _, arg = name.partition(':')
    w = str(eng.p.root / wt)
    if n == 'plan_check':
        ok, line, _ = check_plan(w, f.fdir, arg or 'all')
    elif n == 'cards_cover':
        ok, line, _ = check_cards(w, f.fdir)
    elif n == 'handoff_exists':
        ok, line, _ = check_handoff(w, f.fdir, arg)
    else:
        raise ToolkitBug(f'流程定义里有不认识的出口检查：{name}')
    return ok, line


def cards_changed_reopen(eng, f, head):
    """F8 之后：验收卡或大白话摘要和小白确认时不一样了，就重新打开 F10，要小白再确认变化的部分（8.3）。"""
    c = confirm_of(eng, f, f.scope, 'F10')
    if not c:
        return []
    changed = eng.p.git('diff', '--name-only', c['commit'], head, '--', f'{f.fdir}/cards/', f'{f.fdir}/summary.md')
    return ['F10'] if changed.strip() else []


# ======================================================================
# 受限脚本：门禁（F15、T5）
# ======================================================================
def gate_step(eng, f, sc, step, attempt):
    p = eng.p
    prof = p.profile()
    if not prof:
        raise SopError('项目声明里还没有技术栈档案，门禁没有命令可跑（7.2：选定档案之前不适用）')
    wt = worktree_of(eng, f, sc, step)
    if sc is f:
        ff_feature(eng, f)
    d = run_dir(eng, sc.scope, step['id'], attempt)
    (d / 'task' / 'task.json').write_text(json.dumps({'scope': sc.scope, 'step': step['id'], 'attempt': attempt}))
    cmd = [p.expand(x, prof) for x in prof['commands'][step['action']]]
    tc = prof['toolchain']
    ro = [x for x in (p.expand(y, prof) for y in tc.get('ro', [])) if x]
    env = {k: p.expand(v, prof) for k, v in tc.get('env', {}).items()}
    cache = p.root / '.shared' / 'cache'
    ctx = placement.Ctx(root=p.root, kind='restricted_script', worktree=wt, feature=f.name, task_dir=d / 'task', out_dir=d / 'out',
                        ro=ro, rw=[str(cache)] if cache.is_dir() else [], env=env, docker_sock=eng.docker(prof))
    r = sandbox.run(ctx, cmd, timeout=3600)
    rep_p = d / 'out' / 'report.json'
    if not rep_p.exists():
        # 门禁连报告都没写出来：多半是工具包或档案自己的问题（命令写错、脚本不在），不是代码的问题，不生成修复工单（16.5）
        raise ToolkitBug(f'门禁命令没有正常运行（没有写出报告）：{" ".join(cmd)}；输出：{(r.stdout + r.stderr).strip()[-300:]}')
    rep = json.loads(rep_p.read_text())
    ui = {}
    for path in rep.get('ui_changes', []):
        shot = d / 'out' / 'screens' / pathlib.Path(path).name
        ui[path] = {'blob': blob_of_file(shot), 'file': str(shot)}
    payload = {'tests': rep.get('tests', 0), 'ui': ui, 'run': str(d)}
    if r.returncode != 0 or not rep.get('pass'):
        return R(False, f'门禁不通过：{rep.get("why") or (r.stdout + r.stderr)[-300:]}', payload=payload)
    if not rep.get('tests'):
        return R(False, '门禁说通过了，可是一个测试都没跑（14.2：跑了的测试数不能是 0）', payload=payload)
    return R(True, payload=payload)


# ======================================================================
# 功能流程
# ======================================================================
def f_open(eng, f, sc, step, attempt, pos):
    p = eng.p
    p.fetch('main')
    if not (p.root / f.wt).is_dir():
        p.wt('new', f.branch, 'origin/main')
    head = push(eng, f.branch)
    eng.p.journal.append(J.event(f.scope, 'F1', 'register', what='branch', branch=f.branch, base='main', worktree=f.wt))
    return R(True, payload={'head': head})


def f_plan_check(eng, f, sc, step, attempt, pos):
    ok, line = run_named_check(eng, f, 'plan_check', f.wt)
    return R(ok, line)


def f_freeze(eng, f, sc, step, attempt, pos):
    """F11 规划定稿：记下定稿的提交（之后比对「已确认内容」用），登记工单。重规划之后再来一次：只登记还没做完的。"""
    p = eng.p
    c = confirm_of(eng, f, f.scope, 'F10')
    head = p.wgit(f.wt)('rev-parse', 'HEAD')
    ok, line, _ = check_confirmed(str(p.gitdir), c['commit'], head, f.fdir, 't8')
    if not ok:
        return R(False, '规划在小白确认之后被改了技术部分以外的内容：' + line, hold=True)
    ok, line, rep = check_plan(str(p.root / f.wt), f.fdir)
    if not ok:
        return R(False, line, hold=True)
    evs = eng.events(f)
    _, ts = state.view(p.flows, f, evs)
    items = [J.event(f.scope, 'F11', 'register', what='plan', frozen=head, confirmed=c['commit'])]
    for pid, info in rep['tickets'].items():
        runs = [(t, ps) for t, ps in ts.values() if t.plan_id == pid]
        if any(state.merged(ps) for _, ps in runs) or any(ps.status not in ('dropped',) for _, ps in runs):
            continue
        ids = {t.id for t, _ in runs}
        tid = pid if pid not in ids else next(f'{pid}-{k}' for k in range(2, 99) if f'{pid}-{k}' not in ids)
        fname = next(x for x in os.listdir(p.root / f.wt / f.fdir / 'issues') if x.startswith(pid + '-'))
        items.append(J.event(f.scope, 'F11', 'register', what='ticket', id=tid, plan_id=pid, file=f'issues/{fname}',
                             deps=info['deps'], risk=info['risk']))
    p.journal.append(*items)
    return R(True, payload={'frozen': head, 'tickets': len(items) - 1})


def f_open_pr(eng, f, sc, step, attempt, pos):
    n = feature_pr(eng, f)
    if not n:
        found = gh_json(eng, 'pr', 'list', '--state', 'open', '--head', f.branch, '--json', 'number')
        if found:
            n = found[0]['number']
        else:
            eng.p.wt('pr', '--draft', '--base', 'main', '--title', f'feat: {f.name}', cwd=eng.p.root / f.wt)
            n = gh_json(eng, 'pr', 'list', '--state', 'open', '--head', f.branch, '--json', 'number')[0]['number']
    return R(True, payload={'pr': n})


def f_implement(eng, f, sc, step, attempt, pos):
    raise ToolkitBug('F14 由引擎直接调度，不该走到这里')


def f_fix_ticket(eng, f, sc, step, attempt, pos):
    """F15、F16、F17 不通过：脚本把报告写成一张修复工单（修复工单一律算带风险标记），回 F14。"""
    p = eng.p
    reason = (pos.last_fail or {}).get('reason', '')
    _, ts = state.view(p.flows, f, eng.events(f))
    n = 1 + sum(1 for t, _ in ts.values() if t.fix)
    tid = f'x{n}'
    fdir = p.root / f.wt / f.fdir / 'fixes'
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / f'{tid}.md').write_text(f'# {tid} 修复\n状态：未开始\n依赖：无\n覆盖：（修复）\n风险：修复工单\n## 要做什么\n{reason}\n'
                                    f'## 验收标准\n- [ ] AC1：上面写的问题不再出现\n## 评论\n', encoding='utf-8')
    commit_all(eng, f.wt, f.branch, f'docs({f.name}): 修复工单 {tid}（由流程命令生成）')
    p.journal.append(J.event(f.scope, 'F14fix', 'register', what='ticket', id=tid, plan_id=tid, file=f'fixes/{tid}.md',
                             deps=[], risk='修复工单', fix=True))
    return R(True, payload={'ticket': tid})


def f_ready(eng, f, sc, step, attempt, pos):
    """F18：转正式之前的脚本兜底：功能分支相对主线改了的每个受保护路径，都要对得上本归属最后一条放行（6.4，v0.9）。"""
    p = eng.p
    p.fetch('main', f.branch)
    rel = p.journal.releases(f.branch)
    ok, line, rep = check_protected(str(p.gitdir), 'refs/remotes/origin/main', f'refs/remotes/origin/{f.branch}',
                                    p.protected_patterns(), rel)
    if not ok:
        files = '、'.join(b['path'] for b in rep['bad'])
        return R(False, f'功能分支上有受保护的文件没有对得上的放行：{files}。不自动补放行，已停下（6.4）。请启动维修窗口（sop repair）。',
                 hold=True, payload={'bad': rep['bad']})
    n = feature_pr(eng, f)
    p.gh('pr', 'ready', str(n))
    return R(True, payload={'pr': n, 'released': len(rep['released'])})


def wait_checks(eng, n, names, want_ready, deadline_s=None):
    """等 GitHub 上的检查。返回 (通过, 说明, 最新提交)。失败的先重跑一次（排除偶发，7.4 的 F19）。"""
    t0, reran = time.time(), False
    deadline_s = deadline_s or int(os.environ.get('SOP_CHECK_DEADLINE', '3600'))
    while True:
        pv = pr_view(eng, n)
        if pv['mergeable'] == 'CONFLICTING':
            return 'conflict', '和目标分支有冲突', pv['headRefOid']
        head = pv['headRefOid']
        runs = check_runs(eng, head)
        if want_ready:
            tl = gh_json(eng, 'api', f'repos/{eng.p.slug()}/issues/{n}/timeline')
            readies = [e['created_at'] for e in tl if e.get('event') == 'ready_for_review']
            ok, line, rep = check_f19(head, readies[-1] if readies else '9999', runs, names)
            waiting = [k for k, v in rep.items() if v['why'] and ('还没' in v['why'])]
            failing = [v['run'] for k, v in rep.items() if v['why'] and v['run'] and v['run']['status'] == 'completed' and k not in waiting]
        else:
            fast = [r for r in runs if r['name'] == names['fast'] and r['head_sha'] == head]
            r = max(fast, key=lambda x: x['started_at']) if fast else None
            ok = bool(r) and r['status'] == 'completed' and r['conclusion'] == 'success'
            line = '快档检查通过' if ok else f'快档检查：{(r or {}).get("conclusion") or "还没跑完"}'
            waiting = [] if (r and r['status'] == 'completed') else ['fast']
            failing = [r] if (r and r['status'] == 'completed' and not ok) else []
        if ok:
            return 'ok', line, head
        if failing and not waiting:
            if reran:
                return 'fail', line + '（重跑过一次，仍不通过）', head
            for r in failing:
                rerun(eng, r['id'])
            reran = True
            continue
        if time.time() - t0 > deadline_s:
            return 'timeout', f'等了 {deadline_s // 60} 分钟检查还没结束：{line}', head
        time.sleep(eng.poll)


def f_wait_checks(eng, f, sc, step, attempt, pos):
    st, line, head = wait_checks(eng, feature_pr(eng, f), NAMES, True)
    if st == 'ok':
        return R(True, payload={'head': head})
    return R(False, f'F19：{line}。GitHub 上的检查没过，不合并。', hold=True, payload={'head': head})


def f_merge(eng, f, sc, step, attempt, pos):
    p = eng.p
    n = feature_pr(eng, f)
    checked = last(eng, f, f.scope, ('F19',))['head']
    sop = p.sop_json(fetch=False)
    if sop.get('visibility') == 'public':
        p.gh('pr', 'merge', str(n), '--squash')
    else:
        url = pr_view(eng, n)['url']
        ans = eng.human.ask(f.scope, 'F20', f'GitHub 上的检查三项都过了（F19 查过）。现在可以到网页上点合并了：{url}\n点好了回答「点好了」。',
                            {'choices': ['点好了', '还没'], 'pr': n})
        if ans.get('answer') != '点好了':
            return R(False, '小白还没在网页上点合并', hold=True)
    info = gh_json(eng, 'api', f'repos/{p.slug()}/pulls/{n}')
    if not info['merged']:
        return R(False, 'PR 还没合并', hold=True)
    if info['head']['sha'] != checked:
        return R(False, f'合进去的不是 F19 查过的那一份（查的是 {checked[:8]}，合的是 {info["head"]["sha"][:8]}）。请决定要不要退掉（7.12）。', hold=True)
    return R(True, payload={'merge_commit': info['merge_commit_sha']})


def f_cleanup(eng, f, sc, step, attempt, pos):
    p = eng.p
    if (p.root / f.wt).is_dir():
        p.wt('done', f.branch)
    ports.release(p.name, f.wt)
    return R(True)


def f_metrics(eng, f, sc, step, attempt, pos):
    evs = eng.events(f)
    from . import cost
    _, ts = state.view(eng.p.flows, f, evs)
    m = {'total_usd': cost.total(evs), 'tickets': len(ts),
         'fix_rounds': sum(ps.attempts.get('T6', 0) for _, ps in ts.values()),
         'accept_rework': sum(ps.fails.get('T11', 0) for _, ps in ts.values())}
    eng.p.journal.append(J.event(f.scope, 'F23', 'note', kind='指标', **m),
                         J.event('project', None, 'note', kind='功能结束', feature=f.name))
    eng.say(f'功能 {f.name} 的指标：花费 {m["total_usd"]:.2f} 美元（工具报告的金额），{m["tickets"]} 张工单，修复 {m["fix_rounds"]} 轮，验收返工 {m["accept_rework"]} 次')
    return R(True, payload=m)


# ---- 人的步骤 ----
def human_yes(ans):
    return ans.get('ok') is True or ans.get('answer') in ('通过', '满意', '是', '对', 'ok')


def h_prototype(eng, f, sc, step, attempt, pos):
    ans = eng.human.ask(f.scope, 'F4', '请打开原型看一看（数据是假的）。满意吗？', {'choices': ['满意', '不满意']})
    if human_yes(ans):
        return R(True, confirm=True, payload={'commit': eng.p.wgit(f.wt)('rev-parse', 'HEAD')})
    return R(False, '小白对原型不满意', payload={'note': ans.get('note', '')})


def h_plan(eng, f, sc, step, attempt, pos):
    show = [f'大白话摘要：{f.fdir}/summary.md', f'验收卡：{f.fdir}/cards/']
    ans = eng.human.ask(f.scope, 'F10', '请看大白话摘要、验收卡、已确认的原型。可以按这个做吗？', {'show': show, 'choices': ['是', '不是']})
    if human_yes(ans):
        return R(True, confirm=True, payload={'commit': eng.p.wgit(f.wt)('rev-parse', 'HEAD')})
    return R(False, '小白不确认规划：' + ans.get('note', ''), hold=True)


def h_impl_mode(eng, f, sc, step, attempt, pos):
    """F13：脚本算出建议（带风险标记的逐张验收），小白直接回车就是采纳。"""
    _, ts = state.view(eng.p.flows, f, eng.events(f))
    ok, line, rep = check_plan(str(eng.p.root / f.wt), f.fdir)
    risky = [pid for pid, x in rep.get('tickets', {}).items() if x['risk'].strip() not in ('', '无')]
    ans = eng.human.ask(f.scope, 'F13', f'建议：带风险标记的工单（{"、".join(risky) or "无"}）逐张验收，其余做完统一验收；走流程命令编排的路径。'
                                       '直接回车就是采纳。', {'choices': ['', '全部逐张', '全部统一']})
    a = ans.get('per_ticket')
    if a is None:
        a = {'全部逐张': 'all', '全部统一': []}.get(ans.get('answer', ''), risky)
    return R(True, confirm=True, payload={'per_ticket': a, 'path': 'orchestrated'})


def h_accept_feature(eng, f, sc, step, attempt, pos):
    """F17：照验收卡验收整个功能；这次带来的每一处界面变化并排给小白看（第 13 节）。通过时更新视觉基准：先写放行，再推送（6.4）。"""
    p = eng.p
    gate = last(eng, f, f.scope, ('F15',)) or {}
    ui = gate.get('ui', {})
    show = [f'验收卡：{f.fdir}/cards/'] + [f'界面变化：{k}（旧图、新图、差别并排看）' for k in ui]
    ans = eng.human.ask(f.scope, 'F17', '请照验收卡逐项验收整个功能。', {'show': show, 'choices': ['通过', '不通过']})
    if not human_yes(ans):
        return R(False, '行为验收不通过：' + ans.get('note', ''))
    if ui:
        rel = [J.release(f.branch, path, x['blob'], 'F17') for path, x in ui.items()]
        p.journal.append(*rel)
        for path, x in ui.items():
            shutil.copy(x['file'], p.root / f.wt / path)
        commit_all(eng, f.wt, f.branch, 'chore: 验收通过，更新视觉基准（F17）')
    return R(True, confirm=True, payload={'commit': p.wgit(f.wt)('rev-parse', 'HEAD'), 'images': {k: v['blob'] for k, v in ui.items()}})


# ======================================================================
# 工单流程
# ======================================================================
def t_open(eng, f, t, step, attempt, pos):
    p = eng.p
    p.fetch(f.branch)
    if not (p.root / t.wt).is_dir():
        p.wt('new', t.branch, f'origin/{f.branch}')
    pr = ports.allocate(p.name, t.wt)
    prof = p.profile()
    if prof and prof['commands'].get('setup'):   # 依赖由流程命令在受限侧装，不交给 wt 的准备脚本（5.6）
        ctx = placement.Ctx(root=p.root, kind='restricted_script', worktree=t.wt, feature=f.name,
                            ro=[x for x in (p.expand(y, prof) for y in prof['toolchain'].get('ro', [])) if x],
                            docker_sock=eng.docker(prof))
        r = sandbox.run(ctx, [p.expand(x, prof) for x in prof['commands']['setup']], timeout=3600)
        if r.returncode:
            return R(False, f'装依赖失败：{(r.stdout + r.stderr)[-300:]}', hold=True)
    base = p.wgit(t.wt)('rev-parse', 'HEAD')
    p.journal.append(J.event(t.scope, 'T1', 'register', what='worktree', branch=t.branch, base=f.branch, worktree=t.wt, base_commit=base))
    return R(True, payload={'ports': pr, 'base': base})


def t_taskpack(eng, f, t, step, attempt, pos):
    p = eng.p
    path = p.root / f.wt / f.fdir / t.file
    if not path.exists():
        return R(False, f'工单文件不在功能分支上：{f.fdir}/{t.file}', hold=True)
    text = path.read_text(encoding='utf-8')
    if '## 验收标准' not in text:
        return R(False, '工单没有验收标准', hold=True)
    return R(True)


def t_verify(eng, f, t, step, attempt, pos):
    """T4 结果校验：结果文件格式对；声称的提交存在；工作区干净；只改了允许的路径（连被忽略的文件一起看）；已确认内容没被改。"""
    p = eng.p
    ai = last(eng, f, t.scope, ('T3', 'T6', 'T7', 'T14'))
    if not ai:
        return R(False, '找不到上一个 AI 步骤', hold=True)
    g = p.wgit(t.wt)
    head = g('rev-parse', 'HEAD')
    bad = []
    if ai['step'] != 'T14':
        ok, line, _ = check_result(str(pathlib.Path(ai['run']) / 'out' / 'result.json'), str(g.gitdir), ai['base'], head, 'impl')
        if not ok:
            bad.append(line)
    if g('status', '--porcelain', '--untracked-files=all'):
        bad.append('工作区不干净：有没提交的改动或新文件')
    opened = last(eng, f, t.scope, ('T1',))
    if opened and opened.get('base') == head:
        bad.append('这张工单一个提交都没有（AI 说「做完了」不算数，Y6）')
    acc = confirm_of(eng, f, t.scope, 'T11') or last(eng, f, t.scope, ('T11',), 'confirm') or {}
    exempt = acc.get('images', {})
    ok, line, rep = check_scope(str(g.gitdir), str(p.root / t.wt), ai['base'], ['**'], p.protected_patterns(), ai['snapshot'])
    if not ok:
        left = [b for b in rep['bad'] if not (b['path'] in exempt and g.blob_of('HEAD', b['path']) == exempt[b['path']])]
        if left:
            bad.append('越界：' + '；'.join(f'{b["path"]}（{b["why"]}）' for b in left[:6]))
    ok, line, _ = check_confirmed(str(p.gitdir), frozen_commit(eng, f), head, f.fdir, 'impl')
    if not ok:
        bad.append(line)
    if bad:
        return R(False, '；'.join(bad))
    push(eng, t.branch)        # 工单的实现 T4 通过后就推送（4.7）
    return R(True, payload={'head': head})


def t_open_pr(eng, f, t, step, attempt, pos):
    p = eng.p
    n = ticket_pr(eng, f, t)
    if not n:
        found = gh_json(eng, 'pr', 'list', '--state', 'open', '--head', t.branch, '--json', 'number')
        if found:
            n = found[0]['number']
        else:
            p.wt('pr', '--base', f.branch, '--title', f'feat: 工单 {t.id}', cwd=p.root / t.wt)
            n = gh_json(eng, 'pr', 'list', '--state', 'open', '--head', t.branch, '--json', 'number')[0]['number']
    else:
        push(eng, t.branch)
    if pr_view(eng, n)['mergeable'] == 'CONFLICTING':
        return R(False, '工单 PR 和功能分支有冲突', route='T14', payload={'pr': n})
    return R(True, payload={'pr': n})


def t_accept(eng, f, t, step, attempt, pos):
    """T11 逐张验收：每一处界面变化把旧图、新图、差别并排给小白看；通过时更新视觉基准并提交。放行等合进功能分支之后才写（6.4，v0.9）。"""
    p = eng.p
    gate = last(eng, f, t.scope, ('T5',)) or {}
    ui = gate.get('ui', {})
    show = [f'验收卡：{f.fdir}/cards/{t.plan_id}.md'] + [f'界面变化：{k}（旧图、新图、差别并排看）' for k in ui]
    ans = eng.human.ask(t.scope, 'T11', f'请照验收卡验收工单 {t.id}。', {'show': show, 'choices': ['通过', '不通过']})
    if not human_yes(ans):
        return R(False, '小白验收不通过：' + ans.get('note', ''))
    if ui:
        for path, x in ui.items():
            shutil.copy(x['file'], p.root / t.wt / path)
        commit_all(eng, t.wt, t.branch, f'chore: 工单 {t.id} 验收通过，更新视觉基准')
    return R(True, confirm=True, payload={'commit': p.wgit(t.wt)('rev-parse', 'HEAD'), 'images': {k: v['blob'] for k, v in ui.items()}})


def t_wait_checks(eng, f, t, step, attempt, pos):
    st, line, head = wait_checks(eng, ticket_pr(eng, f, t), NAMES, False)
    if st == 'ok':
        return R(True, payload={'head': head})
    if st == 'conflict':
        return R(False, '工单 PR 和功能分支有冲突（GitHub 在有冲突的 PR 上不跑项目检查）', route='T14')
    return R(False, line)


def t_merge(eng, f, t, step, attempt, pos):
    """T13 合并工单 PR；这张工单在 T11 更新过基准的，合并后核对功能分支上的就是验收时那几张图，再写放行，再让功能 PR 的守门检查重跑。"""
    p = eng.p
    n = ticket_pr(eng, f, t)
    pv = pr_view(eng, n)
    if pv['state'] == 'OPEN':
        if pv['mergeable'] == 'CONFLICTING':
            return R(False, '合并时和功能分支有冲突', route='T14')
        r = p.gh('pr', 'merge', str(n), '--squash', check=False)
        if r.returncode:
            if 'merge' in r.stderr and ('cleanly' in r.stderr or 'conflict' in r.stderr):
                return R(False, '合并时和功能分支有冲突', route='T14')
            return R(False, f'合并失败：{r.stderr.strip()[-300:]}', hold=True)
    elif pv['state'] != 'MERGED':
        return R(False, f'工单 PR 的状态是 {pv["state"]}', hold=True)
    ff_feature(eng, f)
    acc = confirm_of(eng, f, t.scope, 'T11') or {}
    images = acc.get('images', {})
    rel = []
    for path, blob in images.items():
        now = p.git.blob_of(f'refs/remotes/origin/{f.branch}', path)
        if now != blob:
            return R(False, f'合进功能分支后，{path} 不是验收时小白看过的那一张，不写放行，已停下', hold=True)
        rel.append(J.release(f.branch, path, blob, 'T11', ticket=t.id))
    if rel:
        p.journal.append(*rel)
        fpr = feature_pr(eng, f)
        if fpr:
            head = pr_view(eng, fpr)['headRefOid']
            guards = [r for r in check_runs(eng, head) if r['name'] == NAMES['guard']]
            if guards:
                rerun(eng, max(guards, key=lambda r: r['started_at'])['id'])
    return R(True, payload={'released': list(images)})


def t_cleanup(eng, f, t, step, attempt, pos):
    p = eng.p
    if (p.root / t.wt).is_dir():
        p.wt('done', t.branch)
    ports.release(p.name, t.wt)
    return R(True)


def drop_ticket(eng, f, t, why):
    """放弃一张工单：关掉它的 PR，删掉目录和分支，记一条放弃事件。它从来没合进功能分支，也就从来没有留下放行（6.4）。"""
    p = eng.p
    n = ticket_pr(eng, f, t)
    if n and pr_view(eng, n)['state'] == 'OPEN':
        p.gh('pr', 'close', str(n), '--delete-branch')
    if (p.root / t.wt).is_dir():
        p.wt('rm', t.branch)
    ports.release(p.name, t.wt)
    p.journal.append(J.event(t.scope, None, 'drop', reason=why))


def handle_decision(eng, f, t, pos):
    """T8 之后由功能这一级处理（7.5）：拆工单、改规格的技术部分 → 由执行角色改规划，重走 F7、F8、F9；建议放弃 → 用业务语言问小白。"""
    from .engine import Stop
    d = last(eng, f, t.scope, ('T8',)) or {}
    decision, text = d.get('decision', 'tech'), d.get('decision_text', '')
    if decision == 'abandon':
        if not eng.human.can(t.scope, 'T8'):
            eng.waiting.append((t.scope, 'T8', '技术决策建议放弃这条行为：去掉，还是换个做法'))
            raise Stop
        ans = eng.human.ask(t.scope, 'T8', f'工单 {t.id} 做不下去，技术决策建议放弃这条行为：{text}\n去掉它，还是换个做法？',
                            {'choices': ['去掉', '换个做法']})
        if ans.get('answer') == '去掉':
            drop_ticket(eng, f, t, '小白决定去掉这条行为')
            return
    drop_ticket(eng, f, t, f'技术决策：{decision}，重新规划后重做')
    eng.p.journal.append(J.event(f.scope, 'F14', 'failed', reason=f'工单 {t.id} 的技术决策（{decision}）：{text}', route='F9fix'))


HANDLERS = {
    'feature.open': f_open, 'feature.plan_check': f_plan_check, 'feature.freeze_plan': f_freeze, 'feature.open_pr': f_open_pr,
    'feature.implement': f_implement, 'feature.fix_ticket': f_fix_ticket, 'feature.ready': f_ready,
    'feature.wait_checks': f_wait_checks, 'feature.merge': f_merge, 'feature.cleanup': f_cleanup, 'feature.metrics': f_metrics,
    'confirm.prototype': h_prototype, 'confirm.plan': h_plan, 'confirm.impl_mode': h_impl_mode, 'accept.feature': h_accept_feature,
    'ticket.open': t_open, 'ticket.taskpack': t_taskpack, 'ticket.verify': t_verify, 'ticket.open_pr': t_open_pr,
    'accept.ticket': t_accept, 'ticket.wait_checks': t_wait_checks, 'ticket.merge': t_merge, 'ticket.cleanup': t_cleanup,
}
