"""体检：工具在哪（设计书 4.3「合格」、10.1，任务 3-06）。只读：只看文件在不在、量大小、跑 `--version`，不装、不删、不挪。

两件事：
- **另有一份不在规定位置的**（others）：工具包自己装的那几样（uv、nvm、Node、pnpm、gh、Docker、wt），
  按 tools.toml 的 command 在 PATH 里找、再看 elsewhere 列的别的装法常放的位置；解开链接后在规定位置里面的不算
  （例如 ~/.local/bin/wt 指向 ~/tools/wt/wt）。每一份写明在哪、占多大、占的是不是系统盘。
  一份在前面另一份的目录里面的（例如 ~/.nvm 里的 node），大小算在外面那一份里，不重复算。
- **AI 工具**（Claude Code、Codex、OpenCode、Pi）：保持各自官方装法的默认位置，不归工具包管（4.3）；
  这里找它在哪、什么版本。查版本时 HOME 和 XDG 那几个目录都指到一个现建的临时目录、环境变量里不带任何密钥；
  有 bubblewrap 时再套一层「整个系统只读、只有临时目录能写」，所以它读不到、也写不进用户自己的配置目录和它的安装目录。

「占不占系统盘」按文件系统算，和剩余空间提醒（space.py）一样：和 / 是同一个文件系统就算占系统盘。
大小按实际占的磁盘算（和 du 一样），不跨到别的文件系统里去；有的地方没权限看，大小写成「至少」。
"""
import dataclasses
import os
import shutil
import signal
import subprocess
import tempfile

from . import catalog, config, space

# AI 工具：(登记名, 给人看的名字, 命令名, 官方装法的默认位置)。版本用 `<命令> --version` 查。
AI_TOOLS = (
    ('claude', 'Claude Code', 'claude', ('~/.local/bin/claude', '~/.claude/local/claude')),
    ('codex', 'Codex', 'codex', ('~/.local/bin/codex',)),
    ('opencode', 'OpenCode', 'opencode', ('~/.opencode/bin/opencode',)),
    ('pi', 'Pi', 'pi', ('~/.local/bin/pi',)),
)


@dataclasses.dataclass
class Copy:
    path: str                     # 找到的位置
    real: str                     # 解开链接之后
    size: int | None = None       # 占多大（字节）；在另一份里面的是 None
    partial: bool = False         # 有的地方没权限看，size 是「至少」
    on_system_disk: bool | None = None
    inside: str = ''              # 在另一份（这个目录）里面，大小算在那边

    def as_record(self):
        d = {'path': self.path, 'real': self.real, 'size_bytes': self.size, 'on_system_disk': self.on_system_disk}
        if self.partial:
            d['size_partial'] = True
        if self.inside:
            d['inside'] = self.inside
        return d


def expand(p, home=None):
    home = home or os.path.expanduser('~')
    return home + p[1:] if p.startswith('~/') else p


def which_all(command, path_env=None):
    """像 `which -a`：PATH 里每一个能执行的同名文件，按 PATH 的先后。"""
    out = []
    for d in (os.environ.get('PATH', '') if path_env is None else path_env).split(os.pathsep):
        if not d:
            continue
        f = os.path.join(d, command)
        if os.path.isfile(f) and os.access(f, os.X_OK) and f not in out:
            out.append(f)
    return out


def _under(p, root):
    return p == root or p.startswith(root.rstrip('/') + '/')


def disk_usage(path):
    """占的磁盘（字节）和「有没有没权限看的地方」。不跟着链接走，不跨到别的文件系统，硬链接只算一次。"""
    try:
        st = os.lstat(path)
    except OSError:
        return None, True
    total, partial, seen = st.st_blocks * 512, False, set()
    if not os.path.isdir(path) or os.path.islink(path):
        return total, False
    dev, stack = st.st_dev, [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            partial = True
            continue
        with it:
            for e in it:
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    partial = True
                    continue
                if s.st_dev != dev:
                    continue
                if s.st_nlink > 1 and not e.is_dir(follow_symlinks=False):
                    if (s.st_dev, s.st_ino) in seen:
                        continue
                    seen.add((s.st_dev, s.st_ino))
                total += s.st_blocks * 512
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
    return total, partial


class SystemDisk:
    """「这个位置占不占系统盘」，按文件系统算；同一个设备号只查一次。"""

    def __init__(self, run=subprocess.run, same=None):
        self.run, self.cache = run, {}
        self.same = same or (lambda p: space.same_filesystem('/', p, run=self.run))

    def __call__(self, path):
        try:
            dev = os.stat(path).st_dev
        except OSError:
            return None
        if dev not in self.cache:
            self.cache[dev] = self.same(path)
        return self.cache[dev]


def find_others(tool, *, taken=None, path_env=None, home=None, usage=disk_usage, sysdisk=None):
    """工具包自己装的这一样，另外几份不在规定位置的（[Copy]）。系统软件包没有「另一份」，返回 []。
    taken 是前面几样已经找到的另一份（[Copy]，会往里加），在它们目录里面的不重复算大小。"""
    if tool.system_package:
        return []
    taken = [] if taken is None else taken
    sysdisk = sysdisk or SystemDisk()
    in_place = os.path.realpath(tool.path())
    cands = (which_all(tool.command, path_env) if tool.command else []) + [expand(p, home) for p in tool.elsewhere]
    found, reals = [], set()
    for c in cands:
        if not os.path.lexists(c):
            continue
        real = os.path.realpath(c)
        if _under(real, in_place) or real in reals or not os.path.exists(real):
            continue
        reals.add(real)
        cp = Copy(c, real)
        outer = next((t for t in taken if os.path.isdir(t.real) and _under(real, t.real)), None)
        if outer:
            cp.inside = outer.path
            cp.on_system_disk = outer.on_system_disk
        else:
            cp.size, cp.partial = usage(real)
            cp.on_system_disk = sysdisk(real)
        found.append(cp)
        taken.append(cp)
    return found


@dataclasses.dataclass
class ToolStatus:
    tool: catalog.Tool
    check: catalog.CheckResult
    path: str                     # SOP 用的那一份在哪：工具包自己装的是规定位置；系统软件包是命令实际在哪
    others: list

    @property
    def state(self):
        """ok 合格；old 装了但版本不够；missing 规定位置上没有。"""
        if not self.check.installed:
            return 'missing'
        return 'ok' if self.check.ok else 'old'

    def as_record(self):
        return config.tool_entry(path=self.path, version=self.check.version_text if self.check.installed else None,
                                 kind='base', in_place=self.check.installed, others=[o.as_record() for o in self.others],
                                 state=self.state)


def check_tools(tools=None, *, path_env=None, home=None, run_check=catalog.run_check, usage=disk_usage, sysdisk=None):
    """按 tools.toml 逐样核对规定位置，再找另外几份。返回 [ToolStatus]，按清单的先后。"""
    tools = catalog.load() if tools is None else tools
    sysdisk = sysdisk or SystemDisk()
    taken, out = [], []
    for t in tools:
        r = run_check(t)
        if t.system_package:
            where = (which_all(t.command, path_env) or [catalog.SYSTEM])[0] if t.command else catalog.SYSTEM
        else:
            where = str(t.path())
        others = find_others(t, taken=taken, path_env=path_env, home=home, usage=usage, sysdisk=sysdisk)
        out.append(ToolStatus(t, r, where, others))
    return out


# ---------- AI 工具 ----------

@dataclasses.dataclass
class AiTool:
    name: str
    label: str
    path: str = ''                # 找到的位置（PATH 里第一个，没有就看默认位置）；没找到是空的
    real: str = ''
    version: str | None = None
    output: str = ''

    @property
    def found(self):
        return bool(self.path)

    def as_record(self):
        return config.tool_entry(path=self.path, version=self.version, kind='ai', in_place=self.found,
                                 real=self.real, installed=self.found)


def clean_env(home):
    """查 AI 工具版本用的环境：只留 PATH 和语言，HOME 和 XDG 那几个目录指到临时目录，不带任何密钥。"""
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TERM') if k in os.environ}
    env.update({'HOME': home, 'XDG_CONFIG_HOME': f'{home}/.config', 'XDG_DATA_HOME': f'{home}/.local/share',
                'XDG_CACHE_HOME': f'{home}/.cache', 'XDG_STATE_HOME': f'{home}/.local/state', 'LC_ALL': 'C.UTF-8',
                'NO_COLOR': '1', 'CI': '1'})
    return env


def _run_version(cmd, tmp, timeout):
    try:
        p = subprocess.Popen(cmd, env=clean_env(tmp), cwd=tmp, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        return None, '', f'运行不了：{e.strerror or e}'
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return None, '', f'{timeout} 秒没结束'
    return p.returncode, out, err


def tool_version(exe, timeout=30, bwrap=None):
    """跑 `<exe> --version`，返回 (版本文字或 None, 输出)。在临时 HOME 里跑，跑完删掉。
    有 bubblewrap 时套一层：整个系统只读、只有临时 HOME 能写（实测 Pi 查版本时会动它自己安装目录里的东西）。
    bubblewrap 还没装（新电脑上体检在安装之前）或者起不来时，不套，照样在临时 HOME 里跑。"""
    bwrap = shutil.which('bwrap') if bwrap is None else bwrap
    with tempfile.TemporaryDirectory(prefix='sop-doctor-') as tmp:
        rc = out = err = None
        if bwrap:
            rc, out, err = _run_version([bwrap, '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
                                         '--bind', tmp, tmp, '--die-with-parent', '--', exe, '--version'], tmp, timeout)
            if rc is not None and rc != 0 and err.lstrip().startswith('bwrap:'):
                rc = None    # 是 bubblewrap 自己起不来，不是工具的问题：不套再跑一次
                err = ''
        if rc is None and not err:
            rc, out, err = _run_version([exe, '--version'], tmp, timeout)
    if rc is None:
        return None, err
    text = (out + err).strip()
    v = catalog.parse_version(out or err) if rc == 0 else None
    return ('.'.join(map(str, v)) if v else None), text


def find_ai_tools(*, path_env=None, home=None, version=tool_version, table=AI_TOOLS):
    out = []
    for name, label, command, defaults in table:
        a = AiTool(name, label)
        cands = which_all(command, path_env) + [expand(p, home) for p in defaults]
        hit = next((c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK)), None)
        if hit:
            a.path, a.real = hit, os.path.realpath(hit)
            a.version, a.output = version(hit)
        out.append(a)
    return out


def short(p, home=None):
    """给人看的路径：主目录写成 ~。"""
    home = (home or os.path.expanduser('~')).rstrip('/')
    p = str(p)
    return '~' + p[len(home):] if _under(p, home) else p


def human_size(n):
    if n is None:
        return '大小量不出来'
    for unit, k in (('GB', 1000 ** 3), ('MB', 1000 ** 2), ('KB', 1000)):
        if n >= k:
            return f'{n / k:.1f} {unit}'
    return f'{n} 字节'


if __name__ == '__main__':
    for s in check_tools():
        print(s.tool.name, s.state, s.path, [(short(o.path), human_size(o.size), o.on_system_disk, o.inside) for o in s.others])
    for a in find_ai_tools():
        print(a.label, a.path, a.version)
