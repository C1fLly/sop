"""环境迁移 Q1：旧的 nvm、uv、Node 还有谁在用（设计书 4.8「卸掉旧的之前，要先看还有谁在用它」，任务 3-60）。

清点（inventory.py）的 tools 那一部分找出了工具包自己装的那几样另有一份不在规定位置的；这里接着看，
nvm、uv、Node、pnpm 的旧的那一份卸掉之前，还有谁在用它：
- AI 工具（Claude Code、Codex、OpenCode、Pi）：装在旧的里面的；靠 Node 运行、而终端里现在找到的 Node 是旧的；
- 别的命令（~/.local/bin、~/bin、PATH 里主目录下的目录、/usr/local/bin）：链接指向旧的里面的、第一行写死用旧的里面的
  程序运行的、靠 Node 运行而现在找到的 Node 是旧的；
- 旧的里面装着的东西：旧 nvm 里的各个 Node 版本和全局装的包、旧 pnpm 全局装的包、旧 uv 装的 Python 和命令（uv tool）；
- Python 环境（有 pyvenv.cfg 的目录，项目里的 .venv 就是）：记着的 Python 在旧 uv 里面的，旧的卸了要重建。在主目录里找，
  最深 MAX_DEPTH 层，跳过 node_modules、.git、缓存、旧的和规定位置的工具目录、Docker 的数据；
- 终端启动文件里指向旧位置的几行（SOP 自己那一段不算），用户级后台服务、开机自启、桌面图标里指向旧位置的。

每一条写明是哪一样旧的、在哪、卸了会怎样、怎么办。只看文件：不跑这些工具、不跑任何命令、不改任何东西。
"""
import dataclasses
import json
import os
import re

from .. import locate, shellenv

TOOLS = ('nvm', 'uv', 'node', 'pnpm')
# Pi 的安装程序自带的 Node：有它时 Pi 的启动脚本先用它，不用终端里的（本机读了 ~/.pi/agent/bin/pi 的原文）
PRIVATE_NODE = {'pi': ('~/.local/share/pi-node/current/bin/node',)}
SHELL_FILES = ('.bashrc', '.bash_profile', '.bash_login', '.profile', '.zshrc', '.zshenv', '.zprofile', '.zlogin',
               '.config/fish/config.fish')
SERVICE_DIRS = (('.config/systemd/user', ('.service', '.timer', '.socket', '.path')),
                ('.config/autostart', ('.desktop',)), ('.local/share/applications', ('.desktop',)))
SYSTEM_BIN = ('/usr/local/bin',)
SKIP_NAMES = {'node_modules', '.git', '.hg', '.svn', '.cache', '.npm', '.rustup', '.cargo', '.gradle', '.m2', 'Trash',
              '__pycache__', 'snap'}
SKIP_TOOLS = ('nvm', 'uv', 'docker', 'docker-sop', 'cache')     # ~/tools 下不用找的（规定位置的工具、Docker 数据、缓存）
NODE_BUILTIN = {'npm', 'corepack'}                              # 跟着 Node 一起来的，不算「全局装的包」
MAX_DEPTH = 6
MAX_DIRS = 200000
KIND_TITLES = (
    ('ai-tool', 'AI 工具'), ('command', '命令'), ('node-version', '旧的 nvm 里的 Node 版本'),
    ('global', '全局装的包'), ('python', '旧的 uv 装的 Python'), ('uv-tool', '旧的 uv 装的命令'),
    ('venv', 'Python 环境'), ('shell', '终端启动文件'), ('service', '后台服务、开机自启、桌面图标'),
)
LABELS = {'nvm': 'nvm', 'uv': 'uv', 'node': 'Node', 'pnpm': 'pnpm'}


@dataclasses.dataclass
class Root:
    """一处旧的：tool 是哪一样；path 是解开链接后的位置；alias 是找到时的位置（终端启动文件里多半写的是它）。"""
    tool: str
    path: str
    alias: str
    shown: str
    role: str = ''          # companion：uv 安装程序放在它旁边的 uvx、env；node-globals：Node 的全局包目录


def _under(p, root):
    return p == root or p.startswith(root.rstrip('/') + '/')


def _executable(p):
    return os.path.isfile(p) and os.access(p, os.X_OK)


def _listdir(d):
    try:
        return sorted(os.listdir(d))
    except OSError:
        return []


def _head(path, n=256):
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def runtime(path):
    """看可执行文件的开头：('native', '') 自己就是程序；('node-env', '') 第一行是 #!/usr/bin/env node；
    ('interp', 解释器的位置) 第一行写死了用哪个程序运行（node、python……）；('launcher', '') 是 sh、bash 写的启动脚本、
    里面提到 node（Pi 那种：最后交给 node 运行）；('script', 解释器) 别的脚本；('unknown', '')。"""
    b = _head(path)
    if b.startswith(b'\x7fELF'):
        return 'native', ''
    if not b.startswith(b'#!'):
        return 'unknown', ''
    parts = b[2:].split(b'\n', 1)[0].decode('utf-8', 'replace').split()
    if not parts:
        return 'unknown', ''
    prog = parts[0]
    if os.path.basename(prog) == 'env':
        args = [a for a in parts[1:] if not a.startswith('-') and '=' not in a]
        name = args[0] if args else ''
        return ('node-env', '') if name in ('node', 'nodejs') else ('script', name)
    if os.path.basename(prog) in ('sh', 'bash', 'dash', 'zsh'):
        text = _read(path) or ''
        if 'node_modules/.bin/' in text or re.search(r'(?<![\w-])node(?![\w-])', text):
            return 'launcher', prog
        return 'script', prog
    return 'interp', prog


# ---------- 旧的在哪 ----------

def old_roots(probe, tools):
    """按清点的 tools 那一部分（inventory.other_tools 的结果），列出 nvm、uv、Node、pnpm 每一处旧的。
    在另一份里面的（例如 ~/.nvm 里的 node）不另列，算在外面那一份里。"""
    roots = []

    def add(tool, real, alias, role=''):
        if any(_under(real, r.path) for r in roots):
            return
        roots.append(Root(tool, real, alias, probe.show(real), role))

    for t in tools:
        if t['name'] not in TOOLS:
            continue
        for c in t['copies']:
            if c.get('inside'):
                continue
            real, alias = c['real'], _raw_path(probe, c['path'])
            add(t['name'], real, alias)
            if t['name'] == 'uv' and os.path.isfile(real):
                d = os.path.dirname(real)
                for comp in ('uvx', 'env', 'env.fish'):
                    if os.path.isfile(os.path.join(d, comp)):
                        add('uv', os.path.join(d, comp), os.path.join(d, comp), 'companion')
            if t['name'] == 'node' and os.path.isfile(real):
                mods = os.path.join(os.path.dirname(os.path.dirname(real)), 'lib', 'node_modules')
                if os.path.isdir(mods):
                    add('node', mods, mods, 'node-globals')
    return roots


def _raw_path(probe, shown):
    return probe.home + shown[1:] if shown.startswith('~/') else shown


def root_of(path, roots):
    if not path:
        return None
    for p in dict.fromkeys((path, os.path.realpath(path))):
        for r in roots:
            if _under(p, r.path) or _under(p, r.alias):
                return r
    return None


def _item(kind, root, what, where, effect, fix, **extra):
    d = {'kind': kind, 'tool': root.tool, 'old': root.shown, 'what': what, 'where': where, 'effect': effect, 'fix': fix}
    d.update(extra)
    return d


# ---------- 靠 Node 运行的 ----------

def current_node(probe):
    hits = locate.which_all('node', probe.path_env)
    return hits[0] if hits else None


def _node_note(probe, roots):
    """终端里现在找到的 Node 是旧的，返回 (那个 node 的位置, 它属于的旧的)；不是旧的返回 None。"""
    node = current_node(probe)
    r = root_of(node, roots)
    return (node, r) if r else None


def ai_tools(probe, roots, done):
    out = []
    old_node = _node_note(probe, roots)
    for name, label, command, defaults in locate.AI_TOOLS:
        cands = locate.which_all(command, probe.path_env) + [locate.expand(p, probe.home) for p in defaults]
        hit = next((c for c in cands if _executable(c)), None)
        if not hit:
            continue
        real = os.path.realpath(hit)
        done.add(real)
        r = root_of(real, roots)
        if r:
            out.append(_item('ai-tool', r, label, probe.show(hit),
                             f'{label} 装在旧的 {LABELS[r.tool]}（{r.shown}）里面，卸掉旧的它就跟着没了',
                             f'卸之前先照 {label} 官方的装法重装一份（它不归工具包管，4.3）；没重装好之前先留着旧的', command=command))
            continue
        kind, interp = runtime(real)
        if kind == 'interp':
            ir = root_of(interp, roots)
            if ir:
                out.append(_item('ai-tool', ir, label, probe.show(hit),
                                 f'{label} 第一行写死了用旧的 {LABELS[ir.tool]} 里的 {probe.show(interp)} 运行，卸掉旧的它就打不开',
                                 f'卸之前先照 {label} 官方的装法重装一份', command=command))
            continue
        if kind not in ('node-env', 'launcher') or not old_node:
            continue
        own = [p for p in PRIVATE_NODE.get(name, ()) if _executable(locate.expand(p, probe.home))]
        if own:
            continue
        node, nr = old_node
        how = '看启动脚本认出来的' if kind == 'launcher' else '第一行是 #!/usr/bin/env node'
        out.append(_item('ai-tool', nr, label, probe.show(hit),
                         f'{label} 靠 Node 运行（{how}），用的是终端里找到的 Node；现在找到的是旧的 {probe.show(node)}，'
                         f'卸掉旧的之后，终端里要有规定位置那份 Node 它才能运行',
                         f'卸之前新开一个终端，确认 node 是 ~/tools/nvm 里的那份（M2 装好、终端启动文件里旧的几行删掉之后就是），'
                         f'再打开一次 {label} 试试，能用了再卸', node=probe.show(node), how=kind, command=command))
    return out


# ---------- 别的命令 ----------

def _command_dirs(probe, roots):
    path = os.environ.get('PATH', '') if probe.path_env is None else probe.path_env
    dirs = [probe.h('.local/bin'), probe.h('bin')]
    dirs += [d for d in path.split(os.pathsep) if d and _under(d, probe.home)]
    dirs += [probe.p(d) for d in SYSTEM_BIN]
    out = []
    for d in dirs:
        d = d.rstrip('/')
        if d in out or not os.path.isdir(d) or root_of(d, roots) or _under(os.path.realpath(d), probe.tools):
            continue
        out.append(d)
    return out


def commands(probe, roots, done, uv_tools):
    """命令目录里指向旧的、要旧的才能运行的命令。指向旧 uv 装的命令（uv tool）的，记到 uv_tools 里那一条下面。"""
    out = []
    old_node = _node_note(probe, roots)
    for d in _command_dirs(probe, roots):
        for name in _listdir(d):
            p = os.path.join(d, name)
            if not os.path.lexists(p) or os.path.isdir(p):
                continue
            real = os.path.realpath(p)
            if real in done or any(r.path == p or r.alias == p for r in roots):
                continue
            done.add(real)
            r = root_of(real, roots)
            if r:
                tool_dir = next((k for k in uv_tools if _under(real, k)), None)
                if tool_dir:
                    uv_tools[tool_dir].append(probe.show(p))
                    continue
                out.append(_item('command', r, name, probe.show(p),
                                 f'这个命令指向旧的 {LABELS[r.tool]} 里面的 {probe.show(real)}，卸掉旧的它就失效',
                                 '还要用就在规定位置那份里重装；不用了可以一起删'))
                continue
            if not _executable(real):
                continue
            kind, interp = runtime(real)
            if kind in ('interp', 'script'):
                ir = root_of(interp, roots) if interp.startswith('/') else None
                if ir:
                    out.append(_item('command', ir, name, probe.show(p),
                                     f'它第一行写死了用旧的 {LABELS[ir.tool]} 里的 {probe.show(interp)} 运行，卸掉旧的它就打不开',
                                     '还要用就用规定位置那份重装它'))
            elif kind in ('node-env', 'launcher') and old_node:
                node, nr = old_node
                out.append(_item('command', nr, name, probe.show(p),
                                 f'靠 Node 运行，用的是终端里找到的 Node；现在找到的是旧的 {probe.show(node)}',
                                 '卸之前新开一个终端，确认 node 是 ~/tools/nvm 里的那份，再试一次这个命令', node=probe.show(node)))
    return out


# ---------- 旧的里面装着的 ----------

def _bins(pkg_dir, pkg):
    """包的 package.json 里写的命令名；读不出、坏了就是 []。"""
    try:
        meta = json.loads(_read(os.path.join(pkg_dir, 'package.json')) or 'null')
    except ValueError:
        return []
    b = meta.get('bin') if isinstance(meta, dict) else None
    if isinstance(b, dict):
        return sorted(b)
    return [pkg.split('/')[-1]] if isinstance(b, str) else []


def _packages(mods):
    """node_modules 目录里的包：[(包名, [命令名])]。带 @ 的是一组（@openai/codex 这种）。"""
    out = []
    for n in _listdir(mods):
        if n.startswith('.'):
            continue
        names = [f'{n}/{s}' for s in _listdir(os.path.join(mods, n)) if not s.startswith('.')] if n.startswith('@') else [n]
        out += [(pkg, _bins(os.path.join(mods, pkg), pkg)) for pkg in names]
    return out


def _global_item(root, pkg, bins, where, owner):
    cmd = f'（命令 {"、".join(bins)}）' if bins else ''
    fix = '规定位置那份 M2 会装，不用管' if pkg == 'pnpm' else '还要用就在规定位置那份里重装；不用了不用管'
    return _item('global', root, pkg + cmd, where, f'{owner}全局装的，卸掉旧的就没了', fix, commands=bins, package=pkg)


def contents(probe, roots):
    """旧的里面装着的东西。返回 (清单, {旧 uv 装的命令的目录: [指向它的命令]})。"""
    out, uv_tools = [], {}
    for r in roots:
        if r.tool == 'nvm' and os.path.isdir(r.path):
            vdir = os.path.join(r.path, 'versions', 'node')
            default = (_read(os.path.join(r.path, 'alias', 'default')) or '').strip().lstrip('v')
            for v in _listdir(vdir):
                if not v.startswith('v'):
                    continue
                is_default = bool(default) and (v[1:] == default or v[1:].startswith(default + '.'))
                out.append(_item('node-version', r, f'Node {v}', probe.show(os.path.join(vdir, v)),
                                 ('旧的 nvm 里默认用的就是它，' if is_default else '旧的 nvm 里装着的，') + '卸掉旧的就没了',
                                 '规定位置那份 nvm 里有默认的一份（M2 装的）；项目要用别的版本时按项目的 .nvmrc 在新的里装',
                                 version=v, default=is_default))
                mods = os.path.join(vdir, v, 'lib', 'node_modules')
                for pkg, bins in _packages(mods):
                    if pkg not in NODE_BUILTIN:
                        out.append(_global_item(r, pkg, bins, probe.show(os.path.join(mods, pkg)),
                                                f'用旧的 nvm 里的 Node {v} '))
        elif r.tool == 'pnpm' and os.path.isdir(r.path):
            gdir = os.path.join(r.path, 'global')
            for g in _listdir(gdir):
                mods = os.path.join(gdir, g, 'node_modules')
                for pkg, bins in _packages(mods):
                    out.append(_global_item(r, pkg, bins, probe.show(os.path.join(mods, pkg)), '用旧的 pnpm '))
        elif r.role == 'node-globals':
            for pkg, bins in _packages(r.path):
                if pkg not in NODE_BUILTIN:
                    out.append(_global_item(r, pkg, bins, probe.show(os.path.join(r.path, pkg)), '用旧的 Node '))
        elif r.tool == 'uv' and os.path.isdir(r.path):
            pdir = os.path.join(r.path, 'python')
            for py in _listdir(pdir):
                if py.startswith('.') or not os.path.isdir(os.path.join(pdir, py)):
                    continue
                m = re.match(r'(\w+)-(\d+\.\d+[\w.+]*)-', py)
                out.append(_item('python', r, f'Python {m[2]}' if m else py, probe.show(os.path.join(pdir, py)),
                                 '旧的 uv 装的 Python，卸掉旧的就没了；用它建的 Python 环境也跟着用不了（下面列出来了）',
                                 '规定位置那份 uv 会按项目的 .python-version 自己装要的版本'))
            tdir = os.path.join(r.path, 'tools')
            for t in _listdir(tdir):
                if not t.startswith('.') and os.path.isdir(os.path.join(tdir, t)):
                    uv_tools[os.path.join(tdir, t)] = []
    return out, uv_tools


def uv_tool_items(probe, roots, uv_tools):
    out = []
    for d, cmds in uv_tools.items():
        r = root_of(d, roots)
        name = os.path.basename(d)
        cmd = f'（命令 {"、".join(cmds)}）' if cmds else ''
        out.append(_item('uv-tool', r, name + cmd, probe.show(d), '用旧的 uv 装的命令，卸掉旧的就没了',
                         f'还要用就用规定位置那份 uv 重装：uv tool install {name}', commands=cmds, name=name))
    return out


# ---------- Python 环境 ----------

def _venv_cfg(text):
    cfg = {}
    for line in (text or '').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            cfg[k.strip().lower()] = v.strip()
    return cfg


def venvs(probe, roots, max_depth=MAX_DEPTH, max_dirs=MAX_DIRS):
    """在主目录里找 Python 环境（有 pyvenv.cfg 的目录），挑出记着的 Python 在旧的里面的。返回 (清单, 看了几个目录, 找没找全)。"""
    skip = {r.path for r in roots} | {r.alias for r in roots} | {f'{probe.tools}/{x}' for x in SKIP_TOOLS}
    try:
        dev = os.stat(probe.home).st_dev
    except OSError:
        return [], 0, False
    out, seen, partial = [], 0, False
    stack = [(probe.home, 0)]
    while stack:
        d, depth = stack.pop()
        seen += 1
        if seen > max_dirs:
            partial = True
            break
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        if any(e.name == 'pyvenv.cfg' and e.is_file(follow_symlinks=False) for e in entries):
            hit = _check_venv(probe, roots, d)
            if hit:
                out.append(hit)
            continue                          # Python 环境里面不再往下找
        if depth >= max_depth:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False) or e.name in SKIP_NAMES or e.path in skip:
                    continue
                if e.stat(follow_symlinks=False).st_dev != dev:
                    continue
            except OSError:
                continue
            stack.append((e.path, depth + 1))
    out.sort(key=lambda x: x['where'])
    return out, seen, partial


def _check_venv(probe, roots, d):
    cfg = _venv_cfg(_read(os.path.join(d, 'pyvenv.cfg')))
    py = os.path.join(d, 'bin', 'python')
    cands = [cfg.get('home'), cfg.get('executable'), os.readlink(py) if os.path.islink(py) else None,
             os.path.realpath(py) if os.path.lexists(py) else None]
    for c in cands:
        if c and not c.startswith('/'):
            c = os.path.join(d, 'bin', c)
        r = root_of(c, roots) if c else None
        if r:
            ver = cfg.get('version_info') or cfg.get('version') or ''
            return _item('venv', r, probe.show(d), probe.show(d),
                         f'这个 Python 环境用的是旧的 {LABELS[r.tool]} 里的 Python{(" " + ver) if ver else ""}'
                         f'（{probe.show(c)}），卸掉旧的它就用不了',
                         '卸之后在它所在的项目里重建：删掉这个目录，再用规定位置那份 uv 装一遍依赖（用 uv 管的项目就是 uv sync）',
                         python=probe.show(c), version=ver, made_by_uv=cfg.get('uv', ''))
    return None


# ---------- 终端启动文件、后台服务 ----------

_TILDE = re.compile(r'(?<![\w/~.-])~(?=/)')


def _normalize(line, home, systemd=False):
    s = line.replace('${HOME}', home).replace('$HOME', home)
    if systemd:
        s = s.replace('%h', home)
    return _TILDE.sub(home, s)


def _root_in_text(text, roots):
    for r in roots:
        for p in dict.fromkeys((r.alias, r.path)):
            if re.search(re.escape(p.rstrip('/')) + r'(?![\w.-])', text):
                return r
    return None


def _path_dir_others(probe, root, roots):
    """uv 安装程序放的 env 把它所在的目录放进 PATH：那个目录里还有别的命令（不是旧的）时，返回它们的名字。"""
    if root.role != 'companion' or os.path.basename(root.path) not in ('env', 'env.fish'):
        return []
    d = os.path.dirname(root.path)
    return [n for n in _listdir(d) if not root_of(os.path.join(d, n), roots) and _executable(os.path.join(d, n))]


def shell_lines(probe, roots):
    files = [probe.h(f) for f in SHELL_FILES]
    conf_d = probe.h('.config/fish/conf.d')
    files += [os.path.join(conf_d, f) for f in _listdir(conf_d) if f.endswith('.fish')]
    nvms = [r for r in roots if r.tool == 'nvm']
    out = []
    for f in files:
        text = _read(f) if os.path.isfile(f) else None
        if not text:
            continue
        inside = False
        lines = text.splitlines()
        # 这个文件自己把 NVM_DIR 指到哪：指着规定位置的，后面用 $NVM_DIR 的几行就不算旧的
        assigns = [_normalize(m[1], probe.home) for m in
                   (re.match(r'\s*(?:export\s+)?NVM_DIR=["\']?([^"\';\s]+)', ln) for ln in lines) if m]
        nvm_old = next((r for a in assigns for r in nvms if _under(a, r.alias) or _under(a, r.path)), None)
        if nvm_old is None and nvms and not assigns:
            nvm_old = nvms[0]
        for n, line in enumerate(lines, 1):
            s = line.strip()
            if s == shellenv.BEGIN:
                inside = True
                continue
            if s == shellenv.END:
                inside = False
                continue
            if inside or not s or s.startswith('#'):
                continue
            r = _root_in_text(_normalize(line, probe.home), roots)
            if r is None and nvm_old and re.search(r'\$\{?NVM_DIR\b', line):
                r = nvm_old
            if r is None:
                continue
            others = _path_dir_others(probe, r, roots)
            if others:
                d = probe.show(os.path.dirname(r.path))
                effect = (f'这一行是 uv 的安装程序加的，作用是把 {d} 放进 PATH；那里还有 {"、".join(others)}，'
                          f'删了这一行终端里就找不到它们')
                fix = f'卸旧 uv 时这一行和 {r.shown} 都留着（或者换成只把 {d} 放进 PATH 的一行）'
            else:
                effect = f'指向旧的 {LABELS[r.tool]}（{r.shown}）'
                fix = '卸旧的时把这一行一起删掉；只删目录不删这一行，新开的终端可能报找不到文件'
            out.append(_item('shell', r, f'{probe.show(f)} 第 {n} 行', probe.show(f), effect, fix, line=s, line_no=n,
                             keeps=others))
    return out


def services(probe, roots):
    out = []
    for rel, exts in SERVICE_DIRS:
        d = probe.h(rel)
        for name in _listdir(d):
            f = os.path.join(d, name)
            if not name.endswith(exts) or not os.path.isfile(f):
                continue
            text = _read(f) or ''
            r = _root_in_text(_normalize(text, probe.home, systemd=True), roots)
            if r:
                what = '用户级后台服务' if rel.startswith('.config/systemd') else '开机自启' if 'autostart' in rel else '桌面图标'
                out.append(_item('service', r, f'{what} {name}', probe.show(f),
                                 f'登记文件里写着旧的 {LABELS[r.tool]}（{r.shown}）里的东西，卸掉旧的它就起不来',
                                 '卸之前把它改成用规定位置那份（重装那个软件，或者照它的说明改登记文件）'))
    return out


# ---------- 整份 ----------

def find(probe, tools):
    """清点 tools 那一部分接着看「谁还在用旧的」。旧的 nvm、uv、Node、pnpm 一样都没有时什么都不找。"""
    roots = old_roots(probe, tools)
    res = {'old': [{'tool': r.tool, 'path': r.shown} for r in roots if r.role != 'companion'], 'items': [],
           'scanned_dirs': 0, 'scan_partial': False}
    if not roots:
        return res
    done = set()
    items, uv_tools = contents(probe, roots)
    items = ai_tools(probe, roots, done) + commands(probe, roots, done, uv_tools) + items
    items += uv_tool_items(probe, roots, uv_tools)
    vs, res['scanned_dirs'], res['scan_partial'] = venvs(probe, roots)
    items += vs + shell_lines(probe, roots) + services(probe, roots)
    order = {k: i for i, (k, _) in enumerate(KIND_TITLES)}
    res['items'] = sorted(items, key=lambda x: order[x['kind']])
    return res


def describe(res, home_note='主目录'):
    """给人看的几行（接在清点的「别的工具」后面）。"""
    if not res or not res.get('old'):
        return []
    olds = '、'.join(f'{o["path"]}（{LABELS[o["tool"]]}）' for o in res['old'])
    L = ['', f'谁还在用旧的 nvm、uv、Node（旧的在 {olds}；卸掉之前逐条看）：']
    items = res.get('items') or []
    if not items:
        L.append('  没发现还有谁在用。')
    for kind, title in KIND_TITLES:
        group = [i for i in items if i['kind'] == kind]
        if not group:
            continue
        L.append(f'  {title}：')
        for i in group:
            where = '' if i['where'] in i['what'] else f'，在 {i["where"]}' if i['what'].endswith('）') else f'（{i["where"]}）'
            L.append(f'    {i["what"]}{where}：{i["effect"]}。怎么办：{i["fix"]}')
            if i.get('line'):
                L.append(f'      那一行：{i["line"]}')
    tail = '（没找全：目录太多，只看了前面的）' if res.get('scan_partial') else ''
    L.append(f'  Python 环境是在{home_note}里找的：看了 {res.get("scanned_dirs", 0)} 个目录，最深 {MAX_DEPTH} 层，'
             f'跳过 node_modules、.git、缓存和工具目录{tail}。')
    return L
