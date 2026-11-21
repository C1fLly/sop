"""M4 登录 AI 工具（设计书 4.5、10.1；3-10）：出口检查「启用的每个适配器自检通过」。

- 第一版以「自己配的服务」为准：服务商给的服务地址和密钥。存在 ~/tools/sop/config/ai/<工具名>.env（问题 5：
  目录只有用户自己能进、文件只有用户自己能读），sop 启动受限环境时作为环境变量给进去，受限环境里看不到这个文件（适配器做，3-27）。
  地址那一项的名字以 BASE_URL 结尾（3-50：体检按它试连）。
- 引导：已经合格的不重做（先跑出口检查）。终端里已经设了这个工具的地址和密钥（这台开发机就是这样），问一句就照搬；
  没有就让用户填地址、填密钥（密钥输入时不显示）。用官方账号登录的，如实说「没有验证过」（W37），这一步不登记。
- 出口检查：登记文件在、只有自己能读、有地址和密钥，再调适配器的自检 probe（3-27）：真发一次最短的调用，
  不看工具自己的「是否已登录」（4.5）。服务报余额不足、额度用完一类的错：暂停、提示充值、不重试。
  每跑一次出口检查就真花一次钱（很少，几美分），花了多少照实说。
- 第 1 期只有 Claude Code 的适配器，所以「启用的」只有它；Codex、OpenCode、Pi 的适配器在第 5 期，那时把它们加进 TOOLS。

密钥不打印、不写进别的文件；报错里出现了也换成 ***（适配器的输出已经换过）。
也能直接跑：python3 -m machine.aisetup（引导，再出口检查）；python3 -m machine.aisetup --check（只检查）
"""
import dataclasses
import getpass
import os
import re
import sys
import urllib.parse

from kernel import paths
from . import config
from kernel.errors import SopError

URL = re.compile(r'^https?://[^\s/?#]+(/[^\s]*)?$')
NAME = re.compile(r'^[A-Z][A-Z0-9_]*$')
W37 = ('用官方账号登录的做法还没有验证过（设计书 W37：登录信息会过期、要刷新，放进受限环境以后会不会出问题不知道）。'
       '第一版只支持「自己配的服务」：服务商给你的一个地址和一个密钥。真要用官方账号，先在虚拟机里验一次再用。'
       '这一步这次没有登记任何东西')


def _claude():
    from adapters.ai.claude.adapter import ClaudeAdapter
    return ClaudeAdapter()


# 启用的 AI 工具：名字 → 怎么登记、用哪个适配器自检
TOOLS = {
    'claude': {
        'label': 'Claude Code',
        'url_var': 'ANTHROPIC_BASE_URL',
        'key_vars': ('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY'),   # 第一个是默认；服务商说明里写的是第二个时选它
        'env_prefix': 'ANTHROPIC_',          # 照搬终端里的设置时带哪些（和适配器没有登记文件时的退路一样，3-27）
        'adapter': _claude,
    },
}
LATER = 'Codex、OpenCode、Pi 的适配器在第 5 期，这一步现在不登记它们'


@dataclasses.dataclass
class ToolCheck:
    name: str
    label: str
    ok: bool
    message: str
    cost: float = 0.0
    quota: bool = False
    remind: str = ''


@dataclasses.dataclass
class Result:
    ok: bool
    tools: list

    @property
    def cost(self):
        return sum(t.cost for t in self.tools)

    @property
    def quota(self):
        return any(t.quota for t in self.tools)


def env_file(name):
    return paths.config_dir() / 'ai' / f'{name}.env'


def read_env(name):
    """登记文件里的「名字=值」（可带 export、引号、# 注释）。不存在是 None。"""
    from adapters.ai.claude.adapter import ENV_LINE
    f = env_file(name)
    if not f.exists():
        return None
    out = {}
    for line in f.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = ENV_LINE.match(line)
        if m:
            k, v = m.group(1), m.group(2)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            out[k] = v
    return out


def write_env(name, values):
    """写 config/ai/<名字>.env：目录 0700、文件 0600，先写临时文件再换名。值用单引号括起来，所以不能带换行、单引号。"""
    for k, v in values.items():
        if not NAME.match(k):
            raise SopError(f'名字 {k!r} 不对')
        if not v or re.search(r"[\r\n']", v):
            raise SopError(f'{k} 的值是空的，或者带了换行、单引号')
    d = env_file(name).parent
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d.parent, 0o700)
    os.chmod(d, 0o700)
    f = env_file(name)
    tmp = f.with_name(f'.{f.name}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(f'# {TOOLS[name]["label"]} 的服务地址和密钥（sop machine setup 的「登录 AI 工具」一步写的；只有你自己能读）\n')
        fh.write(''.join(f"{k}='{v}'\n" for k, v in values.items()))
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)
    return f


def show_url(url):
    """给人看的地址：去掉里面的账号密码、参数。"""
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ''
    if u.port:
        host += f':{u.port}'
    return urllib.parse.urlunsplit((u.scheme, host, u.path, '', ''))


def precheck_tool(name):
    """出口检查里不花钱的那一半：登记文件在、只有自己能读、有地址、有密钥。都对返回 None，不对返回不通过的 ToolCheck。"""
    spec = TOOLS[name]
    label = spec['label']
    f = env_file(name)
    short = str(f).replace(os.path.expanduser('~'), '~', 1)
    vals = read_env(name)
    if vals is None:
        return ToolCheck(name, label, False, f'还没登记 {label} 的服务地址和密钥（{short} 不存在）')
    if os.stat(f).st_mode & 0o077:
        return ToolCheck(name, label, False, f'{short} 别人也能读（里面有密钥），先执行 chmod 600 {short}')
    if not any(k.endswith('BASE_URL') and v for k, v in vals.items()):
        return ToolCheck(name, label, False, f'{short} 里没有服务地址（{spec["url_var"]}）')
    if not any(vals.get(k) for k in spec['key_vars']):
        return ToolCheck(name, label, False, f'{short} 里没有密钥（{" 或 ".join(spec["key_vars"])}）')
    return None


def fingerprint(name, adapter=None):
    """自检通过时这个工具是什么样子（不花钱就查得到的）：程序实际在哪、版本、登记文件（编号、大小、修改时间；不读密钥）。
    sop machine setup 拿它判断「上次自检通过以后变没变」，没变就不再真调（3-12）。查不到（没装、没登记）是 None。"""
    a = adapter or TOOLS[name]['adapter']()
    try:
        st = os.stat(env_file(name))
    except FileNotFoundError:
        return None
    _, real = a.location()
    ver = a.version() if real else ''
    if not real or not ver:
        return None
    return {'path': real, 'version': ver, 'env': [st.st_ino, st.st_size, st.st_mtime_ns]}


def still_good(name, recorded, adapter=None):
    """上次 sop machine setup 里自检通过时记下的 recorded 和现在比：不花钱的那一半都对、样子一点没变、
    机器级登记里最近一次自检也是通过的，返回 True（这次不用再真调）。"""
    if not recorded or precheck_tool(name) is not None:
        return False
    now = fingerprint(name, adapter)
    reg = config.tools().get(name) or {}
    return now == recorded and bool(reg.get('probe_ok')) and reg.get('probed_version') == now['version']


def check_tool(name, adapter=None):
    """一个工具的出口检查：登记文件对，再自检（真发一次最短的调用）。"""
    spec = TOOLS[name]
    label = spec['label']
    bad = precheck_tool(name)
    if bad is not None:
        return bad
    a = adapter or spec['adapter']()
    try:
        r = a.probe()
    except SopError as e:
        return ToolCheck(name, label, False, str(e))
    return ToolCheck(name, label, r.ok, r.message, cost=r.cost, quota=r.quota, remind=r.remind)


def check(adapters=None):
    """M4 的出口检查：启用的每个适配器自检通过。adapters：{名字: 适配器}（测试用；不给就用各工具的默认）。"""
    out = [check_tool(n, (adapters or {}).get(n)) for n in TOOLS]
    return Result(all(t.ok for t in out), out)


def _yes(answer, default=True):
    a = (answer or '').strip().lower()
    return default if not a else a in ('y', 'yes', '是', '好', '对', '1')


def setup_tool(name, *, ask=input, secret=getpass.getpass, say=print, environ=None, adapter=None):
    """一个工具的引导，做完再跑它的出口检查。返回 ToolCheck。"""
    spec = TOOLS[name]
    label = spec['label']
    environ = os.environ if environ is None else environ
    if env_file(name).exists():
        r = check_tool(name, adapter)
        if r.ok or r.quota:
            if r.ok:
                say(f'{label} 已经登记好了，自检通过：这一步跳过（自检花了 {r.cost:.4f} 美元）')
            return r
        say(f'{label} 已经登记过，但自检没过：{r.message}')
        if not _yes(ask('重新填一次服务地址和密钥吗？[Y/n] ')):
            return r
    say(f'现在登记 {label} 用的 AI 服务。')
    kind = ask('你用的是哪种？\n  1 自己配的服务（服务商给了你一个地址和一个密钥）\n  2 官方账号登录\n请输入 1 或 2（直接回车算 1）：').strip()
    if kind == '2':
        say(W37)
        return ToolCheck(name, label, False, W37)
    url_var = spec['url_var']
    have_key = next((k for k in spec['key_vars'] if environ.get(k)), None)
    values = None
    if environ.get(url_var) and have_key:
        if _yes(ask(f'终端里已经设了 {label} 的服务地址（{show_url(environ[url_var])}）和密钥（不显示），就用这一份吗？[Y/n] ')):
            values = {k: v for k, v in environ.items() if k.startswith(spec['env_prefix']) and v}
    if values is None:
        url = ask('服务地址（服务商给的，像 https://api.example.com）：').strip()
        if not URL.match(url):
            msg = f'服务地址要以 http:// 或 https:// 开头、中间没有空格：{url[:80]!r}。这次没有登记，可以再跑一次这一步'
            say(msg)
            return ToolCheck(name, label, False, msg)
        key = secret('密钥（输入时屏幕上不显示，粘贴后按回车）：').strip()
        if not key or re.search(r"[\s']", key):
            msg = '密钥是空的，或者带了空格、单引号（多半是复制时多带了东西）。这次没有登记，可以再跑一次这一步'
            say(msg)
            return ToolCheck(name, label, False, msg)
        var = spec['key_vars'][0]
        if len(spec['key_vars']) > 1:
            alt = spec['key_vars'][1]
            if ask(f'服务商的说明里，密钥要填在 {alt} 里的输入 2，别的情况直接回车（填在 {var} 里）：').strip() == '2':
                var = alt
        values = {url_var: url, var: key}
    try:
        f = write_env(name, values)
    except SopError as e:
        say(f'{e}。这次没有登记，可以再跑一次这一步')
        return ToolCheck(name, label, False, str(e))
    say(f'登记好了：{str(f).replace(os.path.expanduser("~"), "~", 1)}（只有你自己能读）。现在自检：真的发一次最短的调用……')
    return check_tool(name, adapter)


def setup(*, ask=input, secret=getpass.getpass, say=print, environ=None, adapters=None):
    paths.guard_home('登录 AI 工具（M4：会真调一次 AI）')
    out = [setup_tool(n, ask=ask, secret=secret, say=say, environ=environ, adapter=(adapters or {}).get(n)) for n in TOOLS]
    return Result(all(t.ok for t in out), out)


def report(res):
    lines = [f'AI 工具登录的出口检查：{"通过" if res.ok else "不通过"}']
    for t in res.tools:
        lines.append(f'  {t.label}：{"通过" if t.ok else "不通过"}。{t.message}')
        if t.remind:
            lines.append(f'    提醒（不影响通过）：{t.remind}')
    lines.append(f'  这次自检一共花了 {res.cost:.4f} 美元（工具报告的金额）')
    if res.quota:
        lines.append('  AI 服务说余额不足或额度用完：先暂停，充值以后再跑一次这一步（这次没有重试）')
    lines.append(f'  {LATER}')
    return lines


def main(argv):
    if argv not in ([], ['--check']):
        print('用法：python3 -m machine.aisetup [--check]')
        return 2
    res = check() if argv else setup()
    print('\n'.join(report(res)))
    return 0 if res.ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
