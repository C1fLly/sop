"""专用 Docker 的正式后台服务和分组（设计书 6.3 二，任务 3-17）。

每个项目一个用户级后台服务 sop-docker-<项目名>.service，放进这个项目自己的分组（slice），内存、处理器的上限设在分组上：
换了根的专用 Docker 连不上服务管理器，给单个容器设的上限不生效；分组上的上限管得住它起的所有容器（第一段实测）。

- 分组的名字：sop-<项目名>.slice，项目名里的「-」写成 \\x2d。服务管理器把分组名里的「-」当成上下级：
  不转写的话 sop-my-app.slice 会落在 sop-my.slice 下面，项目 my 的上限就把项目 my-app 也算进去了。
  转写之后所有项目的分组都直接挂在 sop.slice 下面，互不包含。
- 服务不设成登录后自己起来（没有 [Install]、不 enable）：用户定的「用时才起、闲了停」，起停由 sop 管（3-18 做闲了停）。
- 启动前换根（dockerd_wrap.py，安装时拷到 ~/tools/docker-sop/<项目名>/dockerd-wrap.py）：视野里只有系统程序、
  它自己的数据、这个项目的根；.git、各工作目录里指向 .git 的小文件、.shared（依赖缓存除外）盖成只读；
  看不到 ~/tools/sop（含 state）、/run/user。
- 超内存时先杀容器、不杀专用 Docker 自己（3-54）：服务里的进程「先杀谁」分数设成 100（普通用户能设的最低，系统给用户服务的默认是 200），
  容器的设成 1000（换根脚本放的 runc 外壳改的）。不这样的话容器和 dockerd 分数一样，分组超了上限时内核常挑中占内存最多的 dockerd。
- 服务登记文件只有用户自己能读（0600）：拉镜像的代理写在里面，代理地址里可能带账号密码。
- 数据都在 ~/tools/docker-sop/<项目名>/（data、exec、run），停了、删了登记文件都还在。

用法（虚拟机验证、3-18 之前手动用）：
  python3 -m runner.docker.service install <项目名> <项目根> [--memory 300M] [--cpu 100%]
  python3 -m runner.docker.service start <项目名> <项目根> [...]   装好（有变化才重写）再起，等就绪，打印通道
  python3 -m runner.docker.service stop <项目名>
  python3 -m runner.docker.service remove <项目名>                  停掉、删掉两份登记文件（数据不删）
"""
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


class ServiceError(SopError):
    pass


def default_limits():
    """第一版的默认上限（W8 要到第 2b 期定）：内存是这台电脑的一半，处理器是一半的核（至少 1 核）；不用交换区，超了就被系统杀掉。"""
    return {'memory': '50%', 'cpu': f'{max(1, (os.cpu_count() or 2) // 2) * 100}%'}


def service_name(project):
    return f'sop-docker-{paths.check_project_name(project)}.service'


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


def render(project, root, limits=None, proxy=''):
    """生成两份登记文件的内容，返回 {文件名: 内容}。只生成、不写。"""
    lim = {**default_limits(), **(limits or {})}
    if not MEMORY.fullmatch(str(lim['memory'])):
        raise ServiceError(f'内存上限的写法不对：{lim["memory"]}（要像 300M、2G、50%）')
    if not CPU.fullmatch(str(lim['cpu'])):
        raise ServiceError(f'处理器上限的写法不对：{lim["cpu"]}（要像 100%，100% 是 1 核）')
    sv, sl = service_name(project), slice_name(project)
    rd, b = data_dir(project), docker_bin()
    root = pathlib.Path(root)
    if not root.is_absolute():
        raise ServiceError(f'项目根要写完整路径：{root}')
    RD, BIN, PROJ, HOME = (_path(rd, '专用 Docker 数据目录'), _path(b, 'Docker 程序目录'), _path(root, '项目根'),
                           _path(pathlib.Path.home(), '主目录'))
    if len(RD + LONGEST_SOCK) > SOCK_MAX:
        raise ServiceError(f'项目名 {project} 太长：专用 Docker 的通道路径会超过系统允许的 {SOCK_MAX} 个字符，起不来。换一个短一点的项目名')
    env = [_env_quote('HOME', HOME), _env_quote('PATH', f'{BIN}:/usr/bin:/usr/sbin'),
           _env_quote('XDG_RUNTIME_DIR', f'{RD}/run'), _env_quote('DOCKERD', f'{RD}/dockerd-wrap.py'),
           _env_quote('SOPD_RD', RD), _env_quote('SOPD_PROJ', PROJ), _env_quote('SOPD_BIN', BIN)]
    if proxy:
        env += [_env_quote(k, proxy) for k in ('HTTP_PROXY', 'HTTPS_PROXY')] + [_env_quote('NO_PROXY', 'localhost,127.0.0.1')]
    slice_text = '\n'.join([
        '# 工具包生成的（sop，设计书 6.3 二），不要手改：下次起专用 Docker 时会按工具包的重写。',
        '[Unit]',
        f'Description=SOP 项目 {project} 的资源上限（它的专用 Docker 起的所有容器一起算）',
        '',
        '[Slice]',
        f'MemoryMax={lim["memory"]}',
        'MemorySwapMax=0',
        f'CPUQuota={lim["cpu"]}',
        '']) + '\n'
    service_text = '\n'.join([
        '# 工具包生成的（sop，设计书 6.3 二），不要手改：下次起专用 Docker 时会按工具包的重写。',
        '# 不设成登录后自己起来：sop 要用时才起、闲了停。',
        '[Unit]',
        f'Description=SOP 专用 Docker：{project}（只给受限侧用，和用户自己的 Docker 不相干）',
        '',
        '[Service]',
        f'Slice={sl}',
        *env,
        f'ExecStart={BIN}/dockerd-rootless.sh --data-root {RD}/data --exec-root {RD}/exec '
        f'--host unix://{RD}/run/docker.sock --pidfile {RD}/run/docker.pid',
        'Delegate=yes',
        'KillMode=mixed',
        'Restart=on-failure',
        'OOMScoreAdjust=100',
        'RestartSec=2',
        'TimeoutStartSec=60',
        '']) + '\n'
    return {sl: slice_text, sv: service_text}


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


def install(project, root, limits=None, proxy='', ctl=systemctl):
    """写两份登记文件、拷换根脚本、建数据目录；有变化才写，写了就让服务管理器重读。返回改没改。"""
    files = render(project, root, limits, proxy)
    ud = unit_dir()
    ud.mkdir(parents=True, exist_ok=True)
    rd = data_dir(project)
    for d in (rd, rd / 'data', rd / 'exec', rd / 'run'):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    changed = False
    for name, text in files.items():
        changed |= _write_if_changed(ud / name, text)
    changed |= _write_if_changed(rd / 'dockerd-wrap.py', WRAP.read_text(), 0o700)
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


def start(project, root, limits=None, proxy='', ctl=systemctl, wait=WAIT):
    """装好（有变化才重写）、起来、等就绪，返回通道路径。已经在跑就直接用（登记文件改了的话下次起来才生效）。"""
    install(project, root, limits, proxy, ctl)
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


def stop(project, ctl=systemctl):
    ctl('stop', service_name(project), check=False)


def remove(project, ctl=systemctl):
    """停掉、删掉两份登记文件（数据目录不动）。"""
    stop(project, ctl)
    ud, gone = unit_dir(), False
    for name in (service_name(project), slice_name(project)):
        try:
            (ud / name).unlink()
            gone = True
        except FileNotFoundError:
            pass
    if gone:
        ctl('daemon-reload')
    ctl('reset-failed', service_name(project), check=False)


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
    ap.add_argument('action', choices=('install', 'start', 'stop', 'remove'))
    ap.add_argument('project')
    ap.add_argument('root', nargs='?')
    ap.add_argument('--memory')
    ap.add_argument('--cpu')
    a = ap.parse_args(argv)
    limits = {k: v for k, v in (('memory', a.memory), ('cpu', a.cpu)) if v}
    try:
        if a.action in ('install', 'start') and not a.root:
            raise ServiceError('要给项目根')
        if a.action == 'install':
            print('改了' if install(a.project, a.root, limits, proxy()) else '本来就是最新的')
        elif a.action == 'start':
            print(start(a.project, a.root, limits, proxy()))
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
