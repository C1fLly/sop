"""`sop machine migrate`：环境迁移 Q1 到 Q6（设计书 4.8；3-31、3-32、3-61）。

  Q1 清点（inventory.py）→ Q2 规定位置的那一份装好没有（没装好的就是 M2 的安装）→ Q3 逐样选（默认都「留」）
  → Q4 备份并带走（carry.py，Q3 里选了带走的才有）→ Q5 核对 → Q6 卸载选了卸的 Docker（uninstall.py，再确认一次，默认不卸）
  → 选了卸的旧 nvm、uv、pnpm（oldtools.py，同样再确认一次，默认不卸）

规矩（4.8）：到小白最后确认卸载之前，旧的一样都不动；中途任何一步失败都只是停下，旧的照常可用。两处替用户定的（3-31，可否决）：

1. 旧的 Docker 停着时：清点不去连它（系统自带的那种一连就会被系统自动起来，3-30 实测）。只有小白在 Q3 选了「卸」这一份、
   要列出里面的数据卷让他选带不带走时，才先说一句为什么，再问「要先把它起来吗」，默认不起。不起就把这一份改回「留」
   （不知道里面有什么，就不能卸）；起了的，迁移结束（做完或中途停下）时把它停回去。
2. 管理员密码：一开始不问（清点不用管理员也做得了，量不全的写「至少」；--admin 才一开始就用）。只在真要用的那一步之前，
   先说一句为什么，再由系统问：小白选了卸系统自带的 Docker、而他不在 docker 组（不用管理员连不上它）时问一句「现在输吗」，
   默认不输、不输就改回「留」；起停系统的 Docker 服务时；Q2 要装系统软件包时（M2 自己会先说一句）。
"""
import json
import os
import subprocess
import sys
import time

from kernel import paths
from kernel.errors import SopError

from .. import catalog, locate
from . import carry as C, inventory, oldtools, record, uninstall
from .dockercli import ADMIN, Daemon, first_line, new_daemon

KEEP, DROP = 'keep', 'remove'
CARRY, LEAVE = 'carry', 'leave'


class Ask:
    """问小白。answers 给了就按顺序用（测试用），不然在终端里问；不在终端里时一律按默认，并说一句。"""

    def __init__(self, answers=None, say=print, inp=input, tty=None):
        self.answers = list(answers) if answers is not None else None
        self.say, self.inp = say, inp
        self.tty = sys.stdin.isatty() if tty is None else tty

    def _get(self, prompt):
        if self.answers is not None:
            a = self.answers.pop(0) if self.answers else ''
            self.say(f'{prompt}{a}')
            return a
        if not self.tty:
            self.say(f'{prompt}（不是在终端里运行，按默认）')
            return ''
        try:
            return self.inp(prompt).strip()
        except EOFError:
            return ''

    def choose(self, question, options, default):
        """options: [(值, 说法)]。回车 = 默认。返回值。"""
        self.say(question)
        for n, (k, label) in enumerate(options, 1):
            self.say(f'  {n}. {label}{"（默认）" if k == default else ""}')
        while True:
            a = self._get('输入数字，直接回车就是默认：')
            if a == '':
                return default
            if a.isdigit() and 1 <= int(a) <= len(options):
                return options[int(a) - 1][0]
            self.say('没看懂，请输入上面的数字')
            if self.answers is not None and not self.answers:
                return default

    def yes(self, question, default=False):
        a = self._get(f'{question}（{"Y/n" if default else "y/N"}，直接回车是「{"是" if default else "否"}」）：').lower()
        if a == '':
            return default
        return a in ('y', 'yes', '是', '好', '要')


# ---------- Q2 ----------

def q2(inv, say, *, check=catalog.run_check, install=None, tools=None):
    """规定位置的那一份装好没有：有不在规定位置的哪样，就看规定位置的那样。没装好的、属于 M2 的现在装（就是 M2 的安装）；
    别的（wt 等）让小白先执行 sop machine setup。返回装好没有。"""
    want = {t['name'] for t in inv['tools']}
    if inv['docker']:
        want.add('docker')
    cat = catalog.load() if tools is None else tools
    missing = [t for t in cat if t.name in want and not check(t).ok]
    if not missing:
        say('Q2 规定位置的那一份：都已经装好了，跳过。')
        return True
    later = [t.name for t in missing if t.step != 'M2']
    if later:
        say(f'规定位置的 {"、".join(later)} 还没装好，它在 sop machine setup 里装。先执行 sop machine setup，再执行 sop machine migrate。')
        return False
    names = [t.name for t in missing]
    if 'docker' in names:
        from ..install import DOCKER
        names = [n for n in DOCKER if n != 'docker'] + names
    say(f'Q2 规定位置的 {"、".join(t.name for t in missing)} 还没装好，现在装（和 sop machine setup 里装工具那一步一样；旧的不动）。')
    if install is None:
        from ..install import install
    ok, _ = install(tuple(names))
    if not ok:
        say('没装好，迁移停在这里，旧的一样没动。看上面哪一样没装好，处理后再执行一次 sop machine migrate。')
    return ok


# ---------- Q3 ----------

def _system(argv):
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def old_daemon(d, admin):
    dm = d['daemon']
    return Daemon(dm['cli'], dm['host'], admin if dm.get('needs_admin') else None, label=d['label'])


def _relist(probe, d):
    return inventory.contents(probe, d['daemon'])


def _wait_up(daemon, seconds=60, sleep=time.sleep):
    for _ in range(seconds):
        if daemon.ok('version'):
            return True
        sleep(1)
    return False


class Session:
    """一次迁移里要记住、结束时要收拾的：起过的旧 Docker（结束时停回去）。"""

    def __init__(self, say, ask, probe, system=_system, relist=_relist, sleep=time.sleep):
        self.say, self.ask, self.probe, self.system, self.relist, self.sleep = say, ask, probe, system, relist, sleep
        self.started = []           # (说法, 停回去的命令)

    def admin(self):
        return self.probe.admin or ADMIN

    def ensure_listed(self, d):
        """选了卸的这份旧 Docker 还没列出里面的东西：停着的问要不要起，要管理员的问要不要输密码。返回列出来没有。"""
        dm = d.get('daemon')
        if dm is None or d.get('listed'):
            return True
        if not dm.get('cli'):
            self.say(f'找不到 {d["label"]} 的 docker 命令，列不出里面的数据卷，这一份先留着。')
            return False
        if dm.get('needs_admin') and self.probe.admin is None:
            self.say(f'{d["label"]} 只有管理员才连得上（你不在 docker 组里）。要列出里面的镜像、数据卷让你选带不带走，'
                     '后面打包也一样，要用管理员权限：系统会问这台电脑的登录密码（输入时屏幕上不显示）。只看、只打包，不改里面的东西。')
            if not self.ask.yes('现在用管理员权限吗', False):
                self.say('好，不用。这一份 Docker 先留着（不知道里面有什么，就不能卸）。')
                return False
            self.probe.admin = list(ADMIN)
        if not dm.get('running'):
            if not self._start(d):
                return False
            dm['running'] = True
        d.update(self.relist(self.probe, d))
        if not d.get('listed'):
            self.say(f'还是没列出来：{d.get("why", "")}。这一份先留着。')
            return False
        return True

    def _start(self, d):
        system = d['kind'] in ('docker.io', 'docker-ce')
        self.say(f'{d["label"]} 现在停着。要列出里面的镜像、数据卷让你选带不带走，得先把它起来（只是起来，里面的东西一样不动；'
                 f'迁移结束时再把它停回去）。' + ('起它要管理员权限，系统会问这台电脑的登录密码。' if system else ''))
        if not self.ask.yes('现在把它起来吗', False):
            self.say('好，不起。这一份 Docker 先留着（不知道里面有什么，就不能卸）。')
            return False
        if system:
            up, down = self.admin() + ['systemctl', 'start', 'docker.service'], self.admin() + ['systemctl', 'stop', 'docker.service']
        elif d['kind'] == 'rootless' and d.get('residue') and any('docker.service' in r['what'] for r in d['residue']):
            up, down = ['systemctl', '--user', 'start', 'docker.service'], ['systemctl', '--user', 'stop', 'docker.service']
        else:
            self.say('它没有登记成后台服务，工具包不知道怎么起它。你自己起来以后再执行一次 sop machine migrate；这一份先留着。')
            return False
        rc, _, err = self.system(up)
        probe_d = old_daemon(d, self.admin())
        try:
            up_ok = rc == 0 and _wait_up(probe_d, sleep=self.sleep)
        finally:
            probe_d.close()
        if not up_ok:
            self.say(f'没起来（{first_line(err) if rc else "等了一分钟还连不上"}）。这一份先留着。')
            if rc == 0:
                self.started.append((d['label'], down))
            return False
        self.started.append((d['label'], down))
        return True

    def finish(self):
        for label, down in self.started:
            rc, _, err = self.system(down)
            self.say(f'{label} 是这次为了列数据卷才起来的，已经停回去了。' if rc == 0
                     else f'{label} 是这次起来的，停回去没成（{first_line(err)}），它现在开着，不影响什么。')
        self.started = []


def _vol_line(v, now):
    size = locate.human_size(v['size_bytes']) if v.get('size_bytes') is not None else '大小量不出来'
    proj = f'属于项目 {v["project"]}' if v.get('project') else ('匿名卷' if v.get('anonymous') else '看不出属于哪个项目')
    used = inventory._used(v, now) or '最近什么时候用过看不出来'
    return f'数据卷 {v["name"]}（{size}；{proj}；{used}）'


def choose(inv, s, now):
    """Q3：每样旧工具选留还是卸（默认留）；要卸的 Docker，每个数据卷和镜像选带走还是不要（默认带走）。返回选择（能存成 JSON）。"""
    say, ask = s.say, s.ask
    out = {'made_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'docker': [], 'tools': []}
    say('')
    say('Q3 逐样选：旧的留着还是卸掉。拿不准的就留着（默认），留着只是多占点磁盘，不影响用。卸载要等后面再确认一次才真做。')
    for d in inv['docker']:
        say('')
        extra = '' if d['auto'] else '（第一版不自动带走它的数据：要留里面的数据，就先留着它）'
        pick = ask.choose(f'{d["label"]}{" " + d["version"] if d.get("version") else ""}，'
                          f'合计 {"至少 " if d.get("size_partial") else ""}{locate.human_size(d.get("size_bytes"))}'
                          f'{"，占系统盘" if d.get("on_system_disk") else ""}{extra}：',
                          [(KEEP, '留着'), (DROP, '卸掉' + ('（要输管理员密码）' if d.get('admin') else ''))], KEEP)
        c = {'kind': d['kind'], 'label': d['label'], 'choice': pick, 'volumes': {}, 'images': {}, 'skipped': []}
        if pick == DROP and d['auto'] and not s.ensure_listed(d):
            c['choice'] = KEEP
        if c['choice'] == DROP and d.get('listed'):
            _choose_data(d, c, s, now)
        out['docker'].append(c)
    for t in inv['tools']:
        for cp in t['copies']:
            say('')
            if cp.get('inside'):         # 在另一份里面的（~/.nvm 里的 node）跟着外面那一份留或卸，不单独问
                say(f'{t["name"]}：{cp["path"]} 在 {cp["inside"]} 里面，跟着它一起留或卸。')
                out['tools'].append({'name': t['name'], 'path': cp['path'], 'choice': 'inside', 'inside': cp['inside']})
                continue
            need = '要输管理员密码' if cp.get('admin') else '不用管理员密码'
            pick = ask.choose(f'{t["name"]}：{cp["path"]}（{cp.get("how_text", "")}；卸载{need}）。规定位置的那一份在 {t["location"]}：',
                              [(KEEP, '留着'), (DROP, '卸掉')], KEEP)
            out['tools'].append({'name': t['name'], 'path': cp['path'], 'choice': pick})
    return out


def _choose_data(d, c, s, now):
    say, ask = s.say, s.ask
    rw = [x for x in d.get('containers', []) if (x.get('size_rw') or 0) >= inventory.RW_NOTE]
    for x in rw:
        say(f'提醒：容器 {x["name"]} 里有 {locate.human_size(x["size_rw"])} 没放进数据卷的改动。容器不带走（由项目自己的编排文件重新起），'
            '卸掉旧的以后这些改动会丢。')
    vols = d.get('volumes', [])
    if vols:
        say(f'它里面有 {len(vols)} 个数据卷。数据卷里可能是项目的开发数据，默认带走（先备份、试着还原、核对一致，才算带走）。')
    for v in vols:
        if v.get('driver') not in (None, '', 'local'):
            c['skipped'].append(f'数据卷 {v["name"]}：用的不是普通的本机存储（{v["driver"]}），第一版不带')
            say(c['skipped'][-1])
            continue
        c['volumes'][v['name']] = ask.choose(_vol_line(v, now) + '：', [(CARRY, '带走'), (LEAVE, '不要了')], CARRY)
    imgs = d.get('images', [])
    if imgs:
        say(f'它里面有 {len(imgs)} 个镜像。从网上拉的不带也行（用到时会重新下载），自己做出来的不带就没了；分不清就带走（默认）。')
    for i in imgs:
        if not i.get('tags'):
            c['skipped'].append(f'没名字的镜像 {i["id"]}：没有名字，用不上，不带')
            say(c['skipped'][-1])
            continue
        proj = f'项目 {i["project"]}' if i.get('project') else '看不出属于哪个项目'
        used = inventory._used(i, now) or '现在没有容器用它'
        c['images'][i['id']] = ask.choose(f'镜像 {"、".join(i["tags"])}（{locate.human_size(i.get("size_bytes"))}；{proj}；{used}）：',
                                          [(CARRY, '带走'), (LEAVE, '不要了')], CARRY)


def save_choices(ch):
    os.makedirs(record.migrate_dir(), mode=0o700, exist_ok=True)
    p = record.migrate_dir() / 'choices.json'
    tmp = f'{p}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(ch, ensure_ascii=False, indent=1) + '\n')
    os.replace(tmp, p)
    return p


def summary(ch):
    L = ['', '你选的：']
    for c in ch['docker']:
        if c['choice'] == KEEP:
            L.append(f'  {c["label"]}：留着')
            continue
        carried = [n for n, v in c['volumes'].items() if v == CARRY]
        left = [n for n, v in c['volumes'].items() if v == LEAVE]
        imgs = sum(v == CARRY for v in c['images'].values())
        L.append(f'  {c["label"]}：卸掉；带走数据卷 {len(carried)} 个、镜像 {imgs} 个'
                 + (f'；不要的数据卷 {"、".join(left)}（卸载时随旧的一起删掉）' if left else ''))
    for t in ch['tools']:
        what = f'跟着 {t.get("inside")}' if t['choice'] == 'inside' else '留着' if t['choice'] == KEEP else '卸掉'
        L.append(f'  {t["name"]} {t["path"]}：{what}')
    return '\n'.join(L)


# ---------- 整条 ----------

def _new_up(s, new):
    if new.ok('version'):
        return True
    unit = 'sop-docker.service' if '/sop-docker/' in new.host else 'docker.service'
    s.say(f'规定位置的 Docker 没在运行，先把它起来（systemctl --user start {unit}）')
    s.system(['systemctl', '--user', 'start', unit])
    return _wait_up(new, 30, s.sleep)


def migrate(*, ask, say=print, inv=None, probe=None, admin=False, backup_dir=None, q2_fn=q2, new=None,
            system=_system, relist=_relist, sleep=time.sleep, free=None, machine=None, host=None):
    record.recover(say)
    with record.Running():
        probe = probe or inventory.Probe(admin=ADMIN if admin else None, notice=say)
        if inv is None:
            say('Q1 清点：看看电脑上有哪些不在规定位置的工具（只看不改）……')
            inv = inventory.inventory(probe)
        say(inventory.describe(inv, probe.now))
        inventory.save(inv)
        if not inv['docker'] and not inv['tools']:
            say('')
            say('没有不在规定位置的工具，不用迁移。')
            return 0
        say('')
        if not q2_fn(inv, say):
            return 1
        s = Session(say, ask, probe, system, relist, sleep)
        try:
            ch = choose(inv, s, probe.now)
            save_choices(ch)
            say(summary(ch))
            rc = _carry_all(inv, ch, s, backup_dir, new, free)
            if rc != 0:
                return rc
            rc = uninstall.q6(inv, ch, s, m=machine)
            host = host or oldtools.Host(probe, backup_dir=backup_dir)
            return max(rc, oldtools.q6_tools(ch, s, host=host))
        finally:
            s.finish()


def _carry_all(inv, ch, s, backup_dir, new, free):
    say = s.say
    jobs = []
    for d, c in zip(inv['docker'], ch['docker']):
        if c['choice'] != DROP or not d.get('listed'):
            continue
        vols = [v for v in d.get('volumes', []) if c['volumes'].get(v['name']) == CARRY]
        imgs = [i for i in d.get('images', []) if c['images'].get(i['id']) == CARRY]
        jobs.append((d, vols, imgs))
    if not any(v or i for _, v, i in jobs):
        say('')
        say('没有要带走的数据，Q4、Q5 不用做。')
        if jobs:
            st = C.load_state()
            for d, _, _ in jobs:
                st.setdefault('ready_for_q6', {})[d['kind']] = True
            C.save_state(st)
        return 0
    new = new or new_daemon()
    if new is None:
        say('规定位置的 Docker 没装好（找不到 ~/tools/docker/etc/docker-host），先执行 sop machine setup。旧的一样没动。')
        return 1
    try:
        if not _new_up(s, new):
            say('规定位置的 Docker 起不来，迁移停在这里，旧的一样没动。执行 sop machine doctor 看看。')
            return 1
        backup = backup_dir or C.default_backup_dir()
        all_v = [v for _, vs, _ in jobs for v in vs]
        all_i = [i for _, _, im in jobs for i in im]
        say('')
        say(f'Q4 备份并带走：备份放在 {locate.short(str(backup))}（想换地方：sop machine migrate --backup-dir <目录>）。')
        new_data = paths.tools_dir() / 'docker' / 'data'
        ok, text = C.space_plan(all_v, all_i, backup, new_data, **({'free': free} if free else {}))
        say(text)
        if not ok:
            return 1
        for d, vols, imgs in jobs:
            old = old_daemon(d, s.admin())
            try:
                def confirm(names, d=d):
                    say(f'要打包的数据卷正被 {d["label"]} 里的容器 {"、".join(names)} 用着。数据库这类正在写的，边写边打包可能不完整，'
                        '所以先把它们停一下，打完包马上起回来（停的时间大约就是打包的时间）。')
                    return s.ask.yes('现在停一下吗', False)
                C.carry(old, new, vols, imgs, backup, scope=d['kind'], say=say, confirm_stop=confirm)
                say('')
                say('Q5 核对：')
                good, bad = C.verify(new, vols, imgs, scope=d['kind'], say=say)
            except C.CarryError as e:
                say(str(e))
                say('迁移停在这里，旧的照常可用。处理后再执行一次 sop machine migrate，做完的会跳过。')
                return 1
            finally:
                old.close()
            if not good:
                say('核对没通过：')
                for b in bad:
                    say(f'  {b}')
                say('旧的照常可用、不会卸。再执行一次 sop machine migrate 会重新核对。')
                return 1
        say('')
        say('带走的镜像和数据卷都核对过了，和搬之前一致。' + C.remove_backup_hint(backup))
        return 0
    finally:
        new.close()


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='sop machine migrate', description='环境迁移：规定位置装新的，旧的逐样由你选留还是卸（Q1 到 Q6）')
    ap.add_argument('--admin', action='store_true', help='一开始就用管理员权限（清点时量全系统盘上 Docker 的目录；会问一次密码）')
    ap.add_argument('--backup-dir', help='备份放在哪（默认 ~/tools/backup/migrate-<日期>）')
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        return migrate(ask=Ask(), admin=a.admin, backup_dir=os.path.abspath(os.path.expanduser(a.backup_dir)) if a.backup_dir else None)
    except SopError as e:
        print(str(e))
        return 1
