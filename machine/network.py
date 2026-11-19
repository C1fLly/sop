"""体检：网络连通（设计书 4.4「体检检查 GitHub、AI 服务、各软件源是否连得上」，任务 3-50）。

逐样试连，只做网络这一层，不登录、不带任何密钥、不发 AI 调用：
- 网页（http/https）：连上（经代理的先让代理转过去）、加密的做完加密握手并核对证书、发一个不带凭据的 HEAD 请求，
  对方回了任何状态码（200、401、404 都算）就是「连得上」。AI 服务只试连主机的根路径 /，不带地址里的路径和参数。
- GitHub 的 SSH：连上 22 端口、读对方先发的那一行（SSH-2.0-…）就断开，不发任何东西，不用 SSH 密钥，
  也不跑 ssh 命令（所以不写 ~/.ssh/known_hosts）。SSH 默认不走网页代理，所以先直连；直连不通而网页代理能转过去时，
  照实说「经代理能连上，但 SSH 默认不走代理」。

代理：按 config/network.json（第零步记的）。还没有这份设置时（第零步之前、开发机），按终端里的 http_proxy、
https_proxy、no_proxy 试，报告里写明。socks 代理不试（第零步只记网页代理）。代理地址里的账号密码不打印。

连不上的说清是哪一样、卡在哪一步（域名解析、连接、代理、加密握手、没回应）、可能的原因。只读：一个文件都不写。
"""
import base64
import concurrent.futures
import dataclasses
import fnmatch
import glob
import os
import re
import socket
import ssl
import time
import urllib.parse

from kernel import paths

from . import config

TIMEOUT = 8
WORKERS = 8
UA = 'sop-doctor'
APT_FILES = ('/etc/apt/sources.list', '/etc/apt/sources.list.d/*.list', '/etc/apt/sources.list.d/*.sources')

GITHUB_WEB = 'https://github.com/'
GITHUB_SSH = 'ssh://github.com:22'
NPM_DEFAULT = 'https://registry.npmjs.org/'
PYPI_DEFAULT = 'https://pypi.org/simple/'
CLAUDE_DEFAULT = 'https://api.anthropic.com/'
# 安装工具那一步（M2，machine/install/）要下载的地方。gh 和 wt 从 GitHub 取，上面已经试了
DOWNLOADS = (
    ('dl:uv', 'uv 的下载站', 'https://astral.sh/'),
    ('dl:nvm', 'nvm 的下载站', 'https://raw.githubusercontent.com/'),
    ('dl:node', 'Node 的下载站', 'https://nodejs.org/dist/'),
    ('dl:docker', 'Docker 的下载站', 'https://download.docker.com/'),
)
AI_LABELS = {'claude': 'Claude Code', 'codex': 'Codex', 'opencode': 'OpenCode', 'pi': 'Pi'}
# config/ai/<工具名>.env（M4 记的，问题 5）里只认这种名字的那一行，别的行（密钥）不留
AI_URL_LINE = re.compile(r'^\s*(?:export\s+)?[A-Z][A-Z0-9_]*BASE_URL\s*=\s*["\']?([^"\'\s]+)["\']?\s*$')

GROUPS = (
    ('github', 'GitHub', 'GitHub 连不上：取工具包、建项目、推送、开 PR 都做不了'),
    ('ai', 'AI 服务', 'AI 工具连不上它的服务：AI 的步骤都会失败。服务地址是「登录 AI 工具」那一步填的，看看地址对不对'),
    ('source', '软件源', '这个源连不上：装依赖或系统软件包会失败'),
    ('download', '安装工具要用的下载站', '这个下载站连不上：「安装工具」那一步会失败'),
)


@dataclasses.dataclass
class Target:
    key: str
    label: str
    url: str          # https://主机/路径 或 ssh://主机:端口；空的是「不知道地址，没试」
    group: str
    why_skip: str = ''


@dataclasses.dataclass
class Result:
    target: Target
    state: str        # ok 连得上；fail 连不上；skip 没试
    via: str = ''     # 直连 / 经代理 http://主机:端口
    detail: str = ''  # 连得上时：对方回的状态码或 SSH 的那一行
    reason: str = ''  # 连不上、没试的原因（大白话）
    seconds: float = 0.0


@dataclasses.dataclass
class Proxies:
    http: str = ''
    https: str = ''
    no_proxy: str = ''
    source: str = 'none'   # network：网络设置里的；env：终端里的（还没有网络设置）；none：网络设置写的不用代理


class Fail(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# ---------- 地址 ----------

def clean_url(url, keep_path=True):
    """去掉地址里的账号密码、参数（试连用不到，也不该打印）；AI 服务连路径也去掉（keep_path=False）。"""
    u = urllib.parse.urlsplit(url.strip())
    if u.scheme not in ('http', 'https', 'ssh') or not u.hostname:
        return ''
    host = f'[{u.hostname}]' if ':' in u.hostname else u.hostname
    netloc = host + (f':{u.port}' if u.port else '')
    path = (u.path or '/') if keep_path else '/'
    return urllib.parse.urlunsplit((u.scheme, netloc, path, '', ''))


def show_proxy(p):
    """给人看的代理地址：不带账号密码。"""
    u = urllib.parse.urlsplit(p)
    if not u.hostname:
        return p
    return f'{u.scheme}://{u.hostname}' + (f':{u.port}' if u.port else '')


def bypass(host, no_proxy):
    """host 在不走代理的名单里吗（像 curl：逗号隔开；* 是全部；.a.com 和 a.com 都管 a.com 和它的子域名；可以带 *）。"""
    host = host.lower().rstrip('.')
    for e in (no_proxy or '').split(','):
        e = e.strip().lower()
        if not e:
            continue
        if e == '*':
            return True
        if '*' in e:
            if fnmatch.fnmatchcase(host, e):
                return True
            continue
        e = e.lstrip('.').split(':')[0] if not e.startswith('[') else e
        if host == e or host.endswith('.' + e):
            return True
    return False


def proxies_from(net=None, environ=None):
    """代理按网络设置；还没有网络设置时按终端里的环境变量（大小写都认）。"""
    net = config.network() if net is None else net
    if net:
        return Proxies(net.get('http_proxy', ''), net.get('https_proxy', ''), net.get('no_proxy', ''),
                       'network' if (net.get('http_proxy') or net.get('https_proxy')) else 'none')
    env = os.environ if environ is None else environ
    get = lambda k: env.get(k) or env.get(k.upper()) or ''
    p = Proxies(get('http_proxy'), get('https_proxy'), get('no_proxy'), 'env')
    if not (p.http or p.https):
        p.source = 'none'
    return p


def apt_sources(files=APT_FILES):
    """apt 用的软件源：每个主机一个地址（第一次出现的那个）。只读这几个文件里的地址那一部分。"""
    out, hosts = [], set()
    for pat in files:
        for f in sorted(glob.glob(pat)):
            try:
                with open(f, encoding='utf-8', errors='replace') as fh:
                    text = fh.read()
            except OSError:
                continue
            urls = []
            for line in text.splitlines():
                line = line.split('#', 1)[0].strip()
                if f.endswith('.sources'):
                    m = re.match(r'^URIs:\s*(.+)$', line)
                    urls += m.group(1).split() if m else []
                else:
                    m = re.match(r'^deb(?:-src)?\s+(?:\[[^]]*\]\s+)?(\S+)', line)
                    urls += [m.group(1)] if m else []
            for u in urls:
                c = clean_url(u)
                h = urllib.parse.urlsplit(c).hostname if c else None
                if h and h not in hosts:
                    hosts.add(h)
                    out.append(c)
    return out


def ai_address(name, environ=None):
    """AI 工具的服务地址：先看 config/ai/<工具名>.env（M4 记的，只取 …BASE_URL 那一行），
    Claude Code 再看环境变量 ANTHROPIC_BASE_URL、都没有就是官方地址。返回 (地址, 从哪来)；不知道是 ('', '')。
    不打开各 AI 工具自己的配置文件（里面有密钥）。"""
    f = paths.config_dir() / 'ai' / f'{name}.env'
    try:
        with open(f, encoding='utf-8') as fh:
            for line in fh:
                m = AI_URL_LINE.match(line)
                if m and clean_url(m.group(1), keep_path=False):
                    return clean_url(m.group(1), keep_path=False), f'{f.name}'
    except OSError:
        pass
    if name == 'claude':
        env = os.environ if environ is None else environ
        if env.get('ANTHROPIC_BASE_URL') and clean_url(env['ANTHROPIC_BASE_URL'], keep_path=False):
            return clean_url(env['ANTHROPIC_BASE_URL'], keep_path=False), '环境变量'
        return CLAUDE_DEFAULT, '官方地址'
    return '', ''


def targets(net=None, ai_names=(), environ=None, apt_files=APT_FILES):
    """要试连的几样，按报告里的先后。ai_names 是体检找到的 AI 工具（locate.find_ai_tools 的 name）。"""
    net = config.network() if net is None else net
    out = [Target('github', 'GitHub 网页', GITHUB_WEB, 'github'),
           Target('github_ssh', 'GitHub 的 SSH（推送用）', GITHUB_SSH, 'github')]
    for name in ai_names:
        url, src = ai_address(name, environ)
        label = f'{AI_LABELS.get(name, name)} 的服务' + (f'（{src}）' if src else '')
        out.append(Target(f'ai:{name}', label, url, 'ai',
                          '' if url else '服务地址还没登记（「登录 AI 工具」那一步填），这次没试'))
    apt = [clean_url(net['apt_mirror'])] if net.get('apt_mirror') and clean_url(net['apt_mirror']) else []
    for u in apt_sources(apt_files):
        if urllib.parse.urlsplit(u).hostname not in {urllib.parse.urlsplit(a).hostname for a in apt}:
            apt.append(u)
    for u in apt:
        out.append(Target(f'apt:{urllib.parse.urlsplit(u).hostname}', '系统软件源（apt）', u, 'source'))
    out.append(Target('npm', 'Node 依赖包的源（npm）', clean_url(net.get('npm_registry') or '') or NPM_DEFAULT, 'source'))
    out.append(Target('pypi', 'Python 依赖包的源（PyPI）', clean_url(net.get('pypi_index') or '') or PYPI_DEFAULT, 'source'))
    out += [Target(k, label, url, 'download') for k, label, url in DOWNLOADS]
    return out


# ---------- 试连 ----------

def _connect(host, port, timeout, proxy=False):
    what = '代理 ' if proxy else ''
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except socket.gaierror:
        raise Fail(f'{what}域名 {host} 解析不了：电脑可能没联网，或者地址写错了') from None
    except ConnectionRefusedError:
        raise Fail(f'{what}{host}:{port} 拒绝连接：' + ('代理软件可能没开，或者地址、端口不对' if proxy else '地址或端口可能不对')) from None
    except (socket.timeout, TimeoutError):
        raise Fail(f'{what}{host}:{port} {timeout:g} 秒没连上：' + ('代理可能没开' if proxy
                                                                  else '可能要走代理才连得上，或者被网络挡住了')) from None
    except OSError as e:
        raise Fail(f'连不到{what}{host}:{port}（{e.strerror or e}）') from None


def _read_head(s, timeout, limit=65536, step=4096):
    """读到空行（HTTP 的头结束）或者对方断开为止。代理的回复要一个字节一个字节读（step=1）：
    后面紧跟着的是目标服务的数据（SSH 那一行可能和代理的回复挤在同一个包里），不能多读走。"""
    s.settimeout(timeout)
    buf = b''
    while b'\r\n\r\n' not in buf and len(buf) < limit:
        chunk = s.recv(step)
        if not chunk:
            break
        buf += chunk
    return buf


def _status(head):
    m = re.match(rb'^HTTP/\d(?:\.\d)?\s+(\d{3})', head)
    return int(m.group(1)) if m else None


def _proxy_auth(proxy):
    u = urllib.parse.urlsplit(proxy)
    if u.username is None:
        return ''
    raw = f'{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or "")}'
    return f'Proxy-Authorization: Basic {base64.b64encode(raw.encode()).decode()}\r\n'


def _via_proxy(proxy, host, port, timeout):
    """连上网页代理，让它（CONNECT）转到 host:port；返回连好的通道。"""
    u = urllib.parse.urlsplit(proxy)
    s = _connect(u.hostname, u.port or 80, timeout, proxy=True)
    try:
        target = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
        s.sendall(f'CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nUser-Agent: {UA}\r\n{_proxy_auth(proxy)}\r\n'.encode())
        head = _read_head(s, timeout, limit=8192, step=1)
    except (socket.timeout, TimeoutError):
        s.close()
        raise Fail(f'代理 {show_proxy(proxy)} {timeout:g} 秒没回应') from None
    except OSError as e:
        s.close()
        raise Fail(f'代理 {show_proxy(proxy)} 断开了（{e.strerror or e}）') from None
    code = _status(head)
    if code != 200:
        s.close()
        if code == 407:
            raise Fail(f'代理 {show_proxy(proxy)} 要账号密码，网络设置里没写或写错了')
        if code is None:
            raise Fail(f'代理 {show_proxy(proxy)} 回的不是网页代理该回的：地址可能不是网页代理')
        raise Fail(f'代理 {show_proxy(proxy)} 不肯转到 {host}:{port}（回了 {code}）')
    return s


def _open(host, port, proxy, timeout):
    return _via_proxy(proxy, host, port, timeout) if proxy else _connect(host, port, timeout)


def probe_http(url, proxy='', timeout=TIMEOUT, cafile=None):
    """试连一个网页地址，返回对方回的状态码；连不上抛 Fail。不带任何凭据。"""
    u = urllib.parse.urlsplit(url)
    host, port = u.hostname, u.port or (443 if u.scheme == 'https' else 80)
    path = u.path or '/'
    if u.scheme == 'http' and proxy:           # 不加密的网页：直接把整个地址交给代理
        pu = urllib.parse.urlsplit(proxy)
        s = _connect(pu.hostname, pu.port or 80, timeout, proxy=True)
        line, extra = f'HEAD {clean_url(url)} HTTP/1.1', _proxy_auth(proxy)
    else:
        s = _open(host, port, proxy, timeout)
        line, extra = f'HEAD {path} HTTP/1.1', ''
    try:
        if u.scheme == 'https':
            ctx = ssl.create_default_context(cafile=cafile)
            try:
                s.settimeout(timeout)
                s = ctx.wrap_socket(s, server_hostname=host)
            except ssl.SSLCertVerificationError as e:
                raise Fail(f'{host} 的证书核对不过（{e.verify_message}）：可能被网络拦截了，或者地址不对') from None
            except ssl.SSLError as e:
                raise Fail(f'和 {host} 的加密握手失败（{e.reason or e}）：可能被网络拦截了，或者代理有问题') from None
            except (socket.timeout, TimeoutError):
                raise Fail(f'和 {host} 的加密握手 {timeout:g} 秒没做完') from None
        hostport = host if not u.port else f'{host}:{u.port}'
        s.sendall(f'{line}\r\nHost: {hostport}\r\nUser-Agent: {UA}\r\nAccept: */*\r\nConnection: close\r\n{extra}\r\n'.encode())
        head = _read_head(s, timeout)
    except (socket.timeout, TimeoutError):
        raise Fail(f'连上了，但 {host} {timeout:g} 秒没回应') from None
    except ConnectionResetError:
        raise Fail(f'连上了，但 {host} 马上断开了：可能被网络挡住了') from None
    except OSError as e:
        raise Fail(f'和 {host} 的连接出错了（{e.strerror or e}）') from None
    finally:
        s.close()
    if not head:
        raise Fail(f'连上了，但 {host} 什么都没回就断开了')
    code = _status(head)
    if code is None:
        raise Fail(f'连上了，但 {host} 回的不是网页')
    return code


def probe_ssh(host, port=22, proxy='', timeout=TIMEOUT):
    """连上 SSH 服务、读它先发的那一行就断开。不发任何东西、不用密钥。返回那一行；不是 SSH 服务抛 Fail。"""
    s = _open(host, port, proxy, timeout)
    try:
        s.settimeout(timeout)
        buf = b''
        while b'\n' not in buf and len(buf) < 256:
            chunk = s.recv(256)
            if not chunk:
                break
            buf += chunk
    except (socket.timeout, TimeoutError):
        raise Fail(f'连上了，但 {host}:{port} {timeout:g} 秒没回应') from None
    except OSError as e:
        raise Fail(f'和 {host}:{port} 的连接出错了（{e.strerror or e}）') from None
    finally:
        s.close()
    line = buf.split(b'\n')[0].strip().decode('ascii', 'replace')
    if not line.startswith('SSH-'):
        raise Fail(f'连上了，但 {host}:{port} 不是 SSH 服务' + ('（什么都没回）' if not line else ''))
    return line


def _proxy_for(url, proxies):
    u = urllib.parse.urlsplit(url)
    if bypass(u.hostname, proxies.no_proxy):
        return ''
    return proxies.https if u.scheme == 'https' else proxies.http if u.scheme == 'http' else ''


def probe(target, proxies, timeout=TIMEOUT, cafile=None):
    """试连一样，返回 Result。"""
    t0 = time.monotonic()
    done = lambda **kw: Result(target, seconds=round(time.monotonic() - t0, 2), **kw)
    if not target.url:
        return done(state='skip', reason=target.why_skip or '不知道地址，没试')
    u = urllib.parse.urlsplit(target.url)
    if u.scheme == 'ssh':
        try:
            return done(state='ok', via='直连', detail=probe_ssh(u.hostname, u.port or 22, '', timeout))
        except Fail as e:
            direct = e.reason
        web = proxies.https or proxies.http
        if web and not web.startswith('socks') and not bypass(u.hostname, proxies.no_proxy):
            try:
                probe_ssh(u.hostname, u.port or 22, web, timeout)
                return done(state='fail', via='直连', reason=f'{direct}。经代理 {show_proxy(web)} 能连上，但 SSH 默认不走代理：'
                            f'推送会失败，要在 SSH 的设置里给 {u.hostname} 配上代理（已经配了的可以不管）')
            except Fail:
                pass
        return done(state='fail', via='直连', reason=direct)
    proxy = _proxy_for(target.url, proxies)
    if proxy.startswith('socks'):
        return done(state='skip', via=f'代理 {show_proxy(proxy)}', reason='代理是 socks 的，体检只会经网页代理试连，这一样没试')
    via = f'经代理 {show_proxy(proxy)}' if proxy else '直连'
    try:
        code = probe_http(target.url, proxy, timeout, cafile)
    except Fail as e:
        return done(state='fail', via=via, reason=e.reason)
    return done(state='ok', via=via, detail=f'对方回了 {code}')


def check(target_list, proxies, timeout=TIMEOUT, cafile=None, workers=WORKERS):
    """几样一起试（最多 workers 个同时），按给的先后返回。"""
    if not target_list:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(target_list))) as pool:
        return list(pool.map(lambda t: probe(t, proxies, timeout, cafile), target_list))


def collect(ai_names=(), net=None, environ=None, timeout=TIMEOUT):
    """体检用：读网络设置、列出要试连的、试一遍。返回 {'proxies', 'configured'（有没有网络设置）, 'results'}。"""
    net = config.network() if net is None else net
    p = proxies_from(net, environ)
    return {'proxies': p, 'configured': bool(net), 'results': check(targets(net, ai_names, environ), p, timeout)}


# ---------- 报告 ----------

def failed(d):
    return [r for r in (d or {}).get('results', []) if r.state == 'fail']


def describe(d):
    """报告里「网络连通」那一项的文字。"""
    p = d['proxies']
    if p.source == 'none':
        head = '不用代理（网络设置里没写代理）' if d.get('configured') else '不用代理（还没有网络设置，终端里也没有代理）'
    else:
        shown = '、'.join(dict.fromkeys(show_proxy(x) for x in (p.https, p.http) if x))
        src = '网络设置里的' if p.source == 'network' else '还没有网络设置，按终端里的'
        head = f'代理：{shown}（{src}）'
        if p.no_proxy:
            head += '；有一串不走代理的地址'
    lines = [head]
    bad = failed(d)
    ok = sum(r.state == 'ok' for r in d['results'])
    lines.append(f'试连了 {ok + len(bad)} 样，连得上 {ok} 样' + (f'，连不上 {len(bad)} 样' if bad else '') + '。只连不登录，没带任何密钥。')
    for g, name, why in GROUPS:
        rs = [r for r in d['results'] if r.target.group == g]
        if not rs:
            continue
        lines.append(f'{name}：')
        for r in rs:
            where = r.target.url.removeprefix('ssh://') if r.target.url else ''
            where = f'（{where}）' if where else ''
            if r.state == 'ok':
                lines.append(f'  {r.target.label}{where}：连得上，{r.via}，{r.detail}。')
            elif r.state == 'skip':
                lines.append(f'  {r.target.label}{where}：没试。{r.reason}。')
            else:
                lines.append(f'  {r.target.label}{where}：连不上（{r.via}）。{r.reason}。')
                lines.append(f'      {why}。')
    if bad:
        lines.append(f'网络设置在 {paths.config_dir() / "network.json"}；代理不对的话，照第零步的说明重新填一次。')
    return '\n'.join(lines)
