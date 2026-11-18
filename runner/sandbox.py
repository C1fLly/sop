"""启动受限环境（bubblewrap）。"""
import subprocess

from . import placement


def tiocsti_disabled():
    """内核已禁用「往终端里塞按键」（6.3 三；Ubuntu 26.04 默认禁用）。对话步骤的前提。"""
    try:
        return open('/proc/sys/dev/tty/legacy_tiocsti').read().strip() == '0'
    except OSError:
        return False


def argv(ctx, cmd):
    return ['bwrap', *placement.build(ctx), '--', *map(str, cmd)]


def run(ctx, cmd, timeout=None, input=None, capture=True):
    if ctx.interactive and not tiocsti_disabled():
        raise RuntimeError('这台电脑的内核没有禁用「往终端里塞按键」，对话步骤不能在受限环境里安全地启动（6.3 三）')
    return subprocess.run(argv(ctx, cmd), capture_output=capture, text=True, timeout=timeout, input=input,
                          stdin=None if input is not None or ctx.interactive else subprocess.DEVNULL)
