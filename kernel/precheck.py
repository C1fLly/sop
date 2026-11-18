"""特权侧用之前核对（设计书 6.4 第四层、6.2 第二条，v0.9）。

特权侧每次执行 wt、Git、gh 之前调用 verify()；特权侧自己执行完会改 .git/config 的命令（wt new、wt pr、git config 等）之后，
调用 record() 重新记下 .git/config 的指纹。指纹存在 ~/tools/sop/state/<项目名>/git-config.sha256，不在项目根下。
"""
import hashlib
import pathlib

from checks.precheck.check import run as _check

from . import paths
from .errors import Tampered

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_HOOKS = TOOLKIT / 'templates' / 'wt' / 'hooks'


def _file(project):
    return paths.state_dir(project) / 'git-config.sha256'


def record(project, root):
    f = _file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(hashlib.sha256((pathlib.Path(root) / '.git' / 'config').read_bytes()).hexdigest())


def recorded(project):
    f = _file(project)
    return f.read_text().strip() if f.exists() else None


def verify(project, root, worktrees=()):
    ok, line, rep = _check(str(root), str(TEMPLATE_HOOKS), recorded(project), list(worktrees))
    if not ok:
        raise Tampered(line + '。已停下，不执行。请启动维修窗口（sop repair）。')
    return rep
