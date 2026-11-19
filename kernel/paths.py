"""固定位置（设计书 4.3）。

工具包的根目录默认是 ~/tools/sop，可以用环境变量 SOP_HOME 换掉：自测一律放在 /tmp 下的临时根目录里，
不碰真的 ~/tools/sop/state、~/tools/sop/config。
"""
import os
import pathlib
import re

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
