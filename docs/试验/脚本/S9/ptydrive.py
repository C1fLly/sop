#!/usr/bin/env python3
"""给一个程序配一个假终端，按剧本送按键，把屏幕上出现过的文字打出来。
用法: ptydrive.py <记录文件> <剧本.json> -- <命令...>
剧本是一个列表，每项 [等几秒, "要送的按键"或 null]。"""
import os, pty, sys, time, json, select, re, fcntl, termios, struct, signal
log, script = sys.argv[1], json.load(open(sys.argv[2])); cmd = sys.argv[sys.argv.index('--') + 1:]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(cmd[0], cmd)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
raw = b''
def pump(secs):
    global raw
    end = time.time() + secs
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try: d = os.read(fd, 65536)
            except OSError: return False
            if not d: return False
            raw += d
            # 回答终端能力查询，免得程序干等
            if b'\x1b[6n' in d: os.write(fd, b'\x1b[40;1R')
            if b'\x1b[c' in d: os.write(fd, b'\x1b[?62;c')
    return True
def text(b):
    s = b.decode('utf-8', 'replace')
    s = re.sub(r'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', '', s); s = re.sub(r'\x1b\[[0-9]*C', ' ', s); s = re.sub(r'\x1b\[[0-9;]*m', '', s); s = re.sub(r'\x1b\[[0-9;?<>=]*[A-Za-z]', '\n', s); s = re.sub(r'\x1b[()][0-9A-B]|\x1b[=>78M]', '', s)
    out = []
    for l in s.replace('\r', '\n').split('\n'):
        l = l.strip()
        if l and (not out or out[-1] != l): out.append(l)
    return out
alive = True
for i, (wait, keys) in enumerate(script):
    mark = len(raw)
    if keys is not None: os.write(fd, keys.encode())
    alive = pump(wait)
    lines = text(raw[mark:])
    print(f'--- 第 {i} 步（送了 {keys!r}，等 {wait} 秒）屏幕上新出现的文字（最后 14 行）'); print('\n'.join(lines[-14:])); sys.stdout.flush()
    if not alive: print('（程序已退出）'); break
open(log, 'wb').write(raw)
if alive:
    try: os.kill(pid, signal.SIGTERM)
    except Exception: pass
try: _, st = os.waitpid(pid, os.WNOHANG); print('退出状态', st)
except Exception: pass
