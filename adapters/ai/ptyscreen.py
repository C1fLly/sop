"""模拟终端（3-28）：给一个程序配一个假终端，按需要送按键、等屏幕上出现某样东西，记下屏幕上出现过的文字。

用处：
- 适配器的自检：AI 工具升级后，状态目录模板里那几个设置名可能变了，打开一次对话窗口（不发消息）看首次启动的几屏出没出（10.1、W28）；
- 单元测试和真实调用脚本里替小白打字（对话步骤本身在小白真的终端里开，不经过这里）。
照第 0 期 S9 的 ptydrive.py 改的；只用标准库。
"""
import json
import os
import pty
import re
import select
import signal
import struct
import tempfile
import time
import traceback

import fcntl
import termios

# Claude Code 首次启动的几屏（S9、W28 实测见过的，加上程序里同一组对话框的另几句），比对时去掉所有空白
FIRST_RUN = (
    ('Choose the text style', '选界面配色'),
    ('Security notes', '安全提示'),
    ('Quick safety check', '是否信任这个文件夹'),
    ('trust this folder', '是否信任这个文件夹'),
    ('Accessing workspace', '是否信任这个文件夹'),
    ('Bypass Permissions mode', '「不逐条询问」模式的警告'),
    ('Yes, I accept', '「不逐条询问」模式的警告'),
)
# 对话窗口打开、可以打字了：输入框下面那一行「⏵⏵ bypass permissions on」（W28 的屏幕；大小写和警告那一屏不同）
READY = 'bypass permissions on'


def squash(s):
    return re.sub(r'\s+', '', s)


def screen_text(raw):
    """把终端的原始输出变成看得懂的几行字（去掉颜色、光标移动；光标右移当空格）。"""
    s = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    s = re.sub(r'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', '', s)
    s = re.sub(r'\x1b\[[0-9]*C', ' ', s)
    s = re.sub(r'\x1b\[[0-9;]*m', '', s)
    s = re.sub(r'\x1b\[[0-9;?<>=]*[A-Za-z~]', '\n', s)
    s = re.sub(r'\x1b[()][0-9A-B]|\x1b[=>78M]', '', s)
    out = []
    for line in s.replace('\r', '\n').split('\n'):
        line = line.strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return '\n'.join(out)


def first_run_screens(text):
    """屏幕上出现过的首次启动的几屏（给人看的名字，去重、按出现的先后）。"""
    sq = squash(text)
    found = []
    for marker, label in FIRST_RUN:
        if squash(marker) in sq and label not in found:
            found.append(label)
    return found


def is_ready(text):
    return squash(READY) in squash(text)


class Pty:
    """target 是命令（列表）或者一个函数。是函数时在子进程里调它（它的标准输入输出就是这个假终端），
    返回值转成 JSON 交回（self.result）；出错时 self.result 是 {'error': 报错}。"""

    def __init__(self, target, cols=120, rows=40, env=None):
        self.raw = b''
        self.alive = True
        self.status = None
        self.result = None
        self._res_file = None
        self._closed = False
        if callable(target):
            fd, self._res_file = tempfile.mkstemp(prefix='sop-pty-', suffix='.json')
            os.close(fd)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:       # 子进程
            code = 0
            try:
                if env is not None:
                    os.environ.clear()
                    os.environ.update(env)
                if callable(target):
                    r = target()
                    with open(self._res_file, 'w', encoding='utf-8') as fh:
                        json.dump({'value': r}, fh, ensure_ascii=False, default=lambda o: getattr(o, '__dict__', str(o)))
                else:
                    os.execvp(target[0], [str(a) for a in target])
            except BaseException:
                code = 1
                try:
                    with open(self._res_file or os.devnull, 'w', encoding='utf-8') as fh:
                        json.dump({'error': traceback.format_exc()[-2000:]}, fh, ensure_ascii=False)
                except OSError:
                    pass
            os._exit(code)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))

    # ---------- 读 ----------
    def pump(self, secs):
        """读 secs 秒的输出。程序退出了返回 False。"""
        end = time.time() + secs
        while time.time() < end and self.alive:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if not r:
                self._reap()
                continue
            try:
                d = os.read(self.fd, 65536)
            except OSError:
                d = b''
            if not d:
                self.alive = False
                break
            self.raw += d
            # 回答终端能力查询，免得程序干等（S9）
            if b'\x1b[6n' in d:
                os.write(self.fd, b'\x1b[40;1R')
            if b'\x1b[c' in d:
                os.write(self.fd, b'\x1b[?62;c')
        self._reap()
        return self.alive

    def _reap(self):
        if self.status is None:
            try:
                pid, st = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pid, st = self.pid, 0
            if pid:
                self.status = os.waitstatus_to_exitcode(st)
        return self.status

    @property
    def text(self):
        return screen_text(self.raw)

    def text_since(self, mark):
        return screen_text(self.raw[mark:])

    def wait_for(self, cond, timeout):
        """等到 cond(屏幕上的全部文字) 为真，或者程序退出、超时。cond 也可以是一段字（去掉空白后比）。返回是否等到了。"""
        if isinstance(cond, str):
            needle = squash(cond)
            cond = lambda t: needle in squash(t)    # noqa: E731
        end = time.time() + timeout
        while time.time() < end:
            if cond(self.text):
                return True
            if not self.pump(0.3):
                return bool(cond(self.text))
        return bool(cond(self.text))

    # ---------- 写 ----------
    def send(self, keys):
        if self.alive:
            try:
                os.write(self.fd, keys.encode() if isinstance(keys, str) else keys)
            except OSError:
                self.alive = False

    def type_line(self, text, gap=0.8):
        """打一行字再回车（分两次送，免得被当成粘贴、回车变成换行）。"""
        self.send(text)
        self.pump(gap)
        self.send('\r')

    # ---------- 收尾 ----------
    def close(self, wait=10):
        """等程序自己退出（最多 wait 秒），不退就先 SIGTERM 再 SIGKILL。返回退出码。再调一次什么都不做。"""
        if self._closed:
            return self.status
        self._closed = True
        end = time.time() + wait
        while time.time() < end and self._reap() is None:
            self.pump(0.2)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if self._reap() is not None:
                break
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            t = time.time() + 3
            while time.time() < t and self._reap() is None:
                self.pump(0.1)
        if self.status is None:
            try:
                _, st = os.waitpid(self.pid, 0)
                self.status = os.waitstatus_to_exitcode(st)
            except ChildProcessError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        if self._res_file:
            try:
                with open(self._res_file, encoding='utf-8') as fh:
                    self.result = json.load(fh) if os.path.getsize(self._res_file) else None
            except (OSError, ValueError):
                self.result = None
            try:
                os.unlink(self._res_file)
            except OSError:
                pass
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close(wait=0 if exc[0] else 10)
