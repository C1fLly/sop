"""环境迁移 Q1：清点（设计书 4.8，任务 3-30）。只读：只看、只量、只问 Docker「有什么」，不装、不删、不停、不起任何东西。

清点出来的是一份清单（dict，能存成 JSON 给 Q3、Q6 用）：
- docker：电脑上每一份不在规定位置的 Docker。认得出五种装法加一种「以前卸过、东西还留着」：
    docker.io  Ubuntu 软件源装的（系统自带方式，要管理员）
    docker-ce  照 Docker 官网装的（官方软件源、钥匙文件、containerd.io 等几个包）
    rootless   免管理员的、但位置不对（官方一条命令的装法：程序在 ~/bin，数据在 ~/.local/share/docker，服务名 docker）
    snap       snap 版
    desktop    Docker Desktop
    leftover   软件包已经卸了，数据目录、设置文件还留着
  每一份写明：在哪、哪种装法、占多大（系统自带的连 /var/lib/containerd 一起量，新版本把镜像存在那里）、占不占系统盘、
  卸载要不要管理员密码、第一版能不能自动带走和卸载（snap、Docker Desktop 不能，4.8）；
  它在运行时，列出每个镜像、每个数据卷（大小、属于哪个项目、最近一次用的时间）、每个容器（在不在运行、没放进数据卷的改动多大）；
  再记下这次卸载要清掉的残留清单（Q6 逐项核对：软件包连同随它自动装进来的、系统服务、用户组、数据目录、软件源和钥匙文件等）。
- tools：工具包自己装的那几样（uv、nvm、Node、pnpm、gh、wt）另有一份不在规定位置的：在哪、哪种装法、占多大、
  占不占系统盘、卸载要不要管理员密码。找法和体检一样（locate.find_others）。
- tool_users：其中 nvm、uv、Node、pnpm 的旧的那一份，还有谁在用（users.py，3-60）：装在旧 nvm 的 Node 下或靠它运行的
  AI 工具和命令、旧的里面装着的 Node 版本和全局包、用旧 uv 装的 Python 建的 Python 环境、终端启动文件里指向旧位置的几行等。

不做的事（为了「旧的一样都不动」）：
- 旧的 Docker 没在运行时不去连它（系统自带的那种一连通道就会被系统自动起来），清单里写明「要它运行才列得出」。
- 要管理员密码才看得到的（/var/lib/docker 的大小、不在 docker 组时的镜像和数据卷），只有调用方给了 admin（例如 ['sudo']）才去看；
  没给就写「至少多大」「要管理员密码才看得到」。
- 调 docker 命令时总是明说通道（--host）、用一个现建的空设置目录（--config），不靠、也不碰终端里的默认指向和 ~/.docker。
- 「卸了会连带什么软件包」用 apt-get -s（只模拟，不用管理员、不改任何东西）算。
"""
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time

from kernel import paths

from .. import catalog, locate
from .users import describe as describe_users, find as find_users

DOCKER_IO_PKGS = ('docker.io', 'docker-buildx', 'docker-compose-v2', 'docker-doc')
CE_PKGS = ('docker-ce', 'docker-ce-cli', 'containerd.io', 'docker-buildx-plugin', 'docker-compose-plugin',
           'docker-ce-rootless-extras', 'docker-model-plugin')
DESKTOP_PKGS = ('docker-desktop',)
# apt-get -s 用不了时的退路：第一段 vm-a 实测随 docker.io 自动装进来的几个（审查后-专用Docker的视野和迁移残留.md）
DEPS_HINT = ('containerd', 'runc', 'bridge-utils', 'pigz', 'ubuntu-fan')
ALL_PKGS = DOCKER_IO_PKGS + CE_PKGS + DESKTOP_PKGS + ('containerd', 'runc')
SYSTEM_DATA = ('/var/lib/docker', '/var/lib/containerd')
SYSTEM_CONF = ('/etc/docker', '/etc/default/docker', '/etc/systemd/system/docker.service.d',
               '/etc/systemd/system/docker.socket.d', '/etc/systemd/system/containerd.service.d')
SYSTEM_UNITS = ('docker.service', 'docker.socket', 'containerd.service')
SYSTEM_SOCK = '/var/run/docker.sock'
# 官方免管理员安装脚本放进 ~/bin 的程序（docker-rootless-extras 和 docker 两个压缩包里的）
ROOTLESS_BINS = ('containerd', 'containerd-shim-runc-v2', 'ctr', 'docker', 'docker-init', 'docker-proxy', 'dockerd',
                 'dockerd-rootless-setuptool.sh', 'dockerd-rootless.sh', 'rootlesskit', 'rootlesskit-docker-proxy',
                 'runc', 'vpnkit')
DOCKER_KEYRINGS = ('/etc/apt/keyrings/docker.asc', '/etc/apt/keyrings/docker.gpg',
                   '/usr/share/keyrings/docker-archive-keyring.gpg', '/usr/share/keyrings/docker.gpg')
COMPOSE_PROJECT = 'com.docker.compose.project'
RW_NOTE = 1000 ** 2       # 容器里没放进数据卷的改动到 1 MB 才提醒（运行中的容器总有几 KB 的零碎，清单里照记）
LABELS = {
    'docker.io': 'Ubuntu 软件源装的 Docker（docker.io）',
    'docker-ce': '照 Docker 官网装的 Docker（docker-ce）',
    'rootless': '免管理员的 Docker，但不在规定位置',
    'snap': 'snap 版的 Docker',
    'desktop': 'Docker Desktop',
    'leftover': '以前卸过的 Docker 留下的东西',
}


class Probe:
    """清点时看电脑的那几样手段，单元测试整个换掉：
    root    系统里的路径（/var、/etc、/snap、/opt、/usr）都接在它后面找（测试指到一个临时目录造出来的「系统」）
    home    主目录；runtime 是用户的运行时目录（/run/user/<编号>）
    run     跑命令：run(argv, timeout) -> (退出码, 输出, 报错)
    admin   要管理员密码的命令前面加什么（例如 ['sudo']）；None 就是这一次不用管理员，那些地方写「要管理员密码才看得到」
    usage   量大小（locate.disk_usage）；sysdisk 判断占不占系统盘（locate.SystemDisk）
    """

    def __init__(self, *, root='/', home=None, runtime=None, run=None, admin=None, usage=None, sysdisk=None,
                 user=None, tools=None, path_env=None, now=None, notice=None):
        self.root = root.rstrip('/')
        self.home = (home or os.path.expanduser('~')).rstrip('/')
        self.runtime = runtime or os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
        self._run = run or _subprocess_run
        self.admin = list(admin) if admin else None
        self.usage = usage or locate.disk_usage
        self.sysdisk = sysdisk or locate.SystemDisk()
        self.user = user or _user_name()
        self.tools = str(tools or paths.tools_dir()).rstrip('/')
        self.path_env = path_env
        self.now = time.time() if now is None else now
        self.notice = notice
        self.asked_admin = False
        self.ran = []                 # 跑过的命令（测试核对「没有改东西的命令」用）

    def p(self, path):
        """系统路径在这台（或测试造的）电脑上实际在哪。"""
        return self.root + path if self.root else path

    def h(self, rel):
        return f'{self.home}/{rel}'

    def show(self, real):
        """给人看的路径：去掉测试的根，主目录写成 ~。"""
        if self.root and real.startswith(self.root + '/'):
            real = real[len(self.root):]
        return locate.short(real, self.home)

    def run(self, argv, *, admin=False, timeout=120):
        """跑一条只读的命令。要管理员而这一次不让用时返回 None（不跑）。"""
        if admin:
            if self.admin is None:
                return None
            if not self.asked_admin and self.notice:
                self.notice('有几处只有管理员看得到（系统盘上 Docker 的数据目录、镜像和数据卷），下面会问一次管理员密码，只看不改')
            self.asked_admin = True
            argv = self.admin + list(argv)
        self.ran.append(list(argv))
        return self._run(list(argv), timeout)

    def exists(self, real):
        return os.path.lexists(real)

    def read(self, real):
        try:
            with open(real, encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            return None


def _user_name():
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get('USER', '')


def _subprocess_run(argv, timeout):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DOCKER_')}
    env.update(LC_ALL='C.UTF-8', LANG='C.UTF-8')
    try:
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           errors='replace', timeout=timeout)
    except FileNotFoundError:
        return 127, '', f'没有这个命令：{argv[0]}'
    except OSError as e:
        return 126, '', f'运行不了 {argv[0]}：{e.strerror or e}'
    except subprocess.TimeoutExpired:
        return 124, '', f'{argv[0]} {timeout} 秒没结束'
    return p.returncode, p.stdout, p.stderr


# ---------- 解析命令的输出（单元测试用造出来的输出直接测这些） ----------

def parse_dpkg(out):
    """dpkg-query -W -f '${Package}\\t${Version}\\t${db:Status-Abbrev}\\n' 的输出 -> {包名: (版本, 状态)}。
    只留装着的（状态 i 开头）和卸了但设置文件还在的（rc）；没装的（un、pn）不要。"""
    pkgs = {}
    for line in out.splitlines():
        f = line.split('\t')
        if len(f) != 3:
            continue
        name, ver, st = f[0].split(':')[0], f[1], f[2].strip()
        if st.startswith('i') or st.startswith('h') or st == 'rc':
            pkgs[name] = (ver, st)
    return pkgs


def parse_apt_sim(out):
    """apt-get -s 的输出里要删的包（Remv、Purg 开头的行），去掉 :amd64 这种后缀。"""
    return sorted({m[1].split(':')[0] for m in re.finditer(r'^(?:Remv|Purg) (\S+)', out, re.M)})


def parse_systemctl_show(out):
    """systemctl show -p … 多个服务的输出（空行隔开）-> {服务名: {项: 值}}。"""
    units = {}
    for block in re.split(r'\n\s*\n', out.strip()):
        d = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if d.get('Id'):
            units[d['Id']] = d
    return units


_SIZE = re.compile(r'^\s*([\d.]+)\s*([kKMGTPE]?)(i?)B\s*$')


def parse_human_size(text):
    """docker 显示的大小（「41.21MB」「4.096kB」「0B」，1000 进位；带 i 的 1024 进位）-> 字节；「N/A」等 -> None。"""
    m = _SIZE.match(text or '')
    if not m:
        return None
    base = 1024 if m[3] else 1000
    return int(float(m[1]) * base ** ' KMGTPE'.index((m[2] or ' ').upper()))


def parse_time(text):
    """Docker 的时间（「2026-11-21T03:12:45.123456789Z」「2026-11-21T11:12:45+08:00」）-> 秒；零值、看不懂 -> None。"""
    m = re.match(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:\d\d)$', text or '')
    if not m or m[1].startswith('0001-'):
        return None
    import datetime
    return datetime.datetime.fromisoformat(m[1] + ('+00:00' if m[2] == 'Z' else m[2])).timestamp()


def parse_json(out):
    try:
        return json.loads(out)
    except ValueError:
        return None


def parse_df(out):
    """docker system df -v --format '{{json .}}' -> ({卷名: 字节}, {镜像编号: 字节})。量不出来的不在里面。
    镜像的大小是解开以后的（和 docker images 显示的一样，几个镜像共用的那部分各算一次）。"""
    d = parse_json(out)
    if not isinstance(d, dict):
        return {}, {}
    vols, imgs = {}, {}
    for v in d.get('Volumes') or []:
        n = parse_human_size(v.get('Size'))
        if v.get('Name') and n is not None:
            vols[v['Name']] = n
    for i in d.get('Images') or []:
        n = parse_human_size(i.get('Size'))
        if i.get('ID') and n is not None:
            imgs[i['ID']] = n
    return vols, imgs


def exec_start(unit_text):
    """服务登记文件里 ExecStart= 那一行（多行续接也算）。"""
    text = re.sub(r'\\\n', ' ', unit_text or '')
    m = re.findall(r'^\s*ExecStart\s*=\s*(.+)$', text, re.M)
    return m[-1].strip() if m else ''


def host_in(cmdline):
    m = re.search(r'(?:^|\s)(?:-H|--host)(?:\s+|=)(\S+)', cmdline)
    return m[1] if m else None


# ---------- 各种装法 ----------

def _entry(probe, real, what=''):
    """一处位置：在哪、占多大、占不占系统盘。没有就返回 None。"""
    if not probe.exists(real):
        return None
    size, partial = probe.usage(real)
    if partial and probe.admin is not None:
        r = probe.run(['du', '-s', '-x', '-B1', real], admin=True)
        if r and r[0] == 0 and r[1].split():
            size, partial = int(r[1].split()[0]), False
    e = {'path': probe.show(real), 'size_bytes': size, 'on_system_disk': probe.sysdisk(real)}
    if partial:
        e['size_partial'] = True
    if what:
        e['what'] = what
    return e


def _residue(kind, what, *, admin, note='', **extra):
    """残留清单的一项。extra 是给 Q6（uninstall.py）用的：data=True 是数据目录（先删它、再删程序），
    file 是 apt-line 那一项在哪个文件里。"""
    r = {'kind': kind, 'what': what, 'admin': admin}
    if note:
        r['note'] = note
    r.update(extra)
    return r


def _path_residue(probe, real, admin, note='', **extra):
    return _residue('path', probe.show(real), admin=admin, note=note, **extra) if probe.exists(real) else None


def packages(probe):
    r = probe.run(['dpkg-query', '-W', '-f', '${Package}\t${Version}\t${db:Status-Abbrev}\n', *ALL_PKGS])
    return parse_dpkg(r[1]) if r else {}


def removal(probe, mains):
    """卸掉 mains 时连带删掉的软件包（含 mains 自己）：apt-get -s purge --autoremove 减去本来就会被自动清掉的那些。
    apt-get 用不了时退回：第一段实测的那几个里面装着的、标着「自动装的」。返回 (包名列表, 怎么算出来的)。"""
    base = probe.run(['apt-get', '-s', 'autoremove'])
    sim = probe.run(['apt-get', '-s', 'purge', '--autoremove', *mains])
    if base and sim and base[0] == 0 and sim[0] == 0:
        got = set(parse_apt_sim(sim[1])) - set(parse_apt_sim(base[1]))
        return sorted(got | set(mains)), 'apt-get 模拟'
    auto = probe.run(['apt-mark', 'showauto'])
    autos = set(auto[1].split()) if auto and auto[0] == 0 else set()
    return sorted(set(mains) | {d for d in DEPS_HINT if d in autos}), '按第一段实测的那几个估的'   # showauto 只列装着的


def docker_group(probe):
    text = probe.read(probe.p('/etc/group')) or ''
    m = re.search(r'^docker:[^:]*:\d+:(.*)$', text, re.M)
    if not m:
        return None
    return [x for x in m[1].split(',') if x]


def docker_sources(probe):
    """软件源里指向 download.docker.com 的：(文件或行的残留, 钥匙文件的残留)。"""
    found, keys = [], set()
    d = probe.p('/etc/apt/sources.list.d')
    files = [os.path.join(d, f) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []
    for f in [probe.p('/etc/apt/sources.list')] + files:
        text = probe.read(f)
        if not text or not any('download.docker.com' in ln and not ln.lstrip().startswith('#') for ln in text.splitlines()):
            continue                # 注释掉的那几行不算（Q6 删软件源时只删没注释掉的）
        if f.endswith('/sources.list'):
            found.append(_residue('apt-line', f'{probe.show(f)} 里指向 download.docker.com 的那几行', admin=True,
                                  file=probe.show(f)))
        else:
            found.append(_residue('path', probe.show(f), admin=True, note='Docker 官方的软件源'))
        keys |= set(re.findall(r'signed-by=([^\]\s]+)', text, re.I))
        keys |= {k for k in re.findall(r'^Signed-By:\s*(/\S+)\s*$', text, re.M)}
    keys |= set(DOCKER_KEYRINGS)
    for k in sorted(keys):
        e = _path_residue(probe, probe.p(k), True, '软件源的钥匙文件')
        if e:
            found.append(e)
    return found


def _system_units(probe, names):
    r = probe.run(['systemctl', 'show', '-p', 'Id,LoadState,ActiveState,UnitFileState,FragmentPath', '--', *names])
    return parse_systemctl_show(r[1]) if r and r[0] == 0 else {}


def _user_units(probe, names):
    r = probe.run(['systemctl', '--user', 'show', '-p', 'Id,LoadState,ActiveState,UnitFileState,FragmentPath', '--', *names])
    return parse_systemctl_show(r[1]) if r and r[0] == 0 else {}


def data_root(probe, real):
    """Docker 设置文件（daemon.json）里另指的数据目录；没有、读不出、就是默认位置时返回 None。"""
    d = parse_json(probe.read(real) or '')
    v = d.get('data-root') if isinstance(d, dict) else None
    return v if isinstance(v, str) and v.startswith('/') else None


def _cli(probe, *cands):
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def system_docker(probe, pkgs):
    """docker.io、docker-ce，或者软件包卸了东西还留着（leftover）。都没有返回 None。"""
    has_io = any(pkgs.get(p, ('', ''))[1].startswith('i') for p in DOCKER_IO_PKGS)
    has_ce = any(pkgs.get(p, ('', ''))[1].startswith('i') for p in CE_PKGS)
    sources = docker_sources(probe)
    kind = 'docker.io' if has_io else 'docker-ce' if has_ce else None
    leftover_dirs = [d for d in SYSTEM_DATA + ('/etc/docker',) if probe.exists(probe.p(d))]
    rc_pkgs = [p for p, (_, st) in pkgs.items() if st == 'rc' and p in DOCKER_IO_PKGS + CE_PKGS]
    if kind is None:
        if 'containerd' in pkgs and pkgs['containerd'][1].startswith('i'):
            leftover_dirs = [d for d in leftover_dirs if d != '/var/lib/containerd']   # 别的软件在用 containerd
        if not (leftover_dirs or rc_pkgs or sources):
            return None
        kind = 'leftover'
    inst = {'kind': kind, 'label': LABELS[kind], 'auto': True, 'admin': True}
    main_pkgs = [p for p in (DOCKER_IO_PKGS + CE_PKGS) if p in pkgs and pkgs[p][1].startswith('i')]
    if kind != 'leftover':
        top = 'docker.io' if kind == 'docker.io' else 'docker-ce'
        inst['version'] = pkgs.get(top, pkgs.get('docker-ce-cli', ('', '')))[0]
        inst['packages'] = main_pkgs
    # 数据目录：系统自带的连 /var/lib/containerd 一起量（新版本把镜像存在那里）
    custom = data_root(probe, probe.p('/etc/docker/daemon.json'))
    custom = None if custom in (None, '/var/lib/docker') else custom
    dirs = [_entry(probe, probe.p(d)) for d in SYSTEM_DATA + ('/etc/docker',)]
    if custom:
        dirs.append(_entry(probe, probe.p(custom), '数据（设置文件里另指的位置）'))
    inst['dirs'] = [d for d in dirs if d]
    # 残留清单
    res = []
    if main_pkgs:
        gone, how = removal(probe, main_pkgs)
        inst['removal_from'] = how
        for p in gone:
            note = '随 Docker 自动装进来的' if p not in main_pkgs else ''
            res.append(_residue('package', p, admin=True, note=note))
    else:
        gone = []
    for p in rc_pkgs:
        res.append(_residue('package', p, admin=True, note='卸了，设置文件还在（要连设置一起清掉）'))
    containerd_used = 'containerd' in pkgs and pkgs['containerd'][1].startswith('i')
    containerd_goes = (kind == 'leftover' and not containerd_used) or 'containerd' in gone or 'containerd.io' in gone
    units = _system_units(probe, SYSTEM_UNITS)
    for u in SYSTEM_UNITS:
        if u == 'containerd.service' and not containerd_goes:
            continue
        if units.get(u, {}).get('LoadState') == 'loaded':
            res.append(_residue('service', u, admin=True,
                                note='正在运行' if units[u].get('ActiveState') == 'active' else ''))
    members = docker_group(probe)
    if members is not None:
        res.append(_residue('group', 'docker', admin=True, note=f'组里有 {"、".join(members)}' if members else ''))
    for d in SYSTEM_DATA + SYSTEM_CONF + (('/etc/containerd',) if containerd_goes else ()):
        if d == '/var/lib/containerd' and not containerd_goes:
            continue
        e = _path_residue(probe, probe.p(d), True)
        if e:
            res.append(e)
    if custom:
        e = _path_residue(probe, probe.p(custom), True, '设置文件里另指的数据目录')
        if e:
            res.append(e)
    res += sources
    inst['residue'] = res
    if not containerd_goes and 'containerd' in pkgs:
        inst.setdefault('notes', []).append('containerd 还有别的软件在用，卸 Docker 不会卸它；它的目录 /var/lib/containerd 里可能还有 Docker 的镜像')
    # 在不在运行、怎么连
    svc = units.get('docker.service', {})
    inst['daemon'] = {
        'host': f'unix://{SYSTEM_SOCK}',
        'cli': _cli(probe, probe.p('/usr/bin/docker'), f'{probe.tools}/docker/bin/docker'),
        'running': svc.get('ActiveState') == 'active',
        'needs_admin': not os.access(probe.p(SYSTEM_SOCK), os.W_OK),
    } if kind != 'leftover' else None
    return inst


def rootless_docker(probe):
    """免管理员、但不在规定位置的那一份（官方一条命令装的在 ~/bin；也可能是 docker-ce-rootless-extras 带的）。
    规定位置那份（~/tools/docker）自己的服务不算。"""
    ours = f'{probe.tools}/docker/'
    unit_f = probe.h('.config/systemd/user/docker.service')
    unit_text = probe.read(unit_f)
    start = exec_start(unit_text)
    unit_old = bool(unit_text) and ours not in start
    bins = [b for b in ROOTLESS_BINS if probe.exists(probe.h(f'bin/{b}'))]
    if 'dockerd' not in bins and 'rootlesskit' not in bins and 'dockerd-rootless.sh' not in bins:
        bins = []           # ~/bin 里只有个 docker 命令行之类的，不算一份免管理员的 Docker
    data = probe.h('.local/share/docker')
    custom = data_root(probe, probe.h('.config/docker/daemon.json')) if (bins or unit_old) else None
    if custom and custom.rstrip('/') == data:
        custom = None
    if not (bins or unit_old or probe.exists(data)):
        return None
    inst = {'kind': 'rootless', 'label': LABELS['rootless'], 'auto': True}
    if bins:
        inst['program'] = '~/bin'
    elif '/usr/bin/dockerd-rootless.sh' in start:
        inst['program'] = '/usr/bin（docker-ce-rootless-extras 软件包带的）'
    dirs = [_entry(probe, data, '数据')] + ([_entry(probe, custom, '数据（设置文件里另指的位置）')] if custom else [])
    if bins:
        size = sum((probe.usage(probe.h(f'bin/{b}'))[0] or 0) for b in bins)
        dirs.append({'path': '~/bin', 'what': f'Docker 的程序 {len(bins)} 个', 'size_bytes': size,
                     'on_system_disk': probe.sysdisk(probe.h('bin'))})
    inst['dirs'] = [d for d in dirs if d]
    res = []
    # 先删数据、再删程序（4.8：数据目录里属于容器内部账号的文件，要借旧的 rootlesskit 删）
    for d in (data, custom):
        e = _path_residue(probe, d, False, '先删它，再删程序', data=True) if d else None
        if e:
            res.append(e)
    res += [_residue('path', f'~/bin/{b}', admin=False) for b in bins]
    if unit_old:
        res.append(_residue('path', probe.show(unit_f), admin=False, note='用户级后台服务 docker 的登记文件'))
        for extra in ('.config/systemd/user/docker.service.d', '.config/systemd/user/default.target.wants/docker.service'):
            e = _path_residue(probe, probe.h(extra), False)
            if e:
                res.append(e)
    profile = probe.p('/etc/apparmor.d/' + (probe.h('bin/rootlesskit').lstrip('/').replace('/', '.')))
    e = _path_residue(probe, profile, True, '系统安全规则（官方装法要的那一条）')
    if e:
        res.append(e)
    inst['residue'] = res
    inst['admin'] = any(r['admin'] for r in res)
    host = host_in(start) if unit_old else None
    sock = f'{probe.runtime}/docker.sock'
    running = False
    if unit_old:
        running = _user_units(probe, ['docker.service']).get('docker.service', {}).get('ActiveState') == 'active'
    elif not unit_text and probe.exists(sock):
        running = True      # 没有后台服务、自己在默认通道上跑着
    inst['daemon'] = {
        'host': host or f'unix://{sock}',
        'cli': _cli(probe, probe.h('bin/docker'), probe.p('/usr/bin/docker'), f'{probe.tools}/docker/bin/docker'),
        'running': running, 'needs_admin': False,
    }
    if re.search(r'DOCKER_HOST|\$HOME/bin|~/bin', probe.read(probe.h('.bashrc')) or ''):
        inst.setdefault('notes', []).append('~/.bashrc 里有照官方装法提示加的几行（PATH 加 ~/bin、DOCKER_HOST），卸载时一并看一下')
    return inst


def snap_docker(probe):
    if not (probe.exists(probe.p('/snap/docker')) or probe.exists(probe.p('/var/snap/docker'))):
        return None
    meta = probe.read(probe.p('/snap/docker/current/meta/snap.yaml')) or ''
    m = re.search(r'^version:\s*[\'"]?([^\'"\s]+)', meta, re.M)
    snaps = probe.p('/var/lib/snapd/snaps')
    files = sorted(f for f in os.listdir(snaps) if f.startswith('docker_') and f.endswith('.snap')) if os.path.isdir(snaps) else []
    dirs = [_entry(probe, probe.p('/var/snap/docker'), '数据')] + [_entry(probe, os.path.join(snaps, f), '程序') for f in files]
    res = [_residue('snap', 'docker', admin=True)]
    for d in ('/var/snap/docker', '/snap/docker'):
        e = _path_residue(probe, probe.p(d), True)
        if e:
            res.append(e)
    return {'kind': 'snap', 'label': LABELS['snap'], 'auto': False, 'admin': True, 'version': m[1] if m else '',
            'dirs': [d for d in dirs if d], 'residue': res, 'daemon': None,
            'notes': ['第一版不自动带走它的数据、也不自动卸载（4.8）：要留里面的数据，就先留着它；卸载时工具包打印官方的步骤，由你自己做']}


def desktop_docker(probe, pkgs):
    installed = 'docker-desktop' in pkgs and pkgs['docker-desktop'][1].startswith('i')
    places = [probe.h('.docker/desktop'), probe.p('/opt/docker-desktop')]
    if not (installed or any(probe.exists(p) for p in places)):
        return None
    dirs = [_entry(probe, places[0], '数据（里面的虚拟机磁盘）'), _entry(probe, places[1], '程序')]
    res = [_residue('package', 'docker-desktop', admin=True)] if 'docker-desktop' in pkgs else []
    res += [e for e in (_path_residue(probe, p, p.startswith(probe.p('/opt'))) for p in places) if e]
    return {'kind': 'desktop', 'label': LABELS['desktop'], 'auto': False, 'admin': True,
            'version': pkgs.get('docker-desktop', ('', ''))[0], 'dirs': [d for d in dirs if d], 'residue': res,
            'daemon': None,
            'notes': ['第一版不自动带走它的数据、也不自动卸载（4.8）：要留里面的数据，就先留着它；卸载时工具包打印官方的步骤，由你自己做']}


# ---------- 旧 Docker 里面有什么 ----------

def _name_project(name):
    if re.fullmatch(r'[0-9a-f]{64}', name):
        return ''
    return name.split('_', 1)[0] if '_' in name.strip('_') else ''


def _last(container, now):
    st = container.get('State') or {}
    if st.get('Running'):
        return now
    times = [parse_time(st.get('StartedAt')), parse_time(st.get('FinishedAt'))]
    times = [t for t in times if t]
    return max(times) if times else None


def contents(probe, daemon, df_timeout=600):
    """在旧 Docker 里列镜像、数据卷、容器。返回 {'listed': bool, 'why': 列不出来的原因, 'images', 'volumes', 'containers'}。"""
    out = {'listed': False, 'images': [], 'volumes': [], 'containers': []}
    if not daemon.get('cli'):
        out['why'] = '找不到 docker 命令'
        return out
    if not daemon.get('running'):
        out['why'] = '它现在没在运行，镜像和数据卷要它运行才列得出（清点不去起它：旧的一样都不动）'
        return out
    admin = daemon.get('needs_admin', False)
    if admin and probe.admin is None:
        out['why'] = '要管理员密码才看得到（你不在 docker 组里），这一次没用管理员密码'
        return out
    cfg = tempfile.mkdtemp(prefix='sop-q1-')
    try:
        D = [daemon['cli'], '--config', cfg, '--host', daemon['host']]

        def get(*args, timeout=120):
            return probe.run(D + list(args), admin=admin, timeout=timeout)

        r = get('image', 'ls', '-q', '--no-trunc')
        if not r or r[0] != 0:
            out['why'] = '连不上它：' + ((r[2].strip().splitlines() or ['没有输出'])[0] if r else '没跑')
            return out
        ids = list(dict.fromkeys(r[1].split()))
        cr = get('container', 'ls', '-a', '-q', '--no-trunc')
        cids = cr[1].split() if cr and cr[0] == 0 else []
        vr = get('volume', 'ls', '-q')
        vnames = vr[1].split() if vr and vr[0] == 0 else []
        imgs = (parse_json(get('image', 'inspect', *ids)[1]) or []) if ids else []
        ctrs = (parse_json(get('container', 'inspect', '--size', *cids)[1]) or []) if cids else []
        vols = (parse_json(get('volume', 'inspect', *vnames)[1]) or []) if vnames else []
        dfr = get('system', 'df', '-v', '--format', '{{json .}}', timeout=df_timeout)
        vsize, isize = parse_df(dfr[1]) if dfr and dfr[0] == 0 else ({}, {})
    finally:
        shutil.rmtree(cfg, ignore_errors=True)
    out['listed'] = True
    containers = []
    for c in ctrs:
        cfgd = c.get('Config') or {}
        labels = cfgd.get('Labels') or {}
        st = c.get('State') or {}
        containers.append({
            'id': (c.get('Id') or '')[:12], 'name': (c.get('Name') or '').lstrip('/'),
            'image': cfgd.get('Image') or '', 'image_id': c.get('Image') or '',
            'running': bool(st.get('Running')), 'status': st.get('Status') or '',
            'project': labels.get(COMPOSE_PROJECT, ''), 'service': labels.get('com.docker.compose.service', ''),
            'volumes': [m.get('Name') for m in c.get('Mounts') or [] if m.get('Type') == 'volume' and m.get('Name')],
            'binds': [m.get('Source') for m in c.get('Mounts') or [] if m.get('Type') == 'bind'],
            'size_rw': c.get('SizeRw'), 'last_used': _last(c, probe.now),
            'created': parse_time(c.get('Created')),
        })
    out['containers'] = containers
    for v in vols:
        name = v.get('Name') or ''
        labels = v.get('Labels') or {}
        users = [c for c in containers if name in c['volumes']]
        proj, src = labels.get(COMPOSE_PROJECT, ''), 'label'
        if not proj:
            proj, src = next((c['project'] for c in users if c['project']), ''), 'container'
        if not proj:
            proj, src = _name_project(name), 'name'
        times = [c['last_used'] for c in users if c['last_used']]
        out['volumes'].append({
            'name': name, 'size_bytes': vsize.get(name), 'project': proj, 'project_from': src if proj else '',
            'anonymous': 'com.docker.volume.anonymous' in labels or bool(re.fullmatch(r'[0-9a-f]{64}', name)),
            'driver': v.get('Driver') or '',
            'used_by': [c['name'] for c in users], 'in_use': any(c['running'] for c in users),
            'last_used': max(times) if times else None, 'created': parse_time(v.get('CreatedAt')),
        })
    for i in imgs:
        iid = i.get('Id') or ''
        labels = ((i.get('Config') or {}).get('Labels')) or {}
        users = [c for c in containers if c['image_id'] == iid]
        proj = labels.get(COMPOSE_PROJECT, '') or next((c['project'] for c in users if c['project']), '')
        times = [c['last_used'] for c in users if c['last_used']]
        out['images'].append({
            'id': iid.split(':')[-1][:12], 'tags': i.get('RepoTags') or [], 'size_bytes': isize.get(iid, i.get('Size')),
            'project': proj,
            'used_by': [c['name'] for c in users], 'in_use': any(c['running'] for c in users),
            'last_used': max(times) if times else None, 'created': parse_time(i.get('Created')),
            'tagged_at': parse_time(((i.get('Metadata') or {}).get('LastTagTime'))),
        })
    return out


# ---------- 别的工具的另一份 ----------

def classify(probe, copies):
    """给 locate.find_others 找到的每一份写明是哪种装法、卸载要不要管理员密码。"""
    reals = [c.real for c in copies if not c.real.startswith(probe.home + '/') and not c.real.startswith('/snap/')
             and not c.path.startswith('/snap/')]
    owners = {}
    if reals:
        r = probe.run(['dpkg-query', '-S', *reals])
        for line in (r[1] if r else '').splitlines():
            if ': ' in line and not line.startswith('diversion'):
                pk, path = line.split(': ', 1)
                for p in path.split(', '):
                    owners[p.strip()] = pk.split(',')[0].split(':')[0].strip()
    out = []
    for c in copies:
        d = c.as_record()
        d['path'] = probe.show(c.path)
        if c.inside:
            d['inside'] = probe.show(c.inside)
        if c.real in owners:
            d.update(how='package', how_text=f'系统软件包 {owners[c.real]}（apt 装的）', admin=True, package=owners[c.real])
        elif c.real.startswith('/snap/') or c.path.startswith('/snap/'):
            name = os.path.basename(c.path) if c.path.startswith('/snap/bin/') else c.real.split('/')[2]
            d.update(how='snap', how_text=f'snap 软件包 {name}', admin=True, package=name)
        elif c.real == probe.home or c.real.startswith(probe.home + '/'):
            d.update(how='home', how_text='自己装在主目录里的', admin=False)
        else:
            d.update(how='system-dir', how_text='放在系统目录里的（不是软件包）',
                     admin=not os.access(os.path.dirname(c.real), os.W_OK))
        out.append(d)
    return out


def other_tools(probe, tools=None, find=locate.find_others):
    tools = catalog.load() if tools is None else tools
    taken, out = [], []
    for t in tools:
        if t.name == 'docker' or t.system_package:
            continue
        copies = find(t, taken=taken, path_env=probe.path_env, home=probe.home, usage=probe.usage, sysdisk=probe.sysdisk)
        if copies:
            out.append({'name': t.name, 'what': t.what, 'location': t.location, 'copies': classify(probe, copies)})
    return out


# ---------- 整份清单 ----------

def inventory(probe=None, *, tools=None, find=locate.find_others):
    probe = probe or Probe()
    pkgs = packages(probe)
    dockers = [x for x in (system_docker(probe, pkgs), rootless_docker(probe), snap_docker(probe),
                           desktop_docker(probe, pkgs)) if x]
    for d in dockers:
        d['size_bytes'] = sum(e.get('size_bytes') or 0 for e in d['dirs'])
        d['size_partial'] = any(e.get('size_partial') or e.get('size_bytes') is None for e in d['dirs'])
        d['on_system_disk'] = any(e.get('on_system_disk') for e in d['dirs'])
        if d.get('daemon'):
            d.update(contents(probe, d['daemon']))
    others = other_tools(probe, tools, find)
    return {'made_at': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(probe.now)), 'docker': dockers,
            'tools': others, 'tool_users': find_users(probe, others), 'admin_used': probe.asked_admin}


def save(inv, path=None):
    """存到 ~/tools/sop/config/migrate/inventory.json（0600），Q3、Q6 读它。"""
    paths.guard_home('迁移清点（存清单）')
    path = path or paths.config_dir() / 'migrate' / 'inventory.json'
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = f'{path}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(inv, ensure_ascii=False, indent=1) + '\n')
    os.replace(tmp, path)
    return path


# ---------- 给人看的 ----------

def ago(t, now):
    if t is None:
        return None
    s = max(0, now - t)
    if s < 120:
        return '刚刚'
    for unit, k in (('天', 86400), ('小时', 3600), ('分钟', 60)):
        if s >= k:
            return f'{int(s // k)} {unit}前'


def _when(t, now):
    return f'{time.strftime("%Y-%m-%d", time.localtime(t))}（{ago(t, now)}）'


def _size(e):
    s = locate.human_size(e.get('size_bytes'))
    return f'至少 {s}' if e.get('size_partial') and e.get('size_bytes') is not None else s


def _used(x, now):
    if x.get('in_use'):
        return '正在用'
    if x.get('last_used'):
        return '最近一次用：' + _when(x['last_used'], now)
    return ''


def describe(inv, now=None):
    now = time.time() if now is None else now
    L = []
    ds = inv['docker']
    if not ds:
        L.append('Docker：没找到不在规定位置的 Docker。')
    else:
        L.append(f'Docker：找到 {len(ds)} 份不在规定位置的。')
    for n, d in enumerate(ds, 1):
        L.append('')
        ver = f' {d["version"]}' if d.get('version') else ''
        L.append(f'{n}. {d["label"]}{ver}')
        if d.get('program'):
            L.append(f'   程序在 {d["program"]}')
        if d['kind'] != 'leftover':
            L.append('   卸载' + ('要输管理员密码' if d['admin'] else '不用管理员密码') + '；'
                     + ('工具包能帮你把数据带到规定位置那一份、再卸掉它' if d['auto'] else '第一版不自动带走、不自动卸载'))
        for e in d['dirs']:
            what = f'（{e["what"]}）' if e.get('what') else ''
            disk = '，在系统盘上' if e.get('on_system_disk') else ''
            L.append(f'   {e["path"]}{what}：{_size(e)}{disk}')
        if d['dirs']:
            tail = '，占系统盘' if d['on_system_disk'] else ''
            L.append(f'   合计 {"至少 " if d["size_partial"] else ""}{locate.human_size(d["size_bytes"])}{tail}'
                     + ('（有的地方要管理员密码才量得全）' if d['size_partial'] else ''))
        if d.get('daemon') is not None:
            if not d.get('listed'):
                L.append(f'   镜像、数据卷、容器：没列出来，{d.get("why", "")}')
            else:
                _describe_contents(L, d, now)
        for note in d.get('notes', []):
            L.append(f'   提醒：{note}')
        if d['residue']:
            L.append(f'   卸载时要清掉、卸完逐项核对的（{len(d["residue"])} 项）：')
            for r in d['residue']:
                L.append('     ' + _residue_text(r))
    tools = inv.get('tools') or []
    L.append('')
    if not tools:
        L.append('别的工具：工具包自己装的那几样，没有另一份不在规定位置的。')
    else:
        L.append('别的工具另有一份不在规定位置的：')
        for t in tools:
            for c in t['copies']:
                where = f'（在 {c["inside"]} 里面）' if c.get('inside') else f'，{_size(c)}' + ('，在系统盘上' if c.get('on_system_disk') else '')
                need = '要输管理员密码' if c['admin'] else '不用管理员密码'
                L.append(f'  {t["name"]}：{c["path"]}，{c["how_text"]}{where}；卸载{need}')
    L += describe_users(inv.get('tool_users'))
    return '\n'.join(L)


def _describe_contents(L, d, now):
    imgs, vols, ctrs = d['images'], d['volumes'], d['containers']
    L.append(f'   镜像 {len(imgs)} 个：' if imgs else '   镜像：没有')
    for i in imgs:
        name = '、'.join(i['tags']) or f'（没名字的镜像 {i["id"]}）'
        bits = [locate.human_size(i['size_bytes'])]
        bits.append(f'项目 {i["project"]}' if i['project'] else '看不出属于哪个项目')
        u = _used(i, now)
        bits.append(u + (f'（容器 {"、".join(i["used_by"])}）' if i['used_by'] else '') if u else '现在没有容器用它')
        L.append(f'     {name}：' + '；'.join(bits))
    L.append(f'   数据卷 {len(vols)} 个：' if vols else '   数据卷：没有')
    for v in vols:
        size = locate.human_size(v['size_bytes']) if v['size_bytes'] is not None else '大小量不出来'
        if v['project']:
            how = {'label': '编排文件里写的', 'container': '看用它的容器', 'name': '看名字猜的'}[v['project_from']]
            proj = f'属于项目 {v["project"]}（{how}）'
        else:
            proj = '匿名卷（容器自己建的）' if v['anonymous'] else '看不出属于哪个项目'
        u = _used(v, now) or ('现在没有容器用它，用过它的容器已经删了，最近什么时候用过看不出来' if not v['used_by'] else '还没用过')
        users = f'（容器 {"、".join(v["used_by"])}）' if v['used_by'] else ''
        L.append(f'     {v["name"]}：{size}；{proj}；{u}{users}')
    running = sum(c['running'] for c in ctrs)
    L.append(f'   容器 {len(ctrs)} 个（{running} 个在运行）：' if ctrs else '   容器：没有')
    for c in ctrs:
        st = '在运行' if c['running'] else '停着'
        bits = [f'{st}，镜像 {c["image"]}']
        if c['project']:
            bits.append(f'项目 {c["project"]}')
        if c['volumes']:
            bits.append('用数据卷 ' + '、'.join(c['volumes']))
        if (c['size_rw'] or 0) >= RW_NOTE:
            bits.append(f'容器里有 {locate.human_size(c["size_rw"])} 没放进数据卷的改动，容器不带走，卸载后会丢')
        L.append(f'     {c["name"]}：' + '；'.join(bits))


def _residue_text(r):
    kind = {'package': '软件包', 'service': '系统服务', 'group': '用户组', 'path': '', 'apt-line': '',
            'snap': 'snap 软件包'}[r['kind']]
    note = f'（{r["note"]}）' if r.get('note') else ''
    admin = '，要管理员密码' if r['admin'] else ''
    return f'{kind + " " if kind else ""}{r["what"]}{note}{admin}'


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='python3 -m machine.migrate.inventory', description='环境迁移 Q1：清点（只看不改）')
    ap.add_argument('--json', action='store_true', help='输出整份清单（JSON）')
    ap.add_argument('--admin', action='store_true', help='要管理员密码才看得到的地方也看（会问一次 sudo 密码）')
    ap.add_argument('--save', action='store_true', help='把清单存到 ~/tools/sop/config/migrate/inventory.json')
    a = ap.parse_args(argv)
    probe = Probe(admin=['sudo'] if a.admin else None, notice=lambda s: print(s, flush=True))
    inv = inventory(probe)
    print(json.dumps(inv, ensure_ascii=False, indent=1) if a.json else describe(inv, probe.now))
    if a.save:
        print(f'清单存在 {save(inv)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
