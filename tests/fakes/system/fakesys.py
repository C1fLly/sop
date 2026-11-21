#!/usr/bin/env python3
"""假的系统命令（3-32 环境迁移 Q6 的单元测试用）：sudo、apt-get、dpkg-query、systemctl、groupdel、apparmor_parser 都链到这个文件，
按自己被叫的名字干活。从不碰真的系统：

  FAKESYS_ROOT     测试造的「/」，系统路径都接在它后面（没设就拒绝运行）
  FAKESYS_STATE    状态文件（JSON）：
                     packages    {包名: {"version", "status"（ii、rc）, "files": [系统路径…], "rdeps": [卸它会连带卸掉的包…]}}
                     units       {系统服务名: {"LoadState", "ActiveState", "package", "host"}}
                     user_units  {用户级服务名: {"LoadState", "ActiveState", "host", "exec"}}
                     stores      {程序路径: 假 docker 的状态目录}（同一个 dockerd 换了服务名、换了通道，里面的东西还是那些）
  FAKESYS_HOME、FAKESYS_RUNTIME   用户的主目录、运行时目录（用户级服务的登记文件在 $FAKESYS_HOME/.config/systemd/user）
  FAKESYS_LOG      每跑一条记一行 JSON：{"cmd", "args", "sudo"}
  FAKESYS_FAIL     正则，对「命令名 参数…」比，对上的退出码 1（模拟没成）
  FAKEDOCKER_ROOT  假 docker 的目录：服务停了往 <通道换的名字>.down 放一个文件（假 docker 就连不上），起了拿掉

sudo 不提权：只记一笔、设 FAKESYS_SUDO=1，再执行后面的命令；只肯执行 tests/fakes 里的假命令、`env … sh -c`（PATH 里的
apt-get 得是假的），以及路径全在 FAKESYS_ROOT 下面的 rm、rmdir、find，改的文件在 FAKESYS_ROOT 下面的 sed -i。系统级的改动（apt-get purge、systemctl stop 等、groupdel）
没有经过假 sudo 就照真的那样报「权限不够」。
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FAKES = os.path.dirname(HERE)
ROOT = os.environ.get('FAKESYS_ROOT', '')
NAME = os.path.basename(sys.argv[0])
ARGS = sys.argv[1:]
if not ROOT or not os.path.isdir(ROOT):
    print(f'假的 {NAME}：没设 FAKESYS_ROOT（或目录不在），什么都不做', file=sys.stderr)
    sys.exit(99)
SUDO = os.environ.get('FAKESYS_SUDO') == '1'


def die(msg, rc=1):
    print(msg, file=sys.stderr)
    sys.exit(rc)


def log():
    f = os.environ.get('FAKESYS_LOG')
    if f:
        with open(f, 'a') as fh:
            fh.write(json.dumps({'cmd': NAME, 'args': ARGS, 'sudo': SUDO}, ensure_ascii=False) + '\n')


log()
fail = os.environ.get('FAKESYS_FAIL')
if fail and NAME != 'sudo' and re.search(fail, f'{NAME} {" ".join(ARGS)}'):
    die(f'假的 {NAME}：故意出错')

SF = os.environ.get('FAKESYS_STATE', '')


def load():
    try:
        with open(SF) as f:
            s = json.load(f)
    except (FileNotFoundError, ValueError):
        s = {}
    for k in ('packages', 'units', 'user_units', 'stores'):
        s.setdefault(k, {})
    return s


def save(s):
    with open(SF + '.tmp', 'w') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(SF + '.tmp', SF)


def under_root(p):
    return os.path.realpath(p) == os.path.realpath(ROOT) or os.path.realpath(p).startswith(os.path.realpath(ROOT) + '/')


def need_root(what):
    if not SUDO:
        die(f'{what}: Permission denied (are you root?)', 100 if NAME == 'apt-get' else 4)


def dkey(host):
    return re.sub(r'[^A-Za-z0-9.-]', '_', host)


def mark(host, up):
    fd = os.environ.get('FAKEDOCKER_ROOT')
    if not fd or not host:
        return
    f = os.path.join(fd, dkey(host) + '.down')
    if up:
        if os.path.exists(f):
            os.unlink(f)
    else:
        open(f, 'w').close()


# ---------- sudo ----------
if NAME == 'sudo':
    a = list(ARGS)
    while a and a[0].startswith('-'):
        a = a[2:] if a[0] in ('-p', '-u') else a[1:]
    if not a:
        die('假的 sudo：没有要执行的命令')
    exe = shutil.which(a[0]) if '/' not in a[0] else a[0]
    ok = exe and os.path.realpath(exe).startswith(FAKES + '/')
    if a[0] == 'env':
        i = 1
        while i < len(a) and '=' in a[i]:
            i += 1
        apt = shutil.which('apt-get') or ''
        ok = a[i:i + 2] == ['sh', '-c'] and os.path.realpath(apt).startswith(FAKES + '/')
    elif a[0] == 'rm':
        paths = [x for x in a[1:] if x.startswith('/')]
        ok = bool(paths) and all(under_root(x) for x in paths)
    elif a[0] == 'sed':
        ok = '-i' in a and under_root(a[-1])
    elif a[0] in ('rmdir', 'find'):
        paths = [x for x in a[1:] if x.startswith('/')]
        ok = bool(paths) and all(under_root(x) for x in paths)
    if not ok:
        die(f'假的 sudo：不执行 {" ".join(a)}')
    os.environ['FAKESYS_SUDO'] = '1'
    os.execvp(a[0], a)

# ---------- dpkg-query -W -f 格式 包… ----------
if NAME == 'dpkg-query':
    if ARGS[:1] != ['-W']:
        die(f'假的 dpkg-query：只认 -W，不认 {ARGS}')
    s = load()
    names = ARGS[3:] if ARGS[1] == '-f' else ARGS[1:]
    miss = 0
    for n in names:
        p = s['packages'].get(n)
        if p:
            print(f'{n}\t{p.get("version", "1")}\t{p.get("status", "ii")} ')
        else:
            print(f'dpkg-query: no packages found matching {n}', file=sys.stderr)
            miss += 1
    sys.exit(1 if miss else 0)

# ---------- apt-get purge|remove -y -qq 包… ----------
if NAME == 'apt-get':
    s = load()
    if ARGS and ARGS[0] == '-s':          # 只模拟：点名的、装着的包各一行 Purg，再加上依赖它的（packages[包]["rdeps"]）
        if ARGS[1:2] != ['purge'] or '--autoremove' in ARGS:
            die(f'假的 apt-get：模拟只认 -s purge 包…，不认 {ARGS}')
        out = []
        for n in ARGS[2:]:
            if n in s['packages']:
                out += [n] + s['packages'][n].get('rdeps', [])
        for n in dict.fromkeys(out):
            print(f'Purg {n} [1]')
        sys.exit(0)
    sub = next((x for x in ARGS if not x.startswith('-')), '')
    if sub not in ('purge', 'remove'):
        die(f'假的 apt-get：只认 purge、remove，不认 {ARGS}')
    if '--autoremove' in ARGS or 'autoremove' in ARGS:
        die('假的 apt-get：Q6 应该一个一个点名要卸的包，不该用 --autoremove')
    need_root('E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)')
    pkgs = [x for x in ARGS[ARGS.index(sub) + 1:] if not x.startswith('-')]
    for n in pkgs:
        p = s['packages'].pop(n, None)
        if p is None:
            print(f"Package '{n}' is not installed, so not removed")
            continue
        for f in p.get('files', []):
            real = ROOT + f
            if os.path.isdir(real) and not os.path.islink(real):
                shutil.rmtree(real)
            elif os.path.lexists(real):
                os.unlink(real)
        for u, info in list(s['units'].items()):
            if info.get('package') == n:
                mark(info.get('host'), False)
                del s['units'][u]
    save(s)
    sys.exit(0)

# ---------- groupdel 名字 ----------
if NAME == 'groupdel':
    need_root('groupdel: Permission denied.')
    g = os.path.join(ROOT, 'etc/group')
    lines = open(g).read().splitlines(True) if os.path.exists(g) else []
    keep = [ln for ln in lines if not ln.startswith(ARGS[-1] + ':')]
    if len(keep) == len(lines):
        die(f"groupdel: group '{ARGS[-1]}' does not exist", 6)
    open(g, 'w').write(''.join(keep))
    sys.exit(0)

# ---------- apparmor_parser -R 文件 ----------
if NAME == 'apparmor_parser':
    need_root('apparmor_parser: Access denied. You need policy admin privileges to manage profiles.')
    sys.exit(0)

# ---------- systemctl [--user] … ----------
if NAME == 'systemctl':
    a = list(ARGS)
    user = a[:1] == ['--user']
    if user:
        a = a[1:]
    s = load()
    U = s['user_units'] if user else s['units']
    udir = os.path.join(os.environ.get('FAKESYS_HOME', '/nonexistent'), '.config/systemd/user')
    rt = os.environ.get('FAKESYS_RUNTIME', '/nonexistent')
    sub = a[0] if a else ''
    names = [x for x in a[1:] if not x.startswith('-')]
    if sub == 'show':
        out = []
        for n in names:
            u = U.get(n)
            if u is None:
                out.append(f'Id={n}\nLoadState=not-found\nActiveState=inactive')
            else:
                out.append(f'Id={n}\nLoadState={u.get("LoadState", "loaded")}\nActiveState={u.get("ActiveState", "inactive")}')
        print('\n\n'.join(out))
        sys.exit(0)
    if sub == 'is-active':
        sys.exit(0 if all(U.get(n, {}).get('ActiveState') == 'active' for n in names) else 3)
    if not user:
        need_root('Failed: Access denied')
    if sub == 'daemon-reload':
        if user:
            for n in list(U):
                if not os.path.exists(os.path.join(udir, n)):
                    del U[n]
        save(s)
        sys.exit(0)
    if sub not in ('start', 'stop', 'enable', 'disable', 'restart'):
        die(f'假的 systemctl：不认识 {sub}')
    now = '--now' in a
    for n in names:
        u = U.get(n)
        if u is None and user and os.path.exists(os.path.join(udir, n)):
            text = open(os.path.join(udir, n)).read()
            m = re.search(r'^ExecStart=(\S+)', text, re.M)
            sock = f'{rt}/sop-docker/docker.sock' if 'RuntimeDirectory=sop-docker' in text else f'{rt}/docker.sock'
            u = U[n] = {'LoadState': 'loaded', 'ActiveState': 'inactive', 'host': f'unix://{sock}', 'exec': m[1] if m else ''}
        if u is None:
            die(f'Failed to {sub} unit: Unit {n} not found.', 5)
        if sub in ('enable', 'disable'):
            u['UnitFileState'] = 'enabled' if sub == 'enable' else 'disabled'
        up = sub in ('start', 'restart') or (sub == 'enable' and now)
        down = sub == 'stop' or (sub == 'disable' and now)
        if up:
            # 同一个 dockerd（按程序认）换了服务名、换了通道：通道指到它原来的状态目录
            fd = os.environ.get('FAKEDOCKER_ROOT')
            ex = u.get('exec')
            if fd and ex and u.get('host'):
                link = os.path.join(fd, dkey(u['host']))
                store = s['stores'].setdefault(ex, link)
                if os.path.realpath(link) != os.path.realpath(store):
                    if os.path.islink(link):
                        os.unlink(link)
                    elif os.path.exists(link):
                        os.rename(link, link + '.gone')
                    os.symlink(store, link)
            u['ActiveState'] = 'active'
            mark(u.get('host'), True)
        if down:
            u['ActiveState'] = 'inactive'
            mark(u.get('host'), False)
    save(s)
    sys.exit(0)

die(f'假的系统命令：不认识 {NAME}')
