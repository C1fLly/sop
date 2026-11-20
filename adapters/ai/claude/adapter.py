"""Claude Code 适配器（设计书 10.1、10.2）。3-27 做了能力声明、自检（probe）、自动调用（run_headless）；
对话方式（start_interactive）和续接（resume）是 3-28，接进流程引擎是 3-29。

怎么跑（都照第一段、第二段实测过的做法，不加别的花样）：
- 程序：用官方装法默认位置的那一份（~/.local/bin/claude，是个链接），按它指向的实际文件只读放进受限环境，版本号不写死在路径里（10.1）。
- 状态目录：每个会话从模板现建（6.3 三），挂在受限环境里主目录下的 .claude，CLAUDE_CONFIG_DIR 指过去；
  模板只有 .claude.json 里的 5 项设置（W28）。会话日志就在状态目录的 projects/ 下（<工作目录改写>/<会话编号>.jsonl）。
- 服务地址和密钥：先看 ~/tools/sop/config/ai/claude.env（M4 写的，问题 5），没有这份时用终端里的 ANTHROPIC_ 开头的环境变量
  （这台电脑上 Claude Code 就是这么配的）；作为环境变量给进受限环境，不写进任何文件、不打印。官方账号登录没验证过（W37）。
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

# 能力声明（10.1 列的各项）。依据写在 10.2 的表里：「实测」的都真的调用过。
DECLARATION = {
    'interactive': True,                  # 能交互启动（W28 实测；适配器这一半是 3-28）
    'headless': True,                     # 能自动调用：claude -p（实测）
    'resume': True,                       # 能续接：--resume <会话编号>（实测；适配器这一半是 3-28）
    'skill_syntax': '/{skill}',           # 技能调用的写法（实测）
    'skill_headless': True,               # 自动调用下能触发技能（S1 实测；3-29 再验）
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

    def run_headless(self, run_ctx, taskpack, state_dir, timeout=None, budget=None):
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
        return self._invoke(run_ctx, self.command(prompt, budget), state_dir, timeout)

    def resume(self, run_ctx, taskpack, state_dir, session, text, timeout=None):
        raise NotImplementedError('Claude Code 适配器的续接是 3-28')

    def start_interactive(self, run_ctx, taskpack, state_dir):
        raise NotImplementedError('Claude Code 适配器的对话方式是 3-28')

    # ---------- 自检 ----------
    def probe(self, timeout=300, budget=0.5, record=True):
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
        if record:
            record_probe(NAME, path=path, real=real, version=ver, ok=res.ok)
            res.remind = drill_reminder(NAME, ver)
        return res


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    return p


def _mini_project(R, W):
    """自检用的一次性小项目（和真项目一样：项目根下 .git 是裸仓库、工作目录是它的一个工作目录），自检完整个删掉。
    不读用户自己的 Git 设置和钩子模板。"""
    env = {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@sop.invalid',
           'GIT_COMMITTER_NAME': 'sop', 'GIT_COMMITTER_EMAIL': 'sop@sop.invalid'}
    seed = R.parent / 'seed'

    def g(*a):
        subprocess.run(['git', *map(str, a)], env=env, check=True, capture_output=True)
    g('init', '-q', '--template=', '-b', 'main', seed)
    (seed / 'README.md').write_text('自检用的小项目\n', encoding='utf-8')
    g('-C', seed, 'add', '-A')
    g('-C', seed, 'commit', '-qm', 'probe')
    R.mkdir(parents=True)
    g('clone', '-q', '--template=', '--bare', seed, R / '.git')
    g(f'--git-dir={R / ".git"}', 'worktree', 'add', '-q', W, 'main')
    shutil.rmtree(seed)
