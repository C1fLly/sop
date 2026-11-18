#!/usr/bin/python3
"""第一段：专用 Docker 的白名单换根（照 S9 的改成按项目带参数）。在 Docker 自己的隔离空间里，先把根目录换成只含白名单的目录，再启动 dockerd。
环境变量：SOPD_RD（这个专用 Docker 的数据和运行目录）、SOPD_PROJ（项目根）、SOPD_BIN（Docker 程序目录）"""
import ctypes, os, subprocess, sys
RD = os.environ['SOPD_RD']; PROJ = os.environ['SOPD_PROJ']; BIN = os.environ['SOPD_BIN']; NR = RD + '/newroot'
def sh(*a): subprocess.run(a, check=True)
def ro(p): sh('mount', '--bind', p, p); sh('mount', '-o', 'remount,bind,ro', p)
os.makedirs(NR, exist_ok=True)
sh('mount', '-t', 'tmpfs', '-o', 'mode=755', 'tmpfs', NR)
for d in ('usr', 'etc', 'proc', 'sys', 'dev', 'run', 'tmp', 'var/lib', 'var/tmp', '.old'): os.makedirs(f'{NR}/{d}')
for l in ('bin', 'lib', 'lib64', 'sbin'): os.symlink('usr/' + l, f'{NR}/{l}')
os.symlink('/run', f'{NR}/var/run')
for d in ('usr', 'etc', 'proc', 'sys', 'dev'): sh('mount', '--rbind', '/' + d, f'{NR}/{d}')
sh('mount', '-o', 'remount,bind,ro', f'{NR}/usr')
sh('mount', '-t', 'tmpfs', 'tmpfs', f'{NR}/dev/shm')
sh('mount', '-t', 'tmpfs', 'tmpfs', f'{NR}/run')
sh('mount', '-t', 'tmpfs', '-o', 'mode=1777', 'tmpfs', f'{NR}/tmp')
for src, mode in ((BIN, 'ro'), (RD + '/data', 'rw'), (RD + '/exec', 'rw'), (RD + '/run', 'rw'), (PROJ, 'rw')):
    os.makedirs(NR + src, exist_ok=True); sh('mount', '--rbind', src, NR + src)
    if mode == 'ro': sh('mount', '-o', 'remount,bind,ro', NR + src)
if os.path.isdir(f'{PROJ}/.git'): ro(f'{NR}{PROJ}/.git')
for w in os.listdir(PROJ):
    f = f'{NR}{PROJ}/{w}/.git'
    if os.path.isfile(f): ro(f)
libc = ctypes.CDLL(None, use_errno=True)
os.chdir(NR)
if libc.syscall(155, b'.', b'.old') != 0: raise OSError(ctypes.get_errno(), 'pivot_root 失败')
if libc.umount2(b'/.old', 2) != 0: raise OSError(ctypes.get_errno(), '摘掉旧根失败')
os.chdir('/'); os.rmdir('/.old')
os.execv(BIN + '/dockerd', ['dockerd'] + sys.argv[1:])
