"""Claude Code 适配器（设计书 10.1、10.2）。3-27 做了能力声明、自检（probe）、自动调用（run_headless）；
3-28 做了对话方式（start_interactive）、续接（resume）和自检里的「打开对话窗口不出首次启动的那几屏」；
3-29 接进流程引擎（kernel/cli.adapter 按配置选），加了技能触发（任务包点名的技能写成 /<技能名> 放在最前面，从会话日志里认加载了没有）
和真实 AI 演练（drill.py，过了记下演练过的版本）。

怎么跑（都照第一段、第二段实测过的做法，不加别的花样）：
- 程序：用官方装法默认位置的那一份（~/.local/bin/claude，是个链接），按它指向的实际文件只读放进受限环境，版本号不写死在路径里（10.1）。
- 状态目录：每个会话从模板现建（6.3 三），挂在受限环境里主目录下的 .claude，CLAUDE_CONFIG_DIR 指过去；
  模板只有 .claude.json 里的 5 项设置（W28）。会话日志就在状态目录的 projects/ 下（<工作目录改写>/<会话编号>.jsonl）。
- 服务地址和密钥：先看 ~/tools/sop/config/ai/claude.env（M4 写的，问题 5），没有这份时用终端里的 ANTHROPIC_ 开头的环境变量
  （这台电脑上 Claude Code 就是这么配的）；作为环境变量给进受限环境，不写进任何文件、不打印。官方账号登录没验证过（W37）。
- 对话方式：不脱离终端（前提是内核禁用了往终端塞按键，6.3 三），`claude --dangerously-skip-permissions <开场内容>`；
  对话窗口不报 JSON：会话编号取这次写过的会话日志的文件名；花费取会话日志里 Claude Code 记的 cost-state（3-28 实测），
  没有再取状态目录 .claude.json 里的 lastCost（W28 在 2.1.327 上看到的；2.1.329 没记在工作目录名下）。
- 续接：--resume <会话编号>。Claude Code 续接后报的花费是整个会话的累计数，适配器在状态目录旁边记下每个会话的累计数，只报增量。
- 普通调用：任务包原文当普通的提问内容传进去；不加自定义系统提示词、不指定模型、不加钩子（这台电脑接的服务会报 400，10.2 第 7 条）；
  不逐条询问（--dangerously-skip-permissions，隔离完全靠受限环境，10.2 第 6 条）；--output-format json 拿退出状态、花费、会话编号。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time

from adapters.ai import ptyscreen
from adapters.ai.base import Adapter, Outcome, ProbeResult, drill_reminder, record_probe
from checks.quota_scan.check import run as quota_scan
from kernel import paths
from kernel.errors import SopError
from machine import locate
from runner import placement, sandbox

NAME = 'claude'
LABEL = 'Claude Code'
STATE_HOME = '.claude'
PROBE_PROMPT = '请只回复两个字：收到'
# 自动调用要用到的参数，自检时在 `claude --help` 里逐个找（能力声明与实际一致，10.1）
NEEDED_FLAGS = {
    '--print': '自动调用',
    '--output-format': '机器可读的结果（退出状态、花费、会话编号）',
    '--resume': '续接会话',
    '--max-budget-usd': '费用限定',
    '--dangerously-skip-permissions': '不逐条询问（受限环境里都这样跑，10.2 第 6 条）',
}
# 绝不加的参数（10.2 第 7 条：这台电脑接的服务会拒；W35：钩子会往会话里添话）
FORBIDDEN_FLAGS = ('--system-prompt', '--system-prompt-file', '--append-system-prompt', '--append-system-prompt-file',
                   '--model', '--fallback-model', '--settings', '--agents')
# config/ai/claude.env 里认这两种开头的名字；终端里只认 ANTHROPIC_ 开头的（CLAUDE_CODE_ 开头的是当前这个会话自己的，不能带进去）
FILE_PREFIXES = ('ANTHROPIC_', 'CLAUDE_CODE_')
ENV_PREFIXES = ('ANTHROPIC_',)
RESERVED = {'CLAUDE_CONFIG_DIR'}
ENV_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')
OUTPUT_FILE = 'sop-claude-output.txt'   # 每次调用的原始输出（去掉密钥），放在状态目录里，给额度报错的扫描和复盘
SKILL_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
# Claude Code 加载一个技能时，往会话日志里写一条用户消息，开头是这一句，后面是技能目录（W34 在 2.1.32x 上看到的；3-29 在 2.1.329 上再看）
SKILL_LOADED_HEAD = 'Base directory for this skill:'

# 能力声明（10.1 列的各项）。依据写在 10.2 的表里：「实测」的都真的调用过。
DECLARATION = {
    'interactive': True,                  # 能交互启动（W28 实测；3-28 适配器实测）
    'headless': True,                     # 能自动调用：claude -p（实测）
    'resume': True,                       # 能续接：--resume <会话编号>（实测；3-28 适配器实测）
    'skill_syntax': '/{skill}',           # 技能调用的写法（实测）
    'skill_headless': True,               # 自动调用下能触发技能（S1 实测；3-29 在 2.1.330 上经适配器实测，对话方式的开场也能）
    'subagents': True,
    'restrictions': ['--allowedTools', '--permission-mode'],   # 自带的限制手段：受限环境里不用（10.2 第 6 条）
    'budget_flag': True,                  # 能限定费用：--max-budget-usd（只在自动调用时有效）
    'rules_file': 'CLAUDE.md',
    'skills_dir': '.claude/skills',
    'session_logs': '<状态目录>/projects/<工作目录改写>/<会话编号>.jsonl',
    'skills_runnable': 'all',             # 支持子代理，各技能都能完整运行（没有逐个技能核对过）
}


def _default_location():
    row = next(r for r in locate.AI_TOOLS if r[0] == NAME)
    a = locate.find_ai_tools(table=(row,), version=lambda exe: (None, ''))[0]
    return a.path, a.real


def parse_env_file(path):
    """读 config/ai/claude.env：每行「名字=值」（可带 export、引号、# 注释）。只留 FILE_PREFIXES 开头的名字。"""
    out = {}
    for line in pathlib.Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = ENV_LINE.match(line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        if k.startswith(FILE_PREFIXES) and k not in RESERVED:
            out[k] = v
    return out


def parse_output(stdout):
    """--output-format json 的输出：一个对象，有的版本是一串事件（取最后一个 type 是 result 的）。读不出来是 None。"""
    try:
        j = json.loads(stdout)
    except ValueError:
        j = None
        for line in reversed(stdout.strip().splitlines()):   # 万一前面混了别的输出，从后往前找一行 JSON
            try:
                j = json.loads(line)
                break
            except ValueError:
                continue
    if isinstance(j, list):
        j = next((x for x in reversed(j) if isinstance(x, dict) and x.get('type') == 'result'), None)
    return j if isinstance(j, dict) else None


class ClaudeAdapter(Adapter):
    name = NAME
    caps = {k: DECLARATION[k] for k in ('interactive', 'headless', 'resume', 'subagents', 'budget_flag')}
    declaration = DECLARATION
    state_home = STATE_HOME

    def __init__(self, exe=None, version=None, environ=None):
        """exe：程序的位置（不给就按官方装法的默认位置找）；version：不给就跑一次 --version 查；
        environ：找密钥时代替 os.environ（测试用）。"""
        self._exe = exe
        self._version = version
        self._environ = environ

    # ---------- 程序、版本、密钥 ----------
    def location(self):
        """(找到的位置, 实际文件)。没找到是 ('', '')。"""
        if self._exe:
            return str(self._exe), os.path.realpath(self._exe)
        return _default_location()

    @property
    def real(self):
        path, real = self.location()
        if not path:
            raise SopError('没找到 Claude Code（官方装法的默认位置是 ~/.local/bin/claude）')
        return real

    def version(self):
        if self._version is None:
            path, _ = self.location()
            self._version = (locate.tool_version(path)[0] or '') if path else ''
        return self._version

    def credentials(self):
        """(给进受限环境的环境变量, 从哪来)。都没有是 ({}, '')。"""
        f = paths.config_dir() / 'ai' / f'{NAME}.env'
        if f.exists():
            if os.stat(f).st_mode & 0o077:
                raise SopError(f'{f} 别人也能读（里面有密钥），先执行 chmod 600 {f}')
            return parse_env_file(f), str(f)
        env = os.environ if self._environ is None else self._environ
        got = {k: v for k, v in env.items() if k.startswith(ENV_PREFIXES) and k not in RESERVED}
        return got, ('环境变量' if got else '')

    def check_caps(self):
        """能力声明与实际一致（10.1）：自动调用要用的参数在 --help 里都找得到。返回缺的那几个 [(参数, 用来做什么)]。"""
        path, _ = self.location()
        rc, out, err = locate.quiet_run(path, '--help')
        text = out + err
        return [(f, why) for f, why in NEEDED_FLAGS.items() if f not in text]

    # ---------- 受限环境里放什么 ----------
    def template(self, state_dir, workdir):
        """W28 的 5 项设置：引导做过、这一版的引导做过、不自动升级、「不逐条询问」的警告已接受、这个工作目录已信任。"""
        d = {'hasCompletedOnboarding': True, 'lastOnboardingVersion': self.version(), 'autoUpdates': False,
             'bypassPermissionsModeAccepted': True, 'projects': {str(workdir): {'hasTrustDialogAccepted': True}}}
        f = pathlib.Path(state_dir) / '.claude.json'
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as fh:
            fh.write(json.dumps(d, ensure_ascii=False, indent=1))

    def sandbox_extras(self):
        env, _ = self.credentials()
        home = pathlib.Path(os.environ.get('HOME', '/root'))
        return [self.real], {**env, 'CLAUDE_CONFIG_DIR': str(home / STATE_HOME)}, ()

    def _prepare(self, ctx, state_dir):
        ro, env, _ = self.sandbox_extras()
        ctx.ro = list(ctx.ro) + [p for p in ro if p not in ctx.ro]
        ctx.env = {**ctx.env, **env}
        ctx.home_binds = {**ctx.home_binds, STATE_HOME: state_dir}
        return [v for k, v in env.items() if k != 'CLAUDE_CONFIG_DIR' and len(v) >= 8]

    def command(self, prompt, budget=None, session=None):
        a = [self.real, '-p', prompt, '--output-format', 'json', '--dangerously-skip-permissions']
        if session:
            a += ['--resume', session]
        if budget:
            a += ['--max-budget-usd', f'{float(budget):g}']
        return a

    # ---------- 调用 ----------
    def _invoke(self, ctx, argv, state_dir, timeout):
        secrets = self._prepare(ctx, state_dir)
        timed_out = False
        try:
            p = sandbox.run(ctx, argv, timeout=timeout)
            rc, out, err = p.returncode, p.stdout or '', p.stderr or ''
        except subprocess.TimeoutExpired as e:    # 不把异常本身转成文字：里面有整条命令，命令里有密钥
            timed_out = True
            rc = -1
            out = e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
            err = e.stderr.decode(errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or '')

        def scrub(s):
            for v in secrets:
                s = s.replace(v, '***')
            return s
        out, err = scrub(out), scrub(err)
        sd = pathlib.Path(state_dir)
        try:
            (sd / OUTPUT_FILE).write_text(f'退出码 {rc}{"（超时）" if timed_out else ""}\n--- 输出 ---\n{out[-20000:]}\n'
                                          f'--- 报错 ---\n{err[-20000:]}\n', encoding='utf-8')
        except OSError:
            pass
        j = parse_output(out)
        logs = sorted(str(x) for x in (sd / 'projects').rglob('*.jsonl')) if (sd / 'projects').is_dir() else []
        if (sd / OUTPUT_FILE).exists():
            logs.append(str(sd / OUTPUT_FILE))
        if j is None:
            text = f'超过 {timeout} 秒没结束' if timed_out else (err.strip() or out.strip())[-1000:] or '（没有任何输出）'
            return Outcome(rc=rc if rc else 1, cost=0.0, session=None, logs=logs, text=text, timeout=timed_out,
                           cost_basis='没读到工具的报告')
        if j.get('is_error') and rc == 0:
            rc = 1      # 工具说出错了却退出码 0：按出错算（只看退出码不够，9.3）
        text = j.get('result') if isinstance(j.get('result'), str) else ''
        if j.get('is_error') and not text:
            text = f'Claude Code 报错：{j.get("subtype", "")}'
        return Outcome(rc=rc, cost=float(j.get('total_cost_usd') or 0.0), session=j.get('session_id'), logs=logs,
                       text=text, timeout=timed_out, cost_basis='工具报告')

    # ---------- 技能触发（3-29） ----------
    def skill_prompt(self, ctx, taskpack, prompt):
        """任务包点名了技能（task.json 的 skill）时，把 /<技能名> 放在提示词开头（S1：只允许人触发的技能在自动调用下这样能触发；
        对话窗口的开场内容、续接的第一句也一样）。工作目录里没有这个技能的副本（.claude/skills/<技能名>/SKILL.md）就不调用。
        返回 (提示词或 None, 技能名或 None, 不调用的原因或 None)。"""
        skill = _task_skill(taskpack)
        if not skill:
            return prompt, None, None
        if not SKILL_NAME.match(skill):
            return None, skill, f'任务包里的技能名 {skill!r} 不对（只能有小写字母、数字和「-」），没有调用 Claude Code'
        wd = pathlib.Path(ctx.chdir or (pathlib.Path(ctx.root) / ctx.worktree))
        if not (wd / DECLARATION['skills_dir'] / skill / 'SKILL.md').is_file():
            return None, skill, (f'任务包点名的技能 {skill} 在这个工作目录里没有副本（{DECLARATION["skills_dir"]}/{skill}/SKILL.md），'
                                 '没有调用 Claude Code。项目建好时会把技能装进主线（sop project new 的 I4），先查一下主线上的技能目录')
        return DECLARATION['skill_syntax'].format(skill=skill) + ' ' + prompt, skill, None

    def _with_skill(self, ctx, taskpack, prompt, state_dir, session, call):
        """点名了技能就加上写法、调用、再从会话日志里认这次有没有真的加载（Outcome.skill_loaded）。"""
        prompt, skill, problem = self.skill_prompt(ctx, taskpack, prompt)
        if problem:
            return Outcome(rc=1, text=problem, cost_basis='没有调用', skill_loaded=False)
        before = skill_loads(state_dir, session).count(skill) if skill and session else 0
        out = call(prompt)
        if skill and out.cost_basis != '没有调用':     # 没调用成（例如对话步骤不在终端里）的不算「技能没触发」
            out.skill_loaded = skill_loads(state_dir, out.session or session).count(skill) > before
        return out

    def _run_headless(self, run_ctx, taskpack, state_dir, timeout=None, budget=None):
        """在受限环境里自动执行任务包（9.1）：task.md 原文当普通提问传进去。结果文件由 AI 写到 /sop/out/result.json，
        由流程命令校验（9.2）；这里只返回退出状态、花费、会话编号、会话日志位置。"""
        tp = pathlib.Path(taskpack)
        body = (tp / 'task.md').read_text(encoding='utf-8')
        if budget is None:
            try:
                budget = json.loads((tp / 'task.json').read_text(encoding='utf-8')).get('budget_usd')
            except (OSError, ValueError):
                budget = None
        prompt = f'下面是这一步的任务包（原文也在 {placement.TASK_MNT}/task.md），照着做。\n\n{body}'
        return self._with_skill(run_ctx, taskpack, prompt, state_dir, None,
                                lambda pr: self._invoke(run_ctx, self.command(pr, budget), state_dir, timeout))

    # ---------- 对话方式、续接（3-28） ----------
    def interactive_command(self, prompt=None, session=None):
        """对话窗口：不加 -p；不逐条询问（受限环境里都这样，W28 的模板里已接受那一屏警告）；开场内容作为第一句话。"""
        a = [self.real, '--dangerously-skip-permissions']
        if session:
            a += ['--resume', session]
        if prompt:
            a.append(prompt)
        return a

    def _taskpack_prompt(self, taskpack, head='下面是这一步的任务包'):
        tp = pathlib.Path(taskpack) if taskpack else None
        if tp is None or not (tp / 'task.md').exists():
            return ''
        body = (tp / 'task.md').read_text(encoding='utf-8')
        return f'{head}（原文也在 {placement.TASK_MNT}/task.md），照着做。\n\n{body}'

    def _interactive(self, ctx, argv, state_dir, resumed=None):
        """在受限环境里不脱离终端地打开对话窗口（6.3 三），等小白退出。会话编号、花费从状态目录里取（对话窗口不报 JSON）。"""
        if not ctx.interactive or not os.isatty(0):
            return Outcome(rc=1, text='对话步骤要在终端里执行 sop 才能打开对话窗口（现在不在终端里）', cost_basis='没有调用')
        self._prepare(ctx, state_dir)
        cwd = str(ctx.chdir or (pathlib.Path(ctx.root) / ctx.worktree))
        prev = self._prev_total(state_dir, resumed, cwd) if resumed else 0.0
        t0 = time.time()
        try:
            rc = sandbox.run(ctx, argv, capture=False).returncode
        except KeyboardInterrupt:      # 小白在外面按了 Ctrl-C：对话窗口跟着结束，照常收尾
            rc = 130
        sd = pathlib.Path(state_dir)
        # 会话编号：这次写过的会话日志（文件名就是会话编号；续接时还是原来那个），没有再看 .claude.json
        session = _newest_session(sd, t0) or _project_entry(sd, cwd).get('lastSessionId') or resumed
        total, basis = _session_total(sd, session, cwd)
        cost = self._increment(state_dir, session, total, prev)
        if total is None:
            cost = 0.0
        elif resumed and prev is None:
            basis += '（续接前的累计数没记下，按累计数记）'
        logs = sorted(str(x) for x in (sd / 'projects').rglob('*.jsonl')) if (sd / 'projects').is_dir() else []
        return Outcome(rc=rc, cost=cost, session=session, logs=logs, text=_last_answer(sd, session), cost_basis=basis)

    def start_interactive(self, run_ctx, taskpack, state_dir):
        """10.1：在受限环境里启动交互会话，把任务包作为开场内容；不脱离终端；状态目录由模板现建（调用方建好传进来），
        模板里的 5 项设置让小白看不到首次启动的那几屏（W28）。"""
        prompt = self._taskpack_prompt(taskpack)
        if not prompt:
            return self._interactive(run_ctx, self.interactive_command(None), state_dir)
        return self._with_skill(run_ctx, taskpack, prompt, state_dir, None,
                                lambda pr: self._interactive(run_ctx, self.interactive_command(pr), state_dir))

    def resume(self, run_ctx, taskpack, state_dir, session, text, timeout=None):
        """10.1：续接会话并送入补充说明。对话步骤（run_ctx.interactive）打开对话窗口接着聊，补充说明（加上这一步的任务包）是第一句；
        自动步骤用 -p 接着跑。Claude Code 续接时报的花费是整个会话的累计数，这里只记增量（交接「做试验时要守的规矩」）。
        这一步的任务包点名了技能时，/<技能名> 放在最前面（3-29）。"""
        pack = self._taskpack_prompt(taskpack, head='下面是这一步的任务包')
        msg = f'{text}\n\n{pack}' if pack else text
        if run_ctx.interactive:
            return self._with_skill(run_ctx, taskpack, msg, state_dir, session,
                                    lambda pr: self._interactive(run_ctx, self.interactive_command(pr, session=session),
                                                                 state_dir, resumed=session))
        return self._with_skill(run_ctx, taskpack, msg, state_dir, session,
                                lambda pr: self._resume_headless(run_ctx, taskpack, state_dir, session, pr, timeout))

    def _resume_headless(self, run_ctx, taskpack, state_dir, session, msg, timeout):
        budget = None
        try:
            budget = json.loads((pathlib.Path(taskpack) / 'task.json').read_text(encoding='utf-8')).get('budget_usd')
        except (OSError, ValueError, TypeError):
            budget = None
        cwd = str(run_ctx.chdir or (pathlib.Path(run_ctx.root) / run_ctx.worktree))
        prev = self._prev_total(state_dir, session, cwd)
        out = self._invoke(run_ctx, self.command(msg, budget, session=session), state_dir, timeout)
        if out.cost_basis == '工具报告':
            total = out.cost
            out.cost = self._increment(state_dir, out.session or session, total, prev)
            if prev is None:
                out.cost_basis = '工具报告的累计数（续接前的累计数没记下，按累计数记）'
            else:
                out.cost_basis = '工具报告（累计数减去续接前的）'
        return out

    # 续接前的累计数：适配器自己记在状态目录旁边（受限环境里看不到、改不了），没有时看工具自己记在状态目录里的
    def _prev_total(self, state_dir, session, cwd):
        if not session:
            return 0.0
        book = _read_json(_cost_book(state_dir))
        if isinstance(book.get(session), (int, float)):
            return float(book[session])
        return _session_total(state_dir, session, cwd)[0]

    def _increment(self, state_dir, session, total, prev):
        if total is None:
            return 0.0
        if session:
            f = _cost_book(state_dir)
            book = _read_json(f)
            book[session] = total
            try:
                f.write_text(json.dumps(book, ensure_ascii=False))
            except OSError:
                pass
        if prev is None:
            return total
        return round(total - prev, 8) if total >= prev else total

    def run_headless(self, run_ctx, taskpack, state_dir, timeout=None, budget=None):
        out = self._run_headless(run_ctx, taskpack, state_dir, timeout, budget)
        if out.session and out.cost_basis == '工具报告':
            self._increment(state_dir, out.session, out.cost, 0.0)
        return out

    # ---------- 打开对话窗口不出首次启动的那几屏（10.1、W28） ----------
    def check_screens(self, wait=60):
        """在 /tmp 现建的一次性小项目里、从模板现建的状态目录、模拟终端里打开一次对话窗口（不发任何消息），
        看首次启动的那几屏出没出（设置名是 Claude Code 自己定的，升级后可能变）。
        返回 (结论, 给人看的话, 详情)：结论 True 没出、False 出了或没打开、None 没法核对。"""
        if not sandbox.tiocsti_disabled():
            return None, '没核对打开对话窗口（这台电脑的内核没有禁用「往终端里塞按键」，对话步骤不能启动）', {}
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-screens-', dir='/tmp'))
        try:
            R, W, st = tmp / 'p', tmp / 'p' / 'probe', tmp / 'state'
            _mini_project(R, W)
            st.mkdir(mode=0o700)
            self.template(st, W)
            ctx = placement.Ctx(root=R, kind='readonly', worktree=W.name, chdir=W, out_dir=_mk(tmp / 'out'), interactive=True)
            self._prepare(ctx, st)
            with ptyscreen.Pty(sandbox.argv(ctx, self.interactive_command())) as t:
                t.wait_for(lambda s: ptyscreen.is_ready(s) or ptyscreen.first_run_screens(s), wait)
                t.pump(1.5)                 # 有的屏幕在输入框之后才弹出来，多等一下
                text = t.text
                ready, screens = ptyscreen.is_ready(text), ptyscreen.first_run_screens(text)
                if ready and not screens:
                    t.type_line('/exit')
                t.close(wait=10)
            sid = _newest_session(st, 0) or _project_entry(st, str(W)).get('lastSessionId')
            total, cost_basis = _session_total(st, sid, str(W))
            cost = total or 0.0
            if total is None:
                cost_basis = '没读到工具的报告（没发消息，按 0 记）'
        finally:
            subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
        details = {'screens': screens, 'ready': ready, 'cost': cost, 'cost_basis': cost_basis, 'tail': text[-1500:]}
        if screens:
            return False, ('打开对话窗口时出了首次启动的那几屏：' + '、'.join(screens) +
                           '（多半是升级后状态目录模板里的设置名变了，适配器要跟着改，先交维修窗口）'), details
        if not ready:
            return False, f'在模拟终端里打开对话窗口，{wait} 秒没出输入框', details
        return True, '打开对话窗口直接是输入框，没出首次启动的那几屏', details

    def reminder(self):
        """10.1：和最近一次做过真实 AI 演练的版本比，不一样或还没演练过就提醒（流程照常）。没装 Claude Code 时不提醒（到 AI 步骤再说）。"""
        path, _ = self.location()
        if not path:
            return ''
        return drill_reminder(NAME, self.version() or '（查不出版本）')

    # ---------- 自检 ----------
    def probe(self, timeout=300, budget=0.5, record=True, screens=True):
        """10.1 的自检：装了；能用（真的发一次最短的调用，不看工具自己的登录显示，10.2 第 1 条）；
        版本记进机器级登记、和上次做过真实 AI 演练的比；能力声明与实际一致。
        服务报余额不足、额度用完这一类的错：暂停、提示充值，不重试。"""
        path, real = self.location()
        if not path:
            return ProbeResult(False, '没找到 Claude Code（官方装法的默认位置是 ~/.local/bin/claude）')
        ver = self.version()
        if not ver:
            return ProbeResult(False, f'Claude Code 在 {locate.short(path)}，但查不出它的版本（--version 不正常）')
        missing = self.check_caps()
        if missing:
            return ProbeResult(False, f'Claude Code {ver} 的帮助里找不到这几个参数：'
                               + '、'.join(f'{f}（{why}）' for f, why in missing)
                               + '。可能是升级后改了用法，适配器要跟着改，先交维修窗口', version=ver,
                               details={'missing_flags': [f for f, _ in missing]})
        env, src = self.credentials()
        if not env:
            return ProbeResult(False, '没找到 Claude Code 用的服务地址和密钥：'
                               f'{locate.short(paths.config_dir() / "ai" / "claude.env")} 不存在，终端里也没有 ANTHROPIC_ 开头的设置'
                               '（sop machine setup 的「登录 AI 工具」一步会写）。用官方账号登录的做法还没验证过（W37）', version=ver)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-probe-', dir='/tmp'))
        try:
            R, W, st = tmp / 'p', tmp / 'p' / 'probe', tmp / 'state'
            _mini_project(R, W)
            st.mkdir(mode=0o700)
            self.template(st, W)
            ctx = placement.Ctx(root=R, kind='readonly', worktree=W.name, chdir=W, out_dir=_mk(tmp / 'out'))
            out = self._invoke(ctx, self.command(PROBE_PROMPT, budget), st, timeout)
            ok_q, _, rep = quota_scan(out.logs)
        finally:
            subprocess.run(['chmod', '-R', 'u+w', str(tmp)], capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
        details = {'source': src, 'rc': out.rc, 'session': out.session, 'answer': out.text[:200], 'cost_basis': out.cost_basis}
        if not ok_q:
            msg = ('AI 服务报了余额不足或额度用完一类的错（例如「' + rep['hits'][0]['text'][:80] + '」）。'
                   '先暂停：请到 AI 服务的后台看一下余额，不够就充值，充好以后再自检一次（这次没有重试）')
            res = ProbeResult(False, msg, version=ver, cost=out.cost, quota=True, details=details)
        elif out.timeout:
            res = ProbeResult(False, f'Claude Code {ver} 最短的一次调用 {timeout} 秒没结束', version=ver, cost=out.cost, details=details)
        elif out.rc != 0 or not out.text.strip():
            res = ProbeResult(False, f'Claude Code {ver} 最短的一次调用没成功（退出码 {out.rc}）：{out.text[-300:]}',
                              version=ver, cost=out.cost, details=details)
        else:
            res = ProbeResult(True, f'Claude Code {ver} 能用：真的发了一次最短的调用，它回答了「{out.text.strip()[:40]}」',
                              version=ver, cost=out.cost, details=details)
            if screens:     # 3-28：再在模拟终端里打开一次对话窗口（不发消息），看首次启动的那几屏出没出（10.1、W28）
                ok_s, line_s, det_s = self.check_screens()
                res.cost += det_s.get('cost', 0.0)
                res.details['screens'] = {'ok': ok_s, 'message': line_s, **{k: v for k, v in det_s.items() if k != 'tail'}}
                if ok_s is False:
                    res.ok = False
                    res.message = f'Claude Code {ver} 自动调用能用，但{line_s}'
                else:
                    res.message += f'；{line_s}'
        if record:
            record_probe(NAME, path=path, real=real, version=ver, ok=res.ok)
            res.remind = drill_reminder(NAME, ver)
        return res


def _read_json(f):
    try:
        d = json.loads(pathlib.Path(f).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _cost_book(state_dir):
    """适配器自己记的「每个会话到现在的累计花费」，放在状态目录旁边（受限环境里只放进状态目录本身，看不到这份）。"""
    sd = pathlib.Path(state_dir)
    return sd.with_name(sd.name + '.sop-cost.json')


def _project_entry(state_dir, cwd, session=None):
    """Claude Code 退出时记在状态目录 .claude.json 里的几项（lastSessionId、lastCost 等，W28 在 2.1.327 上看到记在工作目录名下）。
    工作目录名下没有 lastSessionId 时，给了 session 就找记着这个会话的那一项（3-28 在 2.1.329 上工作目录名下没记）。"""
    projects = _read_json(pathlib.Path(state_dir) / '.claude.json').get('projects') or {}
    for k in (cwd, os.path.realpath(cwd)):
        if isinstance(projects.get(k), dict) and projects[k].get('lastSessionId'):
            return projects[k]
    if session:
        for v in projects.values():
            if isinstance(v, dict) and v.get('lastSessionId') == session:
                return v
    return {}


def _session_total(state_dir, session, cwd):
    """这个会话到现在的累计花费（工具自己记的）和它从哪来。先看会话日志里的 cost-state（3-28 在 2.1.329 上实测有、续接后是累计数），
    没有再看 .claude.json 里的 lastCost（W28 在 2.1.327 上看到的）。都没有是 (None, '没读到工具的报告')。"""
    if not session:
        return None, '没读到工具的报告'
    cs = _cost_state(state_dir, session)
    if cs is not None:
        return cs, '会话日志里工具记的数'
    proj = _project_entry(state_dir, cwd, session)
    if proj.get('lastSessionId') == session and isinstance(proj.get('lastCost'), (int, float)):
        return float(proj['lastCost']), '状态目录里工具记的数'
    return None, '没读到工具的报告'


def _session_lines(state_dir, session):
    proj = pathlib.Path(state_dir) / 'projects'
    if not session or not proj.is_dir():
        return []
    out = []
    for f in sorted(proj.rglob(f'{session}.jsonl')):
        for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if isinstance(j, dict):
                out.append(j)
    return out


def _task_skill(taskpack):
    """任务包点名的技能（task.json 的 skill），没有是 None。"""
    if not taskpack:
        return None
    try:
        s = json.loads((pathlib.Path(taskpack) / 'task.json').read_text(encoding='utf-8')).get('skill')
    except (OSError, ValueError, AttributeError):
        return None
    return s if isinstance(s, str) and s.strip() else None


def skill_loads(state_dir, session):
    """这个会话里加载过的项目技能（按先后，可重复）：会话日志里用户消息开头是「Base directory for this skill: <目录>」、
    目录是 …/.claude/skills/<技能名> 的那几条（只认项目里的副本；Claude Code 自带的同名技能不算，10.2 第 8 条）。"""
    out = []
    for j in _session_lines(state_dir, session):
        if j.get('type') != 'user':
            continue
        content = (j.get('message') or {}).get('content')
        texts = [content] if isinstance(content, str) else \
            [c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text'] if isinstance(content, list) else []
        for t in texts:
            if not t.startswith(SKILL_LOADED_HEAD):
                continue
            rest = t[len(SKILL_LOADED_HEAD):].strip()
            parent, name = os.path.split(rest.splitlines()[0].strip().rstrip('/') if rest else '')
            if parent.endswith('/' + DECLARATION['skills_dir']):
                out.append(name)
    return out


def _cost_state(state_dir, session):
    """会话日志里工具自己记的累计花费（最后一条 type 是 cost-state 的 totalCostUSD）。没有是 None。"""
    vals = [j.get('totalCostUSD') for j in _session_lines(state_dir, session) if j.get('type') == 'cost-state']
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    return vals[-1] if vals else None


def _newest_session(state_dir, since):
    """since 之后改过的会话日志里最新的那个（文件名就是会话编号）。"""
    proj = pathlib.Path(state_dir) / 'projects'
    fs = [f for f in proj.rglob('*.jsonl') if f.stat().st_mtime >= since - 1] if proj.is_dir() else []
    return max(fs, key=lambda f: f.stat().st_mtime).stem if fs else None


def _last_answer(state_dir, session):
    """会话日志里 AI 最后一次回答的文字（给人看；续接后核对记不记得前文也用它）。"""
    for j in reversed(_session_lines(state_dir, session)):
        if j.get('type') != 'assistant':
            continue
        content = (j.get('message') or {}).get('content')
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            t = ''.join(c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text')
            if t.strip():
                return t
    return ''


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    return p


def _mini_project(R, W, skills=None):
    """自检用的一次性小项目（和真项目一样：项目根下 .git 是裸仓库、工作目录是它的一个工作目录），自检完整个删掉。
    不读用户自己的 Git 设置和钩子模板。skills：{技能名: 副本里的目录}，原样复制进 .claude/skills/<技能名>/ 一起提交（3-29 演练用）。"""
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@sop.invalid',
           'GIT_COMMITTER_NAME': 'sop', 'GIT_COMMITTER_EMAIL': 'sop@sop.invalid'}
    seed = R.parent / 'seed'

    def g(*a):
        subprocess.run(['git', *map(str, a)], env=env, check=True, capture_output=True)
    g('init', '-q', '--template=', '-b', 'main', seed)
    (seed / 'README.md').write_text('自检用的小项目\n', encoding='utf-8')
    for name, src in (skills or {}).items():
        shutil.copytree(src, seed / DECLARATION['skills_dir'] / name)
    g('-C', seed, 'add', '-A')
    g('-C', seed, 'commit', '-qm', 'probe')
    R.mkdir(parents=True)
    g('clone', '-q', '--template=', '--bare', seed, R / '.git')
    g(f'--git-dir={R / ".git"}', 'worktree', 'add', '-q', W, 'main')
    shutil.rmtree(seed)
