"""系统升级后先重跑隔离自检（设计书 4.5，任务 3-07）。

受限环境和免管理员 Docker 靠系统的几样东西（内核、bubblewrap、系统安全规则、往终端塞按键的开关，见 components.py）。
隔离自检通过时，把这几样当时的版本记进机器级登记 config/system.json。sop 每次要推进流程之前拿现在的和登记比：
- 一样：直接推进。
- 不一样（系统升级了），或者还没登记过：先重跑隔离自检。通过了，记下现在的版本，再推进；
  没通过（或者跑不起来、超时），停下、什么都不推进，交给维修窗口（sop repair）。登记不改，下次 sop 还会重新自检。

只在推进流程的命令（sop、sop answer、sop chat）之前做；看进度、看花费、体检不做。
体检（sop machine doctor）只说哪几样变了、不记，否则先跑一次体检就看不出变化了（3-06）。

隔离自检（M6，3-11）分两份，依次跑、都过了才算通过：
- 本机那份 runner/selftest.py（6.2 的四条要求、6.3 的表、往终端塞按键、状态目录）；
- 专用 Docker 那份 runner/docker/selftest_docker.py（借专用 Docker 用三种挂法改 .shared/hooks、.git/config、.git/hooks，
  特权侧核对要发现；经专用 Docker 看不到 ~/tools/sop、/run/user）。要用规定位置的免管理员 Docker（M2 装的），按正式的服务和分组起一个专用 Docker（项目名 sopdk，3-17），跑完停掉、删掉登记文件。
M6（装机时，prepare()）和这里用的是同一个自检；通过后都把自检之前查到的系统组件记进登记。
测试用：环境变量 SOP_SELFTEST_CMD 换成别的命令（只跑这一条；流程沙箱里用 tests/fakes/selftest/selftest 演通过和不通过）。

直接跑（3-12 的 setup 做好之前，虚拟机验证用）：python3 -m machine.syscheck   就是 M6：跑隔离自检，过了记登记。
"""
import os
import pathlib
import re
import subprocess
import sys

from kernel import paths
from kernel.locks import FileLock

from . import components, config

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY = ('隔离自检：', '专用 Docker 的隔离自检：')   # 两份各自最后一行的开头
TIMEOUT = 900          # 每一份的上限。本机那份一般十几秒；专用 Docker 那份第一次要拉一个小镜像，一两分钟；卡住了不能一直等


def selftest_cmds():
    """隔离自检的几份命令：同一个工具包版本里的本机那份、专用 Docker 那份，用跑 sop 的这个 Python 执行。"""
    cmd = os.environ.get('SOP_SELFTEST_CMD')
    if cmd:
        return [[cmd]]
    return [[sys.executable, '-I', str(TOOLKIT / 'runner' / 'selftest.py')],
            [sys.executable, '-I', str(TOOLKIT / 'runner' / 'docker' / 'selftest_docker.py')]]


def selftest_cmd():
    """第一份（本机那份）的命令。留着给只想跑本机那份的地方用。"""
    return selftest_cmds()[0]


def run_selftest(cmds=None, timeout=TIMEOUT):
    """跑一遍隔离自检（几份依次跑，前一份没过也接着跑完，好一次看全），返回 (都通过没有, 给人看的几行)。"""
    cmds = cmds or selftest_cmds()
    if isinstance(cmds[0], str):            # 只给了一条命令
        cmds = [cmds]
    oks, lines = [], []
    for cmd in cmds:
        ok, part = run_one(cmd, timeout)
        oks.append(ok)
        lines += part
    if len(cmds) > 1:
        lines = [x for x in lines if not x.startswith(SUMMARY)] + [_total(lines, len(cmds))]
    return all(oks), lines


def _total(lines, parts):
    """几份的汇总行合成一行：「隔离自检：N 项，M 项不符合」。有一份没跑完（没有汇总行）就加一句。"""
    n = bad = got = 0
    for x in lines:
        m = re.match(r'(?:隔离自检|专用 Docker 的隔离自检)：(\d+) 项，(\d+) 项不符合', x)
        if m:
            n, bad, got = n + int(m.group(1)), bad + int(m.group(2)), got + 1
    return f'隔离自检：{n} 项，{bad} 项不符合' + ('' if got >= parts else '（有一份没跑完，没算在里面）')


def run_one(cmd, timeout=TIMEOUT):
    """跑一份，返回 (通过没有, 给人看的几行)。退出码 0 才算通过；跑不起来、超时都算没通过。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        took = f'{timeout // 60} 分钟' if timeout >= 60 else f'{timeout} 秒'
        return False, [f'隔离自检超过 {took}还没跑完，按没通过处理。']
    except OSError as e:
        return False, [f'隔离自检跑不起来：{e.strerror or e}。']
    lines = p.stdout.splitlines()
    summary = [x for x in lines if x.startswith(SUMMARY)]
    if p.returncode == 0:
        return True, summary
    bad = [x for x in lines if x.startswith('不符合')]
    if not bad and not summary:
        tail = (p.stderr.strip() or p.stdout.strip() or '没有输出').splitlines()[-3:]
        bad = [f'隔离自检中途出错了（退出码 {p.returncode}）：{pathlib.Path(cmd[-1]).name} 最后几行是'] + [f'  {x}' for x in tail]
    return False, bad + summary


def _changes_text(changes):
    if all(old is None for _, old, _ in changes):
        return '还没有隔离自检通过的记录（这台电脑上第一次推进流程，或者登记被删了）。'
    parts = []
    for k, old, new in changes:
        name = config.SYSTEM_PARTS[k]
        parts.append(f'  {name}：上次是「{old or "没登记"}」，现在是「{new}」')
    return '系统有变化（多半是系统升级了），和上次隔离自检通过时记下的不一样：\n' + '\n'.join(parts)


def gate(collect=components.collect, selftest=run_selftest, out=print):
    """推进流程之前调用。返回 True 就接着推进；False 就停下（已经告诉过人为什么、该怎么办）。"""
    if not config.system_changes(collect()):
        return True                                            # 平常都是这样：只读地比一下，什么都不写
    config._ensure_dir()
    with FileLock(paths.config_dir() / 'selftest.lock'):      # 几个项目同时启动 sop 时只跑一遍：拿到锁再比一次
        now = collect()
        changes = config.system_changes(now)
        if not changes:
            return True
        out(_changes_text(changes))
        out('推进流程之前先重跑一遍隔离自检（看受限环境是不是还挡得住 AI 读凭据、改不该改的东西），要等一会儿……')
        ok, lines = selftest()
        if ok:
            components.record(now)
            out('隔离自检通过' + (f'（{lines[-1].removeprefix("隔离自检：")}）' if lines else '') + '，已记下现在的系统组件版本。接着推进流程。')
            return True
        out('隔离自检没通过：')
        for x in lines:
            out(f'  {x}')
        out('受限环境可能已经挡不住 AI，所以停下了，流程一步都没有推进。')
        out('请启动维修窗口（sop repair），把上面这几行给它看。修好之后再执行 sop，会先重新自检。')
        return False


def prepare(collect=components.collect, selftest=run_selftest, out=print):
    """M6 准备受限环境（设计书 4.5）：不管登记里有没有、变没变，都跑一遍隔离自检；通过了把自检之前查到的系统组件记进登记，
    这样装好机器之后第一次推进流程不用再自检（3-07 留下的）。没通过登记不改。返回通过没有。"""
    config._ensure_dir()
    with FileLock(paths.config_dir() / 'selftest.lock'):
        now = collect()
        out('跑隔离自检（看受限环境挡不挡得住 AI 读凭据、改不该改的东西；专用 Docker 那几项要起一个临时的专用 Docker），要等一会儿……')
        ok, lines = selftest()
        if ok:
            components.record(now)
            out('隔离自检通过' + (f'（{lines[-1].removeprefix("隔离自检：")}）' if lines else '') + '，已记下现在的系统组件版本。')
            return True
        out('隔离自检没通过：')
        for x in lines:
            out(f'  {x}')
        out('受限环境可能挡不住 AI。先别开始做项目；请启动维修窗口（sop repair），把上面这几行给它看。')
        return False


if __name__ == '__main__':
    sys.exit(0 if prepare() else 1)
