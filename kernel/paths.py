"""固定位置（设计书 4.3）。

工具包的根目录默认是 ~/tools/sop，可以用环境变量 SOP_HOME 换掉：自测一律放在 /tmp 下的临时根目录里，
不碰真的 ~/tools/sop/state、~/tools/sop/config。
"""
import os
import pathlib
import pwd
import re

from .errors import SopError

PROJECT_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')


def sop_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get('SOP_HOME') or '~/tools/sop').expanduser()


def config_dir() -> pathlib.Path:
    """机器级配置和登记：网络设置、工具位置、端口登记、迁移中停掉的容器的记录。"""
    return sop_home() / 'config'


def tools_dir() -> pathlib.Path:
    """所有工具的固定目录（4.3），平常是 ~/tools，也就是工具包根目录的上一层。自测用 SOP_TOOLS_DIR 换掉。"""
    return pathlib.Path(os.environ.get('SOP_TOOLS_DIR') or sop_home().parent).expanduser()


def versions_dir() -> pathlib.Path:
    return sop_home() / 'versions'


def projects_dir() -> pathlib.Path:
    """项目都放在这里（4.3：~/Project/<项目名>）。自测用 SOP_PROJECTS_DIR 换掉，不碰真的 ~/Project。"""
    return pathlib.Path(os.environ.get('SOP_PROJECTS_DIR') or '~/Project').expanduser()


def check_project_name(name: str) -> str:
    if not PROJECT_NAME.match(name):
        raise ValueError(f'项目名只能用小写字母、数字和「-」：{name!r}')
    return name


def state_dir(project: str) -> pathlib.Path:
    """每个项目在本机的流程状态：运行日志、AI 状态目录、锁、窄接口、.git/config 的指纹。不在项目根下（6.3 二）。"""
    return sop_home() / 'state' / check_project_name(project)


def runtime_dir() -> pathlib.Path:
    """只有用户自己能进的运行时目录，放复用 SSH 连接的通道文件（6.2 第一条）。
    受限环境里 /run 是空的，专用 Docker 的视野里也没有它。"""
    base = os.environ.get('SOP_RUNTIME_DIR') or os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'sop')
    p = pathlib.Path(base)
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


# ---------- 自测的保险（3-59） ----------
TEST_MARK = 'SOP_UNDER_TEST'     # 自测时 tests/__init__.py 设的：值是自测那个公用的假主目录


class HomeGuard(SopError):
    """会写主目录的入口发现自己像是在自测里、主目录却是真的（或是自测那个公用的假主目录），停下不做。"""


def account_home() -> pathlib.Path:
    """这个账号真的主目录（按系统的账号记录，不看 HOME）。"""
    return pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)


def _same(a, b) -> bool:
    return os.path.realpath(os.path.expanduser(str(a))) == os.path.realpath(str(b))


def guard_home(what: str):
    """会改主目录里的东西（终端启动文件、~/.ssh、~/.gitconfig、全局规则、用户级服务、要管理员密码的安装）之前调一下。

    3-12 出过事：一个测试只把 SOP_HOME 指到临时目录、HOME 却是本机真的，结果 sop machine setup 往本机的 ~/.bashrc 写了一段。
    所以这两种情况一律停下（抛 HomeGuard），一个字都不写：
    - 主目录是这个账号真的主目录（或者 HOME 没设，Python 会退回去用真的），环境里却带着自测的痕迹：
      工具包根目录、工具目录、项目目录不是默认的，换了工具清单（SOP_TOOLS_TOML），设了运行时目录（SOP_RUNTIME_DIR），
      或者正在跑自测（SOP_UNDER_TEST）。平常用户自己执行时这些都没有，不受影响。
    - 主目录就是自测那个公用的假主目录（SOP_UNDER_TEST 的值）：这个测试没给自己单独建主目录，不让它往公用的里面写。"""
    raw = os.environ.get('HOME')
    real = account_home()
    mark = os.environ.get(TEST_MARK)
    if mark and raw and _same(raw, mark):
        raise HomeGuard(f'自测的保险：{what} 要改主目录里的东西，可是主目录是自测公用的假主目录 {raw}'
                        '（这个测试没给自己单独设 HOME）。什么都没做。请在测试里把 HOME 指到这个测试自己的临时目录')
    if raw and not _same(raw, real):
        return
    signs = []
    if not raw:
        signs.append('环境变量 HOME 没设')
    if mark:
        signs.append('正在跑自测（SOP_UNDER_TEST）')
    for var, default in (('SOP_HOME', real / 'tools' / 'sop'), ('SOP_TOOLS_DIR', real / 'tools'), ('SOP_PROJECTS_DIR', real / 'Project')):
        v = os.environ.get(var)
        if v and not _same(v, default):
            signs.append(f'{var} 指到 {v}')
    for var in ('SOP_TOOLS_TOML', 'SOP_RUNTIME_DIR'):
        if os.environ.get(var):
            signs.append(f'设了 {var}')
    if signs:
        raise HomeGuard(f'自测的保险：{what} 要改主目录里的东西，主目录却是这台电脑真的主目录 {real}，'
                        f'而环境像是在自测里（{"；".join(signs)}）。什么都没做。请在测试里把 HOME 指到临时目录')
