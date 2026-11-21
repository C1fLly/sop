"""环境迁移 Q6：卸载旧的 Docker、切 docker 命令的默认指向（设计书 4.8；3-32）。旧的 nvm、uv、pnpm 在 oldtools.py（3-61）。

只卸 Q3 里选了「卸掉」的那几份。规矩（4.8）：
- 带了数据的那份（有能连的 Docker 程序的）只在 carry.json 的 ready_for_q6 是真时才卸：选了带走的都备份、试还原、核对过了
  （没选带走任何东西的，flow 也记 ready_for_q6）。迁移停掉的旧容器还没起回来（stopped.json）时不卸。
- 卸之前逐条打印要删什么，再确认一次，默认「不卸」；要管理员的先说一句，再由系统问密码。
- 系统自带的（docker.io、docker-ce、以前卸过留下的）：停服务 → 卸软件包，连同 Q1 算出来随它装进来的（一个一个点名，
  不用 --autoremove，免得顺手卸掉别的「没人要了」的包）→ 删数据和设置目录、软件源、钥匙文件 → 删 docker 用户组 → 重新载入服务登记。
- 免管理员但位置不对的：停掉、取消它的用户级服务 → 先删数据（里面有属于容器内部账号的文件，自己删不掉就借 rootlesskit 删）
  → 再删 ~/bin 里的程序和服务登记 → 删那条系统安全规则（要管理员）→ 规定位置那份原来用 sop-docker 这个名字的，接过 docker
  这个服务名和通道（/run/user/<编号>/docker.sock），~/tools/docker/etc/docker-host 跟着改；接不过去就退回 sop-docker。
- snap 版、Docker Desktop：第一版不自动卸，只打印官方的卸载步骤。
- 默认指向（docker context）：卸之前它若指着新的，先切回原来那份（卸到一半停下时，敲 docker 看到的还是原来那份）；
  卸完、旧的程序确实没了，再切到新的。指着别的（另一份留着的 Docker、远程的）不动。
- 卸完按 Q1 记下的残留清单逐项再看一遍：不空就如实列出还剩哪几样、怎么自己清掉，不说「卸完了」；规定位置那份要仍然过检查。
- 删东西之前核对路径：根目录、太靠近根的、主目录和它上面的、~/tools 里面的，一律不删（列为残留）。
- 软件包卸掉以后还留着的运行时目录、通道（/run/docker、/var/run/docker.sock、/opt/containerd 等）照删；/etc/cni 这种别的软件
  也可能用的，只在空的时候删（rmdir），里面有别的东西就不算残留（3-33）。

结果记在 ~/tools/sop/config/migrate/uninstall.json。
"""
import json
import os
import shutil
import subprocess
import time

from kernel import paths

from .. import catalog, locate
from . import carry as C, inventory, record
from .dockercli import ADMIN, Daemon, first_line, new_daemon

DROP, CARRY = 'remove', 'carry'           # 和 flow.py 的一样（flow 引用这个模块，这里不反过来引用它）
SYSTEM_KINDS = ('docker.io', 'docker-ce', 'leftover')
MAIN_PKGS = inventory.DOCKER_IO_PKGS + inventory.CE_PKGS
SYSTEM_HOST = f'unix://{inventory.SYSTEM_SOCK}'
# 规定位置那份用 sop-docker 这个名字时，服务登记里比用 docker 这个名字多的四行（machine/install/docker-rootless.sh）
SOP_UNIT_LINES = ('Environment=XDG_RUNTIME_DIR=%t/sop-docker', 'Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus',
                  'RuntimeDirectory=sop-docker', 'RuntimeDirectoryMode=0700')
APT_LINE_SED = r'/^[[:space:]]*[^#[:space:]].*download\.docker\.com/d'     # 只删没注释掉的那几行
ACTIVE = ('active', 'activating', 'deactivating', 'reloading')
MANUAL = {
    'snap': ['sudo snap remove --purge docker'],
    'desktop': ['sudo apt remove docker-desktop', 'rm -r $HOME/.docker/desktop', 'sudo rm /usr/local/bin/com.docker.cli',
                'sudo apt purge docker-desktop'],
}
MANUAL_DOC = {'snap': 'https://snapcraft.io/docs/removing-snaps', 'desktop': 'https://docs.docker.com/desktop/uninstall/'}


def _subprocess(argv, timeout):
    env = {k: v for k, v in os.environ.items() if not k.startswith('DOCKER_')}
    env.update(LC_ALL='C.UTF-8', LANG='C.UTF-8')
    try:
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace',
                           timeout=timeout)
    except FileNotFoundError:
        return 127, '', f'没有这个命令：{argv[0]}'
    except subprocess.TimeoutExpired:
        return 124, '', f'{argv[0]} {timeout} 秒没结束'
    return p.returncode, p.stdout, p.stderr


class Machine:
    """Q6 动这台电脑的手段，单元测试整个换掉：
    probe   清点用的那个（root、home、runtime、tools；卸完再看残留也用它，只读）
    run     跑一条会改东西的命令：run(argv, timeout) -> (退出码, 输出, 报错)
    admin   要管理员的命令前面加什么（默认 sudo -p 中文提示）
    new     找规定位置那份 Docker（dockercli.new_daemon）；check 跑清单里 docker 的检查命令"""

    def __init__(self, probe, *, run=None, admin=None, sleep=time.sleep, new=new_daemon, check=None, config_dir=None):
        self.probe, self.sleep, self.new = probe, sleep, new
        self._run = run or _subprocess
        self.admin = list(admin) if admin else list(ADMIN)
        self.check = check or _check_docker
        self.config_dir = config_dir or os.environ.get('DOCKER_CONFIG') or probe.h('.docker')
        self.ran = []

    def cmd(self, argv, *, admin=False, timeout=1800):
        argv = (self.admin if admin else []) + list(argv)
        self.ran.append(argv)
        return self._run(argv, timeout)

    def real(self, what):
        """残留清单里给人看的路径 -> 这台（或测试造的）电脑上实际在哪。"""
        if what.startswith('~/'):
            return self.probe.h(what[2:])
        if what.startswith('/'):
            return self.probe.p(what)
        return None


def _check_docker():
    t = next((t for t in catalog.load() if t.name == 'docker'), None)
    return catalog.run_check(t).ok if t else False


# ---------- 删之前核对路径 ----------

def unsafe(m, what):
    """这个路径不该删时返回原因（大白话），能删返回 None。"""
    rel = what[1:] if what.startswith('~/') else what          # ~/x 按 /x 核对写法
    if not rel.startswith('/') or os.path.normpath(rel) != rel:
        return '路径写法不对'
    if not what.startswith('~/') and rel.count('/') < 2:
        return '太靠近根目录'
    p = os.path.normpath(m.real(what))
    home, tools = m.probe.home.rstrip('/'), m.probe.tools.rstrip('/')
    if p == home or home.startswith(p + '/'):
        return '是主目录或主目录上面的目录'
    if p == tools or p.startswith(tools + '/') or tools.startswith(p + '/'):
        return '在工具包的目录 ~/tools 里（规定位置那份 Docker 的数据就在这里）'
    return None


# ---------- 卸完再看一遍残留 ----------

def still_there(m, residue):
    """逐项看还在不在。返回 [(项, 原因)]：原因是空的就是还在；「查不了：…」是看不出来（也算不空）。只读。"""
    p = m.probe
    left = []
    pkgs = [r['what'] for r in residue if r['kind'] == 'package']
    if pkgs:
        r = p.run(['dpkg-query', '-W', '-f', '${Package}\t${Version}\t${db:Status-Abbrev}\n', *pkgs])
        if not r or r[0] not in (0, 1) or (r[0] == 1 and not r[1] and 'no packages found' not in (r[2] or '')):
            why = f'查不了：{first_line(r[2]) if r else "没跑"}'
            have = None
        else:
            have, why = inventory.parse_dpkg(r[1]), ''
    units = [r['what'] for r in residue if r['kind'] == 'service']
    if units:
        r = p.run(['systemctl', 'show', '-p', 'Id,LoadState,ActiveState', '--', *units])
        shown = inventory.parse_systemctl_show(r[1]) if r and r[0] == 0 else None
    for it in residue:
        k, what = it['kind'], it['what']
        if k == 'package':
            if have is None:
                left.append((it, why))
            elif what in have:
                left.append((it, ''))
        elif k == 'service':
            info = shown.get(what) if shown is not None else None
            if info is None:
                left.append((it, '查不了：systemctl 没回答'))
            elif info.get('LoadState') != 'not-found':       # loaded、masked（指向 /dev/null 的登记）等都算还在
                left.append((it, ''))
        elif k == 'group':
            if inventory.docker_group(p) is not None:
                left.append((it, ''))
        elif k == 'path':
            real = m.real(what)
            if real is None:
                left.append((it, ''))
            elif os.path.lexists(real) and it.get('empty_only'):
                # 是空的才删的目录（/etc/cni 等）：里面有东西就是别的软件的，不算 Docker 的残留
                r = m.cmd(['find', real, '-mindepth', '1', '-maxdepth', '1', '-print', '-quit'], admin=bool(it.get('admin')),
                          timeout=60)
                if r[0] != 0:
                    left.append((it, f'查不了：{first_line(r[2])}'))
                elif not r[1].strip():
                    left.append((it, ''))
            elif os.path.lexists(real):
                left.append((it, ''))
        elif k == 'apt-line':
            real = m.real(it.get('file') or '')
            if real is None:
                left.append((it, '查不了：不知道是哪个文件'))
                continue
            text = p.read(real) or ''
            if any('download.docker.com' in ln and not ln.lstrip().startswith('#') for ln in text.splitlines()):
                left.append((it, ''))
        elif k == 'snap':
            if os.path.lexists(p.p('/snap/docker')):
                left.append((it, ''))
        else:
            left.append((it, '查不了：不认识这一项'))
    return left


def _manual(it):
    """还剩的这一项，小白自己怎么清掉。"""
    k, w = it['kind'], it['what']
    if k == 'package':
        return f'sudo apt purge {w}'
    if k == 'service':
        return f'sudo systemctl disable --now {w}'
    if k == 'group':
        return f'sudo groupdel {w}'
    if k == 'path':
        return ('sudo ' if it.get('admin') else '') + (f'rmdir {w}' if it.get('empty_only') else f'rm -rf {w}')
    if k == 'apt-line':
        return f"sudo sed -i '{APT_LINE_SED}' {it.get('file', '')}"
    if k == 'snap':
        return 'sudo snap remove --purge docker'
    return ''


def _old_gone(d, left):
    """旧的这份的程序是不是确实没了（这时才把默认指向切到新的、才接过服务名）。"""
    if d['kind'] == 'leftover':
        return True
    if d['kind'] in SYSTEM_KINDS:
        return not any(it['kind'] == 'package' and (it['what'] in MAIN_PKGS or why) for it, why in left)
    if d['kind'] == 'rootless':
        return not any(it['kind'] == 'path' and not it.get('data') and not it.get('admin') for it, _ in left)
    return False


# ---------- 默认指向（docker context） ----------

class Pointer:
    """docker 命令的默认指向：用规定位置的 docker 命令、明说设置目录（~/.docker），环境里的 DOCKER_HOST、DOCKER_CONTEXT 去掉。"""

    def __init__(self, m, cli):
        self.m, self.cli = m, cli

    def _d(self, *args):
        return self.m.cmd([self.cli, '--config', self.m.config_dir, *args], timeout=60)

    def current(self):
        """(名字, 通道)；看不出来返回 None。"""
        rc, out, _ = self._d('context', 'show')
        name = out.strip()
        if rc != 0 or not name:
            return None
        rc, out, _ = self._d('context', 'inspect', name, '--format', '{{.Endpoints.docker.Host}}')
        return (name, out.strip()) if rc == 0 else None

    def find(self, host):
        rc, out, _ = self._d('context', 'ls', '--format', '{{.Name}}|{{.DockerEndpoint}}')
        if rc != 0:
            return None
        for line in out.splitlines():
            name, _, ep = line.partition('|')
            if ep.strip() == host:
                return name.strip()
        return None

    def to(self, host, prefer='rootless'):
        """切到指着 host 的那一个；没有就新建（名字 rootless，已被占了就用 sop-rootless）。返回 (成没成, 名字或原因)。"""
        name = self.find(host)
        if name is None:
            rc, _, _ = self._d('context', 'inspect', prefer)
            name = prefer if rc != 0 else 'sop-rootless'
            rc, _, err = self._d('context', 'create', name, '--description', 'SOP 规定位置的免管理员 Docker（~/tools/docker）',
                                 '--docker', f'host={host}')
            if rc != 0:
                return False, first_line(err)
        return self.use(name)

    def use(self, name):
        rc, _, err = self._d('context', 'use', name)
        return (True, name) if rc == 0 else (False, first_line(err))


def _dead(m, host):
    """通道是本机的文件、而文件不在了：指着它的默认指向已经没用。"""
    return host.startswith('unix://') and not os.path.exists(m.probe.p(host[len('unix://'):]))


# ---------- 卸系统自带的 ----------

def _step(m, say, text, argv, *, admin=False, fail=None):
    say(f'  {text}……')
    rc, out, err = m.cmd(argv, admin=admin)
    if rc == 0:
        return True
    say(f'    没成：{(fail(rc) if fail else "") or first_line(err or out)}')
    return False


def _apt_failure(rc):
    if rc == 75:
        return '系统正在自己更新软件、占着软件包的锁，等了好几分钟还没做完。过一会儿再执行一次 sop machine migrate 就行'
    if rc == 100:
        return None          # apt 自己的报错更说明问题
    return f'密码不对、这个账号不能用 sudo，或者不是在终端里运行的（退出码 {rc}）'


def _purge_matches(m, pkgs, say):
    """真卸之前再用 apt-get -s（只模拟，不用管理员）算一遍：卸这几个包会不会连带卸掉清单上没列的。
    会的话（清点之后又装了依赖它们的软件）一样不动、说清楚——屏幕上打印的「要删什么」必须就是真要删的。"""
    r = m.probe.run(['apt-get', '-s', 'purge', *pkgs])
    if not r or r[0] != 0:
        say(f'  卸之前想再核对一遍要卸哪些软件包，没核对成（{first_line(r[2]) if r else "没跑"}），一样都没动。')
        return False
    extra = sorted(set(inventory.parse_apt_sim(r[1])) - set(pkgs))
    if extra:
        say(f'  卸这几个软件包还会连带卸掉上面没列的 {"、".join(extra)}（多半是清点之后又装了用到 Docker 的软件），'
            '一样都没动。要卸的话再执行一次 sop machine migrate，会重新清点、重新列出来。')
        return False
    return True


def _still_installed(m, pkgs):
    """pkgs 里现在还装着的（Q1 之后小白可能自己卸了；没装的不能写「包名+」，不然 apt 会去装它）。"""
    if not pkgs:
        return []
    r = m.probe.run(['dpkg-query', '-W', '-f', '${Package}\t${Version}\t${db:Status-Abbrev}\n', *pkgs])
    have = inventory.parse_dpkg(r[1]) if r else {}
    return [p for p in pkgs if have.get(p, ('', ''))[1].startswith('i')]


def _paths(m, res, *, admin):
    ok, bad = [], []
    for it in res:
        if it['kind'] == 'path' and bool(it.get('admin')) == admin and not it.get('empty_only'):
            why = unsafe(m, it['what'])
            (bad if why else ok).append((it, why))
    return ok, bad


def _remove_system(m, d, say):
    res = d['residue']
    units = [r['what'] for r in res if r['kind'] == 'service']
    pkgs = [r['what'] for r in res if r['kind'] == 'package']
    ok_paths, _ = _paths(m, res, admin=True)
    # 工具包自己要用、随 Docker 装进来的（git 等，3-34）：和卸载同一次 apt 里写「包名+」，标成手动装的、不卸
    held = _still_installed(m, d.get('keep_pkgs') or []) if pkgs else []
    args = pkgs + [f'{p}+' for p in held]
    if pkgs and not _purge_matches(m, args, say):
        return False          # 一样都没动
    if units:   # 没停成也往下：卸软件包时系统会再停一次
        _step(m, say, f'停掉旧 Docker 的系统服务 {"、".join(units)}', ['systemctl', 'stop', *units], admin=True)
    if pkgs:
        from ..install import APT_SH
        script = APT_SH.read_text() + '\nsop_apt purge -y -qq "$@"\n'
        keep = f'；工具包要用的 {"、".join(held)} 不卸、标成「手动装的」' if held else ''
        if not _step(m, say, f'卸软件包 {"、".join(pkgs)}（连同设置一起清掉）{keep}',
                     ['env', 'DEBIAN_FRONTEND=noninteractive', 'NEEDRESTART_SUSPEND=1', 'sh', '-c', script, 'sop-apt', *args],
                     admin=True, fail=_apt_failure):
            return False      # 软件包没卸掉就不删它的数据目录（它可能还在用）
    if ok_paths:
        if not _step(m, say, f'删掉 {"、".join(it["what"] for it, _ in ok_paths)}',
                     ['rm', '-rf', '--', *[m.real(it['what']) for it, _ in ok_paths]], admin=True):
            return False
    empties = [it for it in res if it['kind'] == 'path' and it.get('empty_only') and not unsafe(m, it['what'])]
    if empties:     # rmdir 只删空目录：里面有别的软件的东西就留着（按清单的先后，先里面再外面）
        _step(m, say, f'删掉空目录 {"、".join(it["what"] for it in empties)}（不是空的就留着）',
              ['rmdir', '--ignore-fail-on-non-empty', '--', *[m.real(it['what']) for it in empties]], admin=True)
    for it in res:
        if it['kind'] == 'apt-line':
            _step(m, say, f'从 {it["file"]} 里删掉指向 download.docker.com 的那几行',
                  ['sed', '-i', APT_LINE_SED, m.real(it['file'])], admin=True)
    if any(r['kind'] == 'group' for r in res):
        _step(m, say, '删掉用户组 docker', ['groupdel', 'docker'], admin=True)
    if units or ok_paths:
        _step(m, say, '让系统重新读一遍服务登记', ['systemctl', 'daemon-reload'], admin=True)
    return True


# ---------- 卸免管理员但位置不对的 ----------

def _rm_user(real):
    if os.path.islink(real) or not os.path.isdir(real):
        os.unlink(real)
    else:
        shutil.rmtree(real)


def _remove_rootless(m, d, say):
    p = m.probe
    res = d['residue']
    unit = p.h('.config/systemd/user/docker.service')
    if any(m.real(r['what']) == unit for r in res if r['kind'] == 'path'):
        if not _step(m, say, '停掉旧的这份 Docker，取消它登录后自己起来', ['systemctl', '--user', 'disable', '--now', 'docker.service']):
            return False
        st = inventory._user_units(p, ['docker.service']).get('docker.service', {})
        if st.get('ActiveState') in ACTIVE:
            say('    它还在运行，没停下来。没往下删。')
            return False
    ok_paths, _ = _paths(m, res, admin=False)
    data = [it for it, _ in ok_paths if it.get('data')]
    rest = [it for it, _ in ok_paths if not it.get('data')]
    for it in data:           # 先删数据、再删程序：数据目录里有属于容器内部账号的文件，自己删不掉时借 rootlesskit 删
        real = m.real(it['what'])
        say(f'  删掉数据目录 {it["what"]}……')
        try:
            _rm_user(real)
        except OSError as e:
            rk = next((c for c in (p.h('bin/rootlesskit'), f'{p.tools}/docker/bin/rootlesskit')
                       if os.path.isfile(c) and os.access(c, os.X_OK)), None)
            if rk is None:
                say(f'    没删完（{e.strerror or e}），也找不到 rootlesskit 帮忙删。')
                return False
            say(f'    里面有属于容器内部账号的文件，自己删不掉（{e.strerror or e}），借 {locate.short(rk, p.home)} 删')
            rc, out, err = m.cmd([rk, 'rm', '-rf', real])
            if rc != 0 or os.path.lexists(real):
                say(f'    还是没删完：{first_line(err or out)}')
                return False
    if rest:
        say(f'  删掉旧的程序和服务登记 {"、".join(it["what"] for it in rest)}……')
        for it in rest:
            try:
                _rm_user(m.real(it['what']))
            except FileNotFoundError:
                pass
            except OSError as e:
                say(f'    {it["what"]} 没删掉：{e.strerror or e}')
    _step(m, say, '让系统重新读一遍用户级服务登记', ['systemctl', '--user', 'daemon-reload'])
    ok_admin, _ = _paths(m, res, admin=True)
    for it, _ in ok_admin:      # 那条系统安全规则：先从系统里拿掉，再删文件
        real = m.real(it['what'])
        m.cmd(['apparmor_parser', '-R', real], admin=True)
        _step(m, say, f'删掉系统安全规则 {it["what"]}', ['rm', '-f', '--', real], admin=True)
    return True


def take_over_name(m, new, say):
    """规定位置那份原来用 sop-docker 这个名字（旧的占着 docker）：旧的卸掉后接过 docker 这个服务名和通道。
    返回接过之后的 Daemon；不用接返回 new；没接过去返回 None（已经退回 sop-docker，说清楚了）。"""
    p = m.probe
    units = p.h('.config/systemd/user')
    sop_f, doc_f = f'{units}/sop-docker.service', f'{units}/docker.service'
    if '/sop-docker/' not in new.host:
        return new
    try:
        with open(sop_f, encoding='utf-8') as f:
            text = f.read()
    except OSError:
        say(f'找不到 {locate.short(sop_f, p.home)}，没接过 docker 这个服务名，规定位置那份照旧用 sop-docker。')
        return None
    if f'ExecStart={p.tools}/docker/bin/dockerd-rootless.sh' not in text:
        say(f'{locate.short(sop_f, p.home)} 不是工具包写的那样，没接过 docker 这个服务名。')
        return None
    if os.path.lexists(doc_f):
        say(f'{locate.short(doc_f, p.home)} 还在（旧的服务登记没删掉），没接过 docker 这个服务名，规定位置那份照旧用 sop-docker。')
        return None
    host = f'unix://{p.runtime}/docker.sock'
    say('  规定位置那份 Docker 接过 docker 这个服务名和通道（会停一下再起来，里面的容器按各自的重启设置回来）……')
    out = '\n'.join(ln for ln in text.splitlines() if ln.strip() not in SOP_UNIT_LINES) + '\n'
    m.cmd(['systemctl', '--user', 'disable', '--now', 'sop-docker.service'])
    with open(doc_f + '.sop-tmp', 'w', encoding='utf-8') as f:
        f.write(out)
    os.replace(doc_f + '.sop-tmp', doc_f)
    m.cmd(['systemctl', '--user', 'daemon-reload'])
    rc, _, err = m.cmd(['systemctl', '--user', 'enable', '--now', 'docker.service'])
    got = Daemon(new.cli, host, label=new.label)
    up = False
    try:
        if rc == 0:
            for _ in range(30):
                if got.ok('version'):
                    up = True
                    break
                m.sleep(1)
    finally:
        got.close()
    if not up:
        say(f'    没接过去（{first_line(err) if rc else "起来以后 30 秒还连不上"}），退回原来的 sop-docker。')
        m.cmd(['systemctl', '--user', 'disable', '--now', 'docker.service'])
        os.unlink(doc_f)
        m.cmd(['systemctl', '--user', 'daemon-reload'])
        m.cmd(['systemctl', '--user', 'enable', '--now', 'sop-docker.service'])
        return None
    hf = f'{p.tools}/docker/etc/docker-host'
    with open(hf + '.tmp', 'w') as f:
        f.write(host + '\n')
    os.replace(hf + '.tmp', hf)
    os.unlink(sop_f)
    m.cmd(['systemctl', '--user', 'daemon-reload'])
    say(f'    接过来了：服务名 docker，通道 {host}')
    return Daemon(new.cli, host, label=new.label)


# ---------- 整个 Q6 ----------

def _confirm_text(d, c, carried_note):
    L = ['', f'Q6 卸载旧的：{d["label"]}{" " + d["version"] if d.get("version") else ""}',
         '下面这些会被删掉（删了就找不回来）：']
    for n, it in enumerate(d['residue'], 1):
        L.append(f'  {n}. {inventory._residue_text(it)}')
    for e in d.get('dirs', []):
        if e.get('size_bytes'):
            L.append(f'     （{e["path"]} {inventory._size(e)}）')
    ctrs = [x['name'] for x in d.get('containers', [])]
    if ctrs:
        L.append(f'  旧 Docker 里的容器 {"、".join(ctrs)}（容器不带走，由项目自己的编排文件重新起）')
    left_v = [n for n, v in (c.get('volumes') or {}).items() if v != CARRY]
    left_i = [i['tags'][0] for i in d.get('images', []) if i.get('tags') and (c.get('images') or {}).get(i['id']) != CARRY]
    if left_v:
        L.append(f'  你选了「不要了」的数据卷 {"、".join(left_v)}')
    if left_i:
        L.append(f'  没带走的镜像 {"、".join(left_i)}（用到时可以重新下载）')
    for s in c.get('skipped') or []:
        L.append(f'  {s}（随旧的一起删掉）')
    if d['kind'] == 'leftover':
        L.append('  里面可能还有以前留下的镜像和数据，它已经不能运行，工具包列不出来、也带不走。')
    if d.get('keep_pkgs'):
        L.append(f'不卸的：{"、".join(d["keep_pkgs"])}（随这份 Docker 装进来的，工具包自己也要用；标成「手动装的」留着）')
    if carried_note:
        L.append(carried_note)
    if any(it.get('admin') for it in d['residue']):
        L.append('其中要管理员权限的几步，系统会问这台电脑的登录密码（输入时屏幕上不显示）。')
    return '\n'.join(L)


def _carried_note(c, st):
    v = sum(1 for x in (c.get('volumes') or {}).values() if x == CARRY)
    i = sum(1 for x in (c.get('images') or {}).values() if x == CARRY)
    if not (v or i):
        return ''
    b = st.get('backup_dir')
    return (f'带走的 {v} 个数据卷、{i} 个镜像已经在规定位置的 Docker 里核对过，不受影响'
            + (f'；备份在 {locate.short(b)}，不删。' if b else '。'))


def _save(result):
    p = record.migrate_dir() / 'uninstall.json'
    os.makedirs(record.migrate_dir(), mode=0o700, exist_ok=True)
    try:
        old = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    old.update(result)
    tmp = f'{p}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(old, ensure_ascii=False, indent=1) + '\n')
    os.replace(tmp, p)


def _pending_stopped(old_host):
    try:
        rec = record.load()
    except ValueError:
        return True
    return bool(rec and rec.get('containers') and rec['old'].get('host') == old_host)


def q6(inv, ch, s, *, m=None):
    """Q3 里选了卸掉的 Docker 一份一份卸。s 是 flow.Session（say、ask、probe、起过的旧 Docker）。返回退出码：
    0 = 没有要卸的、小白没确认、或者卸完了且规定位置那份仍正常；1 = 有没做成的、有残留。"""
    say = s.say
    todo = [(d, c) for d, c in zip(inv['docker'], ch['docker']) if c['choice'] == DROP]
    if any(d.get('auto') for d, _ in todo):
        paths.guard_home('迁移 Q6（卸载旧的 Docker）')      # 自测的保险（3-59）：测试漏设 HOME 时一样都不删
    m = m or Machine(s.probe)
    # 留着的那几份用的通道：卸完别的、切默认指向时不从它们身上切走（snap 版也用系统那条通道）
    kept = {(d.get('daemon') or {}).get('host') or (SYSTEM_HOST if d['kind'] == 'snap' else None)
            for d, c in zip(inv['docker'], ch['docker']) if c['choice'] != DROP or not d.get('auto')} - {None}
    rc = 0
    for d, c in todo:
        if not d.get('auto'):
            say('')
            say(f'{d["label"]}：第一版不自动卸载。要卸的话照官方的步骤自己做（{MANUAL_DOC.get(d["kind"], "")}）：')
            for line in MANUAL.get(d['kind'], []):
                say(f'  {line}')
            continue
        r = _one(d, c, s, m, kept)
        rc = max(rc, r)
    return rc


def _one(d, c, s, m, kept=frozenset()):
    say, ask = s.say, s.ask
    st = C.load_state()
    old_host = (d.get('daemon') or {}).get('host') or SYSTEM_HOST
    if d.get('daemon') is not None and not st.get('ready_for_q6', {}).get(d['kind']):
        say('')
        say(f'{d["label"]}：选了带走的数据还没核对通过（Q5），不卸。旧的照常在、照常能用。')
        return 1
    if _pending_stopped(old_host):
        say(f'{d["label"]}：上次迁移停掉的旧容器还没起回来（{locate.short(str(record.record_path()))}），先不卸。')
        return 1
    if d['kind'] == 'rootless' and (d.get('daemon') or {}).get('running') and \
            not any(m.real(r['what']) == m.probe.h('.config/systemd/user/docker.service') for r in d['residue']):
        say(f'{d["label"]} 不是用后台服务起的，工具包停不了它。先自己把它停掉，再执行一次 sop machine migrate；这一次先不卸。')
        return 1
    new = m.new()
    if new is None:      # 4.8：新的先装好，才谈旧的（Q2 核对过；这里是保险）
        say(f'{d["label"]}：规定位置的 Docker 没装好（找不到 ~/tools/docker/etc/docker-host），不卸。先执行 sop machine setup。')
        return 1
    say(_confirm_text(d, c, _carried_note(c, st)))
    if not ask.yes('确定现在卸掉它吗', False):
        say('好，不卸。旧的照常在、照常能用；想好了再执行一次 sop machine migrate。')
        new.close()
        return 0
    s.started = [x for x in s.started if x[0] != d['label']]       # 卸掉的就不用「停回去」了
    ptr = Pointer(m, new.cli)
    say('')
    say('开始卸载：')
    # 卸之前：默认指向若指着新的，先切回原来那份（卸到一半停下时，敲 docker 看到的还是原来那份）
    cur = ptr.current()
    if cur and d.get('daemon') and cur[1] == new.host and old_host != new.host:
        name = ptr.find(old_host)
        done, why = ptr.use(name) if name else (False, f'没有指着 {old_host} 的那一个')
        say(f'  docker 命令的默认指向现在指着新的，先切回原来那份「{name}」（卸完再切到新的）' if done
            else f'  docker 命令的默认指向现在指着新的，想先切回原来那份没切成（{why}），接着卸')
    if d['kind'] in SYSTEM_KINDS:
        _remove_system(m, d, say)
    else:
        _remove_rootless(m, d, say)
    notes = {id(it): f'没删：{w}' for it in d['residue'] if it['kind'] == 'path' for w in [unsafe(m, it['what'])] if w}
    left = [(it, notes.get(id(it), why)) for it, why in still_there(m, d['residue'])]
    gone = _old_gone(d, left)
    result = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'label': d['label'], 'residue': len(d['residue']),
              'left': [inventory._residue_text(it) + (f'（{w}）' if w else '') for it, w in left], 'old_gone': gone}
    ok = not left
    if gone:
        record.forget(old_host)      # 记录里「临时小镜像还没删」那一条随旧的一起没了（不然会去规定位置那份里删同名镜像）
    if gone and d['kind'] == 'rootless':
        took = take_over_name(m, new, say)
        if took is None:
            ok = False
        elif took is not new:
            new.close()
            new = took
    # 卸完、旧的确实没了：默认指向切到新的（指着别的、还活着的就不动）
    if gone:
        cur = ptr.current()
        if cur is None or (cur[1] not in kept and (cur[1] in (old_host, new.host) or _dead(m, cur[1]))):
            done, name = ptr.to(new.host)
            say(f'  docker 命令的默认指向切到规定位置的这份了（「{name}」，通道 {new.host}）' if done
                else f'  docker 命令的默认指向没切成：{name}。可以自己执行 docker context use rootless')
            ok = ok and done
            result['pointer'] = name if done else ''
        else:
            say(f'  docker 命令的默认指向现在指着「{cur[0]}」（{cur[1]}），'
                + ('那条通道还有你留着的另一份 Docker 在用' if cur[1] in kept else '不是这份旧的') + '，不动它。')
    elif not gone:
        say('  旧的程序还在，docker 命令的默认指向不动（还指着原来那份）。')
    new_ok = m.check() and new.ok('version')
    new.close()
    result['new_ok'] = new_ok
    _save({d['kind']: result})
    say('')
    if left:
        say(f'{d["label"]} 没卸干净：Q1 记下的残留清单 {len(d["residue"])} 项，下面 {len(left)} 项还在：')
        for it, why in left:
            say(f'  {inventory._residue_text(it)}' + (f'（{why}）' if why else ''))
        cmds = [x for x in dict.fromkeys(_manual(it) for it, why in left if not why.startswith('没删：')) if x]
        if cmds:
            say('可以再执行一次 sop machine migrate，或者自己执行：')
            for x in cmds:
                say(f'  {x}')
    else:
        say(f'{d["label"]} 卸完了：Q1 记下的残留清单 {len(d["residue"])} 项逐项又看了一遍，都没有了。')
    for note in d.get('notes', []):        # 清点时记下的提醒（~/.bashrc 里照官方装法加的几行等），工具包不动它们
        say(f'提醒：{note}')
    say('规定位置的 Docker 仍然正常（检查命令通过、连得上）。' if new_ok
        else '规定位置的 Docker 现在不正常（检查命令没过或连不上），执行 sop machine doctor 看看。')
    return 0 if ok and new_ok else 1
