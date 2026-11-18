"""端口登记（设计书 5.5）：每个工作目录建立时分配一组端口，删除时归还。

登记在 ~/tools/sop/config/ports.json，机器级的。几个项目的 sop 可能同时分配，读写时先上锁。
分配前另外试一下端口是不是真的没人在用（别的程序可能占着登记里没有的端口）。
"""
import json
import os
import socket

from . import paths
from .locks import FileLock

FIRST, LAST, BLOCK = 20000, 29999, 10


def _file():
    return paths.config_dir() / 'ports.json'


def _load():
    f = _file()
    return json.loads(f.read_text()) if f.exists() else {}


def _save(d):
    f = _file()
    tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True))
    os.replace(tmp, f)


def _free(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def allocate(project, worktree, count=BLOCK):
    """给 <项目>/<工作目录> 一组连续的端口。已经分配过就返回原来那组。"""
    key = f'{paths.check_project_name(project)}/{worktree}'
    with FileLock(paths.config_dir() / 'ports.lock'):
        d = _load()
        if key in d:
            return d[key]
        used = {p for ports in d.values() for p in ports}
        for start in range(FIRST, LAST + 1 - count, BLOCK):
            block = list(range(start, start + count))
            if not used.intersection(block) and all(_free(p) for p in block):
                d[key] = block
                _save(d)
                return block
    raise RuntimeError('端口登记里已经没有空的端口段了')


def release(project, worktree):
    key = f'{project}/{worktree}'
    with FileLock(paths.config_dir() / 'ports.lock'):
        d = _load()
        if d.pop(key, None) is not None:
            _save(d)


def all_allocations():
    return _load()
