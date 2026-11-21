"""M3 登录 GitHub（设计书 4.5、6.5；3-10）：GitHub 的登录状态和 SSH 密钥，出口检查「gh auth status 通过，SSH 连通」。

引导（人做，脚本领着）：
- 已经合格的不重做：先跑一遍出口检查，过了就跳过。
- 登录：gh 的网页登录（浏览器里输一次性代码），`gh auth login --hostname github.com --git-protocol ssh --web
  --skip-ssh-key --scopes admin:public_key`。只申请用得到的权限（4.5、6.5）：gh 网页登录总要的三项 repo、read:org、gist
  去不掉，另外只加传 SSH 公钥要的 admin:public_key；不申请 workflow（推送走 SSH，S4、W21 查明用不着）、delete_repo。
  SSH 密钥不让 gh 去问（它的问答是英文的），由下面工具包自己做。
- Git 的提交身份（3-22 发现、主控窗口按 3-22 的推荐替用户定的，用户可否决）：user.name、user.email 没设时按 GitHub 账号设上，
  名字用 GitHub 上的名字（没填就用账号名），邮箱用 GitHub 给的不公开邮箱 <编号>+<账号>@users.noreply.github.com，
  写进 ~/.gitconfig（4.3 列的例外）；已经设了的不动。
- SSH：
  - GitHub 的主机钥匙从登录后的 `gh api meta` 取（走加密网页、带着登录，取到的就是 GitHub 自己说的），补进 ~/.ssh/known_hosts，
    已有的行不动、只往后加；所以 SSH 从来不用「第一次见到就信」，也不会停下来问。
  - 密钥：~/.ssh/id_ed25519 没有才生成（ed25519，不设口令：工具包的脚本推送时不能停下来问口令；受限环境本来就看不到 ~/.ssh，6.2），
    已有的一把都不动、不覆盖；把 id_ed25519.pub 用 `gh ssh-key add` 传到账号上（标题「sop <电脑名>」）。
    登录时没有 admin:public_key 权限（以前就登录过的）时，用 `gh auth refresh --scopes admin:public_key` 补一次再传。
出口检查（不改任何东西）：
- `gh auth status --hostname github.com` 通过；权限里有 workflow、delete_repo 这类用不着的，照实提醒（不算不通过，以前登录的不替他改）；
- `ssh -T git@github.com` 连通（BatchMode，不问；StrictHostKeyChecking=yes，不自己记主机钥匙），而且连上的就是 gh 登录的那个账号；
- Git 的提交身份设了（M5 的 wt doctor 没有它算失败，提交也会失败）。

整个机器流程由 sop machine setup（3-12）串起来；这里只管这一步。
也能直接跑：python3 -m machine.ghsetup（引导，再出口检查）；python3 -m machine.ghsetup --check（只检查）
"""
import dataclasses
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys

from kernel import paths

from . import config, shellenv

HOST = 'github.com'
EXTRA_SCOPES = ('admin:public_key',)            # 只多要这一项：把 SSH 公钥传到账号上
NOT_NEEDED = ('workflow', 'delete_repo', 'admin:org', 'admin:repo_hook', 'admin:enterprise', 'delete:packages')
KEY_NAME = 'id_ed25519'
SSH_OPTS = ('-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes')
TIMEOUT = 60


@dataclasses.dataclass
class Result:
    ok: bool
    failures: list            # 不通过的原因（大白话）
    warnings: list            # 提醒（不影响通过）
    account: str = ''         # gh 登录的账号
    ssh_account: str = ''     # SSH 连上的账号
    scopes: list = dataclasses.field(default_factory=list)
    ssh_problem: str = ''     # SSH 不通时是哪一种：hostkey、publickey、network、other


# ---------- 跑命令 ----------
def environ(base=None):
    """跑 gh、ssh、git 的环境：规定位置的工具（~/tools/gh/bin 的 gh）在 PATH 最前面，网络设置里的代理，
    去掉外面带进来的 GIT_ 变量和指向某个仓库、某台主机的 GH_REPO、GH_HOST。"""
    env = {k: v for k, v in shellenv.environ(base=base).items() if not k.startswith('GIT_') and k not in ('GH_REPO', 'GH_HOST')}
    env.update(config.proxy_env())
    env.update({'GH_NO_UPDATE_NOTIFIER': '1', 'GH_TELEMETRY': '0', 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C.UTF-8'})
    return env


def _run(argv, env, *, timeout=TIMEOUT, input=None):
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, input=input,
                           stdin=subprocess.DEVNULL if input is None else None)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'{timeout} 秒没结束'
    except FileNotFoundError:
        return -2, '', f'找不到 {argv[0]}'


def gh_path(env):
    return shutil.which('gh', path=env['PATH'])


def gh(env, *args, timeout=TIMEOUT):
    return _run([gh_path(env) or 'gh', *args], {**env, 'GH_PROMPT_DISABLED': '1'}, timeout=timeout)


def ssh_dir():
    return pathlib.Path.home() / '.ssh'


# ---------- 各项 ----------
def gh_status(env):
    """(登录了没有, 账号, 权限, 原文)。"""
    rc, out, err = gh(env, 'auth', 'status', '--hostname', HOST)
    text = (out + err).strip()
    m = re.search(r'Logged in to \S+ account (\S+)', text) or re.search(r'Logged in to \S+ as (\S+)', text)
    scopes = []
    s = re.search(r'Token scopes:\s*(.*)', text)
    if s:
        scopes = [x.strip(" '\"") for x in s.group(1).split(',') if x.strip(" '\"")]
    return rc == 0, (m.group(1) if m else ''), scopes, text


def account(env):
    """gh 登录的账号：(账号名, 编号, 名字)。取不到是 None。"""
    rc, out, err = gh(env, 'api', 'user')
    if rc:
        return None
    try:
        u = json.loads(out)
        return u['login'], int(u['id']), (u.get('name') or '').strip()
    except (ValueError, KeyError, TypeError):
        return None


def ssh_test(env):
    """(连通没有, 连上的账号, 哪一种问题, 原文)。GitHub 连通时也是退出码 1（它不给开终端），所以看那句「Hi <账号>!」。"""
    rc, out, err = _run(['ssh', *SSH_OPTS, f'git@{HOST}'], env, timeout=30)
    text = (out + err).strip()
    m = re.search(r'Hi ([^!\s]+)! You\'ve successfully authenticated', text)
    if m:
        return True, m.group(1), '', text
    if 'Host key verification failed' in text or 'REMOTE HOST IDENTIFICATION HAS CHANGED' in text:
        kind = 'hostkey'
    elif 'Permission denied' in text:
        kind = 'publickey'
    elif re.search(r'timed out|Could not resolve|Connection refused|Network is unreachable|No route to host|秒没结束', text):
        kind = 'network'
    else:
        kind = 'other'
    return False, '', kind, text


def git_identity(env):
    """(user.name, user.email)，没设的是空的。在根目录读：不受当前目录所在仓库的设置影响。"""
    def get(k):
        rc, out, _ = _run(['git', '-C', '/', 'config', '--get', k], env)
        return out.strip() if rc == 0 else ''
    return get('user.name'), get('user.email')


SSH_WHY = {
    'hostkey': '这台电脑还没记下 GitHub 的主机钥匙（~/.ssh/known_hosts）',
    'publickey': 'GitHub 不认这台电脑的 SSH 密钥（账号上还没有它的公钥，或者密钥设了口令）',
    'network': '连不上 GitHub 的 SSH（22 端口）：可能没联网，或者这里的网络挡了 SSH',
    'other': 'SSH 连 GitHub 没成功',
}


def check(env=None):
    """M3 的出口检查。不改任何东西。返回 Result。"""
    env = env or environ()
    fails, warns = [], []
    if not gh_path(env):
        return Result(False, ['还没装 gh（「安装工具」那一步装，规定位置是 ~/tools/gh）'], [])
    logged, acct, scopes, text = gh_status(env)
    if not logged:
        fails.append('gh 还没登录 GitHub（gh auth status 没通过）'
                     + (f'：{text.splitlines()[-1][:200]}' if text else ''))
    wide = [s for s in scopes if s in NOT_NEEDED]
    if wide:
        warns.append(f'gh 的登录多了用不着的权限：{"、".join(wide)}（以前登录时申请的；工具包用不着，'
                     '想收窄可以到 GitHub 网页的 Settings → Applications 里撤销后重新登录）')
    ok_ssh, ssh_acct, kind, stext = ssh_test(env)
    if not ok_ssh:
        fails.append(f'SSH 连不通 GitHub：{SSH_WHY[kind]}' + (f'（{stext.splitlines()[-1][:160]}）' if stext else ''))
    elif acct and ssh_acct.lower() != acct.lower():
        fails.append(f'SSH 连上的是 GitHub 账号 {ssh_acct}，gh 登录的是 {acct}：推送会用 {ssh_acct} 的身份，'
                     '两边要是同一个账号')
    name, email = git_identity(env)
    missing = [k for k, v in (('user.name', name), ('user.email', email)) if not v]
    if missing:
        fails.append(f'Git 的提交身份没设（{"、".join(missing)}），提交会失败')
    return Result(not fails, fails, warns, acct, ssh_acct, scopes, kind)


# ---------- 引导里改东西的几步 ----------
def set_identity(env, who):
    """没设的才设（写 ~/.gitconfig），已经设了的不动。返回设了哪几项 [(键, 值)]。"""
    login, uid, gname = who
    name, email = git_identity(env)
    want = []
    if not name:
        want.append(('user.name', gname or login))
    if not email:
        want.append(('user.email', f'{uid}+{login}@users.noreply.github.com'))
    for k, v in want:
        rc, _, err = _run(['git', 'config', '--global', k, v], env)
        if rc:
            raise RuntimeError(f'设 Git 的 {k} 没成功：{err.strip()[-200:]}')
    return want


def host_keys(env):
    """GitHub 自己说的 SSH 主机钥匙（gh api meta 的 ssh_keys），每项「类型 内容」。"""
    rc, out, err = gh(env, 'api', 'meta')
    if rc:
        raise RuntimeError(f'从 GitHub 取主机钥匙没成功：{(err or out).strip()[-200:]}')
    keys = json.loads(out).get('ssh_keys') or []
    good = [k.strip() for k in keys if re.fullmatch(r'(ssh-ed25519|ecdsa-sha2-nistp\d+|ssh-rsa) [A-Za-z0-9+/=]+', k.strip())]
    if not good:
        raise RuntimeError('GitHub 回的主机钥匙读不出来')
    return good


def add_known_hosts(keys):
    """把 GitHub 的主机钥匙补进 ~/.ssh/known_hosts：已有的同一行不重复加，别的行一个字不动，只往后加。返回加了几行。"""
    d = ssh_dir()
    d.mkdir(mode=0o700, exist_ok=True)
    kh = d / 'known_hosts'
    old = kh.read_text(encoding='utf-8', errors='replace') if kh.exists() else ''
    have = {' '.join(line.split()[:3]) for line in old.splitlines()}
    new = [f'{HOST} {k}' for k in keys if f'{HOST} {k}' not in have]
    if new:
        fd = os.open(kh, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            f.write(('\n' if old and not old.endswith('\n') else '') + '\n'.join(new) + '\n')
    return len(new)


def ensure_key(env, login):
    """~/.ssh/id_ed25519 没有才生成（不设口令）。返回 (公钥文件, 是不是这次新生成的)。已有的一把都不动。"""
    d = ssh_dir()
    d.mkdir(mode=0o700, exist_ok=True)
    key = d / KEY_NAME
    pub = d / f'{KEY_NAME}.pub'
    if key.exists() or pub.exists():
        if not (key.exists() and pub.exists()):
            raise RuntimeError(f'{key} 和 {pub} 只有一个（不完整），工具包不动它：请先把它改个名挪开，再跑一次这一步')
        return pub, False
    comment = f'{login}@{socket.gethostname()} (sop)'
    rc, _, err = _run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', comment, '-f', str(key)], env)
    if rc or not pub.exists():
        raise RuntimeError(f'生成 SSH 密钥没成功：{err.strip()[-200:]}')
    return pub, True


def upload_key(env, pub, *, interactive):
    """把公钥传到 GitHub 账号上。缺 admin:public_key 权限时补一次（gh auth refresh，网页上点一下）再传。返回一句话。"""
    title = f'sop {socket.gethostname()}'
    rc, out, err = gh(env, 'ssh-key', 'add', str(pub), '--title', title, '--type', 'authentication')
    text = (out + err).strip()
    if rc and 'admin:public_key' in text:
        interactive(['auth', 'refresh', '--hostname', HOST, '--scopes', ','.join(EXTRA_SCOPES)],
                    '要多给 gh 一项权限（admin:public_key，只用来把这台电脑的 SSH 公钥传到你的账号上），浏览器会再打开一次')
        rc, out, err = gh(env, 'ssh-key', 'add', str(pub), '--title', title, '--type', 'authentication')
        text = (out + err).strip()
    if rc and 'already' not in text.lower():
        raise RuntimeError(f'把 SSH 公钥传到 GitHub 没成功：{text[-300:]}')
    return f'这台电脑的 SSH 公钥 {pub} 已在 GitHub 账号上（标题「{title}」）'


def login_argv():
    return ['auth', 'login', '--hostname', HOST, '--git-protocol', 'ssh', '--web', '--skip-ssh-key',
            '--scopes', ','.join(EXTRA_SCOPES)]


def setup(env=None, *, say=print, stdio=None):
    """M3 的引导：做完再跑出口检查。返回 Result。stdio：gh 网页登录那两步的输出往哪写（测试用；平常直接在终端里）。"""
    paths.guard_home('登录 GitHub（M3：~/.ssh、~/.gitconfig）')
    env = env or environ()
    res = check(env)
    if res.ok:
        say(f'GitHub 已经登录好了（账号 {res.account}），SSH 连得通，提交身份也设了：这一步跳过')
        return res
    exe = gh_path(env)
    if not exe:
        say(res.failures[0])
        return res

    def interactive(args, why):
        say(why)
        say('  终端里会出现一串一次性代码（像 ABCD-1234）：按回车打开浏览器，在 GitHub 的网页上登录、填这串代码、点授权。')
        p = subprocess.run([exe, *args], env=env, stdout=stdio, stderr=stdio)
        if p.returncode:
            raise RuntimeError(f'gh 的网页登录没完成（退出码 {p.returncode}）。可以再跑一次这一步')

    try:
        logged, _, _, _ = gh_status(env)
        if not logged:
            interactive(login_argv(), '现在登录 GitHub。只申请工具包用得到的权限（不含改检查流程的 workflow、不含删仓库）。')
            if not gh_status(env)[0]:
                raise RuntimeError('登录之后 gh auth status 还是没通过')
        who = account(env)
        if not who:
            raise RuntimeError('登录了，但从 GitHub 取不到账号信息（gh api user 没成功）')
        say(f'已登录 GitHub，账号 {who[0]}')
        for k, v in set_identity(env, who):
            say(f'Git 的提交身份 {k} 原来没设，按 GitHub 账号设成了「{v}」（写在 ~/.gitconfig；想换可以自己改）')
        ok_ssh, _, kind, _ = ssh_test(env)
        if not ok_ssh and kind == 'hostkey':
            n = add_known_hosts(host_keys(env))
            say(f'记下了 GitHub 的 SSH 主机钥匙（从 GitHub 取的，~/.ssh/known_hosts 加了 {n} 行）')
            ok_ssh, _, kind, _ = ssh_test(env)
        if not ok_ssh and kind == 'publickey':
            pub, made = ensure_key(env, who[0])
            if made:
                say(f'生成了这台电脑的 SSH 密钥 {pub.with_suffix("")}（没设口令；只有你自己能读）')
            say(upload_key(env, pub, interactive=interactive))
    except RuntimeError as e:
        say(str(e))
    return check(env)


def report(res):
    if res.ok:
        lines = [f'GitHub 登录的出口检查：通过（账号 {res.account}，SSH 连得通）']
    else:
        lines = ['GitHub 登录的出口检查：不通过'] + [f'  不通过：{f}' for f in res.failures]
    lines += [f'  提醒（不影响通过）：{w}' for w in res.warnings]
    return lines


def main(argv):
    if argv not in ([], ['--check']):
        print('用法：python3 -m machine.ghsetup [--check]')
        return 2
    res = check() if argv else setup()
    print('\n'.join(report(res)))
    return 0 if res.ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
