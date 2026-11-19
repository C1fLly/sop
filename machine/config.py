"""机器级配置和登记（设计书 3.2、4.3、4.4、4.5），都在 ~/tools/sop/config/ 下，JSON（3.3）。

三份：
- network.json  网络设置：代理、软件源。第零步写，之后可改；安装脚本按它配置各工具（4.4）。
- tools.json    工具实际位置登记：每样工具在哪、什么版本、是不是规定位置那一份、另有几份在哪（4.3「合格」）；
                AI 工具保持默认位置，也登记在这里（种类写 ai），连同最近一次做过真实 AI 演练的版本（10.1）。
- system.json   系统组件版本登记：内核、bubblewrap、免管理员 Docker 那条系统规则、系统对普通用户建隔离空间的限制、
                往终端塞按键的开关（4.5）。怎么查见 components.py（3-05）。sop 每次启动拿现在的和它比，变了先重跑隔离自检（3-07）。

规矩：目录只有用户自己能进（0700）、文件只有用户自己能读（0600，代理设置里可能带账号密码）；
读改写时先上锁（几个 sop 可能同时写）；先写临时文件再换名，写到一半断了也不会留下坏文件。
"""
import contextlib
import json
import os
import re
import time

from kernel import paths
from kernel.errors import SopError
from kernel.locks import FileLock

NAMES = ('network', 'tools', 'system')
NETWORK_KEYS = {
    'http_proxy': '网页代理（http://主机:端口）',
    'https_proxy': '加密网页代理（多半和上一个一样）',
    'no_proxy': '不走代理的地址，逗号隔开',
    'apt_mirror': 'Ubuntu 软件源的地址',
    'npm_registry': 'Node 依赖包的源',
    'pypi_index': 'Python 依赖包的源',
    'source': '这些设置从哪来：探测到的（detected）或小白填的（user）',
    'checked_at': '最近一次确认的时间',
}
PROXY = re.compile(r'^(https?|socks5h?)://[^\s/]+(:\d{1,5})?/?$')
URL = re.compile(r'^https?://\S+$')
TOOL_KINDS = ('base', 'ai')


class ConfigError(SopError):
    pass


def _path(name):
    if name not in NAMES:
        raise ValueError(f'没有这份登记：{name}')
    return paths.config_dir() / f'{name}.json'


def _ensure_dir():
    d = paths.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def load(name):
    """读一份登记；还没有就是空的。文件坏了（被手改坏、磁盘出错）明说是哪个文件，不当成空的接着用。"""
    f = _path(name)
    try:
        text = f.read_text()
    except FileNotFoundError:
        return {}
    try:
        d = json.loads(text)
    except ValueError:
        raise ConfigError(f'机器级登记 {f} 坏了，读不出来。可以先把它改个名留着，再执行一次 sop machine doctor 重新生成') from None
    if not isinstance(d, dict):
        raise ConfigError(f'机器级登记 {f} 的内容不对（应该是一个 JSON 对象）')
    return d


def _write(name, data):
    _ensure_dir()
    f = _path(name)
    tmp = f.with_name(f'.{f.name}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


@contextlib.contextmanager
def editing(name):
    """上锁、读出来给调用方改、改完写回去：with editing('tools') as d: d[...] = ..."""
    _ensure_dir()
    with FileLock(paths.config_dir() / f'{name}.lock'):
        d = load(name)
        yield d
        _write(name, d)


def save(name, data):
    if not isinstance(data, dict):
        raise ValueError('登记的内容要是一个字典')
    _ensure_dir()
    with FileLock(paths.config_dir() / f'{name}.lock'):
        _write(name, data)


# ---------- 网络设置 ----------

def network():
    return load('network')


def set_network(**values):
    """改网络设置里的几项；给 None 就是删掉那一项。不认识的项、写法不对的地址直接报错。"""
    for k, v in values.items():
        if k not in NETWORK_KEYS or k == 'checked_at':
            raise ConfigError(f'网络设置里没有「{k}」这一项')
        if v is None:
            continue
        if not isinstance(v, str):
            raise ConfigError(f'网络设置「{k}」要是文字')
        if k in ('http_proxy', 'https_proxy') and not PROXY.match(v):
            raise ConfigError(f'代理地址的写法不对：{v}（要像 http://127.0.0.1:7890）')
        if k in ('apt_mirror', 'npm_registry', 'pypi_index') and not URL.match(v):
            raise ConfigError(f'「{k}」要是一个网址：{v}')
        if k == 'source' and v not in ('detected', 'user'):
            raise ConfigError('source 只能是 detected 或 user')
    with editing('network') as d:
        for k, v in values.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        d['checked_at'] = now()
    return d


def proxy_env(net=None):
    """按网络设置给安装脚本、体检用的环境变量（大小写两套，各工具认的不一样）。"""
    net = network() if net is None else net
    env = {}
    for k in ('http_proxy', 'https_proxy', 'no_proxy'):
        if net.get(k):
            env[k] = env[k.upper()] = net[k]
    return env


# ---------- 工具实际位置 ----------

def tools():
    return load('tools').get('tools', {})


def record_tool(name, *, path, version, kind='base', in_place=True, others=None, **extra):
    """登记一样工具：在哪（path）、什么版本、是不是规定位置那一份（in_place），
    另有几份不在规定位置的（others：[{path, size_bytes, on_system_disk}]）。extra 放适配器要记的别的项。"""
    if kind not in TOOL_KINDS:
        raise ValueError(f'工具的种类只能是 {TOOL_KINDS}')
    entry = {'path': str(path), 'version': version, 'kind': kind, 'in_place': bool(in_place),
             'others': list(others or []), 'checked_at': now(), **extra}
    with editing('tools') as d:
        d.setdefault('tools', {})[name] = entry
    return entry


def forget_tool(name):
    with editing('tools') as d:
        d.setdefault('tools', {}).pop(name, None)


# ---------- 系统组件版本 ----------

SYSTEM_PARTS = {
    'kernel': '系统内核',
    'bubblewrap': '受限环境用的 bubblewrap',
    'userns_rule': '免管理员 Docker 要的那条系统规则',
    'userns_policy': '系统对普通用户建隔离空间的限制（总开关和 bubblewrap 那条规则）',
    'tiocsti': '往终端塞按键的开关（要是关着的）',
}


def system():
    return load('system')


def record_system(components):
    """把这一次看到的系统组件版本记下来（整份换掉）。只认 SYSTEM_PARTS 里那几样。"""
    unknown = set(components) - set(SYSTEM_PARTS)
    if unknown:
        raise ValueError(f'不认识的系统组件：{sorted(unknown)}')
    d = {'components': {k: str(v) for k, v in components.items()}, 'recorded_at': now()}
    save('system', d)
    return d


def system_changes(current):
    """和登记比，返回变了的几样：[(名字, 登记里的, 现在的)]。还没登记过的那几样也算「变了」（要先跑一次自检）。"""
    old = system().get('components', {})
    cur = {k: str(v) for k, v in current.items()}
    return [(k, old.get(k), cur.get(k)) for k in SYSTEM_PARTS if old.get(k) != cur.get(k)]
