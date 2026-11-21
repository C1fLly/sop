"""工具包装的工具要用的环境变量，和终端启动文件里那一段受管的几行（设计书 4.3、4.8；W36）。

同一份变量两处用：
- 写进 ~/.bashrc 末尾一段带开头结尾标记的几行，告诉终端去 ~/tools 下找 nvm、uv、gh、pnpm，缓存放 ~/tools/cache/<工具名>；
- 安装脚本运行时也用这一份（install.py），装的过程中下载的东西同样落在 ~/tools 下。

pnpm 12 只认 pnpm_config_ 开头的变量（W36：npm_config_ 开头的它不认，用 pnpm config set 又会写 ~/.config/pnpm）。
uv 装 Python 时默认往 ~/.local/bin 放一份可执行文件，所以 UV_PYTHON_BIN_DIR 也指进来。
gh 默认每跑一次往 ~/.local/state/gh 写统计用的编号，GH_TELEMETRY=0 关掉。

那一段之外的字一个不动：已经有这一段就原地换掉，没有就加在文件末尾；开头结尾标记对不上（只有一头、有两段）就不改，明说。
"""
import os
import pathlib

from kernel import paths
from kernel.errors import SopError

BEGIN = '# >>> SOP 工具包管理的段落（不要手改，重新安装时会被换回来）>>>'
END = '# <<< SOP 工具包管理的段落 <<<'

# (变量名, 值)。{T} 是工具目录。
VARIABLES = (
    ('NVM_DIR', '{T}/nvm'),
    ('npm_config_cache', '{T}/cache/npm'),
    ('npm_config_update_notifier', 'false'),
    ('pnpm_config_store_dir', '{T}/cache/pnpm/store'),
    ('pnpm_config_cache_dir', '{T}/cache/pnpm/cache'),
    ('pnpm_config_state_dir', '{T}/cache/pnpm/state'),
    ('PNPM_HOME', '{T}/pnpm'),
    ('UV_CACHE_DIR', '{T}/cache/uv'),
    ('UV_PYTHON_INSTALL_DIR', '{T}/uv/python'),
    ('UV_PYTHON_BIN_DIR', '{T}/uv/bin'),
    ('UV_TOOL_DIR', '{T}/uv/tools'),
    ('UV_TOOL_BIN_DIR', '{T}/uv/bin'),
    # gh 每跑一次都往 ~/.local/state/gh 写一个统计用的编号（3-08 在虚拟机里看到的），关掉统计就不写；
    # 它也不用自己提示升级（升级重跑工具包的安装脚本）
    ('GH_TELEMETRY', '0'),
    ('GH_NO_UPDATE_NOTIFIER', '1'),
)
# 放到 PATH 最前面；Node 和 pnpm 由 nvm.sh 放。pnpm 12 全局装的命令在 $PNPM_HOME/bin（不是 $PNPM_HOME）。
# 免管理员 Docker 的命令（3-09）：敲 docker 用规定位置的那个程序；连哪一份 Docker 看默认指向（context），
# 电脑上另有一份时安装脚本把默认指向切回原来那份，所以敲 docker 看到的还是原来的（4.8）
# 第零步（3-13）：~/tools/sop 里的启动器 sop，新开的终端敲 sop 就能用
PATH_DIRS = ('{T}/uv/bin', '{T}/gh/bin', '{T}/pnpm/bin', '{T}/docker/bin', '{T}/sop')
CACHE_DIRS = ('cache/uv', 'cache/npm', 'cache/pnpm')
# 网络设置里的软件源（4.4「安装脚本按它配置各工具」）：设了才写
REGISTRIES = {
    'npm_registry': ('npm_config_registry', 'pnpm_config_registry'),
    'pypi_index': ('UV_DEFAULT_INDEX',),
}
UNSAFE = set('"$`\\\n')
# 指向别处那一份（旧的 ~/.nvm、~/.local/bin/uv……）的变量：运行安装脚本、检查命令时去掉，换成规定位置的
FOREIGN_PREFIXES = ('NVM_', 'UV_', 'PNPM_', 'npm_config_', 'pnpm_config_')


class ShellEnvError(SopError):
    pass


def _base(tools_dir, for_shell):
    t = pathlib.Path(tools_dir) if tools_dir else paths.tools_dir()
    if for_shell and t == pathlib.Path.home() / 'tools':
        return '$HOME/tools'
    t = str(t)
    if UNSAFE & set(t):
        raise ShellEnvError(f'工具目录的路径里有不能写进终端启动文件的字符：{t}')
    return t


def variables(tools_dir=None, net=None, *, for_shell=False):
    """[(变量名, 值)]。for_shell=True 时工具目录写成 $HOME/tools（给终端启动文件），否则是真实路径（给安装脚本）。"""
    t = _base(tools_dir, for_shell)
    out = [(k, v.format(T=t)) for k, v in VARIABLES]
    for key, names in REGISTRIES.items():
        url = (net or {}).get(key)
        if url:
            if UNSAFE & set(url):
                raise ShellEnvError(f'网络设置里「{key}」有不能写进终端启动文件的字符：{url}')
            out += [(n, url) for n in names]
    return out


def path_dirs(tools_dir=None, *, for_shell=False):
    t = _base(tools_dir, for_shell)
    return [d.format(T=t) for d in PATH_DIRS]


def environ(tools_dir=None, net=None, base=None):
    """给安装脚本、检查命令用的环境：原来的环境（默认 os.environ）去掉 FOREIGN_PREFIXES 开头的变量，
    换上规定位置的，SOP_TOOLS 是工具目录，PATH 前面加上规定位置的几个目录。"""
    t = paths.tools_dir() if tools_dir is None else pathlib.Path(tools_dir)
    env = {k: v for k, v in (os.environ if base is None else base).items() if not k.startswith(FOREIGN_PREFIXES)}
    env.update(variables(t, net))
    env['SOP_TOOLS'] = str(t)
    env['PATH'] = ':'.join(path_dirs(t) + [env.get('PATH') or '/usr/bin:/bin'])
    return env


def block(tools_dir=None, net=None):
    """终端启动文件里那一段的全文（带开头结尾标记，最后有换行）。"""
    lines = [BEGIN,
             '# 告诉终端去 ~/tools 下找工具包装的工具（sop，nvm 和它装的 Node、pnpm，uv 和它装的 Python，gh，免管理员的 Docker），',
             '# 各工具的缓存放 ~/tools/cache 下（设计书 4.3）。'] + \
            [f'export {k}="{v}"' for k, v in variables(tools_dir, net, for_shell=True)] + \
            ['[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"',
             'export PATH="' + ':'.join(path_dirs(tools_dir, for_shell=True)) + ':$PATH"',
             END]
    return '\n'.join(lines) + '\n'


def rc_file():
    return pathlib.Path.home() / '.bashrc'


def _find(lines, mark):
    return [i for i, line in enumerate(lines) if line.rstrip('\n') == mark]


def apply(text, new_block, begin=BEGIN, end=END, what='终端启动文件'):
    """返回加好（或换好）这一段之后的全文。标记对不上就报错、不改。
    begin、end 换成别的标记，全局规则文件（globalrules.py，M7）也用这一套。"""
    lines = text.splitlines(keepends=True)
    b, e = _find(lines, begin), _find(lines, end)
    if not b and not e:
        sep = '' if not text else ('\n' if text.endswith('\n') else '\n\n')
        return text + sep + new_block
    if len(b) == 1 and len(e) == 1 and b[0] < e[0]:
        return ''.join(lines[:b[0]]) + new_block + ''.join(lines[e[0] + 1:])
    raise ShellEnvError(f'{what}里工具包那一段的开头、结尾标记对不上（只剩一头，或者有两段），'
                        '为了不改坏别的内容，这次没有改它。可以把那几行删干净后再装一次')


def read_text(target, what):
    """读出文件的文字和权限；没有这个文件就是空的、0644。不是 UTF-8 就报错。"""
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return '', 0o644
    try:
        return raw.decode('utf-8'), target.stat().st_mode & 0o7777
    except UnicodeDecodeError:
        raise ShellEnvError(f'{what} {target} 不是 UTF-8 的文字，没有改它') from None


def write_text(target, text, mode):
    """先写临时文件再换名，写到一半断了也不会留下坏文件；权限照原来的。"""
    tmp = target.with_name(f'.{target.name}.sop-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, target)


def install_block(rc=None, tools_dir=None, net=None):
    """把那一段写进终端启动文件（平常是 ~/.bashrc）。内容没变就不写（文件的修改时间也不动）。返回改没改。"""
    if not rc:
        paths.guard_home('往 ~/.bashrc 写工具包那一段')     # 自测的保险（3-59）：给了别的文件就是调用的人自己定的
    rc = pathlib.Path(rc) if rc else rc_file()
    target = pathlib.Path(os.path.realpath(rc))    # 是链接（管点文件的工具常这么做）就写到它指的那个文件
    text, mode = read_text(target, '终端启动文件')
    new = apply(text, block(tools_dir, net))
    if new == text:
        return False
    write_text(target, new, mode)
    return True
