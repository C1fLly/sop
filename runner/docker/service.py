"""专用 Docker 的正式后台服务和分组（设计书 6.3 二，任务 3-17）。

每个项目一个用户级后台服务 sop-docker-<项目名>.service，放进这个项目自己的分组（slice），处理器的上限设在分组上：
换了根的专用 Docker 连不上服务管理器，给单个容器设的上限不生效；分组上的上限管得住它起的所有容器（第一段实测）。
- 内存上限只管容器（3-55）：服务分组下分两个小组，专用 Docker 自己的进程在 daemon/（DelegateSubgroup=daemon），
  容器都在 ctr/（换根脚本建、把项目的内存上限写在它上面，runc 外壳建容器时把容器放进去）。
  不这样的话容器和专用 Docker 共用一个上限：内核杀了吃内存的容器后，containerd-shim、dockerd 收尾要的那点内存又触发一次超限，
  被杀的内存还没还回来，内核接着再杀一个，常常是同项目别的容器（3-54 记录）。分开以后它们要内存记在 daemon/ 上，不会再顺带杀容器。
  每个容器还设成「超内存时整个容器一起杀」（memory.oom.group），免得吃内存的容器里剩下的进程又触发一次。
  项目的分组（slice）上只留一道兜底：容器的上限再加 DAEMON_ROOM（专用 Docker 自己平常约 180 MB），防专用 Docker 自己失控。

- 分组的名字：sop-<项目名>.slice，项目名里的「-」写成 \\x2d。服务管理器把分组名里的「-」当成上下级：
  不转写的话 sop-my-app.slice 会落在 sop-my.slice 下面，项目 my 的上限就把项目 my-app 也算进去了。
  转写之后所有项目的分组都直接挂在 sop.slice 下面，互不包含。
- 服务不设成登录后自己起来（没有 [Install]、不 enable）：用户定的「用时才起、闲了停」，起停由 sop 管（3-18，见下）。
- 启动前换根（dockerd_wrap.py，安装时拷到 ~/tools/docker-sop/<项目名>/dockerd-wrap.py）：视野里只有系统程序、
  它自己的数据、这个项目的根；.git、各工作目录里指向 .git 的小文件、.shared（依赖缓存除外）盖成只读；
  看不到 ~/tools/sop（含 state）、/run/user。
- 超内存时先杀容器、不杀专用 Docker 自己（3-54）：服务里的进程「先杀谁」分数设成 100（普通用户能设的最低，系统给用户服务的默认是 200），
  容器的设成 1000（换根脚本放的 runc 外壳改的）。不这样的话容器和 dockerd 分数一样，分组超了上限时内核常挑中占内存最多的 dockerd。
- 服务登记文件只有用户自己能读（0600）：拉镜像的代理写在里面，代理地址里可能带账号密码。
- 数据都在 ~/tools/docker-sop/<项目名>/（data、exec、run），停了、删了登记文件都还在。
- 用时才起、闲了停（3-18，用户定的：sop 退出后 15 分钟没再用就停）：
  - sop 要用时调 use()：先拿这个项目的「在用」锁（~/tools/sop/state/<项目名>/docker.lock，共享锁，几个 sop 可以同时用），
    再起（没在跑才起）、等它答话；sop 退出时放开锁、把锁文件的修改时间记成「最后一次用完」。进程怎么退出（含被强制结束、关掉终端）
    锁都由系统放开。
  - 另有一个计时器 sop-idle-<项目名>.timer（专用 Docker 起来时跟着起：服务的 Wants；它停了计时器跟着停：PartOf），
    每分钟跑一次 idle-stop.sh（拷到数据目录，专用 Docker 的视野里没有它）：
    拿得到独占锁（没有 sop 在用）、且最后一次用完已经过了 15 分钟，就停掉专用 Docker。停的时候拿着锁，sop 这时要用就等它停完再起。
  - sop 每一步要用时把修改时间刷成现在；被强制结束的 sop 来不及记「最后一次用完」，按它最后一步开始用的时间算，
    可能不到 15 分钟就停；停了下次要用再起，数据都在。
  - 登记文件四份：服务、分组、计时器和它触发的那个服务（都 0600，都不 enable）。重启电脑、注销后都不在跑，下次要用时起。
  - 哪些项目要用、上限多少：技术栈档案 toolchain.toml 里有 [docker] 段就用（memory、cpu 可省，省了用默认），
    在工具包里、受限侧改不了；sop 在要运行项目代码时（装依赖、门禁、工单上的实现）才调 use()。

用法（sop 自己用 use()，见 kernel/engine.py 的 docker()；命令行给虚拟机验证用）：
  python3 -m runner.docker.service install <项目名> <项目根> [--memory 300M] [--cpu 100%] [--idle 秒数]
  python3 -m runner.docker.service start <项目名> <项目根> [...]   装好（有变化才重写）再起，等就绪，打印通道
  python3 -m runner.docker.service use <项目名> <项目根> [...]     像 sop 那样拿着「在用」锁起来，打印通道；读到一行（回车）放开
  python3 -m runner.docker.service stop <项目名>
  python3 -m runner.docker.service remove <项目名>                  停掉、删掉四份登记文件（数据不删）
"""
import fcntl
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
from kernel import paths  # noqa: E402
from kernel.errors import SopError  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
WRAP = HERE / 'dockerd_wrap.py'
SAFE_PATH = re.compile(r'^/[A-Za-z0-9/._+@-]+$', re.ASCII)   # 写进登记文件的路径：不用引号、不会被当成替换符号
MEMORY = re.compile(r'^(\d+[KMGT]?|\d{1,2}%|100%|infinity)$')
CPU = re.compile(r'^[1-9]\d{0,4}%$')
SOCK_MAX = 107                                              # 通道文件路径的长度上限（Linux 的 108 字节含结尾的 0）
LONGEST_SOCK = '/exec/containerd/containerd.sock.ttrpc'      # 专用 Docker 自己建的最长的那个通道
WAIT = 60
IDLE = 15 * 60                                              # sop 退出后多久没再用就停（问题 3，用户 2026-11-19 定）
CHECK = 60                                                  # 闲了停的计时器多久看一次
DAEMON_ROOM = 512 * 1024 ** 2                               # 项目分组的兜底上限比容器的上限多留这么多，给专用 Docker 自己（3-55）
UNIT = {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3, 'T': 1024 ** 4}
# 闲了停（3-18）：由计时器每分钟跑一次。参数：服务名、「在用」锁文件、闲多少秒停。
# 没有锁文件（从没经 use() 用过，例如隔离自检、虚拟机里手动 start）就不管；拿不到独占锁就是有 sop 在用，什么都不做；
# 拿到了看锁文件的修改时间（sop 最后一次用完的时间），够久了就停，停完才放开锁（这时 sop 要用就等它停完再起）。
IDLE_SH = r'''#!/bin/sh
svc=$1 lock=$2 idle=$3
[ -f "$lock" ] || exit 0
exec 9<"$lock"
flock -n -x 9 || exit 0
age=$(( $(date +%s) - $(stat -c %Y "$lock") ))
[ "$age" -ge "$idle" ] || exit 0
echo "专用 Docker $svc 已经 $age 秒没有 sop 用了，停掉（数据都还在，下次要用时再起）"
exec systemctl --user stop "$svc"
'''


class ServiceError(SopError):
    pass


def default_limits():
    """第一版的默认上限（W8 要到第 2b 期定）：内存是这台电脑的一半，处理器是一半的核（至少 1 核）；不用交换区，超了就被系统杀掉。"""
    return {'memory': '50%', 'cpu': f'{max(1, (os.cpu_count() or 2) // 2) * 100}%'}


def service_name(project):
    return f'sop-docker-{paths.check_project_name(project)}.service'


def idle_name(project, suffix):
    """闲了停的计时器（.timer）和它触发的服务（.service）。
    不能叫 sop-docker-<项目名>-idle（3-18 原来的名字）：项目 app 的 sop-docker-app-idle.service 就是项目 app-idle 的专用 Docker 服务，
    装一个会把另一个的登记文件盖掉（3-19 验两个项目同时开时发现的）。前缀 sop-idle- 和 sop-docker- 不同，项目名又各不相同，四种名字互不重。"""
    return f'sop-idle-{paths.check_project_name(project)}{suffix}'


def lease_file(project):
    """「在用」锁：sop 用专用 Docker 期间拿着共享锁；修改时间是最后一次用完的时间。在 state 下：受限侧和专用 Docker 都看不到。"""
    return paths.state_dir(project) / 'docker.lock'


def slice_name(project):
    return 'sop-' + paths.check_project_name(project).replace('-', '\\x2d') + '.slice'


def unit_dir():
    """用户级后台服务的登记文件放在哪。测试用 SOP_SYSTEMD_USER_DIR 换成临时目录。"""
    d = os.environ.get('SOP_SYSTEMD_USER_DIR')
    if d:
        return pathlib.Path(d)
    return pathlib.Path(os.environ.get('XDG_CONFIG_HOME') or pathlib.Path.home() / '.config') / 'systemd' / 'user'


def data_dir(project):
    """这个项目的专用 Docker 的数据和运行目录（4.3）。"""
    return paths.tools_dir() / 'docker-sop' / paths.check_project_name(project)


def docker_bin():
    return paths.tools_dir() / 'docker' / 'bin'


def socket(project):
    return data_dir(project) / 'run' / 'docker.sock'


def _path(p, what):
    s = str(p)
    if not SAFE_PATH.fullmatch(s):
        raise ServiceError(f'{what}的路径 {s} 里有空格、引号或别的特殊字符，专用 Docker 的服务登记写不了，没有装')
    return s


def _env_quote(k, v):
    """一行 Environment=，值用双引号括起来；「%」是登记文件里的替换符号，要写成「%%」。"""
    v = v.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return f'Environment="{k}={v}"'


def check_limits(limits):
    """技术栈档案 toolchain.toml 的 [docker] 段（memory = "2G"、cpu = "200%"，都可省）。只认这两项，写法在 render() 里再核。"""
    if limits is None:
        return {}
    if not isinstance(limits, dict) or set(limits) - {'memory', 'cpu'}:
        raise ServiceError(f'技术栈档案 toolchain.toml 的 [docker] 段只能写 memory、cpu 两项：{limits!r}')
    return dict(limits)


def memory_bytes(v):
    """项目的内存上限换成字节数（和服务管理器一样：K、M、G、T 按 1024 算，百分数按这台电脑的物理内存算）；infinity 是 None。"""
    if v == 'infinity':
        return None
    if v.endswith('%'):
        n = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') * int(v[:-1]) // 100
    else:
        n = int(v.rstrip('KMGT')) * UNIT[v[-1] if v[-1] in 'KMGT' else '']
    if n <= 0:
        raise ServiceError(f'内存上限不能是 0：{v}')
    return n


def render(project, root, limits=None, proxy='', idle=IDLE):
    """生成四份登记文件的内容（服务、分组、闲了停的计时器和它触发的服务），返回 {文件名: 内容}。只生成、不写。"""
    lim = {**default_limits(), **check_limits(limits)}
    if not MEMORY.fullmatch(str(lim['memory'])):
        raise ServiceError(f'内存上限的写法不对：{lim["memory"]}（要像 300M、2G、50%）')
    if not CPU.fullmatch(str(lim['cpu'])):
        raise ServiceError(f'处理器上限的写法不对：{lim["cpu"]}（要像 100%，100% 是 1 核）')
    mem = memory_bytes(str(lim['memory']))
    sv, sl = service_name(project), slice_name(project)
    it, isv = idle_name(project, '.timer'), idle_name(project, '.service')
    rd, b = data_dir(project), docker_bin()
    root = pathlib.Path(root)
    if not root.is_absolute():
        raise ServiceError(f'项目根要写完整路径：{root}')
    RD, BIN, PROJ, HOME = (_path(rd, '专用 Docker 数据目录'), _path(b, 'Docker 程序目录'), _path(root, '项目根'),
                           _path(pathlib.Path.home(), '主目录'))
    LOCK = _path(lease_file(project), '「在用」锁文件')
    if not (isinstance(idle, int) and 0 < idle <= 7 * 24 * 3600):
        raise ServiceError(f'闲多久停的写法不对：{idle!r}（秒数）')
    if len(RD + LONGEST_SOCK) > SOCK_MAX:
        raise ServiceError(f'项目名 {project} 太长：专用 Docker 的通道路径会超过系统允许的 {SOCK_MAX} 个字符，起不来。换一个短一点的项目名')
    env = [_env_quote('HOME', HOME), _env_quote('PATH', f'{BIN}:/usr/bin:/usr/sbin'),
           _env_quote('XDG_RUNTIME_DIR', f'{RD}/run'), _env_quote('DOCKERD', f'{RD}/dockerd-wrap.py'),
           _env_quote('SOPD_RD', RD), _env_quote('SOPD_PROJ', PROJ), _env_quote('SOPD_BIN', BIN),
           _env_quote('SOPD_MEM', 'max' if mem is None else str(mem))]
    if proxy:
        env += [_env_quote(k, proxy) for k in ('HTTP_PROXY', 'HTTPS_PROXY')] + [_env_quote('NO_PROXY', 'localhost,127.0.0.1')]
    slice_text = '\n'.join([
        '# 工具包生成的（sop，设计书 6.3 二），不要手改：下次起专用 Docker 时会按工具包的重写。',
        f'# 内存：容器合起来 {lim["memory"]}（换根脚本写在服务分组下的 ctr/ 上），这里是兜底：再多留 {DAEMON_ROOM >> 20}M 给专用 Docker 自己。',
        '[Unit]',
        f'Description=SOP 项目 {project} 的资源上限（它的专用 Docker 起的所有容器一起算）',
        '',
        '[Slice]',
        f'MemoryMax={"infinity" if mem is None else mem + DAEMON_ROOM}',
        'MemorySwapMax=0',
        f'CPUQuota={lim["cpu"]}',
        '']) + '\n'
    service_text = '\n'.join([
        '# 工具包生成的（sop，设计书 6.3 二），不要手改：下次起专用 Docker 时会按工具包的重写。',
        '# 不设成登录后自己起来：sop 要用时才起、闲了停。',
        '[Unit]',
        f'Description=SOP 专用 Docker：{project}（只给受限侧用，和用户自己的 Docker 不相干）',
        f'Wants={it}',
        '',
        '[Service]',
        f'Slice={sl}',
        *env,
        f'ExecStart={BIN}/dockerd-rootless.sh --data-root {RD}/data --exec-root {RD}/exec '
        f'--host unix://{RD}/run/docker.sock --pidfile {RD}/run/docker.pid',
        'Delegate=yes',
        'DelegateSubgroup=daemon',
        'KillMode=mixed',
        'Restart=on-failure',
        'OOMScoreAdjust=100',
        'RestartSec=2',
        'TimeoutStartSec=60',
        '']) + '\n'
    timer_text = '\n'.join([
        '# 工具包生成的（sop，3-18），不要手改。专用 Docker 起来时跟着起（服务的 Wants），专用 Docker 停了它跟着停（PartOf）。',
        '[Unit]',
        f'Description=SOP 专用 Docker 闲了停：{project}（每分钟看一次）',
        f'PartOf={sv}',
        '',
        '[Timer]',
        f'OnActiveSec={CHECK}',
        f'OnUnitActiveSec={CHECK}',
        'AccuracySec=5',
        '']) + '\n'
    idle_text = '\n'.join([
        '# 工具包生成的（sop，3-18），不要手改。没有 sop 在用、最后一次用完已经过了一段时间，就停掉专用 Docker。',
        '[Unit]',
        f'Description=SOP 专用 Docker 闲了停：{project}',
        '',
        '[Service]',
        'Type=oneshot',
        f'ExecStart={RD}/idle-stop.sh {sv} {LOCK} {idle}',
        '']) + '\n'
    return {sl: slice_text, sv: service_text, it: timer_text, isv: idle_text}


def _write_if_changed(target, text, mode=0o600):
    target = pathlib.Path(target)
    try:
        if target.read_bytes() == text.encode() and (target.stat().st_mode & 0o777) == mode:
            return False
    except FileNotFoundError:
        pass
    tmp = target.with_name(f'.{target.name}.sop-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(text.encode())
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, target)
    return True


def systemctl(*args, check=True):
    p = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check and p.returncode:
        raise ServiceError(f'systemctl --user {" ".join(args)} 没成功：{(p.stderr or p.stdout).strip()[-300:]}')
    return p


def install(project, root, limits=None, proxy='', ctl=systemctl, idle=IDLE):
    """写四份登记文件、拷换根脚本和闲了停的脚本、建数据目录；有变化才写，写了就让服务管理器重读。返回改没改。"""
    files = render(project, root, limits, proxy, idle)
    ud = unit_dir()
    ud.mkdir(parents=True, exist_ok=True)
    rd = data_dir(project)
    for d in (rd, rd / 'data', rd / 'exec', rd / 'run'):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    changed = False
    for name, text in files.items():
        changed |= _write_if_changed(ud / name, text)
    changed |= _write_if_changed(rd / 'dockerd-wrap.py', WRAP.read_text(), 0o700)
    changed |= _write_if_changed(rd / 'idle-stop.sh', IDLE_SH, 0o700)
    if changed:
        ctl('daemon-reload')
    return changed


def is_active(project, ctl=systemctl):
    return ctl('is-active', '--quiet', service_name(project), check=False).returncode == 0


def ready(project):
    """通道连得上、专用 Docker 答话了。"""
    try:
        p = subprocess.run([str(docker_bin() / 'docker'), 'info', '--format', '{{.ServerVersion}}'], capture_output=True,
                           text=True, env={**os.environ, 'DOCKER_HOST': f'unix://{socket(project)}'}, stdin=subprocess.DEVNULL,
                           timeout=10)
    except (OSError, subprocess.TimeoutExpired):     # 还没装 Docker、卡住了
        return False
    return p.returncode == 0


def start(project, root, limits=None, proxy='', ctl=systemctl, wait=WAIT, idle=IDLE):
    """装好（有变化才重写）、没在跑就起（闲了停的计时器跟着起）、等就绪，返回通道路径。
    已经在跑就直接用（处理器上限、内存的兜底改了当场生效；容器的内存上限和服务本身的登记改了下次起来才生效）。"""
    install(project, root, limits, proxy, ctl, idle)
    sv = service_name(project)
    if not is_active(project, ctl):
        ctl('reset-failed', sv, check=False)
        ctl('start', '--no-block', sv)
    for _ in range(wait):
        if ready(project):
            return socket(project)
        time.sleep(1)
    if not (docker_bin() / 'dockerd-rootless.sh').exists():
        raise ServiceError(f'专用 Docker（{sv}）起不来：规定位置的免管理员 Docker 没装（{docker_bin()} 下没有 dockerd-rootless.sh），'
                           '先跑 sop machine setup')
    try:
        log = subprocess.run(['journalctl', '--user', '-u', sv, '-n', '30', '--no-pager'], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=10).stdout.strip()[-1500:]
    except (OSError, subprocess.TimeoutExpired):
        log = '（读不到）'
    raise ServiceError(f'专用 Docker（{sv}）{wait} 秒没起来。系统日志最后几行：\n{log}')


class Lease:
    """sop 在用专用 Docker（拿着「在用」锁）。release() 放开，并把锁文件的修改时间记成最后一次用完的时间。"""

    def __init__(self, project, fd, sock):
        self.project, self.fd, self.sock = project, fd, sock

    def touch(self):
        """还在用：把「最后一次用」记成现在（sop 每一步要用时调，被强制结束时算到最后一步开始的时候）。"""
        if self.fd is not None:
            os.utime(self.fd)

    def release(self):
        if self.fd is None:
            return
        try:
            os.utime(self.fd)
        finally:
            os.close(self.fd)
            self.fd = None


def use(project, root, limits=None, proxy='', ctl=systemctl, wait=WAIT, idle=IDLE):
    """sop 要用专用 Docker 时调：拿「在用」锁（闲了停正在停它时等它停完）、起来、等就绪。返回 Lease，用完 release()。"""
    f = lease_file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.utime(fd)
        sock = start(project, root, limits, proxy, ctl, wait, idle)
    except BaseException:
        os.close(fd)
        raise
    return Lease(project, fd, sock)


def stop(project, ctl=systemctl):
    """停掉专用 Docker（闲了停的计时器跟着停）。"""
    ctl('stop', service_name(project), idle_name(project, '.timer'), check=False)


def remove(project, ctl=systemctl):
    """停掉、删掉四份登记文件（数据目录不动）。"""
    stop(project, ctl)
    ud, gone = unit_dir(), False
    for name in (service_name(project), slice_name(project), idle_name(project, '.timer'), idle_name(project, '.service')):
        try:
            (ud / name).unlink()
            gone = True
        except FileNotFoundError:
            pass
    if gone:
        ctl('daemon-reload')
    ctl('reset-failed', service_name(project), idle_name(project, '.service'), check=False)


def proxy():
    """拉镜像用的代理：SOPD_PROXY 给了就用它，否则用网络设置里的（读不出来就不用）。"""
    if 'SOPD_PROXY' in os.environ:
        return os.environ['SOPD_PROXY']
    try:
        from machine import config
        net = config.network()
    except Exception:          # 登记坏了也不挡；拉不下镜像时 Docker 会明说
        return ''
    return net.get('https_proxy') or net.get('http_proxy') or ''


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='python3 -m runner.docker.service', description='专用 Docker 的正式后台服务和分组')
    ap.add_argument('action', choices=('install', 'start', 'use', 'stop', 'remove'))
    ap.add_argument('project')
    ap.add_argument('root', nargs='?')
    ap.add_argument('--memory')
    ap.add_argument('--cpu')
    ap.add_argument('--idle', type=int, default=IDLE)
    a = ap.parse_args(argv)
    limits = {k: v for k, v in (('memory', a.memory), ('cpu', a.cpu)) if v}
    try:
        if a.action in ('install', 'start', 'use') and not a.root:
            raise ServiceError('要给项目根')
        if a.action == 'install':
            print('改了' if install(a.project, a.root, limits, proxy(), idle=a.idle) else '本来就是最新的')
        elif a.action == 'start':
            print(start(a.project, a.root, limits, proxy(), idle=a.idle))
        elif a.action == 'use':
            lease = use(a.project, a.root, limits, proxy(), idle=a.idle)
            print(lease.sock, flush=True)
            try:
                sys.stdin.readline()
            finally:
                lease.release()
        elif a.action == 'stop':
            stop(a.project)
        else:
            remove(a.project)
    except (ServiceError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
