"""环境迁移 Q4 备份并带走、Q5 核对（设计书 4.8；3-31）。只管 Docker 的镜像和数据卷（别的工具没有要带的数据）。

Q4（Q3 里选了带走的才有）：
- 空间不够就不开始，用大白话说还差多少（备份位置和新 Docker 的数据目录在同一个分区时合起来算）。
- 镜像：从旧 Docker 导出（docker save）到备份位置，再导入新 Docker（docker load）。没名字的镜像不带（用不上）。
- 数据卷：一个一个处理。在旧 Docker 里起一个用完就删的临时容器，把卷打成一个 tar 包——包从容器的标准输出接出来，
  由小白自己的账号写成备份文件（不往旧 Docker 里挂宿主机的目录：系统自带的 Docker 会以真管理员写文件，留下删不掉的备份）；
  同时在容器里算一份文件清单（路径、类型、归属、权限、每个文件的校验值、链接指向；不比目录的大小，不同文件系统上不一样）。
  打包之前先停掉正在用这些卷的旧容器——停之前先写记录（record.py），打完包马上起回来，任何一步出错也先起回来。
  然后在新 Docker 里建一个临时卷，把包解进去、算清单，和打包时的一字不差才删掉临时卷、解进同名的新卷（带上原来的标签，
  编排工具认得出是自己的卷）；对不上就停下，旧的照常可用。小镜像里 busybox 的 tar 解包时不给符号链接设归属，
  解完按备份包里记的归属补上（3-33）。
- 打包用的小镜像（HELPER）：新 Docker 里没有就拉一个；旧 Docker 里没有就从新的那份导过去，用完删掉（记在记录里，断了下次 sop 删）。
- 新 Docker 里已经有同名的卷、又不是这次迁移建的：不覆盖，停下说清楚。
- 做到哪一步记在 ~/tools/sop/config/migrate/carry.json，断了再执行一次接着做（做完的跳过）。

Q5：带走的每个镜像在新 Docker 里都在；每个数据卷在新 Docker 里重新算一遍清单，和打包时的一致。都对才在 carry.json 记「可以卸载」，
Q6（3-32）只认这个。
"""
import json
import os
import pathlib
import subprocess
import tarfile
import time

from kernel import paths
from kernel.errors import SopError

from .. import locate
from . import record
from .dockercli import first_line

HELPER = 'alpine:3.20'          # 第一段 W27 用它打包、还原、算清单，两种装法都走通过
MARGIN = 1024 ** 3              # 算空间时多留 1 GB
TRY_PREFIX = 'sop-migrate-try-'
MANIFEST_SH = r'''cd "$1" || exit 1
find . -print0 | sort -z | xargs -0 stat -c '%n|%F|%u:%g|%a'
find . -type f -print0 | sort -z | xargs -0 -r sha256sum
find . -type l | sort | while IFS= read -r l; do printf '%s -> %s\n' "$l" "$(readlink "$l")"; done
'''
FROM, TO = '/sop-from', '/sop-to'


class CarryError(SopError):
    pass


# ---------- 做到哪一步 ----------

def state_path():
    return record.migrate_dir() / 'carry.json'


def load_state():
    try:
        with open(state_path(), encoding='utf-8') as f:
            d = json.load(f)
    except FileNotFoundError:
        d = {}
    d.setdefault('items', {})
    return d


def save_state(d):
    os.makedirs(record.migrate_dir(), mode=0o700, exist_ok=True)
    tmp = f'{state_path()}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1) + '\n')
    os.replace(tmp, state_path())


def _key(scope, kind, name):
    return f'{scope}/{kind}:{name}' if scope else f'{kind}:{name}'


def _mark(st, key, **kw):
    st['items'].setdefault(key, {}).update(kw)
    save_state(st)


def default_backup_dir(now=None):
    return paths.tools_dir() / 'backup' / f'migrate-{time.strftime("%Y%m%d", time.localtime(now))}'


# ---------- 空间 ----------

def _existing(path):
    p = os.path.abspath(str(path))
    while not os.path.exists(p):
        p = os.path.dirname(p)
    return p


def _dev(path):
    return os.stat(path).st_dev


def _free(path):
    s = os.statvfs(_existing(path))
    return s.f_bavail * s.f_frsize


def space_plan(volumes, images, backup_dir, new_data, free=_free):
    """要多少空间、够不够。volumes、images 是清单里的条目（有 size_bytes）。
    备份位置要放下所有镜像和卷的包；新 Docker 的数据目录要放下导入的镜像、解开的卷，外加最大那个卷的临时卷。
    返回 (够不够, 一段大白话)。量不出大小的不开始。"""
    unknown = [f'数据卷 {v["name"]}' for v in volumes if v.get('size_bytes') is None]
    unknown += [f'镜像 {"、".join(i["tags"])}' for i in images if i.get('size_bytes') is None]
    if unknown:
        return False, f'量不出 {"、".join(unknown)} 的大小，算不了空间够不够，没有开始。'
    vs = sum(v['size_bytes'] for v in volumes)
    imgs = sum(i['size_bytes'] for i in images)
    biggest = max((v['size_bytes'] for v in volumes), default=0)
    need_backup = vs + imgs + MARGIN
    need_new = vs + imgs + biggest + MARGIN
    a, b = _existing(backup_dir), _existing(new_data)
    H = locate.human_size
    if _dev(a) == _dev(b):
        need, have = need_backup + need_new - MARGIN, free(a)
        text = (f'要的空间：备份 {H(vs + imgs)}，新 Docker 里再放一份 {H(vs + imgs)}，还原时临时多占 {H(biggest)}，'
                f'再多留 1 GB，合计 {H(need)}（备份位置和新 Docker 在同一个分区上）；那里还剩 {H(have)}。')
        if have < need:
            return False, text + f'还差 {H(need - have)}。腾出空间，或者换一个备份位置（--backup-dir），或者少带几样，再执行一次。'
        return True, text
    fa, fb = free(a), free(b)
    text = (f'要的空间：备份位置 {H(need_backup)}（剩 {H(fa)}）；新 Docker 的数据目录 {H(need_new)}（剩 {H(fb)}）；都多留了 1 GB。')
    short = []
    if fa < need_backup:
        short.append(f'备份位置还差 {H(need_backup - fa)}')
    if fb < need_new:
        short.append(f'新 Docker 那边还差 {H(need_new - fb)}')
    if short:
        return False, text + '；'.join(short) + '。腾出空间，或者换一个备份位置（--backup-dir），或者少带几样，再执行一次。'
    return True, text


# ---------- 用到的几样 docker 操作 ----------

def _check(r, what):
    if r[0] != 0:
        raise CarryError(f'{what}没成：{first_line(r[2])}')
    return r


def volume_exists(d, name):
    return d.ok('volume', 'inspect', name)


def volume_info(d, name):
    r = d.run('volume', 'inspect', name)
    if r[0] != 0:
        return None
    try:
        return (json.loads(r[1]) or [None])[0]
    except ValueError:
        return None


def manifest(d, vol, out_file):
    with open(out_file, 'wb') as f:
        _check(d.run('run', '--rm', '--network', 'none', '-v', f'{vol}:{FROM}:ro', HELPER, 'sh', '-c', MANIFEST_SH, 'sh', FROM,
                     stdout=f, timeout=3600), f'给数据卷 {vol} 算文件清单')


def pack(d, vol, out_file):
    with open(out_file, 'wb') as f:
        _check(d.run('run', '--rm', '--network', 'none', '-v', f'{vol}:{FROM}:ro', HELPER,
                     'tar', '-C', FROM, '--numeric-owner', '-cpf', '-', '.', stdout=f, timeout=6 * 3600),
               f'把数据卷 {vol} 打包')


def unpack(d, vol, tar_file):
    with open(tar_file, 'rb') as f:
        _check(d.run('run', '--rm', '-i', '--network', 'none', '-v', f'{vol}:{TO}', HELPER,
                     'tar', '-C', TO, '--numeric-owner', '-xpf', '-', stdin=f, timeout=6 * 3600),
               f'把备份解进新 Docker 的数据卷 {vol}')
    fix_link_owners(d, vol, tar_file)


def link_owners(tar_file):
    """备份包里归属不是 root 的符号链接：[(包里的名字, 'uid:gid')]。只读包头（tarfile 跳过文件内容），不解包。"""
    out = []
    with tarfile.open(tar_file, 'r:') as t:
        for m in t:
            if m.issym() and (m.uid or m.gid):
                n = m.name if m.name.startswith('./') else './' + m.name
                out.append((n, f'{m.uid}:{m.gid}'))
    return out


def fix_link_owners(d, vol, tar_file):
    """小镜像里的 tar 是 busybox 的：解包时不给符号链接设归属，解出来的链接都归 root（3-33 在虚拟机里查出来的；文件、目录不受影响）。
    解完按备份包里记的归属逐个补上（chown -h 只改链接本身）。没有这样的链接就什么都不做。"""
    pairs = link_owners(tar_file)
    if not pairs:
        return
    lst = f'{tar_file}.links'
    with open(lst, 'wb') as f:
        for n, owner in pairs:
            f.write(owner.encode() + b'\0' + n.encode('utf-8', 'surrogateescape') + b'\0')
    try:
        with open(lst, 'rb') as f:
            _check(d.run('run', '--rm', '-i', '--network', 'none', '-v', f'{vol}:{TO}', HELPER,
                         'sh', '-c', 'cd "$1" && xargs -0 -r -n 2 chown -h', 'sh', TO, stdin=f, timeout=3600),
                   f'给数据卷 {vol} 里的符号链接补上原来的归属')
    finally:
        os.unlink(lst)


def _same(a, b):
    with open(a, 'rb') as x, open(b, 'rb') as y:
        return x.read() == y.read()


def _diff(a, b, n=5):
    la = pathlib.Path(a).read_text(encoding='utf-8', errors='replace').splitlines()
    lb = pathlib.Path(b).read_text(encoding='utf-8', errors='replace').splitlines()
    sa, sb = set(la), set(lb)
    out = [f'  少了：{x}' for x in la if x not in sb][:n] + [f'  多了或变了：{x}' for x in lb if x not in sa][:n]
    return '\n'.join(out)


def running_users(d, vol):
    r = _check(d.run('ps', '--filter', f'volume={vol}', '--filter', 'status=running', '--format', '{{.Names}}'),
               f'查哪些容器在用数据卷 {vol}')
    return r[1].split()


def ensure_helper(old, new, say):
    """打包用的小镜像：新的里没有就拉，旧的里没有就从新的导过去（记进记录，用完删）。返回往旧的里放了没有。"""
    if not new.ok('image', 'inspect', HELPER):
        say(f'新 Docker 里还没有打包用的小镜像 {HELPER}，现在下载（几 MB）')
        _check(new.run('pull', HELPER, timeout=1800), f'下载小镜像 {HELPER}')
    if old.ok('image', 'inspect', HELPER):
        return False
    say(f'旧 Docker 里临时放一个打包用的小镜像 {HELPER}（从新的那份导过去，用完删掉）')
    record.set_helper(old, HELPER)
    env = {k: v for k, v in os.environ.items() if not k.startswith('DOCKER_')}
    src = subprocess.Popen(new.argv('save', HELPER), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                           stdin=subprocess.DEVNULL)
    r = old.run('load', stdin=src.stdout, timeout=1800)
    src.stdout.close()
    serr = src.stderr.read().decode('utf-8', 'replace')
    src.stderr.close()
    src.wait()
    if src.returncode != 0:
        raise CarryError(f'从新 Docker 导出小镜像没成：{first_line(serr)}')
    _check(r, f'把小镜像 {HELPER} 导进旧 Docker')
    return True


def drop_helper(old, say):
    r = old.run('image', 'rm', HELPER, timeout=300)
    if r[0] == 0 or 'No such image' in r[2]:
        record.set_helper(old, '')
    else:
        say(f'提醒：临时放进旧 Docker 的小镜像 {HELPER} 没删掉（{first_line(r[2])}），下次执行 sop 会再删。')


# ---------- Q4 ----------

def carry(old, new, volumes, images, backup_dir, *, scope='', say=print, confirm_stop=None, stop_timeout=30):
    """把选了带走的镜像和数据卷备份、试还原、带进新 Docker。volumes、images 是清单里的条目。
    scope 是这份旧 Docker 的装法（docker.io 等）：两份旧 Docker 里有同名的卷时分得开。
    confirm_stop(容器名列表) 返回 False 就不停、不做（None 表示不问）。出错抛 CarryError，旧的照常可用。"""
    st = load_state()
    st['backup_dir'] = str(backup_dir)
    save_state(st)
    tags = [t for i in images for t in i['tags']]
    todo_tags = [t for t in tags if st['items'].get(_key(scope, 'image', t), {}).get('status') not in ('loaded', 'verified')]
    todo = [v for v in volumes if st['items'].get(_key(scope, 'volume', v['name']), {}).get('status') not in ('restored', 'verified')]
    if not todo_tags and not todo:
        say('Q4：选了带走的都已经带过去了，跳过')
        return
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    # 新 Docker 里已经有同名的卷：这次迁移建的（上次断在半截）删掉重来，别人的不覆盖
    clash = []
    for v in todo:
        n = v['name']
        if volume_exists(new, n):
            if st['items'].get(_key(scope, 'volume', n), {}).get('created_new'):
                _check(new.run('volume', 'rm', n), f'删掉上次做了一半的数据卷 {n}')
            else:
                clash.append(n)
    if clash:
        raise CarryError(f'新 Docker 里已经有同名的数据卷 {"、".join(clash)}，不是这次迁移建的，不覆盖。'
                         '要带的话先在新 Docker 里把它们改名或删掉（里面的东西你自己看要不要），再执行一次。')
    helper_added = False
    try:
        if todo:
            helper_added = ensure_helper(old, new, say)
        if todo_tags:
            f = os.path.join(backup_dir, 'images.tar')
            say(f'导出镜像 {"、".join(todo_tags)} 到 {locate.short(f)}')
            with open(f, 'wb') as out:
                _check(old.run('save', *todo_tags, stdout=out, timeout=6 * 3600), '从旧 Docker 导出镜像')
            say('导入新 Docker')
            with open(f, 'rb') as inp:
                _check(new.run('load', stdin=inp, timeout=6 * 3600), '把镜像导入新 Docker')
            for t in todo_tags:
                _mark(st, _key(scope, 'image', t), status='loaded', backup=f)
        if todo:
            _pack_all(old, todo, backup_dir, st, say, confirm_stop, stop_timeout, scope)
            for v in todo:
                _restore(new, v, st, say, scope)
    finally:
        if helper_added:
            drop_helper(old, say)


def _pack_all(old, todo, backup_dir, st, say, confirm_stop, stop_timeout, scope):
    labels = {}
    for v in todo:
        info = volume_info(old, v['name'])
        if info is None:
            raise CarryError(f'旧 Docker 里找不到数据卷 {v["name"]}（清点之后被删了？）。重新执行一次 sop machine migrate。')
        labels[v['name']] = info.get('Labels') or {}
    stop = sorted({c for v in todo for c in running_users(old, v['name'])})
    if stop and confirm_stop is not None and not confirm_stop(stop):
        raise CarryError('你选了先不停容器，没有打包。旧的照常在用；想好了再执行一次。')
    if stop:
        record.add_stopped(old, stop)          # 先写记录，再停：断电、被强制结束，下次 sop 也会起回来
        say(f'先停掉正在用这些数据卷的旧容器 {"、".join(stop)}（打完包马上起回来）')
    try:
        if stop:
            _check(old.run('stop', '-t', str(stop_timeout), *stop, timeout=stop_timeout * len(stop) + 120), '停旧容器')
        for v in todo:
            n = v['name']
            tar = os.path.join(backup_dir, f'vol-{n}.tar')
            before = os.path.join(backup_dir, f'vol-{n}.before')
            say(f'打包数据卷 {n} 到 {locate.short(tar)}')
            pack(old, n, tar)
            manifest(old, n, before)
            _mark(st, _key(scope, 'volume', n), status='backed-up', backup=tar, before=before, labels=labels[n])
    finally:
        if stop:
            r = old.run('start', *stop, timeout=300)
            if r[0] == 0:
                record.remove_stopped(old, stop)
                say(f'旧容器 {"、".join(stop)} 已经起回来了')
            else:
                say(f'旧容器 {"、".join(stop)} 没起回来：{first_line(r[2])}。记录留着，下次执行 sop 会再试。')


def _restore(new, v, st, say, scope):
    n = v['name']
    key = _key(scope, 'volume', n)
    it = st['items'][key]
    trial = TRY_PREFIX + n
    if volume_exists(new, trial):
        new.run('volume', 'rm', trial)
    tried = os.path.join(os.path.dirname(it['backup']), f'vol-{n}.try')
    _check(new.run('volume', 'create', trial), f'在新 Docker 里建临时数据卷 {trial}')
    try:
        unpack(new, trial, it['backup'])
        manifest(new, trial, tried)
    finally:
        new.run('volume', 'rm', trial)
    if not _same(it['before'], tried):
        raise CarryError(f'数据卷 {n}：备份试着还原到临时卷以后，文件清单和打包时的对不上，停下了。旧的照常可用，一样没动。\n'
                         f'{_diff(it["before"], tried)}\n两份清单在 {locate.short(it["before"])}、{locate.short(tried)}')
    say(f'数据卷 {n}：试还原以后文件清单、归属、权限、校验值都一致')
    lab = [x for k, val in sorted((it.get('labels') or {}).items()) for x in ('--label', f'{k}={val}')]
    _mark(st, key, created_new=True)
    _check(new.run('volume', 'create', *lab, n), f'在新 Docker 里建数据卷 {n}')
    unpack(new, n, it['backup'])
    _mark(st, key, status='restored')
    say(f'数据卷 {n} 已经在新 Docker 里了')


# ---------- Q5 ----------

def verify(new, volumes, images, *, scope='', say=print):
    """Q5：带走的镜像都在、每个数据卷的清单和打包时一致。返回 (都对没有, [问题])。都对时 carry.json 的 ready_for_q6[scope] 记 true。"""
    st = load_state()
    bad = []
    for i in images:
        for t in i['tags']:
            if new.ok('image', 'inspect', t):
                _mark(st, _key(scope, 'image', t), status='verified')
                say(f'镜像 {t}：在新 Docker 里')
            else:
                bad.append(f'镜像 {t} 不在新 Docker 里')
    for v in volumes:
        n = v['name']
        key = _key(scope, 'volume', n)
        it = st['items'].get(key)
        if not it or it.get('status') not in ('restored', 'verified'):
            bad.append(f'数据卷 {n} 还没带过去')
            continue
        after = os.path.join(os.path.dirname(it['backup']), f'vol-{n}.after')
        try:
            manifest(new, n, after)
        except CarryError as e:
            bad.append(str(e))
            continue
        if _same(it['before'], after):
            _mark(st, key, status='verified')
            say(f'数据卷 {n}：和搬之前一致')
        else:
            _mark(st, key, status='restored')
            bad.append(f'数据卷 {n} 在新 Docker 里的文件清单和搬之前的对不上：\n{_diff(it["before"], after)}')
    st = load_state()
    st.setdefault('ready_for_q6', {})[scope or 'docker'] = not bad      # Q6 只认这一项：这份旧 Docker 带走的都核对过了
    st['verified_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    save_state(st)
    return not bad, bad


def remove_backup_hint(backup_dir):
    """备份不自动删（Q6 卸完、用了一阵新的再删也不迟）。给人看的一句。"""
    return f'备份留在 {locate.short(str(backup_dir))}，不自动删；新的用了一阵没问题，再自己删掉它腾空间。'

