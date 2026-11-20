#!/usr/bin/python3
"""专用 Docker 的白名单换根（设计书 6.3 二）。由审查后试验的改法版定稿。正式的用户级后台服务和分组见 service.py（3-17），
它把这个文件拷到 ~/tools/docker-sop/<项目名>/dockerd-wrap.py，由 dockerd-rootless.sh 经环境变量 DOCKERD 调用。
要点：
  1. 项目根照样放进去（开起来以后才建的工单目录也看得到），但 .shared 整个盖成只读，只有依赖缓存 .shared/cache 可写。
  试过「换根之后再套一层用户空间，把只读锁死」：dockerd 起不来（进不了它自己的网络空间），放弃。
  所以这里的只读只挡普通容器；要了管理员能力的容器（--privileged）能把它改回可写，特权侧靠「用之前核对指纹」兜住。
  2. 超内存时先杀容器、不杀专用 Docker 自己（3-54）：免管理员的 dockerd 给容器的「先杀谁」分数（oom_score_adj）默认等于它自己的，
  分组超了上限、内核挑第二个时常挑中占内存最多的 dockerd。所以在新根（内存盘）里放一个 runc 外壳 /sop/runc、设成默认的运行时，
  建容器时把容器的分数改成 1000（最先杀）；专用 Docker 自己的几个进程由服务设成 100（普通用户能设的最低，service.py）。
  3. 容器单独一个内存分组（3-55）：服务用 DelegateSubgroup=daemon，专用 Docker 自己的进程在服务分组下的 daemon/ 里；
  这里在服务分组下另建 ctr/，把项目的内存上限（SOPD_MEM）设在 ctr/ 上，runc 外壳建容器时把容器放进 ctr/<容器编号>。
  这样容器超了上限只在 ctr/ 里挑着杀；被杀容器的 containerd-shim、dockerd 收尾要内存记在 daemon/ 上，不会再触发一次、顺带杀掉同项目别的容器。
  每个容器的小组还设 memory.oom.group=1（超内存时整个容器一起杀）：不然吃内存的容器里剩下的进程紧接着又要内存，也会再触发一次。
环境变量：SOPD_RD（这个专用 Docker 的数据和运行目录）、SOPD_PROJ（项目根）、SOPD_BIN（Docker 程序目录）、
  SOPD_MEM（容器合起来的内存上限，字节数或 max）"""
import ctypes, os, re, subprocess, sys
# runc 外壳（改动 2、3）：建容器（--bundle 下的 config.json）、在容器里另起进程（docker exec 的 --process 文件）之前，
# 交给 spec.py 把「先杀谁」分数改成 1000、建容器时把容器的分组指到 ctr/<容器编号>，改不成就不起（不让容器落到 ctr/ 外面），
# 再交给真的 runc。最后一个参数是容器编号（create、run、exec 都是）。单元测试按名字把这两段取出来试。
RUNC_SH = r'''#!/bin/sh
p= c= x=
for a in "$@"; do
  case $p in --bundle) c=$a/config.json ;; --process) x=$a ;; esac
  p=$a
done
if [ -n "$c$x" ]; then /usr/bin/python3 -I -S @SOP@/spec.py "$c" "$x" "$p" || exit 1; fi
exec @BIN@/runc "$@"
'''
SPEC_PY = r'''import json, re, sys
cfg, proc, cid = sys.argv[1:4]
def edit(f, fix):
    with open(f) as h: j = json.load(h)
    fix(j)
    with open(f, 'w') as h: json.dump(j, h, separators=(',', ':'))
def ctr(j):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cid): sys.exit('sop-runc: 容器编号不认识：' + cid)
    j.setdefault('process', {})['oomScoreAdj'] = 1000
    j.setdefault('linux', {})['cgroupsPath'] = 'ctr/' + cid   # 相对 runc 所在分组（daemon/）的上一层，即服务分组下的 ctr/
    # 超内存时整个容器一起杀（3-55）：不然吃内存的容器里剩下的进程（例如管道另一头的 head）紧接着又要内存、又触发一次，
    # 被杀的内存还没还回来，内核按大小在 ctr/ 里再挑，可能挑中别的容器
    r = j['linux'].get('resources') or {}; u = r.get('unified') or {}
    u['memory.oom.group'] = '1'; r['unified'] = u; j['linux']['resources'] = r
if cfg: edit(cfg, ctr)
if proc: edit(proc, lambda j: j.__setitem__('oomScoreAdj', 1000))
'''
RD = os.environ['SOPD_RD']; PROJ = os.environ['SOPD_PROJ']; BIN = os.environ['SOPD_BIN']; NR = RD + '/newroot'
MEM = os.environ['SOPD_MEM']
if not re.fullmatch(r'[1-9][0-9]*|max', MEM): raise SystemExit(f'SOPD_MEM 的写法不对：{MEM!r}')
# 改动 3：容器的分组 ctr/（服务分组下，和专用 Docker 自己的 daemon/ 平级），内存上限设在它上面，不用交换区
own = [l for l in open('/proc/self/cgroup').read().splitlines() if l.startswith('0::')][0][3:]
if os.path.basename(own) != 'daemon': raise SystemExit(f'专用 Docker 不在服务分组的 daemon/ 里（{own}），服务登记少了 DelegateSubgroup=daemon')
SVC = '/sys/fs/cgroup' + os.path.dirname(own); CTR = SVC + '/ctr'
# 服务管理器把服务分组交给我们（Delegate=yes），但不替我们打开下一层的内存、处理器开关：不打开的话 ctr/ 里没有 memory.max
ctl = open(f'{SVC}/cgroup.controllers').read().split()
if 'memory' not in ctl: raise SystemExit(f'服务分组没有交出内存的开关（{SVC} 只有 {ctl}）')
with open(f'{SVC}/cgroup.subtree_control', 'w') as f: f.write(' '.join('+' + c for c in ctl))
os.makedirs(CTR, exist_ok=True)
for k, v in (('memory.max', MEM), ('memory.swap.max', '0')):
    with open(f'{CTR}/{k}', 'w') as f: f.write(v)
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
# 改动 2、3：runc 外壳，放在新根（内存盘）里的 /sop/runc、/sop/spec.py，只读
os.makedirs(f'{NR}/sop')
with open(f'{NR}/sop/runc', 'w') as f: f.write(RUNC_SH.replace('@BIN@', BIN).replace('@SOP@', '/sop'))
with open(f'{NR}/sop/spec.py', 'w') as f: f.write(SPEC_PY)
os.chmod(f'{NR}/sop/runc', 0o555); os.chmod(f'{NR}/sop/spec.py', 0o444)
ro(f'{NR}/sop')
libc = ctypes.CDLL(None, use_errno=True)
os.chdir(NR)
if libc.syscall(155, b'.', b'.old') != 0: raise OSError(ctypes.get_errno(), 'pivot_root 失败')
if libc.umount2(b'/.old', 2) != 0: raise OSError(ctypes.get_errno(), '摘掉旧根失败')
os.chdir('/'); os.rmdir('/.old')
os.execv(BIN + '/dockerd', ['dockerd'] + sys.argv[1:] + ['--add-runtime', 'sop-runc=/sop/runc', '--default-runtime', 'sop-runc'])
