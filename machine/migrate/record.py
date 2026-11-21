"""迁移中停掉的旧容器的记录（设计书 4.8 Q4、4.3 的 config/；3-31）。

Q4 打包数据卷之前要先停掉正在用它的旧容器（数据库正在写时打包可能不完整），这是「旧的一样都不动」的一个例外：
事先告诉小白、事后起回来。中途出错时迁移自己会起回来；可是断电、被强制结束、终端被关掉时它来不及。所以：

- 停容器之前，先把「停了哪几个、在哪份 Docker 里」写进 ~/tools/sop/config/migrate/stopped.json；
  迁移往旧 Docker 里临时放了一个小镜像（打包用的）时也记在这里，用完删掉；
- `sop` 每次启动（任何子命令）先看它（recover）：有就先把那几个容器起回来、把临时放的小镜像删掉，都做好了才删记录；
  没做成就说清楚、记录留着，下次再试，不挡这次要做的事；
- 同一时刻只能有一个迁移（running.lock，文件锁，进程怎么死都由系统放开）。迁移正在进行时，别的终端里的 `sop` 不去起
  那几个容器（不然正在打包的卷会被写）。
"""
import fcntl
import json
import os

from kernel import paths
from kernel.errors import SopError

from .dockercli import Daemon, first_line


def migrate_dir():
    return paths.config_dir() / 'migrate'


def record_path():
    return migrate_dir() / 'stopped.json'


def lock_path():
    return migrate_dir() / 'running.lock'


class Busy(SopError):
    pass


class Running:
    """迁移进行中拿着的锁。另一个终端里已经在迁移时抛 Busy。"""

    def __init__(self):
        self.fd = None

    def __enter__(self):
        os.makedirs(migrate_dir(), mode=0o700, exist_ok=True)
        self.fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise Busy('另一个终端里正在做环境迁移。等它做完再执行。') from None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def load():
    """读记录；没有返回 None；读不懂抛 ValueError。"""
    try:
        with open(record_path(), encoding='utf-8') as f:
            d = json.load(f)
    except FileNotFoundError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get('old'), dict):
        raise ValueError('记录的格式不对')
    d.setdefault('containers', [])
    d.setdefault('helper_added', '')
    return d


def _write(d):
    if not d['containers'] and not d.get('helper_added'):
        try:
            os.unlink(record_path())
        except FileNotFoundError:
            pass
        return
    os.makedirs(migrate_dir(), mode=0o700, exist_ok=True)
    tmp = f'{record_path()}.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, record_path())
    dfd = os.open(migrate_dir(), os.O_RDONLY)
    try:
        os.fsync(dfd)           # 断电也要留得住：先落盘，再去停容器
    finally:
        os.close(dfd)


def _current(old):
    d = load() or {'old': old.as_record(), 'containers': [], 'helper_added': ''}
    if d['old'].get('host') != old.host:
        raise SopError(f'上一次迁移停掉的容器还没起回来（{d["old"].get("host")}），先执行一次 sop 把它们起回来')
    return d


def add_stopped(old, names):
    d = _current(old)
    d['containers'] = sorted(set(d['containers']) | set(names))
    _write(d)


def remove_stopped(old, names):
    d = _current(old)
    d['containers'] = [c for c in d['containers'] if c not in set(names)]
    _write(d)


def set_helper(old, image):
    """往旧 Docker 里临时放了打包用的小镜像（image），或者删掉了（''）。"""
    d = _current(old)
    d['helper_added'] = image
    _write(d)


def recover(say=None):
    """`sop` 每次启动先调（kernel/cli.py）。没有记录就什么都不做（只看一个文件在不在）。
    返回 True：没有要起回来的，或者起回来了；False：没起回来（已经说清楚，记录留着）。从不抛错。"""
    say = say or print
    try:
        if not record_path().exists():
            return True
    except OSError:
        return True
    try:
        with Running():
            return _recover(say)
    except Busy:
        return True          # 迁移正在另一个终端里进行，它自己会起回来
    except Exception as e:  # noqa: BLE001  这一步不能挡住 sop 要做的事
        say(f'提醒：上次环境迁移停掉的旧容器没能起回来：{e}。记录在 {record_path()}，下次执行 sop 再试。')
        return False


def _recover(say):
    try:
        d = load()
    except ValueError as e:
        say(f'提醒：上次环境迁移留下的记录 {record_path()} 读不懂（{e}），没有自动起回容器。'
            '请看一下旧 Docker 里的容器是不是都起来了。')
        return False
    if d is None:
        return True
    old = Daemon.from_record(d['old'])
    try:
        names = d['containers']
        if names:
            say(f'上次环境迁移时，为了备份数据卷停掉了旧 Docker 里的容器 {"、".join(names)}，迁移没走完就断了。现在先把它们起回来。')
            if old.admin:
                say('旧的 Docker 要管理员权限才能操作，系统会问一次这台电脑的登录密码（输入时屏幕上不显示）。')
            rc, _, err = old.run('start', *names, timeout=300)
            if rc != 0:
                say(f'没起回来：{first_line(err)}。记录留着，下次执行 sop 会再试；也可以自己执行：'
                    f'{"sudo " if old.admin else ""}{old.cli} --host {old.host} start {" ".join(names)}')
                return False
            d['containers'] = []
            _write(d)
            say(f'旧容器 {"、".join(names)} 已经起回来了。')
        if d.get('helper_added'):
            rc, _, err = old.run('image', 'rm', d['helper_added'], timeout=120)
            if rc == 0 or 'No such image' in err:
                d['helper_added'] = ''
                _write(d)
            else:
                say(f'提醒：迁移临时放进旧 Docker 的小镜像 {d["helper_added"]} 没删掉（{first_line(err)}），下次执行 sop 再试。')
                return False
        return True
    finally:
        old.close()
