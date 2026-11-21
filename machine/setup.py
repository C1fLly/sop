"""sop machine setup：把机器流程 M2 到 M7 串起来（设计书 4.5、4.6；3-12）。第零步（M0）之后执行，之后随时可以再执行。

按 4.5 的先后一步一步做，每一步做完跑它的出口检查，过了才做下一步；一步没过就停下，说清是哪一步、为什么、怎么办，
后面的不做（后面几步要靠前面的：M5 取 wt 要 M3 的登录，M6 的自检要 M2 装的 Docker）。

- M2 安装工具（machine/install.py）：清单里第零步、这一步的几样（M0 的 git、curl、uv 照样核对，缺了顺手补）、
  缓存目录、终端启动文件里那一段。出口检查：这些工具符合清单。
- M3 登录 GitHub（machine/ghsetup.py）；M4 登录 AI 工具（machine/aisetup.py）；M5 安装 wt（machine/wtsetup.py）；
  M6 准备受限环境（machine/syscheck.py 的 prepare，隔离自检）；M7 安装全局规则（machine/globalrules.py）。

已经合格的跳过：每一步先跑一遍出口检查，过了就不再做。只有两步例外，因为出口检查本身贵：
- M4 的出口检查每跑一次就真调一次 AI（几美分）。上次在这里自检通过、之后这几样都没变，就不再真调：
  AI 工具程序的实际位置和版本（--version，不花钱）、登记文件（编号、大小、修改时间）、不花钱的那一半检查（文件在、只有自己能读、
  有地址有密钥）、机器级登记里最近一次自检是通过的。哪一样变了，或者加了 --recheck，就真调一次。（3-12 替用户定的，用户可否决。）
- M6 的隔离自检要十几秒、要起一个临时的专用 Docker。系统组件的登记（config/system.json，只在隔离自检通过时写）
  和现在一样，就不再跑；变了（系统升级了）或者加了 --recheck 就跑。和 sop 推进流程之前的判断（3-07）是同一条。

中途断了（关了终端、断电、按了 Ctrl+C）：进度记在 config/setup.json，正在做哪一步先记下来，做完才清掉。
再执行一次，先说一句上次断在哪一步；然后照样从 M2 起逐步核对，合格的跳过，所以自然从断的那一步接着做
（各步自己都能重做：安装脚本先放旁边再换名，登录、登记、写规则都是先查再做）。
同一时刻只能有一个 sop machine setup 在跑（文件锁，进程怎么退出锁都会放开）。
"""
import dataclasses
import fcntl
import json
import os
import pathlib
import sys
import time

from kernel import paths
from kernel.errors import SopError
from . import catalog, config, shellenv

USAGE = '用法：sop machine setup [--recheck]（--recheck：M4 也真调一次 AI 自检、M6 也重跑隔离自检，不管上次通过以后变没变）'
M2_STEPS = ('M0', 'M2')        # M2 核对清单里这两步的工具（M0 的是第零步装的，缺了顺手补）
BUSY = 3
INTERRUPTED = 130


@dataclasses.dataclass
class StepResult:
    ok: bool
    lines: list = dataclasses.field(default_factory=list)   # 给人看的几句（不通过时是原因）
    skipped: bool = False      # 本来就合格，这次什么都没做
    cost: float = 0.0          # 这一步花在 AI 上的钱（工具报告的金额）
    record: dict = dataclasses.field(default_factory=dict)  # 通过时要记进进度的东西


@dataclasses.dataclass
class Ctx:
    recheck: bool
    say: object
    passed: dict               # 上次以前各步通过时记下的（config/setup.json 的 passed）


# ---------- 各步 ----------
def m2_tools():
    return [t for t in catalog.load() if t.step in M2_STEPS]


def m2_problems():
    """M2 的出口检查（加上缓存目录、终端启动文件那一段）：还不合格的几样，大白话。空的就是合格。"""
    out = []
    for t in m2_tools():
        r = catalog.run_check(t)
        if not r.ok:
            out.append(f'{t.name}：{"还没装（规定位置 " + t.location + "）" if not r.installed else f"版本 {r.version_text}，不够清单要的 {t.version}"}')
    tdir = paths.tools_dir()
    missing = [d for d in shellenv.CACHE_DIRS if not (tdir / d).is_dir()]
    if missing:
        out.append(f'缓存目录还没建：{"、".join(missing)}')
    rc = shellenv.rc_file()
    target = os.path.realpath(rc)
    try:
        text, _ = shellenv.read_text(pathlib.Path(target), '终端启动文件')
        if shellenv.apply(text, shellenv.block()) != text:
            out.append(f'终端启动文件 {rc} 里工具包那一段还没写，或者不是最新的')
    except SopError as e:
        out.append(str(e))
    return out


def step_m2(ctx):
    from . import install
    before = m2_problems()
    tools = m2_tools()
    if not before:
        return StepResult(True, [f'清单里这一步的 {len(tools)} 样（{"、".join(t.name for t in tools)}）都在规定位置、版本够，'
                                 '终端启动文件那一段也是最新的'], skipped=True)
    ctx.say('要装或要补的：' + '；'.join(before))
    install.install(tuple(t.name for t in tools))
    after = m2_problems()
    if after:
        return StepResult(False, ['装完核对，还不合格的：'] + [f'  {x}' for x in after])
    return StepResult(True, [f'清单里这一步的 {len(tools)} 样都符合清单了'])


def step_m3(ctx):
    from . import ghsetup
    res = ghsetup.check()
    if res.ok:
        return StepResult(True, ghsetup.report(res), skipped=True)
    res = ghsetup.setup(say=ctx.say)
    return StepResult(res.ok, ghsetup.report(res))


def step_m4(ctx):
    from . import aisetup
    rec = (ctx.passed.get('M4') or {}).get('tools') or {}
    if not ctx.recheck and all(aisetup.still_good(n, rec.get(n)) for n in aisetup.TOOLS):
        labels = '、'.join(s['label'] for s in aisetup.TOOLS.values())
        return StepResult(True, [f'上次在这里自检通过以后，{labels} 的程序、版本、登记的服务地址和密钥都没变：'
                                 '这次不再真调 AI（每调一次花几美分）。想再真调一次：sop machine setup --recheck',
                                 f'  {aisetup.LATER}'], skipped=True)
    res = aisetup.setup(say=ctx.say)
    record = {}
    if res.ok:
        record = {'tools': {n: aisetup.fingerprint(n) for n in aisetup.TOOLS}}
    return StepResult(res.ok, aisetup.report(res), cost=res.cost, record=record)


def step_m5(ctx):
    from . import wtsetup
    res = wtsetup.check()
    if res.ok:
        return StepResult(True, wtsetup.report(res), skipped=True)
    ok, msg = wtsetup.install()
    ctx.say(msg)
    if not ok:
        return StepResult(False, [msg])
    res = wtsetup.check()
    return StepResult(res.ok, wtsetup.report(res))


def step_m6(ctx):
    from . import components, syscheck
    if not ctx.recheck and not config.system_changes(components.collect()):
        return StepResult(True, ['上次隔离自检通过以后，系统组件（内核、bubblewrap、免管理员 Docker 的系统规则、'
                                 '往终端塞按键的开关等）都没变：这次不再跑。想再跑一次：sop machine setup --recheck'], skipped=True)
    ok = syscheck.prepare(out=ctx.say)
    return StepResult(ok, [] if ok else ['隔离自检没通过（上面列了哪几项不符合）'])


def step_m7(ctx):
    from . import globalrules
    ok, rows = globalrules.check()
    if ok:
        return StepResult(True, ['各 AI 工具的全局规则文件里，工具包那一段和工具包里的一字不差'], skipped=True)
    ok1, _ = globalrules.install(out=ctx.say)
    ok2, rows = globalrules.check()
    bad = [f'  {tool}：{globalrules._short(p)}（{globalrules.STATE_TEXT[s]}）' for tool, p, s in rows if s != 'ok']
    return StepResult(ok1 and ok2, [] if ok1 and ok2 else ['还不合格的：'] + bad)


STEPS = (
    ('M2', '安装工具', step_m2),
    ('M3', '登录 GitHub', step_m3),
    ('M4', '登录 AI 工具', step_m4),
    ('M5', '安装 wt', step_m5),
    ('M6', '准备受限环境', step_m6),
    ('M7', '安装全局规则', step_m7),
)


# ---------- 串起来 ----------
def _lock():
    """拿 setup 的锁；另一个 sop machine setup 正在跑就返回 None。
    锁文件不能叫 setup.lock：那是改 setup.json 时 config.editing 自己用的锁，同一个进程里两把锁抢同一个文件会一直等下去。"""
    config._ensure_dir()
    fd = os.open(paths.config_dir() / 'setup-running.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            who = json.loads(os.pread(fd, 4096, 0) or b'{}')
        except ValueError:
            who = {}
        os.close(fd)
        return None, who
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps({'pid': os.getpid(), 'since': time.strftime('%Y-%m-%d %H:%M:%S')}).encode(), 0)
    return fd, None


def _note(**changes):
    with config.editing('setup') as d:
        for k, v in changes.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        return dict(d)


def _names(steps):
    return {code: name for code, name, _ in steps}


def _say(*args):
    print(*args, flush=True)      # 安装脚本、gh 直接往终端写，先把自己的话刷出去，先后才对得上


def run(*, recheck=False, say=_say, steps=STEPS):
    """执行一遍。返回退出码：0 都通过，1 有一步没通过，3 另一个正在跑，130 中途按了 Ctrl+C。
    自测的保险（3-59）：主目录是真的、环境却像在自测里，一开头就抛 paths.HomeGuard，什么都不做（连进度、锁都不写）。"""
    paths.guard_home('sop machine setup')
    fd, who = _lock()
    if fd is None:
        say(f'另一个窗口正在执行 sop machine setup（进程 {who.get("pid", "?")}，{who.get("since", "?")} 开始）。'
            '等它做完再执行；那个窗口要是已经关了，过一会儿再试')
        return BUSY
    try:
        return _run(recheck, say, steps)
    finally:
        os.close(fd)


def _run(recheck, say, steps):
    names = _names(steps)
    prog = config.load('setup')
    prev = prog.get('running')
    if prev:
        say(f'上次执行 sop machine setup 时，「{prev.get("step")} {names.get(prev.get("step"), "")}」那一步没做完就断了'
            f'（{prev.get("since", "")} 开始的）。这次从头逐步核对：已经合格的跳过，从没做完的那一步接着做。')
    passed = dict(prog.get('passed') or {})
    done, cost = [], 0.0
    ctx = Ctx(recheck=recheck, say=say, passed=passed)
    total = len(steps)
    for i, (code, name, fn) in enumerate(steps, 1):
        say(f'\n【第 {i} 步，共 {total} 步】{code} {name}')
        _note(running={'step': code, 'since': config.now(), 'pid': os.getpid()})
        try:
            res = fn(ctx)
        except KeyboardInterrupt:
            say(f'\n在「{code} {name}」这一步中途停了（按了 Ctrl+C）。再执行一次 sop machine setup，做好了的会跳过，从这一步接着做。')
            return INTERRUPTED
        except SopError as e:
            res = StepResult(False, [str(e)])
        cost += res.cost
        for x in res.lines:
            say(x)
        if not res.ok:
            _note(running=None, last={'result': 'stopped', 'step': code, 'at': config.now()})
            say(f'\n停在「{code} {name}」：这一步的出口检查没通过，后面的步骤先不做（后面几步要靠它）。')
            say('按上面说的处理好之后，再执行一次 sop machine setup：做好了的会跳过，从这一步接着做。')
            _summary(say, done, cost)
            return 1
        if res.skipped:
            say(f'{code} {name}：已经合格，跳过')
            entry = passed.get(code) or {}
            entry = {**entry, 'checked_at': config.now()}
        else:
            say(f'{code} {name}：做好了，出口检查通过')
            entry = {'at': config.now(), 'checked_at': config.now(), **res.record}
        passed[code] = entry
        _note(passed=passed)
        done.append((code, name, res.skipped))
    _note(running=None, last={'result': 'ok', 'at': config.now()})
    say('\n这台电脑装好了：M2 到 M7 都通过了。')
    _summary(say, done, cost)
    say('下一步：执行 sop machine doctor 看一遍体检报告；然后新项目执行 sop project new <项目名>，'
        '换了电脑继续旧项目执行 sop project clone <所有者/项目名>。')
    return 0


def _summary(say, done, cost):
    if done:
        say('这次：' + '；'.join(f'{c} {n}{"（本来就合格）" if s else "（这次做的）"}' for c, n, s in done))
    say(f'这次在 AI 自检上一共花了 {cost:.4f} 美元（工具报告的金额）')


def main(argv):
    if argv not in ([], ['--recheck']):
        print(USAGE)
        return 2
    try:
        return run(recheck=bool(argv))
    except paths.HomeGuard as e:
        print(e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
