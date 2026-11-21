"""迁移时调 docker 命令的统一办法（3-31）：总是明说通道（--host）、用一个现建的空设置目录（--config），
不靠也不碰终端里的默认指向、DOCKER_HOST 和 ~/.docker（和清点 inventory.py 一样）。旧的那份要管理员才连得上时，前面加 sudo。"""
import os
import shutil
import subprocess
import tempfile

from kernel import paths

SUDO_PROMPT = '[sudo] 请输入 %u 的登录密码：'
ADMIN = ['sudo', '-p', SUDO_PROMPT]


class Daemon:
    """一份 Docker：cli 是 docker 命令的位置，host 是通道（unix:///…），admin 是要管理员时前面加的（例如 ADMIN），不要就是 None。"""

    def __init__(self, cli, host, admin=None, label=''):
        self.cli, self.host, self.admin, self.label = cli, host, list(admin) if admin else None, label
        self._cfg = None

    def as_record(self):
        return {'cli': self.cli, 'host': self.host, 'admin': self.admin, 'label': self.label}

    @classmethod
    def from_record(cls, d):
        return cls(d['cli'], d['host'], d.get('admin'), d.get('label', ''))

    def argv(self, *args):
        if self._cfg is None:
            self._cfg = tempfile.mkdtemp(prefix='sop-migrate-cfg-')
        return (self.admin or []) + [self.cli, '--config', self._cfg, '--host', self.host, *args]

    def run(self, *args, stdin=None, stdout=None, timeout=None):
        """跑一条 docker 命令。stdin/stdout 可以给打开的文件（打包、导出镜像时直接写文件，不经内存）。
        返回 (退出码, 输出, 报错)；stdout 给了文件时输出是空的。"""
        env = {k: v for k, v in os.environ.items() if not k.startswith('DOCKER_')}
        env.update(LC_ALL='C.UTF-8', LANG='C.UTF-8')
        try:
            p = subprocess.run(self.argv(*args), env=env, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                               stdout=stdout if stdout is not None else subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout)
        except FileNotFoundError:
            return 127, '', f'没有这个命令：{self.cli}'
        except subprocess.TimeoutExpired:
            return 124, '', f'docker {" ".join(args[:2])} {timeout} 秒没结束'
        out = p.stdout.decode('utf-8', 'replace') if isinstance(p.stdout, bytes) else ''
        return p.returncode, out, p.stderr.decode('utf-8', 'replace')

    def ok(self, *args, **kw):
        return self.run(*args, **kw)[0] == 0

    def close(self):
        if self._cfg:
            shutil.rmtree(self._cfg, ignore_errors=True)
            self._cfg = None


def first_line(err):
    return (err or '').strip().splitlines()[-1] if (err or '').strip() else '没有报错信息'


def new_daemon():
    """规定位置那一份（~/tools/docker）：安装脚本把通道写在 ~/tools/docker/etc/docker-host。没装好返回 None。"""
    t = paths.tools_dir() / 'docker'
    cli = t / 'bin' / 'docker'
    try:
        host = (t / 'etc' / 'docker-host').read_text().strip()
    except OSError:
        return None
    if not host or not os.access(cli, os.X_OK):
        return None
    return Daemon(str(cli), host, label='规定位置的 Docker')
