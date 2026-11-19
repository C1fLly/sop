"""系统升级后先重跑隔离自检（设计书 4.5，任务 3-07）。

受限环境和免管理员 Docker 靠系统的几样东西（内核、bubblewrap、系统安全规则、往终端塞按键的开关，见 components.py）。
隔离自检通过时，把这几样当时的版本记进机器级登记 config/system.json。sop 每次要推进流程之前拿现在的和登记比：
- 一样：直接推进。
- 不一样（系统升级了），或者还没登记过：先重跑隔离自检。通过了，记下现在的版本，再推进；
  没通过（或者跑不起来、超时），停下、什么都不推进，交给维修窗口（sop repair）。登记不改，下次 sop 还会重新自检。

只在推进流程的命令（sop、sop answer、sop chat）之前做；看进度、看花费、体检不做。
体检（sop machine doctor）只说哪几样变了、不记，否则先跑一次体检就看不出变化了（3-06）。

隔离自检现在用的是 runner/selftest.py（本机那份，6.2 的四条要求、6.3 的表）；M6 的正式做法在 3-11。
测试用：环境变量 SOP_SELFTEST_CMD 换成别的命令（流程沙箱里用 tests/fakes/selftest/selftest 演通过和不通过）。
"""
import os
import pathlib
import subprocess
import sys

from kernel import paths
from kernel.locks import FileLock

from . import components, config

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent
TIMEOUT = 900          # 本机那份自检一般十几秒；卡住了不能一直等


def selftest_cmd():
    """跑隔离自检的命令：同一个工具包版本里的 runner/selftest.py，用跑 sop 的这个 Python 执行。"""
    cmd = os.environ.get('SOP_SELFTEST_CMD')
    return [cmd] if cmd else [sys.executable, '-I', str(TOOLKIT / 'runner' / 'selftest.py')]


def run_selftest(cmd=None, timeout=TIMEOUT):
    """跑一遍隔离自检，返回 (通过没有, 给人看的几行)。退出码 0 才算通过；跑不起来、超时都算没通过。"""
    cmd = cmd or selftest_cmd()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        took = f'{timeout // 60} 分钟' if timeout >= 60 else f'{timeout} 秒'
        return False, [f'隔离自检超过 {took}还没跑完，按没通过处理。']
    except OSError as e:
        return False, [f'隔离自检跑不起来：{e.strerror or e}。']
    lines = p.stdout.splitlines()
    summary = [x for x in lines if x.startswith('隔离自检：')]
    if p.returncode == 0:
        return True, summary
    bad = [x for x in lines if x.startswith('不符合')]
    if not bad and not summary:
        tail = (p.stderr.strip() or p.stdout.strip() or '没有输出').splitlines()[-3:]
        bad = [f'隔离自检中途出错了（退出码 {p.returncode}）：'] + [f'  {x}' for x in tail]
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
