#!/usr/bin/python3
"""专用 Docker 的白名单换根（改法试验版，针对第一段结束审查的严重 1）。
和第一段那一份的差别：
  1. 项目根照样放进去（开起来以后才建的工单目录也看得到），但 .shared 整个盖成只读，只有依赖缓存 .shared/cache 可写。
  2. 换根之后，再套一层「用户空间」，然后才启动 dockerd。这样外面这一层设的只读，在 dockerd 和它起的容器里是锁死的：
     就算容器要了管理员能力（--privileged），也改不回可写，也摘不掉盖在上面的那一层。
环境变量：SOPD_RD（这个专用 Docker 的数据和运行目录）、SOPD_PROJ（项目根）、SOPD_BIN（Docker 程序目录）"""
import ctypes, os, signal, subprocess, sys
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
# 改动 2：再套一层用户空间（身份照原样对应），让上面设的只读在里面锁死
CLONE_NEWUSER, CLONE_NEWNS = 0x10000000, 0x00020000
def span(f):  # 这一层用户空间里能用的编号一共多少个
    return max(int(a) + int(n) for a, _, n in (l.split() for l in open(f)))
nu, ng = span('/proc/self/uid_map'), span('/proc/self/gid_map')
r1, w1 = os.pipe(); r2, w2 = os.pipe()
pid = os.fork()
if pid == 0:
    if libc.unshare(CLONE_NEWUSER | CLONE_NEWNS) != 0: raise OSError(ctypes.get_errno(), '套用户空间失败')
    os.write(w1, os.readlink('/proc/self').encode()); os.read(r2, 1)  # 报出自己在这份进程表里的编号
    os.execv(BIN + '/dockerd', ['dockerd'] + sys.argv[1:])
ppid = os.read(r1, 32).decode()
print('调试：外层能力', [l for l in open('/proc/self/status') if l.startswith(('CapEff','NSpid','Uid'))], '对应表', open('/proc/self/uid_map').read().split(), '子进程', ppid, pid, file=sys.stderr, flush=True)
for f, n in (('uid_map', nu), ('gid_map', ng)):
    fd = os.open(f'/proc/{ppid}/{f}', os.O_WRONLY); print('调试：打开了', f, file=sys.stderr, flush=True)
    try: os.write(fd, f'0 0 {n}\n'.encode())
    except OSError as e:
        print('调试：整段写不进，改只写 1..', e, file=sys.stderr, flush=True); raise
    os.close(fd)
os.write(w2, b'1')
for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(s, lambda n, _f: os.kill(pid, n))
while True:
    try: _, st = os.waitpid(pid, 0); break
    except InterruptedError: continue
sys.exit(os.waitstatus_to_exitcode(st))
