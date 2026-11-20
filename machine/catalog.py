"""读工具清单 machine/tools.toml（设计书 4.4），比版本，跑检查命令。

清单写错了（少字段、名字重复、apt 装的却说不要管理员密码……）读的时候就报出来，说清是哪一项哪个字段。
"""
import dataclasses
import os
import pathlib
import re
import signal
import subprocess
import tomllib

from kernel import paths
from kernel.errors import SopError

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT = HERE / 'tools.toml'
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')
STEPS = ('M0', 'M2', 'M5')
SYSTEM = '系统软件包'
VERSION_REQ = re.compile(r'^>=(\d+(?:\.\d+)*)$')
COMMAND = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,40}$')
VERSION_IN_TEXT = re.compile(r'(?:\b\d+:)?(\d+(?:\.\d+)+|\d+)')   # 系统软件包的版本前面可能带「1:」，跳过
FIELDS = {'name': str, 'what': str, 'version': str, 'location': str, 'check': str,
          'install': str, 'admin': bool, 'step': str}


class CatalogError(SopError):
    pass


@dataclasses.dataclass(frozen=True)
class Tool:
    name: str
    what: str
    version: str
    location: str
    check: str
    install: str
    admin: bool
    step: str
    needs: tuple = ()
    command: str = ''          # 命令名：系统软件包靠它找实际在哪；工具包自己装的，体检按它在 PATH 里找另外几份
    elsewhere: tuple = ()      # 别的装法常放的位置（~/ 开头或绝对路径），体检看有没有另一份（4.3）
    base: pathlib.Path | None = dataclasses.field(default=None, compare=False, repr=False)   # 安装脚本的相对路径从哪里算（清单所在的目录；没给就是 machine/）

    @property
    def system_package(self):
        return self.location == SYSTEM

    def path(self):
        """规定位置的真实路径；系统软件包没有固定的目录，返回 None。"""
        if self.system_package:
            return None
        return paths.tools_dir() / self.location.removeprefix('~/tools/')

    def install_kind(self):
        """('apt', 软件包名) 或 ('script', 安装脚本的路径)。"""
        kind, _, what = self.install.partition(':')
        return (kind, what) if kind == 'apt' else (kind, (self.base or HERE) / what)


def parse_version(text):
    """从命令的输出里取第一个像版本号的数：「git version 2.53.0」→ (2, 53, 0)；「v26.13.1」→ (26, 13, 1)；「1:4.16.0-2」→ (4, 16, 0)。"""
    m = VERSION_IN_TEXT.search(text or '')
    return tuple(int(x) for x in m.group(1).split('.')) if m else None


def version_ok(requirement, found):
    """found 是 parse_version 的结果。要求是空串时只要装了就行。"""
    if not requirement:
        return True
    if found is None:
        return False
    need = tuple(int(x) for x in VERSION_REQ.match(requirement).group(1).split('.'))
    n = max(len(need), len(found))
    return found + (0,) * (n - len(found)) >= need + (0,) * (n - len(need))


def _check_entry(i, d, seen):
    where = f'machine/tools.toml 第 {i + 1} 项（{d.get("name", "没写名字")}）'
    for k, typ in FIELDS.items():
        if k not in d:
            raise CatalogError(f'{where}：少了「{k}」')
        if not isinstance(d[k], typ):
            raise CatalogError(f'{where}：「{k}」的写法不对')
    extra = set(d) - set(FIELDS) - {'needs', 'command', 'elsewhere'}
    if extra:
        raise CatalogError(f'{where}：不认识的字段 {sorted(extra)}')
    if not NAME.match(d['name']):
        raise CatalogError(f'{where}：名字只能用小写字母、数字和「-」')
    if d['name'] in seen:
        raise CatalogError(f'{where}：名字和前面的重复了')
    if d['version'] and not VERSION_REQ.match(d['version']):
        raise CatalogError(f'{where}：版本要求要写成「>=1.2」这样，或者空着')
    if d['step'] not in STEPS:
        raise CatalogError(f'{where}：step 只能是 {"、".join(STEPS)}')
    kind, _, what = d['install'].partition(':')
    if kind not in ('apt', 'script') or not what:
        raise CatalogError(f'{where}：install 要写成「apt:软件包名」或「script:安装脚本」')
    if kind == 'apt':
        if d['location'] != SYSTEM:
            raise CatalogError(f'{where}：用 apt 装的，位置要写「{SYSTEM}」')
        if not d['admin']:
            raise CatalogError(f'{where}：用 apt 装要管理员密码，admin 要写 true')
    else:
        if not d['location'].startswith('~/tools/'):
            raise CatalogError(f'{where}：工具包自己装的东西都要在 ~/tools 下（4.3）')
        if pathlib.PurePosixPath(what).is_absolute() or '..' in pathlib.PurePosixPath(what).parts:
            raise CatalogError(f'{where}：安装脚本要写 machine/ 下的相对路径')
    needs = d.get('needs', [])
    if not isinstance(needs, list) or not all(isinstance(x, str) for x in needs):
        raise CatalogError(f'{where}：needs 要写成名字的列表')
    for n in needs:
        if n not in seen:
            raise CatalogError(f'{where}：要先装的「{n}」不在它前面')
    command = d.get('command', '')
    if not isinstance(command, str) or (command and not COMMAND.match(command)):
        raise CatalogError(f'{where}：command 只写一个命令名')
    elsewhere = d.get('elsewhere', [])
    if not isinstance(elsewhere, list) or not all(isinstance(x, str) and (x.startswith('~/') or x.startswith('/'))
                                                  for x in elsewhere):
        raise CatalogError(f'{where}：elsewhere 要写成「~/」或「/」开头的路径的列表')
    if elsewhere and kind == 'apt':
        raise CatalogError(f'{where}：系统软件包只有 apt 那一份，不写 elsewhere')
    return Tool(**{k: d[k] for k in FIELDS}, needs=tuple(needs), command=command, elsewhere=tuple(elsewhere))


def load(path=None):
    """读清单，按写的先后返回 Tool 的列表。不给 path 就是工具包自带的 machine/tools.toml；
    测试用环境变量 SOP_TOOLS_TOML 换成别的清单（流程沙箱里用假的安装脚本，3-12），安装脚本按那份清单所在的目录找。"""
    path = pathlib.Path(path or os.environ.get('SOP_TOOLS_TOML') or DEFAULT)
    try:
        data = tomllib.loads(pathlib.Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CatalogError(f'工具清单读不了：{e}') from None
    items = data.get('tool')
    if not isinstance(items, list) or not items:
        raise CatalogError('工具清单里一项工具都没有')
    tools, seen = [], set()
    for i, d in enumerate(items):
        t = dataclasses.replace(_check_entry(i, d, seen), base=path.resolve().parent)
        seen.add(t.name)
        tools.append(t)
    return tools


def find(name, tools=None):
    for t in tools if tools is not None else load():
        if t.name == name:
            return t
    raise CatalogError(f'工具清单里没有「{name}」')


@dataclasses.dataclass
class CheckResult:
    installed: bool
    version: tuple | None
    ok: bool
    output: str

    @property
    def version_text(self):
        return '.'.join(map(str, self.version)) if self.version else '看不出版本'


def run_check(tool, timeout=30):
    """跑检查命令，看装没装、版本够不够。不改任何东西。
    环境里指向别处那一份的变量（旧的 NVM_DIR 等）去掉，换成规定位置的（shellenv.environ），只认规定位置那一份。"""
    from . import shellenv
    env = {**shellenv.environ(), 'LC_ALL': 'C'}
    p = subprocess.Popen(['bash', '-c', tool.check], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)   # 连它带起的子进程一起结束，不然管道一直不关
        p.communicate()
        return CheckResult(False, None, False, f'检查命令 {timeout} 秒没结束')
    out = (stdout + stderr).strip()
    if p.returncode != 0:
        return CheckResult(False, None, False, out)
    v = parse_version(stdout or stderr)
    return CheckResult(True, v, version_ok(tool.version, v), out)
