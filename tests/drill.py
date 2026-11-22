#!/usr/bin/env python3
"""破坏演练（设计书 16.3，3-47）：脚本逐项做破坏动作，每一项都要看到检查失败（被拦住）。小白只看结果。

用法（在工具包开发目录里）：
  python3 tests/drill.py                 全部演一遍（几分钟）
  python3 tests/drill.py --list          列出有哪几项
  python3 tests/drill.py --only a,b      只演这几项
  python3 tests/drill.py --keep          演完不删 /tmp 里的现场（看现场用）
退出码：0 每一项破坏都被拦住了；1 有一项没拦住或演不下去（屏幕上写着是哪一项、为什么）；2 用法不对或拒绝执行。
sop self check --isolation（3-44）按这个位置找它、在开发目录里这样执行，退出码 0 才算过。

**破坏动作只在 /tmp 里现造的东西上做**，开发目录、~/tools/wt、本机主目录、真的 GitHub 一样都不碰：
- 开发目录只读两样：Git 记着的文件清单（被跟踪的加没被忽略的新文件，和 sop self check 看的改动一致，所以没提交的改动也算进来）
  和文件内容，原样拷到 /tmp/sop-drill-<随机>/toolkit，在那里 git init 提交成「演练起点」。读 Git 时带 GIT_OPTIONAL_LOCKS=0，不写索引。
- wt 从它现在的位置只读克隆一份到 /tmp（git clone --no-local），项目那几项用克隆出来的这一份。
- 主目录、临时目录（TMPDIR）换成现场里现建的；GitHub 用流程沙箱的本机假远程加假的 gh（tests/sandbox/world.py）；不调 AI、不碰 Docker。
- 拷完以后换到 /tmp 里那份副本自己的 tests/drill.py 接着做（--inner），所以之后导入的工具包代码、被破坏的文件都是副本里的。
  两层开头都先核对「当前目录和主目录都在 /tmp 下这次现建的目录里」，不是就拒绝执行；每个写文件、提交的动作也先核对目标在里面。
每一项：先确认没破坏时检查通过 → 破坏 → 检查必须失败，而且失败的原因就是这次破坏（不是别的毛病）→ 还原 → 检查又通过。
"""
import json
import os
import pathlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent.parent      # 这一份 drill.py 所在的工具包
TMP = '/tmp'
DROP = ('ANTHROPIC_', 'CLAUDE', 'OPENAI_', 'CODEX_', 'OPENCODE_', 'GEMINI_', 'GH_', 'GITHUB_', 'DOCKER_', 'NVM_', 'SOP_',
        'SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'GPG_AGENT_INFO', 'GIT_', 'PNPM_HOME', 'npm_config_')
GIT_ID = '[user]\n\tname = drill\n\temail = drill@example.invalid\n[init]\n\tdefaultBranch = main\n'


class Refuse(Exception):
    """不安全，拒绝执行。"""


class DrillError(Exception):
    """演练本身演不下去（例如要改的那一行工具包里已经没有了）。"""


# ---------- 安全 ----------
def real(p):
    return os.path.realpath(str(p))


def under(p, root):
    p, root = real(p), real(root)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def account_home():
    return pwd.getpwuid(os.getuid()).pw_dir


def assert_safe(work, cwd=None, home=None):
    """现场必须是 /tmp 下这次现建的目录，当前目录和主目录都在它里面，而且和本机真的主目录不沾边。不是就抛 Refuse。"""
    work = real(work)
    cwd = real(cwd or os.getcwd())
    home = real(home if home is not None else os.environ.get('HOME', ''))
    acct = real(account_home())
    if not under(work, TMP) or work == real(TMP):
        raise Refuse(f'现场 {work} 不是 /tmp 下现建的目录')
    if under(work, acct) or under(acct, work):
        raise Refuse(f'现场 {work} 和本机真的主目录 {acct} 沾边')
    if not under(cwd, work):
        raise Refuse(f'当前目录 {cwd} 不在现场 {work} 里')
    if not home or not under(home, work):
        raise Refuse(f'主目录 {home or "（没设）"} 不在现场 {work} 里')


def inside(work, p):
    """每个写文件、提交、删文件的动作之前调：目标不在现场里就抛 Refuse。"""
    if not under(p, work) or real(p) == real(work):
        raise Refuse(f'要动的 {p} 不在现场 {work} 里，不动')
    return pathlib.Path(p)


def git(work, *args, cwd=None, check=True, env=None):
    """在现场里执行 git：身份用现场的，不读本机的 ~/.gitconfig 和系统的设置。"""
    if cwd is not None:
        inside(work, cwd)
    e = {**os.environ, 'GIT_CONFIG_GLOBAL': str(pathlib.Path(work) / 'gitconfig'), 'GIT_CONFIG_NOSYSTEM': '1', **(env or {})}
    p = subprocess.run(['git', *map(str, args)], cwd=cwd, env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check and p.returncode:
        raise DrillError(f'git {" ".join(map(str, args))} 失败：{(p.stderr or p.stdout).strip()[-400:]}')
    return p.stdout.strip()


def read_src(src, *args):
    """只读开发目录：不写索引（GIT_OPTIONAL_LOCKS=0）、不读本机的设置。"""
    e = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    p = subprocess.run(['git', '-C', str(src), *args], env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise DrillError(f'读不了 {src} 的 Git 记录：{p.stderr.strip()[-300:]}')
    return p.stdout


def copy_source(work, src, dest):
    """把开发目录里 Git 记着的文件（被跟踪的加没被忽略的新文件）原样拷到 dest，提交成「演练起点」。返回 (起点, 文件数)。"""
    dest = inside(work, dest)
    names = [f for f in read_src(src, 'ls-files', '-co', '--exclude-standard', '-z').split('\0') if f]
    n = 0
    for f in dict.fromkeys(names):
        s = pathlib.Path(src) / f
        if not (s.is_file() or s.is_symlink()):
            continue                      # 被跟踪、但工作区里已经删了的
        d = inside(work, dest / f)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d, follow_symlinks=False)
        n += 1
    git(work, 'init', '-q', '-b', 'main', cwd=dest)
    git(work, 'add', '-A', cwd=dest)
    git(work, 'commit', '-qm', '演练起点', '--allow-empty', cwd=dest)
    return git(work, 'rev-parse', 'HEAD', cwd=dest), n


def clone_wt(work, dest):
    """wt 只读克隆一份到现场。找不到 wt 返回 None（项目那几项就演不了，照实说）。"""
    exe = shutil.which('wt')
    if not exe:
        return None
    src = os.path.dirname(real(exe))
    e = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    top = subprocess.run(['git', '-C', src, 'rev-parse', '--show-toplevel'], env=e, capture_output=True, text=True)
    dest = inside(work, dest)
    if top.returncode == 0 and real(top.stdout.strip()) == real(src):
        p = subprocess.run(['git', 'clone', '-q', '--no-local', src, str(dest)], env=e, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if p.returncode:
            raise DrillError(f'克隆 wt 失败：{p.stderr.strip()[-300:]}')
    else:
        shutil.copytree(src, dest, symlinks=True)
    exe_copy = dest / os.path.basename(real(exe))
    return exe_copy if exe_copy.is_file() else None


def rmtree(p):
    if os.path.exists(p):
        subprocess.run(['chmod', '-R', 'u+w', str(p)], capture_output=True)
        shutil.rmtree(p, ignore_errors=True)


# ---------- 一项怎么演、怎么判 ----------
class Item:
    """name 短名；title 破坏动作（大白话）；check_name 应当拦住它的是哪道检查。
    setup/check/brk/restore 都接 ctx；check 返回 (过没过, 输出)；marker 是失败输出里必须在同一行出现的几段字，
    对得上才算「失败的原因就是这次破坏」。"""

    def __init__(self, name, title, check_name, check, brk, restore, marker, setup=None):
        self.name, self.title, self.check_name = name, title, check_name
        self.check, self.brk, self.restore, self.setup = check, brk, restore, setup
        self.marker = marker if isinstance(marker, (list, tuple)) else [marker]

    def hits(self, text):
        """输出里同一行同时写着全部标记的那几行：失败的原因就是这次破坏。"""
        return [x.strip() for x in text.splitlines() if all(m in x for m in self.marker)]

    def blocked_by(self, text):
        return bool(self.hits(text))

    def evidence(self, text):
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        best = self.hits(text) or sorted(lines, key=lambda x: -sum(m in x for m in self.marker)) or ['']
        return best[0][:300]


BLOCKED, NOT_BLOCKED, BROKEN = '拦住了', '没拦住', '演不下去'


def run_item(it, ctx, out=print):
    """演一项：返回 (结果, 原因)。结果只有三种：拦住了 / 没拦住 / 演不下去（后两种都算没过）。"""
    def check():
        try:
            return it.check(ctx)
        except DrillError as e:  # 检查跑不起来（例如假 gh 报错）：算没过，原因对不上标记，不会被当成拦住
            return False, f'检查跑不起来：{e}'
        except Exception as e:   # noqa: BLE001  检查自己崩了：同上
            return False, f'检查自己出错：{type(e).__name__}: {e}'

    ctx.state = {}                      # 每一项自己的现场（开的 PR、改之前的字节……），不带到下一项
    result = None
    try:
        if it.setup:
            it.setup(ctx)
        ok, text = check()
        if not ok:
            out(f'  没破坏时：{it.check_name}就没过：{it.evidence(text)}')
            result = (BROKEN, f'没破坏时{it.check_name}就没过（{it.evidence(text)}），演不下去')
        else:
            out(f'  没破坏时：{it.check_name}通过')
            it.brk(ctx)
            out(f'  破坏：{it.title}')
            ok, text = check()
            if ok:
                out(f'  破坏之后：{it.check_name}还是通过 —— 没拦住！')
                result = (NOT_BLOCKED, f'{it.check_name}没发现这次破坏')
            elif not it.blocked_by(text):
                out(f'  破坏之后：{it.check_name}失败了，但不是因为这次破坏：{it.evidence(text)}')
                result = (BROKEN, f'{it.check_name}失败的原因不是这次破坏（{it.evidence(text)}）')
            else:
                out(f'  破坏之后：检查失败（{it.check_name}拦住了）：{it.evidence(text)}')
                result = (BLOCKED, '')
    except DrillError as e:
        out(f'  演不下去：{e}')
        result = (BROKEN, str(e))
    finally:
        try:
            it.restore(ctx)
        except Exception as e:   # noqa: BLE001
            out(f'  还原失败：{e}')
            result = (BROKEN, f'还原失败：{e}')
    if result[0] == BROKEN:
        return result
    ok, text = check()
    if not ok:
        out(f'  还原之后：{it.check_name}没回到通过：{it.evidence(text)}')
        return BROKEN, f'还原之后{it.check_name}没回到通过（{it.evidence(text)}）'
    out(f'  还原之后：{it.check_name}又通过了')
    return result


def run_items(items, ctx, out=print):
    results = []
    for i, it in enumerate(items, 1):
        out(f'[{i}/{len(items)}] {it.name}：{it.title}（应当由{it.check_name}拦住）')
        t0 = time.time()
        res, why = run_item(it, ctx, out)
        out(f'  结果：{res}（{round(time.time() - t0, 1)} 秒）')
        results.append((it, res, why))
    return results


def summary(results, out=print):
    """打总结，返回退出码：每一项都拦住了才是 0。"""
    out('')
    out('===== 破坏演练的结果 =====')
    for it, res, why in results:
        out(f'  {"检查失败（拦住了）" if res == BLOCKED else res}  {it.name}：{it.title}' + (f'。{why}' if why else ''))
    bad = [(it, res) for it, res, _ in results if res != BLOCKED]
    if not results:
        out('一项都没演，不能算过')
        return 1
    if bad:
        out(f'破坏演练没过：{len(results)} 项里 {len(bad)} 项不对：' + '；'.join(f'{it.name} {res}' for it, res in bad))
        return 1
    out(f'破坏演练过了：{len(results)} 项破坏全部被检查拦住')
    return 0


# ---------- 具体的检查（在副本里跑） ----------
def run_py(ctx, *args, timeout=600):
    p = subprocess.run([sys.executable, *map(str, args)], cwd=ctx.toolkit, env=ctx.child_env(), capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def unit_check(pattern):
    """单元测试：和 GitHub 上一样带 --no-skip，只跑被改的那一个测试文件。一个测试都没跑也算没过。"""
    def check(ctx):
        rc, text = run_py(ctx, 'tests/run_all.py', '--no-skip', '--pattern', pattern, 'unit')
        ran = re.search(r'^Ran (\d+) tests?', text, re.M)
        if ran and int(ran.group(1)) == 0:
            return False, f'一个测试都没跑（{pattern} 不在了？）\n' + text
        return rc == 0, text
    return check


def total_check(ctx):
    rc, text = run_py(ctx, 'checks/total_check.py')
    return rc == 0, text


def docs_check(ctx):
    rc, text = run_py(ctx, 'tests/run_all.py', 'docs')
    return rc == 0, text


# ---------- 破坏动作（工具包副本里的） ----------
def replace_in(ctx, rel, old, new):
    f = inside(ctx.work, ctx.toolkit / rel)
    if not f.is_file():
        raise DrillError(f'工具包里没有 {rel} 了（tests/drill.py 要跟着改）')
    text = f.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise DrillError(f'{rel} 里要改的那一处「{old.strip()[:60]}」有 {text.count(old)} 处，不是正好一处'
                         '（工具包改过了，tests/drill.py 要跟着改）')
    f.write_text(text.replace(old, new, 1), encoding='utf-8')


def commit(ctx, msg):
    git(ctx.work, 'add', '-A', cwd=ctx.toolkit)
    git(ctx.work, 'commit', '-qm', msg, cwd=ctx.toolkit)


def reset_toolkit(ctx):
    """还原工具包副本：回到演练起点，删掉破坏时新加的文件（被忽略的缓存不动），再核对干净了。"""
    git(ctx.work, 'reset', '-q', '--hard', ctx.start, cwd=ctx.toolkit)
    git(ctx.work, 'clean', '-fdq', cwd=ctx.toolkit)
    left = git(ctx.work, 'status', '--porcelain', cwd=ctx.toolkit)
    if left:
        raise DrillError(f'工具包副本没还原干净：{left[:200]}')


def edit_then_commit(rel, old, new, msg):
    def brk(ctx):
        replace_in(ctx, rel, old, new)
        commit(ctx, msg)
    return brk


def append_then_commit(rel, text, msg):
    def brk(ctx):
        f = inside(ctx.work, ctx.toolkit / rel)
        if not f.is_file():
            raise DrillError(f'工具包里没有 {rel} 了（tests/drill.py 要跟着改）')
        with open(f, 'a', encoding='utf-8') as fh:
            fh.write(text)
        commit(ctx, msg)
    return brk


def rename_sample(ctx):
    d = ctx.toolkit / 'checks' / 'scope' / 'samples'
    fails = sorted(p for p in d.iterdir() if p.name.startswith('fail-')) if d.is_dir() else []
    if not fails:
        raise DrillError('checks/scope 下没有「应报错」的样例了（tests/drill.py 要跟着改）')
    to = 'pass-' + fails[0].name[len('fail-'):]
    os.rename(inside(ctx.work, fails[0]), inside(ctx.work, d / to))
    commit(ctx, '样例的预期改成应通过')


def edit_skill(ctx):
    rec = ctx.toolkit / 'skills' / 'source.json'
    try:
        first = sorted(json.loads(rec.read_text(encoding='utf-8'))['files'])[0]
    except (OSError, ValueError, KeyError, IndexError):
        raise DrillError('读不出技能副本的版本记录 skills/source.json（tests/drill.py 要跟着改）')
    f = inside(ctx.work, ctx.toolkit / 'skills' / 'mattpocock' / first)
    if not f.is_file():
        raise DrillError(f'技能副本里没有 {first}')
    with open(f, 'ab') as fh:
        fh.write(b'\n')
    commit(ctx, '技能里顺手改一个字')


# ---------- 假项目（流程沙箱的世界：本机假远程、假 gh、经 wt 接入层建的项目） ----------
class Proj:
    def __init__(self, ctx):
        from kernel import wtx
        from tests.helpers import mock_env
        from tests.sandbox.world import World
        self.ctx, self.wtx, self.mock_env = ctx, wtx, mock_env
        base = inside(ctx.work, ctx.work / 'sbx')
        home = base / 'test-home'
        for sub in ('.config', '.cache', '.local/share', '.local/state'):
            (home / sub).mkdir(parents=True, exist_ok=True)
        (home / '.gitconfig').write_text(GIT_ID)
        os.environ.update({'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_CACHE_HOME': str(home / '.cache'),
                           'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_STATE_HOME': str(home / '.local/state'),
                           'SOP_HOME': str(base / 'sop-home'), 'SOP_RUNTIME_DIR': str(base / 'run')})
        assert_safe(ctx.work)
        self.w = World(base / 'w')
        self.root = self.w.root
        self.scratch = base / 'scratch'
        self.git('clone', '-q', self.w.remote, self.scratch, cwd=base)
        self.n = 0

    def git(self, *args, cwd=None):
        return git(self.ctx.work, *args, cwd=cwd or self.scratch, env=self.w.git_env())

    def gh(self, *args):
        p = self.w.gh(*args)
        if p.returncode:
            raise DrillError(f'假 gh {" ".join(args)} 失败：{(p.stderr or p.stdout).strip()[-300:]}')
        return p.stdout

    # 守门检查：在假 GitHub 上开 PR、推送；假 gh 照 GitHub 上的守门流程真跑主线声明的那个工具包版本里的 guard.py
    def open_pr(self, branch, path, content):
        inside(self.ctx.work, self.scratch / path)
        self.git('checkout', '-q', '-B', branch, 'origin/main')
        (self.scratch / path).parent.mkdir(parents=True, exist_ok=True)
        (self.scratch / path).write_text(content, encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', f'演练：改 {path}')
        self.git('push', '-q', 'origin', f'HEAD:refs/heads/{branch}')
        url = self.gh('pr', 'create', '--base', 'main', '--head', branch, '--title', f'演练 {branch}', '--body', '')
        return url.strip().rsplit('/', 1)[-1]

    def push_change(self, branch, path, content=None, msg='演练'):
        f = inside(self.ctx.work, self.scratch / path)
        if content is None:
            self.git('checkout', '-q', 'origin/main', '--', path)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding='utf-8')
        self.git('add', '-A'); self.git('commit', '-qm', msg)
        self.git('push', '-q', 'origin', f'HEAD:refs/heads/{branch}')

    def guard_result(self, pr):
        self.gh('pr', 'view', pr, '--json', 'number')          # 假 gh 每次被调用先看有没有新推送，有就重跑检查
        runs = [r for r in self.w.db()['runs'] if str(r['pr']) == str(pr) and r['name'] == 'guard']
        if not runs:
            return False, '守门检查一次都没跑'
        r = runs[-1]
        return r['conclusion'] == 'success', f'守门检查结论 {r["conclusion"]}\n{r["log"]}'

    # 特权侧用之前核对：经 wt 接入层建一个新目录（wt new），对不上时 wt 一条命令都不该执行
    def wt_new(self):
        from kernel.errors import Tampered
        self.n += 1
        branch = f'drill/w{self.n}'
        d = self.root / self.wtx.dirname(branch)
        with self.mock_env(self.w.env()):
            try:
                self.wtx.new(self.w.name, self.root, branch)
            except Tampered as e:
                if d.exists():          # 说了不执行，wt 却执行了：算没拦住
                    return True, f'说了不执行，可目录 {d.name} 还是建出来了：{e}'
                return False, f'{e}\n（wt new {branch} 没有执行，目录 {d.name} 没建出来）'
        return d.is_dir(), f'wt new {branch} 建好了 {d.name}'


def project(ctx):
    if ctx.proj is None:
        if not ctx.wt:
            raise DrillError('这台电脑上找不到 wt，假项目建不起来（项目那几项演不了）')
        t0 = time.time()
        ctx.proj = Proj(ctx)
        ctx.out(f'  （假项目建好了：{ctx.proj.root}，{round(time.time() - t0, 1)} 秒）')
    return ctx.proj


def guard_item(name, title, path, content, marker):
    branch = f'drill/{name}'

    def setup(ctx):
        ctx.state['pr'] = project(ctx).open_pr(branch, 'src/app.py', 'print("演练：正常的改动")\n')

    def check(ctx):
        return project(ctx).guard_result(ctx.state['pr'])

    def brk(ctx):
        project(ctx).push_change(branch, path, content, f'演练：{title}')

    def restore(ctx):
        if ctx.state.get('pr'):
            project(ctx).push_change(branch, path, None, '演练：改回去')
    return Item(name, title, '守门检查', check, brk, restore, [marker + '：'], setup=setup)


def file_tamper(name, title, rel, marker, make, mode=None):
    """改项目根下特权侧要用的一个文件；还原成原来的字节和权限（原来没有就删掉）。make(原来的内容或 None) -> 新内容。"""
    def brk(ctx):
        p = project(ctx)
        f = inside(ctx.work, p.root / (rel(p) if callable(rel) else rel))
        old = f.read_bytes() if f.exists() else None
        ctx.state['saved'] = (f, old, f.stat().st_mode if f.exists() else None)
        if f.exists() and not os.access(f, os.W_OK):
            os.chmod(f, f.stat().st_mode | 0o200)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(make(old))
        if mode:
            os.chmod(f, mode)

    def restore(ctx):
        saved = ctx.state.pop('saved', None)
        if not saved:
            return
        f, data, st = saved
        if data is None:
            f.unlink(missing_ok=True)
            return
        if not os.access(f, os.W_OK):
            os.chmod(f, f.stat().st_mode | 0o200)
        f.write_bytes(data)
        os.chmod(f, st)

    def check(ctx):
        return project(ctx).wt_new()
    return Item(name, title, '特权侧用之前核对', check, brk, restore, ['被改过，不执行', marker])


def first_worktree(p):
    names = p.wtx.worktrees(p.root)
    if not names:
        raise DrillError('假项目里一个工作目录都没有')
    return names[0]


# ---------- 可改范围（每个 AI 步骤结束后核对改动都在范围内） ----------
def scope_setup(ctx):
    r = inside(ctx.work, ctx.work / 'scope-repo')
    rmtree(r)
    (r / 'src').mkdir(parents=True)
    (r / 'src' / 'a.py').write_text('x = 1\n')
    (r / 'docs').mkdir()
    (r / 'docs' / 'rules.md').write_text('规则\n')
    git(ctx.work, 'init', '-q', '-b', 'main', cwd=r)
    git(ctx.work, 'add', '-A', cwd=r); git(ctx.work, 'commit', '-qm', '这一步开始时', cwd=r)
    ctx.state['scope_base'] = git(ctx.work, 'rev-parse', 'HEAD', cwd=r)
    (r / 'src' / 'a.py').write_text('x = 2\n')
    git(ctx.work, 'commit', '-qam', 'AI：在范围里的改动', cwd=r)
    ctx.state['scope_repo'] = r


def scope_check(ctx):
    r = ctx.state['scope_repo']
    args = inside(ctx.work, ctx.work / 'scope-args.json')
    args.write_text(json.dumps({'gitdir': str(r / '.git'), 'worktree': str(r), 'base': ctx.state['scope_base'],
                                'allowed': ['src/**'], 'protected': ['/sop.json']}, ensure_ascii=False))
    rc, text = run_py(ctx, 'checks/scope/check.py', args)
    return rc == 0, text


def scope_break(ctx):
    r = ctx.state['scope_repo']
    (inside(ctx.work, r / 'docs' / 'rules.md')).write_text('规则（AI 顺手放宽了）\n')
    git(ctx.work, 'commit', '-qam', 'AI：顺手改了范围外的文件', cwd=r)


def scope_restore(ctx):
    r = ctx.state.get('scope_repo')
    if r and (r / '.git').exists():
        git(ctx.work, 'checkout', '-q', ctx.state['scope_base'], '--', 'docs/rules.md', cwd=r)
        if git(ctx.work, 'status', '--porcelain', cwd=r):
            git(ctx.work, 'commit', '-qam', '改回去', cwd=r)


# ---------- 清单 ----------
def items():
    t = 'tests/unit/test_basics.py'
    return [
        Item('test-expect', '改掉一个单元测试的预期结果并提交（运行时目录的权限从 700 改成 755）', '单元测试',
             unit_check('test_basics.py'),
             edit_then_commit(t, 'st_mode & 0o777, 0o700)', 'st_mode & 0o777, 0o755)', '测试预期改一下'),
             reset_toolkit, ['FAIL: test_runtime_dir_private']),
        Item('test-skip', '把一个单元测试标成跳过并提交', '单元测试（带 --no-skip，和 GitHub 上一样）',
             unit_check('test_basics.py'),
             edit_then_commit(t, '    def test_runtime_dir_private(self):\n',
                              "    def test_runtime_dir_private(self):\n        self.skipTest('先跳过')\n", '先跳过一个测试'),
             reset_toolkit, ['跳过：', 'test_runtime_dir_private', '先跳过']),
        Item('ci-weaken', '把 GitHub 上单元测试那道检查的 --no-skip 去掉并提交（缺了东西也能悄悄跳过）', '单元测试（核对检查流程的那一组）',
             unit_check('test_ci_workflow.py'),
             edit_then_commit('.github/workflows/check.yml', 'run: uv run python tests/run_all.py --no-skip unit',
                              'run: uv run python tests/run_all.py unit',
                              '检查流程简化一下'),
             reset_toolkit, ['unit 在 GitHub 上不许悄悄跳过']),
        Item('sample-expect', '把一个检查的「应报错」样例改标成「应通过」并提交', '总检查',
             total_check, rename_sample, reset_toolkit, ['不符合', 'scope/pass-']),
        Item('skill-edit', '在技能副本的一个文件末尾加一个换行并提交', '总检查（技能副本逐字比）',
             total_check, edit_skill, reset_toolkit, ['不符合', 'skills_pristine/', '内容改了']),
        Item('doc-path', '在 README 里写一个不存在的文件路径并提交', '文档检查',
             docs_check,
             append_then_commit('README.md', '\n演练：详见 `tests/drill_没有这个文件.py`。\n', '文档补一句'),
             reset_toolkit, ['drill_没有这个文件.py']),
        guard_item('guard-rules', '在 PR 上改规范文件 docs/standards/rules.md，没有放行', 'docs/standards/rules.md',
                   '规范第 1 版（AI 放宽了）\n', 'docs/standards/rules.md'),
        guard_item('guard-checkdef', '在 PR 上把项目检查的定义改成永远通过，没有放行', '.github/workflows/sop-check.yml',
                   'name: sop-check\non: [pull_request]\njobs:\n  fast:\n    runs-on: ubuntu-latest\n    steps:\n      - run: exit 0\n',
                   '.github/workflows/sop-check.yml'),
        file_tamper('wt-hook', '改 wt 钩子 .shared/hooks/post-create（wt new 会带着凭据执行它）', '.shared/hooks/post-create',
                    '.shared/hooks/post-create 和工具包模板不一样', lambda old: old + b'\necho drill >/dev/null\n'),
        file_tamper('git-config', '往项目的 .git/config 里加一条 core.fsmonitor（Git 会执行它）', '.git/config',
                    '.git/config 和特权侧上一次记下的不一样', lambda old: old + b'[core]\n\tfsmonitor = /tmp/drill-fsmonitor\n'),
        file_tamper('git-hook', '在项目的 .git/hooks/ 里放一个会被 Git 执行的钩子 post-checkout', '.git/hooks/post-checkout',
                    '.git/hooks/post-checkout 是一个会被 Git 执行的钩子', lambda old: b'#!/bin/sh\necho drill >/dev/null\n', 0o755),
        file_tamper('worktree-config', '给一个工作目录放「工作目录专用配置」config.worktree',
                    lambda p: f'.git/worktrees/{first_worktree(p)}/config.worktree', 'config.worktree 存在',
                    lambda old: b'[core]\n\tfsmonitor = /tmp/drill-fsmonitor\n'),
        file_tamper('gitfile', '把一个工作目录里指向 .git 的小文件改指到别处', lambda p: f'{first_worktree(p)}/.git',
                    '/.git 的内容不对', lambda old: b'gitdir: /tmp/drill-elsewhere\n'),
        Item('scope', 'AI 在一步里顺手改了可改范围外的文件并提交', '可改范围检查',
             scope_check, scope_break, scope_restore, ['越界', 'docs/rules.md（提交了的改动，不在可改范围）'], setup=scope_setup),
    ]


# ---------- 里层：在 /tmp 的副本里演 ----------
class Ctx:
    def __init__(self, work, out=print):
        self.work = pathlib.Path(work)
        self.toolkit = self.work / 'toolkit'
        self.start = None
        self.wt = shutil.which('wt')
        self.proj = None
        self.state = {}
        self.out = out

    def child_env(self):
        return {**os.environ, 'SOP_TEST_TMP': str(self.work / 'tmp')}


def inner(work, only):
    work = pathlib.Path(work)
    assert_safe(work)
    if real(HERE) != real(work / 'toolkit'):
        raise Refuse(f'里层必须是 /tmp 副本里的那一份（现在是 {HERE}）')
    sys.path.insert(0, str(HERE))
    os.environ['SOP_TEST_TMP'] = str(work / 'tmp')
    import tests  # noqa: F401  自测的保险（3-59）：换成 /tmp 里的假主目录、去掉密钥一类的变量
    assert_safe(work)
    ctx = Ctx(work)
    ctx.start = git(work, 'rev-parse', 'HEAD', cwd=ctx.toolkit)
    chosen = [it for it in items() if not only or it.name in only]
    return summary(run_items(chosen, ctx))


# ---------- 外层：建现场、拷副本、交给副本 ----------
def outer(only, keep):
    src = HERE
    acct = account_home()
    work = pathlib.Path(tempfile.mkdtemp(prefix='sop-drill-', dir=TMP))
    t0 = time.time()
    try:
        home = work / 'home'
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(DROP)}
        env.update({'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_CACHE_HOME': str(home / '.cache'),
                    'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_STATE_HOME': str(home / '.local/state'),
                    'SOP_TEST_TMP': str(work / 'tmp'), 'TMPDIR': str(work / 'tmp'), 'PYTHONDONTWRITEBYTECODE': '1'})
        (work / 'tmp').mkdir()
        old_path = env.get('PATH', '/usr/bin:/bin')
        os.chdir(work)
        os.environ.clear()
        os.environ.update(env)
        assert_safe(work)
        (work / 'gitconfig').write_text(GIT_ID)
        print(f'破坏演练：现场 {work}（演完删掉），主目录 {home}')
        start, n = copy_source(work, src, work / 'toolkit')
        head = read_src(src, 'rev-parse', '--short', 'HEAD').strip()
        print(f'工具包：从 {src}（提交 {head}，含还没提交的改动）拷了 {n} 个文件到 {work / "toolkit"}')
        wt = clone_wt(work, work / 'wt')
        bindir = work / 'bin'
        bindir.mkdir()
        if wt:
            os.symlink(wt, bindir / 'wt')
            print(f'wt：只读克隆了一份到 {wt.parent}')
        else:
            print('wt：这台电脑上找不到，项目那几项会演不下去')
        keep_path = [d for d in old_path.split(os.pathsep) if d and not under(d, acct)]
        os.environ['PATH'] = os.pathsep.join([str(bindir), *keep_path])
        args = [sys.executable, str(work / 'toolkit' / 'tests' / 'drill.py'), '--inner', str(work)]
        if only:
            args += ['--only', ','.join(only)]
        p = subprocess.run(args, cwd=work, env=dict(os.environ), stdin=subprocess.DEVNULL)
        print(f'用时 {round(time.time() - t0)} 秒')
        return p.returncode if p.returncode in (0, 1, 2) else 1
    finally:
        os.chdir(TMP)
        if keep:
            print(f'现场留着：{work}（看完自己删）')
        else:
            rmtree(work)


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)
    if '--list' in argv:
        for it in items():
            print(f'{it.name:16} {it.title}（{it.check_name}）')
        return 0
    only = []
    if '--only' in argv:
        i = argv.index('--only')
        if i + 1 >= len(argv):
            print('--only 后面写项目名，用逗号隔开（--list 看有哪些）'); return 2
        only = [x for x in argv[i + 1].split(',') if x]
        names = {it.name for it in items()}
        bad = [x for x in only if x not in names]
        if bad:
            print(f'没有这几项：{"、".join(bad)}（--list 看有哪些）'); return 2
    try:
        if '--inner' in argv:
            return inner(argv[argv.index('--inner') + 1], only)
        return outer(only, '--keep' in argv)
    except Refuse as e:
        print(f'拒绝执行：{e}')
        return 2
    except DrillError as e:
        print(f'破坏演练演不下去：{e}')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
