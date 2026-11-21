"""M7 安装全局规则（设计书 4.5、4.8，任务 3-11）。

往各 AI 工具的全局规则文件里写一段带开头结尾标记的受管段落，内容是 machine/global-rules.md（只含包管理、Docker 的
机器级规则，写明环境迁移是例外；与流程有关的规则都在项目的 AGENTS.md 里，随项目声明的版本走）。

规矩和终端启动文件那一段一样（shellenv.apply）：
- 段落外的字一个不动：已经有这一段就原地换掉，没有就加在文件末尾；开头结尾标记对不上（只剩一头、有两段）就不改，明说。
- 内容没变不写（修改时间也不动）；文件是链接（管点文件的工具常这么做）就写到它指的那个文件；权限照原来的。
- 先写临时文件再换名。文件没有就新建（所在目录没有就建成只有用户自己能进的）。

各工具的全局规则文件（官方文档，2026-11-19 经网页摘要工具读的，没有在真工具上逐个试）：
- Claude Code：~/.claude/CLAUDE.md（设了 CLAUDE_CONFIG_DIR 就在那个目录下）
- Codex：~/.codex/AGENTS.md（设了 CODEX_HOME 就在那下面）。同一个目录里有不是空的 AGENTS.override.md 时 Codex 只读那一份，
  所以那一份里也写上这一段
- OpenCode：~/.config/opencode/AGENTS.md（XDG_CONFIG_HOME）。它自己的这一份不存在时，OpenCode 读 ~/.claude/CLAUDE.md；
  一旦新建了它自己的，就不再读 ~/.claude/CLAUDE.md，用户原来写在那里的规则对 OpenCode 就不生效了。
  所以它自己的这一份不存在时不新建，靠 ~/.claude/CLAUDE.md 里那一段（出口检查照样核对那一段）
- Pi：~/.pi/agent/AGENTS.md（设了 PI_CODING_AGENT_DIR 就在那下面）

只读写这几个规则文件，不碰各工具的设置、密钥、会话记录。
出口检查（check）：每个工具实际会读到的那一份里，有且只有一段，和工具包里的一字不差。

直接跑（3-12 的 setup 做好之前，虚拟机验证用）：python3 -m machine.globalrules [--check]
"""
import dataclasses
import os
import pathlib
import sys

from kernel import paths

from .shellenv import ShellEnvError, apply, read_text, write_text

SOURCE = pathlib.Path(__file__).resolve().parent / 'global-rules.md'
BEGIN = '<!-- >>> SOP 工具包管理的段落（不要手改，重新安装时会被换回来）>>> -->'
END = '<!-- <<< SOP 工具包管理的段落 <<< -->'
WHAT = '全局规则文件'


def block():
    """受管段落的全文（带开头结尾标记，最后有换行）。"""
    body = SOURCE.read_text(encoding='utf-8').rstrip('\n')
    return f'{BEGIN}\n{body}\n{END}\n'


def _home():
    return pathlib.Path.home()


def _env_dir(var, default):
    v = os.environ.get(var)
    return pathlib.Path(v).expanduser() if v else default


@dataclasses.dataclass
class Target:
    tool: str            # 给人看的名字
    path: pathlib.Path   # 规则文件
    create: bool = True  # 没有这个文件时新建
    via: str = ''        # 不新建时，这个工具改读哪个文件（给人看）


def targets():
    """各工具要写的规则文件，按 Claude Code、Codex、OpenCode、Pi 的先后。路径按现在的环境变量算。"""
    home = _home()
    claude = _env_dir('CLAUDE_CONFIG_DIR', home / '.claude') / 'CLAUDE.md'
    codex_home = _env_dir('CODEX_HOME', home / '.codex')
    opencode = _env_dir('XDG_CONFIG_HOME', home / '.config') / 'opencode' / 'AGENTS.md'
    pi = _env_dir('PI_CODING_AGENT_DIR', home / '.pi' / 'agent') / 'AGENTS.md'
    out = [Target('Claude Code', claude), Target('Codex', codex_home / 'AGENTS.md')]
    override = codex_home / 'AGENTS.override.md'
    if _nonempty(override):
        out.append(Target('Codex（AGENTS.override.md，Codex 现在读的是这一份）', override, create=False))
    # OpenCode 的退路认的是 ~/.claude/CLAUDE.md 这个固定位置；Claude Code 的规则文件被 CLAUDE_CONFIG_DIR 挪走了时，
    # 退路里没有这一段，那就给 OpenCode 新建它自己的
    fallback = home / '.claude' / 'CLAUDE.md'
    out.append(Target('OpenCode', opencode, create=False, via=str(fallback)) if fallback == claude else Target('OpenCode', opencode))
    out.append(Target('Pi', pi))
    return out


def _nonempty(p):
    """文件在、里面不只是空白。"""
    try:
        return bool(pathlib.Path(p).read_text(encoding='utf-8', errors='replace').strip())
    except OSError:
        return False


def _short(p):
    s, h = str(p), str(_home())
    return '~' + s[len(h):] if s == h or s.startswith(h + '/') else s


def install_one(path, text_block=None):
    """往一个文件里写这一段。返回改没改。标记对不上、不是 UTF-8 就报错（ShellEnvError），文件不动。"""
    path = pathlib.Path(path)
    target = pathlib.Path(os.path.realpath(path))
    text, mode = read_text(target, WHAT)
    new = apply(text, text_block or block(), BEGIN, END, WHAT)
    if new == text:
        return False
    missing = []
    d = target.parent
    while not d.exists():
        missing.append(d)
        d = d.parent
    for d in reversed(missing):                 # 新建的每一层都只有用户自己能进（mkdir 的 parents 不管中间几层的权限）
        d.mkdir()
        os.chmod(d, 0o700)
    write_text(target, new, mode)
    return True


def state_of(path, text_block=None):
    """一个文件里这一段的状态：ok 一字不差；missing 没有这个文件或没有这一段；stale 有、但和工具包里的不一样；
    broken 标记对不上；unreadable 读不了或不是 UTF-8。"""
    target = pathlib.Path(os.path.realpath(path))
    try:
        text, _ = read_text(target, WHAT)
    except (ShellEnvError, OSError):
        return 'unreadable'
    b = text_block or block()
    lines = text.splitlines()
    nb, ne = lines.count(BEGIN), lines.count(END)
    if nb == 0 and ne == 0:
        return 'missing'
    if nb != 1 or ne != 1 or lines.index(BEGIN) > lines.index(END):
        return 'broken'
    i, j = lines.index(BEGIN), lines.index(END)
    return 'ok' if '\n'.join(lines[i:j + 1]) + '\n' == b else 'stale'


def install(out=print):
    """M7：往各工具的全局规则文件里写这一段。返回 (都成没有, [大白话])。一个文件不成不影响别的文件。"""
    paths.guard_home('安装全局规则（M7）')
    b = block()
    ok, msgs = True, []
    for t in targets():
        where = _short(t.path)
        if not t.create and not os.path.lexists(t.path):
            msgs.append(f'{t.tool}：它自己的 {where} 不存在，它读的是 {_short(t.via)}，规矩在那里面（不新建，免得它不再读那一份）'
                        if t.via else f'{t.tool}：{where} 不存在，不用写')
            continue
        try:
            changed = install_one(t.path, b)
        except (ShellEnvError, OSError) as e:
            ok = False
            msgs.append(f'{t.tool}：{where} 没有改：{getattr(e, "strerror", None) or e}')
            continue
        msgs.append(f'{t.tool}：{where} 里工具包那一段{"写好了" if changed else "本来就是最新的，没改"}')
    for m in msgs:
        out(m)
    return ok, msgs


STATE_TEXT = {
    'missing': '没有工具包那一段',
    'stale': '工具包那一段和工具包里的不一样（被手改过，或者工具包升级了）',
    'broken': '工具包那一段的开头、结尾标记对不上',
    'unreadable': '读不了，或者不是 UTF-8 的文字',
}


def check():
    """出口检查：每个工具实际会读到的那一份里，这一段和工具包里的一字不差。返回 (都合格没有, [(工具, 文件, 状态)])。"""
    b = block()
    rows = []
    for t in targets():
        p = t.path
        if not t.create and not os.path.lexists(p):
            if not t.via:
                continue
            p = pathlib.Path(t.via)
        rows.append((t.tool, p, state_of(p, b)))
    return all(s == 'ok' for _, _, s in rows), rows


def main(argv):
    if argv == ['--check']:
        ok, rows = check()
        for tool, p, s in rows:
            print(f'{"合格  " if s == "ok" else "不合格"} {tool}：{_short(p)}' + ('' if s == 'ok' else f'（{STATE_TEXT[s]}）'))
        print('全局规则：合格' if ok else '全局规则：不合格，重新执行一次安装（M7）')
        return 0 if ok else 1
    if argv:
        print('用法：python3 -m machine.globalrules [--check]')
        return 2
    ok, _ = install()
    ok2, rows = check()
    bad = [f'{tool}：{_short(p)}（{STATE_TEXT[s]}）' for tool, p, s in rows if s != 'ok']
    print('全局规则装好了，出口检查合格' if ok and ok2 else '全局规则没装好：' + '；'.join(bad))
    return 0 if ok and ok2 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
