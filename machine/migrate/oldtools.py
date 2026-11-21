"""环境迁移 Q6：卸旧的 nvm、uv、pnpm（设计书 4.8「nvm、uv：旧的选了卸载时，删掉它的目录和终端启动文件里对应的几行」；3-61）。

只卸 Q3 里选了「卸掉」、自己装在主目录里的那几样（旧的 nvm 目录连同里面的 Node、旧的 uv 程序和它旁边的 uvx 等、
~/.local/share/uv、旧的 pnpm 目录）。别的（gh、wt、系统软件包装的 Node 等）第一版只打印怎么卸。

先后（到小白最后确认之前一样都不动）：
1. 按 3-60 的「谁还在用」（users.py）逐条摆出来。这几种这一样就不卸，说清楚怎么办：装在旧的里面（或写死用旧的运行）的
   AI 工具在别处找不到另一份；旧的里面全局装的包、uv tool 在规定位置那份里没重装；用户级后台服务、开机自启指着旧的。
2. 终端启动文件里要删的几行先在临时文件上试删、核对语法（bash -n 等）；改不了的（续行、认不出的 pnpm 写法、删了语法就坏）
   这一样也不卸。uv 安装程序加的 `. "$HOME/.local/bin/env"`：~/.local/bin 里还有别的命令（claude、pi、wt 等）就留着，
   env 文件也留着；只剩旧 uv 自己才一起删。
3. 逐条打印要删的目录、文件、那几行，「卸掉后要重建的」（Python 环境等）；再确认一次，默认「否」。
4. 改终端启动文件：先备份到 ~/tools/backup/migrate-<日期>/，只删那几行，别的一字不动。
5. 开一个新的终端（桌面上开的那种 bash -i，和登录的那种 bash -l -i，都用干净的环境）看 node、pnpm、uv 找到的是谁：
   跳过马上要删的旧的之后，第一个得是 ~/tools 里规定位置的那份（靠 Node 运行的 Pi 等就是靠它）。不是、或者看不出来，
   把终端启动文件原样放回去，目录一样不删。
6. 删目录和文件（删之前核对路径：只删主目录里面、不是 ~/.local 这类公用目录、不在 ~/tools 里的），指向它们的链接一起删。
7. 再清点一遍：这几样旧的、终端启动文件里那几行都不再出现；再开一次新终端，第一个找到的就得是规定位置那份
   （3-08 留下的「登录的终端里 ~/.local/bin 排在前面、旧 uv 先被用到」，卸掉旧 uv 后要没了）。
结果记在 ~/tools/sop/config/migrate/uninstall.json 的 tools 里。
"""
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time

from kernel import paths

from .. import catalog, locate, shellenv
from . import carry as C, inventory, users

DROP = 'remove'
AUTO = ('nvm', 'uv', 'pnpm')
# 卸了这一样之后，新开的终端里要看哪几个命令
WATCH = {'nvm': ('node',), 'pnpm': ('pnpm',), 'uv': ('uv',)}
SHOW_CMDS = ('node', 'pnpm', 'uv')
# 主目录下的公用目录：不管清单怎么写都不删它们本身
PROTECT = ('.local', '.local/share', '.local/bin', '.local/state', '.config', '.cache', 'bin', 'tools')
DEFAULT_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
# pnpm 官方安装程序（pnpm setup）往终端启动文件里加的一段
PNPM_BLOCK = (r'#\s*pnpm', r'export\s+PNPM_HOME=.*', r'case\s+":\$PATH:"\s+in', r'\*":\$PNPM_HOME:"\*\)\s*;;',
              r'\*\)\s*export\s+PATH="\$PNPM_HOME:\$PATH"\s*;;', r'esac', r'#\s*pnpm\s+end')
MARK = 'SOP-WHICH'


def _subprocess(argv, timeout, env=None):
    try:
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace',
                           timeout=timeout, start_new_session=True)     # 新会话：交互的 bash 拿不到这个终端
    except FileNotFoundError:
        return 127, '', f'没有这个命令：{argv[0]}'
    except subprocess.TimeoutExpired:
        return 124, '', f'{timeout} 秒没结束'
    return p.returncode, p.stdout, p.stderr


def _check_tool(name):
    t = next((t for t in catalog.load() if t.name == name), None)
    return catalog.run_check(t).ok if t else False


class Host:
    """卸旧工具时动这台电脑的手段，单元测试换掉其中几样：
    probe   清点用的那个（home、tools、path_env；只读）
    check   check(名字) -> 规定位置那份过不过清单的检查命令
    wrap    开新终端时套在外面的（测试里是「整个系统只读」的 bubblewrap）
    run     run(argv, timeout, env) -> (退出码, 输出, 报错)"""

    def __init__(self, probe, *, check=None, wrap=(), run=None, tools=None, backup_dir=None):
        self.probe = probe
        self.check = check or _check_tool
        self.wrap = list(wrap)
        self.run = run or _subprocess
        self.tools = tools
        self.backup_dir = backup_dir

    def login_path(self):
        """登录时系统给的 PATH（/etc/environment），没有就用 Ubuntu 默认的。"""
        text = self.probe.read(self.probe.p('/etc/environment')) or ''
        m = re.search(r'^\s*PATH=["\']?([^"\'\n]+)', text, re.M)
        return m[1] if m else DEFAULT_PATH

    def new_shell(self, login):
        """开一个新终端（干净的环境，和桌面上新开的、或登录进来的一样），返回 {命令: [PATH 里依次找到的位置]}；
        终端没正常跑完返回 (None, 原因)。"""
        script = (f'for c in {" ".join(SHOW_CMDS)}; do printf "\\n{MARK} %s" "$c"; '
                  'type -a -P "$c" 2>/dev/null | while IFS= read -r p; do printf "\\t%s" "$p"; done; done; '
                  f'printf "\\n{MARK}-END\\n"')
        env = {'HOME': self.probe.home, 'USER': self.probe.user, 'LOGNAME': self.probe.user, 'SHELL': '/bin/bash',
               'TERM': 'dumb', 'LANG': 'C.UTF-8', 'PATH': self.login_path()}
        argv = self.wrap + ['bash'] + (['-l'] if login else []) + ['-i', '-c', script]
        rc, out, err = self.run(argv, 60, env)
        if f'{MARK}-END' not in out:
            return None, (err.strip().splitlines() or [f'退出码 {rc}'])[-1]
        found = {}
        for line in out.splitlines():
            if line.startswith(MARK + ' '):
                parts = line[len(MARK) + 1:].split('\t')
                found[parts[0]] = [p for p in parts[1:] if p]
        return found, ''

    def syntax_ok(self, path, text):
        """在临时文件上核对终端启动文件的语法（只解析，不执行）。没有那种终端程序就算过（不会读它）。"""
        name = os.path.basename(path)
        if name.endswith('.fish'):
            shell, args = 'fish', ['--no-execute']
        elif name.startswith('.z'):
            shell, args = 'zsh', ['-n']
        else:
            shell, args = 'bash', ['-n']
        exe = shutil.which(shell)
        if not exe:
            return True, ''
        with tempfile.TemporaryDirectory(prefix='sop-rc-') as d:
            f = os.path.join(d, name)
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write(text)
            rc, _, err = self.run([exe, *args, f], 30, None)
        return rc == 0, err.strip().replace(f, name)


# ---------- 要卸的是哪几样 ----------

class Unit:
    """一样要卸的旧工具：root 是 users.Root；companions 是旧 uv 旁边的 uvx、env 等。"""

    def __init__(self, name, copy, root):
        self.name, self.copy, self.root = name, copy, root
        self.companions = []
        self.items = []           # 3-60 列出来的「谁还在用」里属于它的
        self.why = ''             # 不卸的原因（空的就是要卸）
        self.lines = {}           # {终端启动文件: [要删的行号]}
        self.kept_lines = []      # 留着的那几行（uv 的 env）
        self.paths = []           # 要删的 [(真实路径, 给人看的)]

    @property
    def label(self):
        return f'{self.name} {self.copy["path"]}'

    def roots(self):
        return [self.root] + self.companions

    def owns(self, shown):
        return any(r.shown == shown for r in self.roots())


def _is_under(p, root):
    return p == root or p.startswith(root.rstrip('/') + '/')


def _raw(probe, shown):
    return probe.home + shown[1:] if shown.startswith('~/') else shown


def select(probe, tools_now, ch):
    """Q3 选了卸的、自己装在主目录里的 nvm、uv、pnpm -> ([Unit], [(工具, 那一份) 第一版不自动卸的], [不在了的])。"""
    want = {(t['name'], t['path']) for t in ch.get('tools', []) if t['choice'] == DROP}
    copies = {(t['name'], c['path']): c for t in tools_now for c in t['copies']}
    roots = users.old_roots(probe, tools_now)
    units, manual, gone = [], [], []
    for name, path in sorted(want):
        c = copies.get((name, path))
        if c is None:
            gone.append(f'{name} {path}')
            continue
        if name not in AUTO or c.get('how') != 'home' or c.get('inside'):
            manual.append((name, c))
            continue
        r = next((r for r in roots if r.tool == name and not r.role and r.alias == _raw(probe, c['path'])), None)
        if r is None:
            manual.append((name, c))
            continue
        u = Unit(name, c, r)
        if name == 'uv' and os.path.isfile(r.path):
            d = os.path.dirname(r.path)
            u.companions = [x for x in roots if x.role == 'companion' and os.path.dirname(x.path) == d]
        units.append(u)
    return units, manual, gone


def manual_steps(name, c):
    how = c.get('how')
    if how == 'package':
        return [f'sudo apt purge {c.get("package", name)}']
    if how == 'snap':
        return [f'sudo snap remove {c.get("package", name)}']
    p = c['path'].replace('~/', '$HOME/', 1)
    return [('sudo ' if c.get('admin') else '') + (f'rm -r "{p}"' if os.path.isdir(c.get('real', '')) else f'rm "{p}"')]


# ---------- 谁还在用：挡不挡 ----------

def _all_removing(units):
    out = []
    for u in units:
        for r in u.roots():
            out += [r.path, r.alias]
    return out


def _outside(p, removing):
    real = os.path.realpath(p)
    return not any(_is_under(p, x) or _is_under(real, x) for x in removing)


def _new_bins(probe):
    t = probe.tools
    return [f'{t}/uv/bin', f'{t}/pnpm/bin'] + sorted(glob.glob(f'{t}/nvm/versions/node/*/bin'))


def _found_elsewhere(probe, cmd, removing, extra=()):
    path = os.environ.get('PATH', '') if probe.path_env is None else probe.path_env
    cands = locate.which_all(cmd, os.pathsep.join(_new_bins(probe) + [path])) + [locate.expand(p, probe.home) for p in extra]
    return next((c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK) and _outside(c, removing)), None)


def blocker(probe, it, removing):
    """这一条挡不挡卸载：挡就返回原因（大白话），不挡返回 ''。"""
    k = it['kind']
    if k == 'ai-tool':
        if it.get('how') in ('node-env', 'launcher'):
            return ''        # 靠 Node 运行的：改完终端启动文件后开新终端看 node 是规定位置的那份（第 5 步）
        defaults = next((d for _, _, c, d in locate.AI_TOOLS if c == it.get('command')), ())
        hit = _found_elsewhere(probe, it.get('command') or '', removing, defaults) if it.get('command') else None
        return '' if hit else f'{it["what"]}：{it["effect"]}。{it["fix"]}'
    if k == 'global':
        pkg = it.get('package') or it['what'].split('（')[0]
        if pkg == 'pnpm':
            return ''        # 规定位置那份 pnpm 是 M2 装的，Q2 核对过
        t = probe.tools
        if glob.glob(f'{t}/nvm/versions/node/*/lib/node_modules/{pkg}') or glob.glob(f'{t}/pnpm/global/*/node_modules/{pkg}'):
            return ''
        cmds = it.get('commands') or []
        if cmds and all(_found_elsewhere(probe, c, removing) for c in cmds):
            return ''
        return (f'全局装的包 {it["what"]}（{it["where"]}）：规定位置那份里还没有它，卸掉旧的就没了。还要用就先在规定位置那份里重装'
                f'（新开一个终端执行 pnpm add -g {pkg}）；不要了就先删掉它（rm -r "{_sh(it["where"])}"）。再执行一次 sop machine migrate')
    if k == 'uv-tool':
        name = it.get('name') or it['what'].split('（')[0]
        if os.path.isdir(f'{probe.tools}/uv/tools/{name}'):
            return ''
        return (f'旧的 uv 装的命令 {it["what"]}：规定位置那份 uv 里还没有它，卸掉旧的就没了。还要用就先在新开的终端里执行 '
                f'uv tool install {name}；不要了就先删掉它（rm -r "{_sh(it["where"])}"）。再执行一次 sop machine migrate')
    if k == 'service':
        return f'{it["what"]}（{it["where"]}）：{it["effect"]}。{it["fix"]}，再执行一次 sop machine migrate'
    return ''


def _sh(shown):
    return '$HOME/' + shown[2:] if shown.startswith('~/') else shown


def _executable(p):
    return os.path.isfile(p) and os.access(p, os.X_OK)


def env_keeps(unit, removing):
    """uv 安装程序放的 env 把它所在的目录（~/.local/bin）放进 PATH：那里还有别的命令（不是这次要删的）时返回它们的名字。"""
    if unit.name != 'uv' or not unit.companions:
        return []
    d = os.path.dirname(unit.root.path)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [n for n in names if _executable(os.path.join(d, n)) and _outside(os.path.join(d, n), removing)]


# ---------- 终端启动文件：要删哪几行 ----------

def _pnpm_block(lines, i):
    """第 i 行（从 0 数）在 pnpm 官方安装程序加的那一段里：返回整段的行号范围；不是返回 None。"""
    for s in range(i, max(-1, i - 2), -1):
        if s + len(PNPM_BLOCK) <= len(lines) and all(
                re.fullmatch(pat, lines[s + k].strip()) for k, pat in enumerate(PNPM_BLOCK)):
            return range(s, s + len(PNPM_BLOCK))
    return None


def _outside_sop(lines):
    """不在工具包那一段里的行号（从 0 数）。"""
    out, inside = [], False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == shellenv.BEGIN:
            inside = True
        elif s == shellenv.END:
            inside = False
        elif not inside:
            out.append(i)
    return out


def _unit_lines(lines, nums, fname):
    """一样旧工具在一个文件里要删的行（从 1 数的行号）-> (要删的行号集合（从 0 数）, 不能改的原因)。"""
    drop = set()
    for n in nums:
        i = n - 1
        if i >= len(lines):
            return set(), f'{fname} 第 {n} 行不见了（文件在清点之后被改过）'
        if lines[i].rstrip('\n').rstrip().endswith('\\') or (i and lines[i - 1].rstrip('\n').rstrip().endswith('\\')):
            return set(), f'{fname} 第 {n} 行和上下行是接在一起的（行末有 \\），工具包不拆它'
        if re.match(r'\s*export\s+PNPM_HOME=', lines[i]):
            blk = _pnpm_block(lines, i)
            if blk is None:
                others = [k + 1 for k in _outside_sop(lines) if k != i and 'PNPM_HOME' in lines[k]
                          and not lines[k].lstrip().startswith('#')]
                if others:
                    return set(), (f'{fname} 第 {"、".join(map(str, others))} 行还用着 PNPM_HOME（不是 pnpm 官方装法加的那一段），'
                                   f'只删第 {n} 行会让它把当前目录放进 PATH，工具包不改它')
                drop.add(i)
            else:
                drop.update(blk)
            continue
        drop.add(i)
    return drop, ''


def plan_edits(host, units, shell_items, removing):
    """算出每个终端启动文件改成什么样，先在临时文件上核对语法。改不了的那一样记下原因（unit.why）。
    返回 {文件: (原来的全文, 改后的全文, [这个文件里删掉的行（给人看）])}。"""
    probe = host.probe
    for u in units:
        u.lines, u.kept_lines = {}, []
        keeps = env_keeps(u, removing)
        for it in shell_items:
            if not u.owns(it['old']):
                continue
            if keeps and os.path.basename(_raw(probe, it['old'])) in ('env', 'env.fish'):
                u.kept_lines.append((it, keeps))
                continue
            u.lines.setdefault(_raw(probe, it['where']), []).append(it['line_no'])
    texts = {}
    for u in units:
        for f in u.lines:
            if f not in texts:
                try:
                    with open(f, encoding='utf-8') as fh:
                        texts[f] = fh.read()
                except (OSError, UnicodeDecodeError) as e:
                    texts[f] = None
                    u.why = u.why or f'{probe.show(f)} 读不了（{e}）'
    drops = {}
    for u in units:
        if u.why:
            continue
        for f, nums in u.lines.items():
            if texts.get(f) is None:
                u.why = u.why or f'{probe.show(f)} 读不了'
                continue
            d, why = _unit_lines(texts[f].splitlines(keepends=True), nums, probe.show(f))
            if why:
                u.why = why
            drops[(id(u), f)] = d

    def new_text(f, us):
        lines = texts[f].splitlines(keepends=True)
        gone = set().union(*[drops.get((id(u), f), set()) for u in us]) if us else set()
        return ''.join(ln for i, ln in enumerate(lines) if i not in gone), [lines[i].rstrip('\n') for i in sorted(gone)]

    while True:
        live = [u for u in units if not u.why]
        bad = False
        for f in sorted({f for u in live for f in u.lines}):
            us = [u for u in live if f in u.lines]
            ok, err = host.syntax_ok(f, new_text(f, us)[0])
            if ok:
                continue
            bad = True
            alone = [u for u in us if not host.syntax_ok(f, new_text(f, [u])[0])[0]]
            for u in alone or us:
                u.why = f'{probe.show(f)} 删掉那几行以后语法不对了（{err}），工具包不改它'
        if not bad:
            break
    live = [u for u in units if not u.why]
    out = {}
    for f in sorted({f for u in live for f in u.lines}):
        t, removed = new_text(f, [u for u in live if f in u.lines])
        if t != texts[f]:
            out[f] = (texts[f], t, removed)
    return out


# ---------- 删什么 ----------

def unsafe(probe, real):
    """这个路径不该删时返回原因，能删返回 None。只删主目录里面的。"""
    home, real = probe.home.rstrip('/'), os.path.normpath(real)
    if real == home or not _is_under(real, home):
        return '不在主目录里面'
    if any(real == f'{home}/{x}' for x in PROTECT):
        return '是主目录里的公用目录'
    if _is_under(real, probe.tools) or _is_under(probe.tools, real):
        return '在工具包的目录 ~/tools 里'
    if os.path.isdir(real) and not os.path.islink(real) and os.path.ismount(real):
        return '是另一个分区挂在这里'
    return None


def _receipt(probe, uv_bin):
    """uv 官方安装程序留的记录文件 ~/.config/uv/uv-receipt.json：记的安装位置就是这个旧 uv 时一起删。"""
    f = probe.h('.config/uv/uv-receipt.json')
    try:
        with open(f, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    prefix = data.get('install_prefix') if isinstance(data, dict) else None
    if isinstance(prefix, str):
        prefix = os.path.normpath(_raw(probe, prefix.replace('$HOME', probe.home)))
        if prefix in (os.path.dirname(uv_bin), os.path.dirname(os.path.dirname(uv_bin))):
            return f
    return None


def plan_paths(probe, u, items, removing):
    """这一样要删的 [(真实路径, 给人看的)]。"""
    out = []

    def add(p):
        if p and os.path.lexists(p) and p not in [x for x, _ in out]:
            out.append((p, probe.show(p)))

    keeps = env_keeps(u, removing)
    if u.root.alias != u.root.path and os.path.islink(u.root.alias):
        add(u.root.alias)
    add(u.root.path)
    for c in u.companions:
        if os.path.basename(c.path) in ('env', 'env.fish') and keeps:
            continue
        add(c.path)
    for it in items:
        cmds = []
        if it['kind'] == 'command':
            cmds = [it['where']]
        elif it['kind'] == 'uv-tool':
            cmds = it.get('commands') or []
        for shown in cmds:
            p = _raw(probe, shown)
            if os.path.islink(p) and any(_is_under(os.path.realpath(p), x) for r in u.roots() for x in (r.path, r.alias)):
                add(p)        # 指向旧的里面的链接，旧的删了它就断了，一起删
    if u.name == 'uv' and os.path.isfile(u.root.path):
        add(_receipt(probe, u.root.path))
    return out


def _chmod_retry(func, path, exc):
    os.chmod(os.path.dirname(path), 0o700)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, 0o700)
    func(path)


def delete(real):
    """删掉一个文件、链接或整个目录。返回出错的原因，删掉了返回 ''。"""
    try:
        if os.path.isdir(real) and not os.path.islink(real):
            shutil.rmtree(real, onexc=_chmod_retry)
        else:
            os.remove(real)
    except OSError as e:
        return e.strerror or str(e)
    return ''


# ---------- 新开的终端里找到的是谁 ----------

def watch(units):
    out = []
    for u in units:
        if u.name == 'uv' and not os.path.isfile(u.root.path):
            continue          # 只删 ~/.local/share/uv：uv 命令本身不受影响
        out += [c for c in WATCH[u.name] if c not in out]
    return out


def judge(found, cmds, removing, tools, skip_old):
    """新终端里每个命令第一个找到的（skip_old：先跳过马上要删的旧的）得在 ~/tools 里。返回 [(命令, 第一个找到的或 None)]。"""
    bad = []
    for c in cmds:
        lst = found.get(c, [])
        if skip_old:
            lst = [p for p in lst if _outside(p, removing)]
        first = lst[0] if lst else None
        if not first or not _is_under(os.path.realpath(first), tools):
            bad.append((c, first))
    return bad


def shell_check(host, cmds, removing, skip_old):
    """开两种新终端（桌面上开的、登录进来的）看一遍。返回 (都对没有, 给人看的几行)。"""
    lines, ok = [], True
    if not cmds:
        return True, []
    for login, what in ((False, '桌面上新开的终端'), (True, '登录进来的终端（ssh、bash -l）')):
        found, why = host.new_shell(login)
        if found is None:
            return False, [f'  {what}：没看成（{why}）']
        bad = judge(found, cmds, removing, host.probe.tools, skip_old)
        for c in cmds:
            hit = [b for b in bad if b[0] == c]
            lst = [p for p in found.get(c, []) if not skip_old or _outside(p, removing)]
            if hit:
                ok = False
                lines.append(f'  {what}：{c} 找到的是 {host.probe.show(hit[0][1]) if hit[0][1] else "（找不到）"}，不是 ~/tools 里规定位置那份')
            else:
                lines.append(f'  {what}：{c} 是 {host.probe.show(lst[0])}')
    return ok, lines


# ---------- 整个 ----------

def _confirm_text(probe, units, edits, items):
    L = ['', 'Q6 卸载旧的 nvm、uv、pnpm。下面这些会被删掉（删了就找不回来）：']
    n = 0
    for u in units:
        for p, shown in u.paths:
            n += 1
            size = locate.disk_usage(p)[0] if os.path.isdir(p) and not os.path.islink(p) else None
            L.append(f'  {n}. {shown}' + (f'（{locate.human_size(size)}）' if size else '') + f'（{u.label}）')
    if edits:
        L.append('终端启动文件里删掉这几行（别的一个字不动，改之前先备份）：')
        for f, (_, _, removed) in edits.items():
            for ln in removed:
                L.append(f'  {probe.show(f)}：{ln}')
    for u in units:
        for it, keeps in u.kept_lines:
            L.append(f'留着：{it["what"]}的「{it["line"]}」和 {os.path.basename(_raw(probe, it["old"]))} 文件'
                     f'（它把 {probe.show(os.path.dirname(u.root.path))} 放进 PATH，那里还有 {"、".join(keeps)}）')
    later = [it for it in items if it['kind'] in ('command', 'venv', 'node-version', 'python', 'ai-tool')]
    if later:
        L.append('卸掉以后，下面这些要你自己处理（工具包不替你删、不替你重装）：')
        for it in later:
            if it.get('node'):
                L.append(f'  {it["what"]}（{it["where"]}）：靠 Node 运行，卸掉以后用 ~/tools 里规定位置那份 Node'
                         '（工具包会先开新终端核对），卸完你打开一次试试')
                continue
            L.append(f'  {it["what"]}' + ('' if it['where'] in it['what'] else f'（{it["where"]}）') + f'：{it["fix"]}')
    L.append('改完终端启动文件，工具包会开一个新终端看 node、pnpm、uv 是不是 ~/tools 里规定位置那份；不是就把启动文件放回原样，'
             '目录一样不删。不用管理员密码。')
    return '\n'.join(L)


def _write(f, text):
    target = os.path.realpath(f)
    mode = os.stat(target).st_mode & 0o7777
    shellenv.write_text(pathlib.Path(target), text, mode)


def _backup(probe, edits, backup_dir):
    d = os.path.join(str(backup_dir), f'startup-files-{time.strftime("%H%M%S")}')
    for f, (orig, _, _) in edits.items():
        rel = os.path.relpath(f, probe.home)
        b = os.path.join(d, rel)
        os.makedirs(os.path.dirname(b), mode=0o700, exist_ok=True)
        fd = os.open(b, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(orig)
    return d


def _restore(edits, done, say, probe):
    for f in done:
        try:
            _write(f, edits[f][0])
        except OSError as e:
            say(f'  {probe.show(f)} 没能放回原样（{e}）：备份里有原来那份，请自己拷回去')


def q6_tools(ch, s, *, host=None):
    """Q3 里选了卸的旧 nvm、uv、pnpm。s 是 flow.Session（say、ask、probe）。返回退出码：0 = 没有要卸的、小白没确认、
    或者卸完了；1 = 有没卸成的、没卸干净的。"""
    say, ask = s.say, s.ask
    if not any(t['choice'] == DROP for t in ch.get('tools', [])):
        return 0
    host = host or Host(s.probe)
    probe = host.probe
    tools_now = inventory.other_tools(probe, host.tools)
    units, manual, gone = select(probe, tools_now, ch)
    rc = 0
    for g in gone:
        say(f'{g}：现在已经找不到了，不用卸。')
    for name, c in manual:
        say('')
        if c.get('inside'):
            say(f'{name} {c["path"]} 在 {c["inside"]} 里面，跟着它一起留或卸（Q3 里选 {c["inside"]} 那一项）。')
            continue
        say(f'{name} {c["path"]}（{c.get("how_text", "")}）：第一版不自动卸。要卸的话自己执行：')
        for line in manual_steps(name, c):
            say(f'  {line}')
    if not units:
        return rc
    removing = _all_removing(units)
    res = users.find(probe, tools_now)
    for u in units:
        u.items = [it for it in res['items'] if u.owns(it['old'])]
    # 规定位置那份没装好的不卸（4.8：新的先装好，才谈旧的；Q2 核对过，这里是保险）
    for u in units:
        need = {'nvm': ('nvm', 'node'), 'uv': ('uv',), 'pnpm': ('pnpm',)}[u.name]
        miss = [n for n in need if not host.check(n)]
        if miss:
            u.why = f'规定位置的 {"、".join(miss)} 没装好（先执行 sop machine setup）'
    # 谁还在用：挡的那几种
    for u in units:
        if u.why:
            continue
        why = [b for b in (blocker(probe, it, removing) for it in u.items) if b]
        if why:
            u.why = '还有东西要用它：\n    ' + '\n    '.join(why)
    # 终端启动文件要删的行、要删的路径：有一样改不了就不卸它，剩下的重算（env 那一行留不留看剩下要删的）
    shell_items = [it for it in res['items'] if it['kind'] == 'shell']
    live = [u for u in units if not u.why]
    while True:
        removing = _all_removing(live)
        edits = plan_edits(host, live, shell_items, removing)
        for u in live:
            u.paths = plan_paths(probe, u, u.items, removing) if not u.why else []
            bad = [f'{shown} {w}' for p, shown in u.paths for w in [unsafe(probe, p)] if w]
            if bad and not u.why:
                u.why = '、'.join(bad) + '，工具包不删它'
        now = [u for u in live if not u.why]
        if len(now) == len(live):
            break
        live = now
    for u in units:
        if u.why:
            say('')
            say(f'{u.label}：这次不卸，旧的照常在、照常能用。原因：{u.why}')
            rc = 1
    if not live:
        return rc
    paths.guard_home('迁移 Q6（卸载旧的 nvm、uv、pnpm）')      # 自测的保险（3-59）：测试漏设 HOME 时一样都不删
    items = [it for u in live for it in u.items]
    say(_confirm_text(probe, live, edits, items))
    if not ask.yes('确定现在卸掉它们吗', False):
        say('好，不卸。旧的照常在、照常能用；想好了再执行一次 sop machine migrate。')
        return rc
    result = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'units': [u.label for u in live]}
    cmds = watch(live)
    say('')
    say('开始卸载：')
    done = []
    if edits:
        backup = host.backup_dir or C.default_backup_dir()
        bdir = _backup(probe, edits, backup)
        result['backup'] = probe.show(bdir)
        say(f'  终端启动文件原来的样子备份在 {probe.show(bdir)}')
        for f, (orig, new, removed) in edits.items():
            try:
                with open(f, encoding='utf-8') as fh:
                    now_text = fh.read()
            except OSError as e:
                now_text = None
                err = str(e)
            if now_text != orig:
                say(f'  {probe.show(f)} 在这期间被改过（{err if now_text is None else "和刚才看到的不一样"}），一样都不卸了')
                _restore(edits, done, say, probe)
                return 1
            _write(f, new)
            done.append(f)
            say(f'  {probe.show(f)}：删掉了 {len(removed)} 行')
    ok, lines = shell_check(host, cmds, removing, True)
    say('  开一个新终端看看（跳过马上要删的旧的）：')
    for ln in lines:
        say('  ' + ln)
    if not ok:
        _restore(edits, done, say, probe)
        say('新开的终端里用的还不是规定位置那份，终端启动文件已经放回原样，目录一样没删，旧的照常能用。'
            '执行 sop machine doctor 看看规定位置那份；或者自己看看终端启动文件里还有什么在改 PATH。')
        result.update(ok=False, why='新终端里用的不是规定位置那份')
        _save(result)
        return 1
    left = []
    for u in live:
        for p, shown in u.paths:
            why = delete(p)
            say(f'  删掉了 {shown}' if not why else f'  {shown} 没删掉：{why}')
            if why:
                left.append(f'{shown}（没删掉：{why}）')
    left += after_check(probe, host, live)
    ok2, lines2 = shell_check(host, cmds, removing, False)    # 3-08：登录的终端里旧 uv 排在前面，卸掉以后要没了
    say('  再开一个新终端看看：')
    for ln in lines2:
        say('  ' + ln)
    result.update(ok=not left and ok2, left=left, new_shell_ok=ok2)
    _save(result)
    say('')
    if left:
        say('没卸干净，下面几样还在：')
        for x in left:
            say(f'  {x}')
        rc = 1
    else:
        say(f'旧的 {"、".join(u.label for u in live)} 卸完了：再清点一遍，它们和终端启动文件里那几行都没有了。')
    if not ok2:
        say('新开的终端里第一个找到的还不是规定位置那份（见上面），执行 sop machine doctor 看看。')
        rc = 1
    pi = [it for it in items if it['kind'] in ('ai-tool', 'command') and it.get('node')]
    if pi:
        say(f'靠 Node 运行的 {"、".join(it["what"] for it in pi)}：新开一个终端打开一次试试（现在用的是 ~/tools 里的 Node）。')
    return rc


def after_check(probe, host, live):
    """卸完再看一遍（只读）：要删的都不在了；再清点一遍，这几样旧的不再出现；终端启动文件里指着它们的行没有了（留着的不算）。"""
    left = []
    gone_roots = [r for u in live for r in u.roots()]
    for u in live:
        for p, shown in u.paths:
            if os.path.lexists(p):
                left.append(f'{shown}（还在）')
    removed = [x for r in gone_roots for x in (r.path, r.alias)]
    for r in users.old_roots(probe, inventory.other_tools(probe, host.tools)):
        if any(_is_under(r.path, x) or _is_under(r.alias, x) for x in removed) and f'{r.shown}（还在）' not in left:
            left.append(f'{r.shown}（再清点时还找得到）')
    kept = {(it['where'], it['line']) for u in live for it, _ in u.kept_lines}
    for it in users.shell_lines(probe, gone_roots):
        if (it['where'], it['line']) not in kept:
            left.append(f'{it["what"]}：{it["line"]}')
    return left


def _save(result):
    from . import uninstall
    uninstall._save({'tools': result})
