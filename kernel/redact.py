"""去掉密钥和个人信息（3-42，设计书 16.5 第 1 条「日志先去掉密钥」）。只用标准库。

问题单登记在公开的工具包仓库上，任何人都看得到，所以除了密钥，本机用户名、主目录、本机名、邮箱、Git 里设的名字、
IP 地址也一起抹掉。抹掉的地方换成「[已抹掉：<类别>]」（本机用户名、本机名换成 <用户名>、<本机名>，主目录换成 ~）。

两类规则，按 RULES 的先后做：
- 认得出样子的：私钥块、Authorization 头、网址里的账号密码、各家密钥的前缀（Anthropic、OpenAI 风格 sk-、GitHub、AWS、
  Google、Slack、JWT）、「名字像密钥=值」的赋值（环境变量、JSON、YAML、命令行开关），再加一条兜底：32 个字以上、
  大写小写数字都有的长串；
- 认不出样子、但知道值的：运行时从 ~/tools/sop/config/ai/*.env 读出的每一个值（服务地址也算，可能透露用的是哪家服务）、
  终端里名字像密钥的环境变量的值、gh 登录的凭据（`gh auth token`）。值不写进代码。

每条规则都有只靠它才抹得掉的样例（tests/unit/test_self_report.py）：拿掉任何一条，就有样例漏出来。
自动抹不保证抹得干净（认不出样子、又不知道值的密钥就抹不掉），所以登记之前还要给小白看一遍（kernel/selfreport.py）。
"""
import json
import os
import pathlib
import pwd
import re
import socket
import subprocess
import urllib.parse


def mask(label):
    return f'[已抹掉：{label}]'


MASKED = '[已抹掉：'

# 名字里有这些词的，值当密钥（名字按 _ - . 和大小写分开再比）
SECRET_WORDS = {'key', 'keys', 'apikey', 'token', 'secret', 'secrets', 'password', 'passwd', 'pass', 'passphrase', 'pwd',
                'auth', 'authorization', 'credential', 'credentials', 'cookie', 'privatekey', 'accesskey', 'secretkey'}
NOT_SECRET_NAMES = {'pwd', 'oldpwd'}          # 当前目录，不是密码


def name_is_secret(name):
    if name.lower() in NOT_SECRET_NAMES or name.endswith(('Error', 'Exception', 'Warning')):   # KeyError: 'x' 是报错的类名
        return False
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    parts = [x for x in re.split(r'[_\-.]+', s.lower()) if x]
    return any(p in SECRET_WORDS for p in parts) or name.lower().replace('_', '').replace('-', '') in SECRET_WORDS


# ---------- 认得出样子的 ----------
_PRIV_BLOCK = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----(?:(?!-----BEGIN ).)*?-----END [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----',
                         re.S)
# 没有结尾（日志在中间截断了）：BEGIN 那一行，加上后面连着的像 base64 的行、PEM 的头（Proc-Type: 之类）、空行；碰到别的行就停，
# 不把后面的日志一起吞掉
_PRIV_OPEN = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----[^\n]*(?:\r?\n(?:[A-Za-z0-9+/=]{16,}|[A-Za-z][A-Za-z\-]*:[^\n]*|[ \t]*)(?=\r?\n|\Z))*')
# 日志从中间截断时只剩后半截：连着几行像 base64 的，后面跟着 END 那一行
_PRIV_TAIL = re.compile(r'(?:^[A-Za-z0-9+/=]{16,}\r?\n)+-----END [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----', re.M)


def _private_key(text):
    n = 0
    text, k = _PRIV_BLOCK.subn(mask('私钥'), text)
    n += k
    text, k = _PRIV_OPEN.subn(mask('私钥'), text)
    n += k
    text, k = _PRIV_TAIL.subn(mask('私钥'), text)
    return text, n + k


_AUTH = re.compile(r'(?i)(\b(?:proxy-)?authorization\s*["\']?\s*[:=]\s*["\']?\s*)(?:(bearer|basic|token|digest|bot)\s+)?([^\s"\',;]+)')
_BEARER = re.compile(r'\b([Bb]earer|BEARER)\s+([A-Za-z0-9._~+/=\-]{12,})')


def _auth_header(text):
    n = 0

    def one(m):
        nonlocal n
        scheme = f'{m.group(2)} ' if m.group(2) else ''
        if m.group(3).startswith(MASKED):
            return m.group(0)
        n += 1
        return f'{m.group(1)}{scheme}{mask("凭据")}'
    text = _AUTH.sub(one, text)
    text, b = _BEARER.subn(lambda m: f'{m.group(1)} {mask("凭据")}', text)
    return text, n + b


_USERINFO = re.compile(r'\b([A-Za-z][A-Za-z0-9+.\-]*://)([^\s/@:]+):([^\s/@]*)@')


def _url_userinfo(text):
    return _USERINFO.subn(lambda m: f'{m.group(1)}{mask("账号密码")}@', text)


def _pattern(regex, label):
    rx = re.compile(regex)

    def f(text):
        return rx.subn(mask(label), text)
    return f


_ASSIGN = re.compile(
    r'(?<![A-Za-z0-9_])(["\']?)([A-Za-z_][A-Za-z0-9_.\-]*)\1(\s*[:=]\s*)'
    r'(?:"((?:[^"\\\n]|\\.)*)"|\'([^\'\n]*)\'|([^\s,;&"\'}\])]+))')
SKIP_VALUES = {'***', 'null', 'None', 'true', 'false', '""', "''", 'Bearer', 'bearer', 'Basic', 'basic', 'Token', 'token', 'Digest'}
_FLAG = re.compile(r'(--[A-Za-z0-9\-]*(?:token|password|passwd|secret|key|auth)[A-Za-z0-9\-]*)(\s+)([^\s\-][^\s]*)', re.I)


def _assignment(text):
    n = 0

    def one(m):
        nonlocal n
        name = m.group(2)
        if not name_is_secret(name):
            return m.group(0)
        val = next(v for v in (m.group(4), m.group(5), m.group(6)) if v is not None)
        if not val or val.startswith(MASKED) or val in SKIP_VALUES:
            return m.group(0)
        n += 1
        q = '"' if m.group(4) is not None else ("'" if m.group(5) is not None else '')
        return f'{m.group(1)}{name}{m.group(1)}{m.group(3)}{q}{mask("密钥")}{q}'
    text = _ASSIGN.sub(one, text)

    def flag(m):
        nonlocal n
        if m.group(3).startswith(MASKED):
            return m.group(0)
        n += 1
        return f'{m.group(1)}{m.group(2)}{mask("密钥")}'
    text = _FLAG.sub(flag, text)
    return text, n


_LONG = re.compile(r'(?<![A-Za-z0-9_+\-])[A-Za-z0-9_+\-]{32,}(?![A-Za-z0-9_+\-])')


def _long_token(text):
    n = 0

    def one(m):
        nonlocal n
        s = m.group(0)
        if re.search(r'[A-Z]', s) and re.search(r'[a-z]', s) and re.search(r'[0-9]', s):
            n += 1
            return mask('疑似密钥')
        return s
    return _LONG.sub(one, text), n


# ---------- 个人信息 ----------
_EMAIL = re.compile(r'(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+)@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})(?![A-Za-z0-9])')


def _email(text):
    n = 0

    def one(m):
        nonlocal n
        if m.group(1) == 'git':                 # git@github.com 这种是 SSH 的固定写法，不是谁的邮箱
            return m.group(0)
        n += 1
        return mask('邮箱')
    return _EMAIL.sub(one, text), n


_IPV4 = re.compile(r'(?<![0-9.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![0-9.])')


def _ip(text):
    n = 0

    def one(m):
        nonlocal n
        ip = m.group(1)
        if ip.startswith('127.') or ip == '0.0.0.0':      # 本机自己的地址，不透露什么
            return ip
        n += 1
        return mask('IP 地址')
    return _IPV4.sub(one, text), n


def _word(value):
    return re.compile(r'(?<![A-Za-z0-9_])' + re.escape(value) + r'(?![A-Za-z0-9_])')


class Redactor:
    """known：知道值的密钥（运行时读出来的）；homes：主目录（换成 ~）；users：本机用户名；hosts：本机名；
    names：Git 里设的名字等要抹掉的个人信息；projects：私有项目的名字（换成 <项目名>）；skip：拿掉哪几条规则（只给测试反着试用）。"""

    def __init__(self, known=(), homes=(), users=(), hosts=(), names=(), projects=(), skip=()):
        self.known = sorted({v for v in known if v and len(v) >= 6}, key=len, reverse=True)
        self.homes = sorted({h.rstrip('/') for h in homes if h and h.rstrip('/') not in ('', '/', '/root')}, key=len, reverse=True)
        self.users = sorted({u for u in users if u and len(u) >= 3}, key=len, reverse=True)
        self.hosts = sorted({h for h in hosts if h and len(h) >= 3 and h not in ('localhost',)}, key=len, reverse=True)
        self.names = sorted({x for x in names if x and len(x.strip()) >= 2}, key=len, reverse=True)
        self.projects = sorted({x for x in projects if x and len(x) >= 2}, key=len, reverse=True)
        self.skip = set(skip)

    # 每条规则：(键, 给人看的类别, 函数)。先后有讲究：知道值的最先（最准）；Anthropic 在 OpenAI 风格之前；
    # 赋值在各家前缀之后（前缀抹完值已经是 [已抹掉…]，不重复算）；兜底的长串最后
    def rules(self):
        return [
            ('known', '已知的密钥值（config/ai/*.env、环境变量、gh 登录）', self._known),
            ('private_key', '私钥', _private_key),
            ('auth_header', 'Authorization 头和 Bearer 凭据', _auth_header),
            ('url_userinfo', '网址里的账号密码', _url_userinfo),
            ('anthropic', 'Anthropic 密钥（sk-ant-）', _pattern(r'\bsk-ant-[A-Za-z0-9_\-]{8,}', '密钥')),
            ('openai', 'OpenAI 风格密钥（sk-）', _pattern(r'\bsk-(?!ant-)[A-Za-z0-9_\-]{16,}', '密钥')),
            ('github', 'GitHub 凭据（ghp_、gho_、github_pat_ 等）',
             _pattern(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})', '密钥')),
            ('aws', 'AWS 密钥（AKIA）', _pattern(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b', '密钥')),
            ('google', 'Google 密钥（AIza）', _pattern(r'\bAIza[0-9A-Za-z_\-]{35}', '密钥')),
            ('slack', 'Slack 凭据（xox）', _pattern(r'\bxox[abposr]-[A-Za-z0-9\-]{10,}', '密钥')),
            ('jwt', 'JWT 凭据（eyJ）', _pattern(r'\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}', '密钥')),
            ('assignment', '名字像密钥的赋值（环境变量、JSON、YAML、命令行开关）', _assignment),
            ('long_token', '疑似密钥的长串（32 个字以上、大小写数字都有）', _long_token),
            ('email', '邮箱', _email),
            ('home', '主目录（换成 ~）', self._home),
            ('host', '本机名', self._host),           # 本机名常带着用户名（alice-pc），先抹本机名
            ('user', '本机用户名', self._user),
            ('name', 'Git 里设的名字', self._name),
            ('project', '私有项目的名字', self._project),
            ('ip', 'IP 地址（127.* 除外）', _ip),
        ]

    def _known(self, text):
        n = 0
        for v in self.known:
            for form in {v, json.dumps(v)[1:-1], urllib.parse.quote(v, safe='')}:
                if form and form in text:
                    n += text.count(form)
                    text = text.replace(form, mask('密钥'))
        return text, n

    def _home(self, text):
        n = 0
        for h in self.homes:
            rx = re.compile(re.escape(h) + r'(?![A-Za-z0-9_.\-])')
            text, k = rx.subn('~', text)
            n += k
        return text, n

    def _sub_words(self, values, repl, text):
        n = 0
        for v in values:
            text, k = _word(v).subn(repl, text)
            n += k
        return text, n

    def _user(self, text):
        return self._sub_words(self.users, '<用户名>', text)

    def _host(self, text):
        return self._sub_words(self.hosts, '<本机名>', text)

    def _name(self, text):
        return self._sub_words(self.names, mask('名字'), text)

    def _project(self, text):
        return self._sub_words(self.projects, '<项目名>', text)

    def apply(self, text):
        """返回 (抹过的文字, {类别: 处数})。抹过的再抹一遍不会再变。"""
        counts = {}
        for key, label, f in self.rules():
            if key in self.skip:
                continue
            text, n = f(text)
            if n:
                counts[label] = counts.get(label, 0) + n
        return text, counts


# ---------- 运行时收集「知道值的」和本机的个人信息 ----------
def env_file_values(config_dir):
    """config/ai/*.env 里的每一个值（不管名字）。只在这里读，不打印、不写到别处。"""
    out = []
    d = pathlib.Path(config_dir) / 'ai'
    if not d.is_dir():
        return out
    rx = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')
    for f in sorted(d.glob('*.env')):
        try:
            lines = f.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            m = rx.match(line)
            if not m:
                continue
            v = m.group(2)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            if v:
                out.append(v)
    return out


def env_values(environ=None):
    """终端里名字像密钥的环境变量的值（8 个字以上）。"""
    environ = os.environ if environ is None else environ
    return [v for k, v in environ.items() if name_is_secret(k) and len(v) >= 8]


def gh_token(timeout=10):
    """gh 登录的凭据（只读：gh auth token 从它自己的登记里取，不联网）。没有 gh、没登录都返回 None。"""
    try:
        p = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, 'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1'})
    except (OSError, subprocess.SubprocessError):
        return None
    t = p.stdout.strip()
    return t if p.returncode == 0 and t and ' ' not in t else None


def git_identity():
    """~/.gitconfig 里设的名字和邮箱（只读）。"""
    out = []
    for k in ('user.name', 'user.email'):
        try:
            p = subprocess.run(['git', 'config', '--global', '--get', k], capture_output=True, text=True, timeout=10,
                               env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
            if p.returncode == 0 and p.stdout.strip():
                out.append(p.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return out


def for_this_machine(config_dir, with_gh=True, projects=()):
    """按这台电脑现在的样子建一个 Redactor。projects：私有项目的名字。"""
    homes, users = set(), set()
    try:
        pw = pwd.getpwuid(os.getuid())
        homes.add(pw.pw_dir)
        users.add(pw.pw_name)
    except KeyError:
        pass
    if os.environ.get('HOME'):
        homes.add(os.environ['HOME'])
    for k in ('USER', 'LOGNAME'):
        if os.environ.get(k):
            users.add(os.environ[k])
    hosts = {socket.gethostname()}
    known = env_file_values(config_dir) + env_values()
    if with_gh:
        t = gh_token()
        if t:
            known.append(t)
    names = git_identity()          # 名字和邮箱（邮箱的规则先抹；万一写法认不出，这里照值再抹一次）
    return Redactor(known=known, homes=homes, users=users, hosts=hosts, names=names, projects=projects)
