"""体检：受限环境和免管理员 Docker 依赖的几样系统组件，现在是什么版本、什么状态（设计书 4.5，任务 3-05）。
只读：读几个系统文件、跑 `bwrap --version` 和 `dpkg-query`，不改任何东西。

记进机器级登记 config/system.json（config.record_system）。sop 每次启动拿现在的和登记比，
变了先重跑隔离自检（3-07）。所以这里的值只求「变了就看得出来」：系统规则记文件内容的指纹，不解读规则写了什么。

五样（config.SYSTEM_PARTS）：
- kernel         内核：版本号加编译记录（Ubuntu 有时版本号不变、只换一次编译）
- bubblewrap     bubblewrap：程序报的版本，加软件包的版本（安全补丁只改软件包版本）
- userns_rule    免管理员 Docker 要的那条系统规则：/etc/apparmor.d/ 下按 rootlesskit 的真实路径起名的文件
                 （~/tools/docker/bin/rootlesskit → home.<用户名>.tools.docker.bin.rootlesskit），连同它引用的 local/ 下的同名文件
- userns_policy  系统对「普通用户建隔离空间」的限制：总开关 kernel.apparmor_restrict_unprivileged_userns，
                 和 bubblewrap 靠它放行的那条规则 bwrap-userns-restrict（Ubuntu 24.04 起有）。这两样变了，bubblewrap 可能就起不来
- tiocsti        往终端塞按键的开关 dev.tty.legacy_tiocsti：0 是关着（对话步骤的前提，6.3、9 节），1 是开着；
                 老内核（6.2 以前）没有这个开关，等于开着
"""
import hashlib
import os
import pathlib
import re
import subprocess

from kernel import paths

from . import catalog, config

MISSING = 'missing'
APPARMOR = pathlib.Path('/etc/apparmor.d')
PROC_SYS = pathlib.Path('/proc/sys')
RESTRICT = 'kernel/apparmor_restrict_unprivileged_userns'
TIOCSTI = 'dev/tty/legacy_tiocsti'
BWRAP_RULE = 'bwrap-userns-restrict'


def _read(p):
    try:
        return pathlib.Path(p).read_text().strip()
    except FileNotFoundError:
        return MISSING
    except OSError as e:
        return f'unreadable({e.strerror or e})'


def fingerprint(p):
    """文件内容的指纹（sha256 的前 12 位）；没有这个文件是 missing，读不了照实写。"""
    try:
        return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:12]
    except FileNotFoundError:
        return MISSING
    except OSError as e:
        return f'unreadable({e.strerror or e})'


def rootlesskit_path():
    """规定位置那份免管理员 Docker 的 rootlesskit（4.3）。系统规则按真实路径认程序，所以解开链接。"""
    return os.path.realpath(paths.tools_dir() / 'docker' / 'bin' / 'rootlesskit')


def docker_rule_name(rootlesskit=None):
    """官方安装脚本给规则起名的办法：路径去掉开头的 /，其余的 / 换成 .。"""
    return (rootlesskit or rootlesskit_path()).lstrip('/').replace('/', '.')


def _run(cmd, run):
    try:
        r = run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def kernel(uname=os.uname):
    u = uname()
    return f'{u.release} {u.version}'


def bubblewrap(run=subprocess.run):
    out = _run(['bwrap', '--version'], run)
    if out is None:
        return MISSING
    found = catalog.parse_version(out)
    v = '.'.join(map(str, found)) if found else out
    pkg = _run(['dpkg-query', '-W', '-f', '${Version}', 'bubblewrap'], run)
    return f'{v} (package {pkg})' if pkg else v


def userns_rule(apparmor=APPARMOR, rootlesskit=None):
    name = docker_rule_name(rootlesskit)
    main = fingerprint(apparmor / name)
    if main == MISSING:
        return MISSING
    local = fingerprint(apparmor / 'local' / name)
    return f'{name} {main}' + ('' if local == MISSING else f' local {local}')


def userns_policy(apparmor=APPARMOR, proc_sys=PROC_SYS):
    return f'restrict={_read(proc_sys / RESTRICT)} {BWRAP_RULE}={fingerprint(apparmor / BWRAP_RULE)}'


def tiocsti(proc_sys=PROC_SYS):
    v = _read(proc_sys / TIOCSTI)
    return v if v in ('0', '1', MISSING) else f'unexpected({v})'


def collect(run=subprocess.run, uname=os.uname, apparmor=APPARMOR, proc_sys=PROC_SYS, rootlesskit=None):
    """只读地查一遍，返回 {名字: 值}，名字就是 config.SYSTEM_PARTS 那几样。参数换成假的就能在测试里造。"""
    return {
        'kernel': kernel(uname),
        'bubblewrap': bubblewrap(run),
        'userns_rule': userns_rule(apparmor, rootlesskit),
        'userns_policy': userns_policy(apparmor, proc_sys),
        'tiocsti': tiocsti(proc_sys),
    }


def record(current=None):
    """把这一次看到的记进登记（整份换掉）。只在隔离自检通过之后调用（3-07、M6）。
    体检（3-06）不调用：体检要是记了，系统升级后先跑一次体检，sop 启动时就看不出变化、跳过了隔离自检。"""
    return config.record_system(collect() if current is None else current)


def describe(parts, changes=None):
    """大白话的几行，给体检报告用（3-06）。changes 是 config.system_changes 的结果，给了就说哪几样和上次登记的不一样。"""
    lines = [f'系统内核：{parts["kernel"].split(" ")[0]}。']
    b = parts['bubblewrap']
    lines.append('bubblewrap（受限环境用的）：没装。' if b == MISSING else f'bubblewrap（受限环境用的）：{b.split(" ")[0]}。')
    r = parts['userns_rule']
    lines.append('免管理员 Docker 要的那条系统规则：还没有（装免管理员 Docker 时会装上，那一步要管理员密码）。'
                 if r == MISSING else f'免管理员 Docker 要的那条系统规则：有（{r.split(" ")[0]}）。')
    m = re.match(r'restrict=(\S+)', parts['userns_policy'])
    flag = m.group(1) if m else ''
    lines.append({'1': '系统限制普通用户建隔离空间：开着（Ubuntu 默认如此，bubblewrap、免管理员 Docker 靠各自那条规则放行）。',
                  '0': '系统限制普通用户建隔离空间：关着。',
                  MISSING: '系统没有「限制普通用户建隔离空间」这个开关。'}.get(flag, f'系统限制普通用户建隔离空间的开关：{flag}。'))
    t = parts['tiocsti']
    lines.append({'0': '往终端塞按键：已禁用（对话步骤的前提，合格）。',
                  '1': '要注意：往终端塞按键没有禁用，AI 对话的步骤不会启动（6.3）。',
                  MISSING: '要注意：这个内核太老，没有禁用「往终端塞按键」的开关，AI 对话的步骤不会启动（6.3）。'}
                 .get(t, f'往终端塞按键的开关读出来是「{t}」，看不懂，按没禁用处理，AI 对话的步骤不会启动。'))
    if changes and all(old is None for _, old, _ in changes) and len(changes) == len(config.SYSTEM_PARTS):
        lines.append('这几样还没登记过：先跑一次隔离自检，过了再记下来。')
    elif changes:
        names = '、'.join(config.SYSTEM_PARTS[k] for k, _, _ in changes)
        lines.append(f'和上次登记的不一样：{names}。下次推进流程之前会先重跑隔离自检。')
    return '\n'.join(lines)


if __name__ == '__main__':
    now = collect()
    print(describe(now, config.system_changes(now)))
