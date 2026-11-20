"""sop project new 的 GitHub 那一半（设计书 7.2 的 I2、I5、I6、I7；3-24）。本机那一半（I0、I1、I3、I4）在 kernel/projectnew.py。

- I2 建仓库和目录：GitHub 账号名用 gh 登录的那个（`gh api user`），仓库是 <账号名>/<项目名>，地址默认
  git@github.com:<账号名>/<项目名>.git（SOP_GITHUB_URL_PREFIX 换前缀，自测指到假的 GitHub）。先查 GitHub 上还没有同名仓库；
  经接入层 wtx.init 调 `wt init --create`（带 WT_TEMPLATE，wt 同时设好只允许压成一次提交的合并、合并后删分支）。
  出口检查：在项目根跑 `wt doctor`，没有失败项。
- I5 首次推送到主线：特权侧自己的 Git 把本机 main（GitHub 的 README 提交加 I3、I4 的那一个）推上去，不强制；
  核对远程 main 和本地一致。这是唯一一次直接推主线。
- I6 建日志分支、开保护：建 sop/journal；公开仓库开 main 的保护（必须通过 fast、full、guard 三个检查，对管理员同样生效，
  走 PR、不许强制推送和删除，S4 的设法）和 sop/journal 的保护（禁止改写和删除、对管理员生效，S4 第 7 项），
  设事件规则只放开守门检查那个文件的 pull_request_target（W40 的请求格式）；设完读回来核对。
  私有仓库的免费计划开不了保护，在日志里记一条说明。
- I7 验证检查：从主线拉四条试验分支（特权侧直接造提交、推送，不检出、不运行任何东西），各开一个 PR，等检查跑完：
  故意出错的（.gitignore 去掉 .env）项目检查不通过；改了检查定义的守门检查不通过；改了受保护路径并且先写了放行事件的守门检查通过；
  正常的三个检查（快档、全档、守门）都通过。四个都关掉、删分支，不合并。试验分支的名字登记进日志（归属名不重复用，6.4）。

断了重跑：进度记在 ~/tools/sop/state/<项目名>/init/progress.json（done 里是做完的步骤），再执行 sop project new <项目名>
就从断的那一步接着做（kernel/projectnew.py 的 new_project）。每一步都能重做：推送不强制、日志分支已有就不建、
保护和事件规则先查再设、上次留下的试验 PR 先关掉。
"""
import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import time

from . import journal as J, paths, precheck, wtx
from .errors import SopError
from .gitx import Git, clean_env

URL_PREFIX = 'git@github.com:'
GUARD_WORKFLOW = '.github/workflows/sop-guard.yml'
REQUIRED_CHECKS = ('fast', 'full', 'guard')
POLICY_NAME = 'sop-guard-allow-pull_request_target'
TRIAL_PREFIX = 'sop-init/'
LABEL = {'fast': '项目检查（快档）', 'full': '项目检查（全档）', 'guard': '守门检查'}
SAID = {'success': '通过', 'failure': '不通过', 'skipped': '被跳过', 'cancelled': '被取消', 'timed_out': '超时', None: '没跑完'}

# 分支保护（S4 第 4 项、第 7 项的设法；6.4 要求必须通过的检查按名字列出、对管理员同样生效）
MAIN_PROTECTION = {
    'required_status_checks': {'strict': False, 'contexts': list(REQUIRED_CHECKS)},
    'enforce_admins': True,
    'required_pull_request_reviews': {'required_approving_review_count': 0},   # 只有一个账号，批准人数只能是 0（S4）
    'restrictions': None,
    'allow_force_pushes': False,
    'allow_deletions': False,
}
JOURNAL_PROTECTION = {
    'required_status_checks': None,          # 日志分支不要求检查、不要求走 PR，正常追加事件不受影响（S4 第 7 项）
    'enforce_admins': True,
    'required_pull_request_reviews': None,
    'restrictions': None,
    'allow_force_pushes': False,
    'allow_deletions': False,
}
# 事件规则（W40 第一部分在试验仓库上设成功的格式；include、exclude 两个都要写）
GUARD_POLICY = {
    'name': POLICY_NAME,
    'enforcement': 'active',
    'conditions': {'workflow_path': {'include': [GUARD_WORKFLOW], 'exclude': []}},
    'rules': [{'type': 'restrict_action_events', 'parameters': {'allowed_events': ['pull_request_target']}}],
}


# ---------- 进度（断了重跑用） ----------
def progress_file(name):
    return paths.state_dir(name) / 'init' / 'progress.json'


def load_progress(name):
    f = progress_file(name)
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def save_progress(name, **changes):
    f = progress_file(name)
    f.parent.mkdir(parents=True, exist_ok=True)
    d = {**(load_progress(name) or {'done': []}), **changes}
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, f)
    return d


def mark_done(name, step, **info):
    d = load_progress(name) or {'done': []}
    done = d['done'] + ([step] if step not in d['done'] else [])
    return save_progress(name, done=done, **info)


def is_done(name, step):
    return step in ((load_progress(name) or {}).get('done') or [])


def test_break(where):
    """自测用：SOP_TEST_BREAK 等于 where 时，在这里像被强制结束那样立刻退出（演断了重跑）。"""
    if os.environ.get('SOP_TEST_BREAK') == where:
        print(f'（测试）在 {where} 断了', flush=True)
        os._exit(137)


def _now():
    return datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------- gh ----------
def gh(*args, slug=None, input=None, check=True, what=None):
    """项目根还没有的时候调 gh（I2 之前）。有项目根之后用 Project.gh（先做特权侧用之前核对）。"""
    env = clean_env({'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1'})
    env.pop('GH_REPO', None)
    if slug:
        env['GH_REPO'] = slug
    p = subprocess.run(['gh', *args], env=env, capture_output=True, text=True, input=input,
                       stdin=subprocess.DEVNULL if input is None else None)
    if check and p.returncode:
        raise SopError(f'{what or "gh " + " ".join(args[:2])}失败：{(p.stderr or p.stdout).strip()[-500:]}')
    return p


def url_for(slug):
    return (os.environ.get('SOP_GITHUB_URL_PREFIX') or URL_PREFIX) + slug + '.git'


def _policies(obj):
    """读回来的事件规则列表。接口回的样子没核实过（W40 只看到建成了），列表或包着列表的对象都认。"""
    if isinstance(obj, list):
        return obj
    for v in (obj or {}).values():
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return v
    return []


def _contexts(prot):
    rsc = prot.get('required_status_checks') or {}
    return sorted(set(rsc.get('contexts') or []) | {c.get('context') for c in rsc.get('checks') or [] if c.get('context')})


def _enabled(prot, key):
    v = prot.get(key)
    return v.get('enabled') if isinstance(v, dict) else v


# ---------- I7 的四个试验 PR ----------
def _drop_env_line(data):
    lines = data.decode('utf-8').splitlines(keepends=True)
    return ''.join(l for l in lines if l.strip() not in ('.env', '/.env')).encode('utf-8')


def _append(text):
    return lambda data: data + ('' if data.endswith(b'\n') or not data else '\n').encode() + text.encode('utf-8')


TRIALS = (
    {'kind': 'broken', 'name': '故意出错', 'path': '.gitignore', 'edit': _drop_env_line, 'release': False,
     'expect': {'fast': 'failure'},
     'body': '.gitignore 里去掉了 .env。项目检查（目录结构检查）应该不通过。'},
    {'kind': 'checkdef', 'name': '改了检查定义', 'path': '.github/workflows/sop-check.yml', 'release': False,
     'edit': _append('# 初始化试验：改了检查定义（这个 PR 不会合并）\n'), 'expect': {'guard': 'failure'},
     'body': '改了项目检查的定义（检查流程文件），没有放行。守门检查应该不通过。'},
    {'kind': 'released', 'name': '改了受保护路径并且带着放行', 'path': 'docs/standards/README.md', 'release': True,
     'edit': _append('\n（初始化试验：改了受保护的文件，先写了放行事件；这个 PR 不会合并）\n'), 'expect': {'guard': 'success'},
     'body': '改了受保护的 docs/standards/README.md，推送之前在日志分支上写了放行事件。守门检查应该通过。'},
    {'kind': 'normal', 'name': '正常', 'path': 'README.md', 'release': False,
     'edit': _append('\n（初始化试验：正常的改动；这个 PR 不会合并）\n'),
     'expect': {'fast': 'success', 'full': 'success', 'guard': 'success'},
     'body': '只改了 README.md。快档、全档、守门三个检查都应该通过（还没有技术栈档案，门禁暂不适用）。'},
)


class GitHub:
    """I2、I5、I6、I7。create 在 I3、I4 之前，publish 在之后（kernel/projectnew.py 的 new_project 依次调）。"""

    def __init__(self, poll=None, deadline=None):
        self.poll = float(os.environ.get('SOP_POLL_SECONDS', '15')) if poll is None else poll
        self.deadline = int(os.environ.get('SOP_CHECK_DEADLINE', '1800')) if deadline is None else deadline

    # ---------- I2 ----------
    def login(self):
        p = gh('api', 'user', '--jq', '.login', check=False)
        who = p.stdout.strip()
        if p.returncode or not who:
            raise SopError('查不到这台电脑上 gh 登录的 GitHub 账号（先做机器准备里登录 GitHub 那一步：sop machine setup）。'
                           f'还没有建任何仓库。gh 说：{(p.stderr or p.stdout).strip()[-300:]}')
        return who

    def repo_exists(self, slug):
        return gh('repo', 'view', slug, '--json', 'name', check=False).returncode == 0

    def create(self, name, root, visibility):
        prog = load_progress(name) or {}
        slug, url = prog.get('slug'), prog.get('url')
        if not slug:
            slug = f'{self.login()}/{name}'
            url = url_for(slug)
            if self.repo_exists(slug):
                raise SopError(f'你的 GitHub 账号下已经有一个叫 {name} 的仓库（{slug}）。换一个项目名再执行；'
                               '这次什么都没建。')
            save_progress(name, slug=slug, url=url)       # 先记下来：建到一半断了，重跑时认得出是自己建的
            create = True
        else:
            create = not self.repo_exists(slug)          # 重跑：上次可能仓库建好了、本机目录还没建
        root = pathlib.Path(root)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise SopError(f'项目目录 {root} 上次建到一半就断了。把它挪走（GitHub 上的仓库不用动）后重新执行 '
                           f'sop project new {name}，会接着做。')
        print(f'在 GitHub 上建仓库 {slug}（{"公开" if visibility == "public" else "私有"}），并建本机的项目目录……'
              if create else f'GitHub 上的仓库 {slug} 上次已经建好，接着建本机的项目目录……')
        wtx.init(name, root, slug, url, create=create, public=visibility == 'public', settings=not create)
        self.doctor(name, root)
        save_progress(name, i2_time=_now())

    def doctor(self, name, root):
        """I2 的出口检查：在项目根跑 wt doctor，wt 报失败（✖）的一项都没有才算过（提醒照列，不算不过）。"""
        from machine.wtsetup import parse
        p = wtx.call(name, root, 'doctor', check=False)
        out = (p.stdout + p.stderr).strip()
        fails, warns = parse(out)
        if p.returncode or fails or '── 项目' not in out:
            raise SopError('建好的项目目录没通过 wt doctor：' + ('；'.join(fails) or out[-400:]))
        for w in warns:
            print(f'  提醒（wt doctor）：{w}')

    # ---------- I5 到 I7 ----------
    def publish(self, root, visibility):
        from .project import Project
        p = Project(root)
        try:
            if not is_done(p.name, 'I5'):
                self.push_main(p)
                mark_done(p.name, 'I5')
                test_break('after-I5')
            if not is_done(p.name, 'I6'):
                self.protect(p, visibility)
                mark_done(p.name, 'I6')
            if not is_done(p.name, 'I7'):
                self.trials(p)
                mark_done(p.name, 'I7')
        finally:
            p.journal.close()

    def _verify(self, p):
        precheck.verify(p.name, p.root, p.worktrees())

    def push_main(self, p):
        """I5：唯一一次直接推主线（仓库刚建好，保护还没开）。不强制：远程不是本机 main 的祖先就推不上去。"""
        url = p.git('remote', 'get-url', 'origin')
        local = p.git.rev('refs/heads/main')
        if not local:
            raise SopError('本机没有 main 分支，推不了')
        self._verify(p)
        remote = p.git('ls-remote', url, 'refs/heads/main').split('\t')[0] or None
        if remote != local:
            print('把初始内容推送到 GitHub 的主线（这是唯一一次直接推主线）……')
            r = p.git.run('push', '-q', url, 'refs/heads/main:refs/heads/main', check=False)
            if r.returncode:
                raise SopError(f'推送主线失败（没有强制推送）：{r.stderr.strip()[-400:]}')
        p.fetch('main')
        if p.git.rev('refs/remotes/origin/main') != local:
            raise SopError('推送之后 GitHub 上的主线和本机的不一样，停下')
        p.journal.init_branch()        # 日志要用（I6 的第一件事），先建好，I5 的记录才写得进去
        p.journal.append(J.event('project', 'I5', 'note', kind='项目初始化', text='初始内容推上了主线', commit=local))

    def protect(self, p, visibility):
        """I6：建日志分支（已有就不动）；公开仓库开两条分支的保护、设事件规则，再读回来核对。"""
        p.journal.init_branch()
        slug = p.slug()
        if visibility != 'public':
            text = ('私有仓库：GitHub 免费计划开不了分支保护，没有开（主线、日志分支都没有保护；'
                    '没通过检查的 PR 靠工具包自己查，合并由你在网页上点，日志分支靠本机隔离和事后核对，7.2 的 I1 那张表）')
            p.journal.append(J.event('project', 'I6', 'note', kind='项目初始化', text=text))
            print('日志分支已建。' + text)
            return
        print('开分支保护（主线、日志分支），设事件规则（只放开守门检查）……')
        for branch, body in (('main', MAIN_PROTECTION), (J.BRANCH, JOURNAL_PROTECTION)):
            p.gh('api', '-X', 'PUT', f'repos/{slug}/branches/{branch}/protection', '--input', '-', input=json.dumps(body))
        skip_policy = os.environ.get('SOP_TEST_SKIP_POLICY') == '1'      # 自测用：反着试「没设事件规则」
        have = [x for x in _policies(p.gh('api', f'repos/{slug}/actions/policies', as_json=True)) if x.get('name') == POLICY_NAME]
        if not have and not skip_policy:
            p.gh('api', '-X', 'POST', f'repos/{slug}/actions/policies', '--input', '-', input=json.dumps(GUARD_POLICY))
        problems = self.check_protection(p, slug, skip_policy)
        if problems:
            raise SopError('分支保护或事件规则读回来不对：' + '；'.join(problems))
        p.journal.append(J.event('project', 'I6', 'note', kind='项目初始化',
                                 text='开了 main 和 sop/journal 的分支保护，设了只放开守门检查的事件规则',
                                 required=list(REQUIRED_CHECKS), policy=POLICY_NAME))

    def check_protection(self, p, slug, skip_policy=False):
        bad = []
        m = p.gh('api', f'repos/{slug}/branches/main/protection', as_json=True) or {}
        if _contexts(m) != sorted(REQUIRED_CHECKS):
            bad.append(f'主线必须通过的检查是 {_contexts(m)}，应该是 {list(REQUIRED_CHECKS)}')
        if _enabled(m, 'enforce_admins') is not True:
            bad.append('主线的保护对管理员没有生效')
        for k in ('allow_force_pushes', 'allow_deletions'):
            if _enabled(m, k) is not False:
                bad.append(f'主线的 {k} 没有关')
        j = p.gh('api', f'repos/{slug}/branches/{J.BRANCH}/protection', as_json=True) or {}
        for k, want in (('enforce_admins', True), ('allow_force_pushes', False), ('allow_deletions', False)):
            if _enabled(j, k) is not want:
                bad.append(f'日志分支的 {k} 不是 {want}')
        pol = [x for x in _policies(p.gh('api', f'repos/{slug}/actions/policies', as_json=True)) if x.get('name') == POLICY_NAME]
        if skip_policy:
            pass
        elif len(pol) != 1:
            bad.append(f'事件规则 {POLICY_NAME} 有 {len(pol)} 条')
        else:
            x = pol[0]
            wp = (x.get('conditions') or {}).get('workflow_path') or {}
            events = [e for r in x.get('rules') or [] if r.get('type') == 'restrict_action_events'
                      for e in (r.get('parameters') or {}).get('allowed_events') or []]
            if x.get('enforcement') != 'active' or wp.get('include') != [GUARD_WORKFLOW] or wp.get('exclude') or \
                    events != ['pull_request_target']:
                bad.append(f'事件规则的内容不对：{json.dumps(x, ensure_ascii=False)[:300]}')
        return bad

    # ---------- I7 ----------
    def _commit(self, p, base, path, edit, message):
        """在主线上改一个文件，造一个提交（不检出、不运行任何东西）。返回 (提交, 新内容的指纹)。"""
        g = p.git
        mode = g('ls-tree', base, '--', path).split()[0]
        new = edit(g.run('show', f'{base}:{path}', binary=True).stdout)
        blob = g.run('hash-object', '-w', '--stdin', input=new, binary=True).stdout.decode().strip()
        with tempfile.TemporaryDirectory(prefix='sop-i7-') as td:
            ix = {'GIT_INDEX_FILE': os.path.join(td, 'index')}
            g('read-tree', base, env=ix)
            g('update-index', '--cacheinfo', f'{mode},{blob},{path}', env=ix)
            tree = g('write-tree', env=ix)
        return g('commit-tree', tree, '-p', base, '-m', message), blob

    def _cleanup(self, p, url):
        """上次断在 I7 中间留下的试验 PR 和分支：关掉、删掉。"""
        for x in p.gh('pr', 'list', '--state', 'open', '--json', 'number,headRefName', as_json=True) or []:
            if x['headRefName'].startswith(TRIAL_PREFIX):
                p.gh('pr', 'close', str(x['number']))
        for line in p.git('ls-remote', url, f'refs/heads/{TRIAL_PREFIX}*').splitlines():
            self._verify(p)
            p.git('push', '-q', url, '--delete', line.split('\t')[1])

    def _register(self, p, kind, extra=()):
        """试验分支的名字登记进日志（归属名一律不重复用，6.4）；重跑时用下一个序号。"""
        for n in range(1, 1000):
            branch = f'{TRIAL_PREFIX}{kind}-{n}'
            try:
                p.journal.append(J.register_name(branch, kind='初始化试验'), *[f(branch) for f in extra])
                return branch
            except J.NameTaken:
                continue
        raise SopError('试验分支的名字用完了')

    def trials(self, p):
        slug, url = p.slug(), p.git('remote', 'get-url', 'origin')
        self._cleanup(p, url)
        p.fetch('main')
        base = p.git.rev('refs/remotes/origin/main')
        print('开四个试验 PR，看 GitHub 上的检查拦不拦得住（验完都关掉，不合并）……')
        prs = {}
        for t in TRIALS:
            commit, blob = self._commit(p, base, t['path'], t['edit'], f'初始化试验：{t["name"]}')
            extra = [lambda b, t=t, blob=blob: J.release(b, t['path'], blob, '初始化试验', note='I7')] if t['release'] else []
            branch = self._register(p, t['kind'], extra)          # 放行事件先写，再推送带着那份改动的提交（6.4 的先后）
            self._verify(p)
            p.git('push', '-q', url, f'{commit}:refs/heads/{branch}')
            out = p.gh('pr', 'create', '--base', 'main', '--head', branch, '--title', f'初始化试验：{t["name"]}',
                       '--body', t['body'] + '\n\n这是 sop project new 的 I7 自动开的试验 PR，验完就关掉，不会合并。').stdout.strip()
            prs[t['kind']] = {'number': int(out.rstrip('/').rsplit('/', 1)[-1]), 'branch': branch, 'sha': commit}
        test_break('mid-I7')
        results, timeout = self.wait(p, slug, prs)
        bad = []
        for t in TRIALS:
            got = results[t['kind']]
            for k, want in t['expect'].items():
                if got.get(k) != want:
                    bad.append(f'「{t["name"]}」那个：{LABEL[k]}应该{SAID[want]}，实际{SAID.get(got.get(k), got.get(k))}')
        for t in TRIALS:                                            # 验完四个都关掉、删分支，不合并
            p.gh('pr', 'close', str(prs[t['kind']]['number']))
        self._cleanup(p, url)
        rec = {t['kind']: {**prs[t['kind']], 'name': t['name'], 'expect': t['expect'], 'got': results[t['kind']]} for t in TRIALS}
        (paths.state_dir(p.name) / 'init' / 'i7.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        p.journal.append(J.event('project', 'I7', 'note', kind='项目初始化', ok=not bad, trials=rec,
                                 text='四个试验 PR 的检查结果都对' if not bad else '试验 PR 的检查结果不对：' + '；'.join(bad)))
        for t in TRIALS:
            got = results[t['kind']]
            print(f'  试验 PR #{prs[t["kind"]]["number"]}「{t["name"]}」：' +
                  '，'.join(f'{LABEL[k]}{SAID.get(got.get(k), got.get(k))}' for k in REQUIRED_CHECKS))
        if timeout:
            bad.insert(0, f'等了 {self.deadline // 60} 分钟检查还没全跑完')
        if bad:
            raise SopError('GitHub 上的检查没有按预期拦住或放行（I7），项目还不能用：' + '；'.join(bad) +
                           '。四个试验 PR 已关掉。重新执行 sop project new 会再试一次 I7；还不对就启动维修窗口（sop repair）。')
        print('四个试验 PR 的检查结果都对，已关掉。')

    def wait(self, p, slug, prs):
        """等四个 PR 最新提交上的三个检查都跑完。返回 ({种类: {检查: 结论}}, 是否超时)。"""
        t0 = time.time()
        while True:
            results, pending = {}, False
            for kind, pr in prs.items():
                runs = p.gh('api', f'repos/{slug}/commits/{pr["sha"]}/check-runs', as_json=True)['check_runs']
                got = {}
                for name in REQUIRED_CHECKS:
                    rs = [r for r in runs if r['name'] == name and r['head_sha'] == pr['sha']]
                    r = max(rs, key=lambda r: (r.get('started_at') or '', r.get('id') or 0)) if rs else None
                    got[name] = r['conclusion'] if r and r['status'] == 'completed' else None
                    pending |= got[name] is None
                results[kind] = got
            if not pending:
                return results, False
            if time.time() - t0 > self.deadline:
                return results, True
            time.sleep(self.poll)
