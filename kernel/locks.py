"""同一个项目同一时刻只有一个 sop 在推进流程（设计书 8.4）；端口登记读写时上锁（5.5）。

锁用操作系统的文件锁（flock）：进程不管怎么退出（包括被强制结束），锁都自动放开，不会留下「死锁文件」。
锁文件放在 ~/tools/sop/state/<项目名>/，不在项目根下：那里经专用 Docker 改得了（6.3 二）。
"""
import fcntl
import json
import os
import socket
import time

from . import paths
from .errors import Busy


class ProjectLock:
    """推进流程的锁。拿不到时抛 Busy，调用方转成「只能看」。"""

    def __init__(self, project):
        self.project = project
        self.path = paths.state_dir(project) / 'sop.lock'
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                who = json.loads(os.pread(fd, 4096, 0) or b'{}')
            except ValueError:
                who = {}
            os.close(fd)
            raise Busy(f'另一个窗口正在推进项目 {self.project}（进程 {who.get("pid", "?")}，'
                       f'{who.get("since", "?")} 开始）。这个窗口只能看：sop status、sop cost、sop guide。') from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps({'pid': os.getpid(), 'host': socket.gethostname(),
                                  'since': time.strftime('%Y-%m-%d %H:%M:%S')}).encode(), 0)
        self.fd = fd
        return self

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


class FileLock:
    """等着拿的锁（端口登记这类很快就放开的）。"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
