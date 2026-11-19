#!/usr/bin/python3
"""专用 Docker 的白名单换根（设计书 6.3 二）。由审查后试验的改法版定稿。正式的用户级后台服务和分组见 service.py（3-17），
它把这个文件拷到 ~/tools/docker-sop/<项目名>/dockerd-wrap.py，由 dockerd-rootless.sh 经环境变量 DOCKERD 调用。
要点：
  1. 项目根照样放进去（开起来以后才建的工单目录也看得到），但 .shared 整个盖成只读，只有依赖缓存 .shared/cache 可写。
  试过「换根之后再套一层用户空间，把只读锁死」：dockerd 起不来（进不了它自己的网络空间），放弃。
  所以这里的只读只挡普通容器；要了管理员能力的容器（--privileged）能把它改回可写，特权侧靠「用之前核对指纹」兜住。
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
# 改动 1：.shared 盖成只读，依赖缓存从外面的原路径重新绑成可写
if os.path.isdir(f'{PROJ}/.shared'):
    ro(f'{NR}{PROJ}/.shared')
    if os.path.isdir(f'{PROJ}/.shared/cache'): sh('mount', '--bind', f'{PROJ}/.shared/cache', f'{NR}{PROJ}/.shared/cache')
libc = ctypes.CDLL(None, use_errno=True)
os.chdir(NR)
if libc.syscall(155, b'.', b'.old') != 0: raise OSError(ctypes.get_errno(), 'pivot_root 失败')
if libc.umount2(b'/.old', 2) != 0: raise OSError(ctypes.get_errno(), '摘掉旧根失败')
os.chdir('/'); os.rmdir('/.old')
os.execv(BIN + '/dockerd', ['dockerd'] + sys.argv[1:])
