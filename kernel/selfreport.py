"""sop self report（3-42，设计书 16.5 第 1 条、17.1）：把工具包自己的问题打成一份问题单，登记到工具包仓库。

    sop self report [--text <一句话说明>] [--log <日志文件>]… [--yes]
    sop self report --send <草稿文件> [--yes]

1. 收集：现象（小白自己的一句话；在项目里时，本机事件日志里最近记下的「工具包问题」和停下来的步骤、运行日志里最近的报错）、
   工具包版本（正在运行的这一份的提交编号、改没改过；项目主线 sop.json 声明的）、电脑的几样版本、--log 给的日志（只取最后一段）。
2. 去掉密钥和个人信息（kernel/redact.py）：问题单登记在公开的工具包仓库上，谁都看得到。
3. 草稿存在 ~/tools/sop/reports/<时间>.md（只有自己能读），给小白看抹掉了几处、草稿在哪，问一句再登记。
   不在终端里（例如维修窗口替小白执行）又没加 --yes 时只存草稿，不登记：说清看过之后怎么登记。
4. 登记：gh issue create（小白自己的 gh 登录），登记之前把草稿再抹一遍（小白可能改过草稿）。登记过的草稿记一个 .sent.json，
   不重复登记。

工具包仓库：环境变量 SOP_REPORT_REPO（只给自测用，写成「所有者/仓库名」）→ 在项目里时主线 sop.json 的 toolkit.repo →
SOP_TOOLKIT_REPO → 默认的公开仓库（kernel/projectnew.DEFAULT_REPO）。不是 GitHub 上的仓库就登记不了，只存草稿。
"""
import datetime
import json
import os
import pathlib
import platform
import re
import subprocess
import sys

from . import paths, redact
from .errors import SopError
from .project import TOOLKIT

MAX_BODY = 60000          # GitHub 问题单正文最多 65536 个字，留点余地
ERR_FILES, ERR_TAIL = 3, 4000
LOG_FILES, LOG_TAIL = 5, 8000
READ_AT_MOST = 1 << 20     # 一个日志文件最多读最后 1 MB（先抹再截，截断不会把密钥切成半截漏出去）
EVENTS = 10

USAGE = ('用法：sop self report [--text <一句话说明>] [--log <日志文件>]… [--yes]\n'
         '      sop self report --send <草稿文件> [--yes]')


def reports_dir():
    return paths.sop_home() / 'reports'


# ---------- 工具包仓库 ----------
def github_slug(url):
    m = re.search(r'github\.com[:/]+([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$', url or '')
    return f'{m.group(1)}/{m.group(2)}' if m else None


def toolkit_repo(p=None):
    """(所有者/仓库名 或 None, 仓库地址)。"""
    if os.environ.get('SOP_REPORT_REPO'):
        return os.environ['SOP_REPORT_REPO'], os.environ['SOP_REPORT_REPO']
    url = None
    if p is not None:
        try:
            url = (p.sop_json(fetch=False).get('toolkit') or {}).get('repo')
        except Exception:     # noqa: BLE001  主线还没有 sop.json：按下面的
            url = None
    if not url:
        from .projectnew import DEFAULT_REPO
        url = os.environ.get('SOP_TOOLKIT_REPO') or DEFAULT_REPO
    return github_slug(url), url


# ---------- 收集 ----------
def _run(*args, cwd=None):
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, timeout=20, cwd=cwd, stdin=subprocess.DEVNULL,
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GH_NO_UPDATE_NOTIFIER': '1', 'GH_PROMPT_DISABLED': '1'})
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    return p.returncode, (p.stdout or p.stderr or '').strip()


def toolkit_version(toolkit=TOOLKIT):
    rc, head = _run('git', '-C', str(toolkit), 'rev-parse', 'HEAD')
    if rc != 0:
        return [f'正在运行的：看不出提交编号（{toolkit} 不是 Git 仓库）']
    _, dirty = _run('git', '-C', str(toolkit), 'status', '--porcelain', '--untracked-files=no')
    where = '装好的版本' if pathlib.Path(toolkit).parent == paths.versions_dir() else '开发目录或测试，不是装好的版本'
    lines = [f'正在运行的：`{head}`（{where}{"；有没提交的改动" if dirty else ""}）', f'位置：`{toolkit}`']
    return lines


def machine_info():
    pretty = ''
    try:
        for line in pathlib.Path('/etc/os-release').read_text().splitlines():
            if line.startswith('PRETTY_NAME='):
                pretty = line.split('=', 1)[1].strip('"')
    except OSError:
        pass
    out = [f'系统：{pretty or "看不出"}；内核 {platform.release()}；{platform.machine()}', f'Python：{sys.version.split()[0]}']
    for name, args in (('Git', ['git', '--version']), ('gh', ['gh', '--version']), ('bubblewrap', ['bwrap', '--version'])):
        rc, text = _run(*args)
        out.append(f'{name}：{text.splitlines()[0] if rc == 0 and text else "没有或看不出"}')
    return out


def tail(text, n):
    """最后 n 个字，从整行开始。"""
    if len(text) <= n:
        return text
    cut = text[-n:]
    i = cut.find('\n')
    return '……（前面省略）\n' + (cut[i + 1:] if 0 <= i < len(cut) - 1 else cut)


def read_tail(path):
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - READ_AT_MOST))
        data = f.read()
    text = data.decode('utf-8', errors='replace')
    if size > READ_AT_MOST:
        i = text.find('\n')
        text = text[i + 1:] if i >= 0 else text
    return text


def project_part(p):
    """(项目信息几行, 事件几行, [(名字, 报错原文)])。只读本机，不联网。"""
    info, events, errors = [f'项目：{p.name}'], [], []
    try:
        sop = p.sop_json(fetch=False)
        info.append(f'项目主线 sop.json 声明的工具包版本：`{(sop.get("toolkit") or {}).get("version", "没写")}`')
        info.append(f'项目仓库：{"公开" if sop.get("visibility") == "public" else "私有或没写"}')
    except Exception as e:     # noqa: BLE001
        info.append(f'项目主线 sop.json：读不出（{type(e).__name__}）')
    try:
        tip = p.journal.tip()
        if tip:
            dirs = sorted({'/'.join(x.split('/')[1:3]) for x in p.git('ls-tree', '-r', '--name-only', tip, 'events/').splitlines()})
            evs = p.journal.read(dirs or ['project'], fetch=False)
            pick = [e for e in evs if e.get('type') == 'failed' or (e.get('type') == 'note' and e.get('kind') == '工具包问题')]
            for e in pick[-EVENTS:]:
                e = {k: v for k, v in e.items() if not k.startswith('_')}
                events.append(json.dumps(e, ensure_ascii=False)[:1500])
    except Exception as e:     # noqa: BLE001
        events.append(f'（读不出本机的事件日志：{type(e).__name__}）')
    runs = p.state / 'runs'
    files = sorted(runs.glob('error-*.txt'), key=lambda f: f.stat().st_mtime, reverse=True)[:ERR_FILES] if runs.is_dir() else []
    for f in files:
        errors.append((f.name, read_tail(f)))
    return info, events, errors


def fence(text):
    longest = max((len(m) for m in re.findall(r'`+', text)), default=0)
    return '`' * max(3, longest + 1)


def block(text):
    f = fence(text)
    return f'{f}\n{text.rstrip()}\n{f}'


def build(text='', logs=(), p=None, r=None):
    """返回 (标题, 正文, {类别: 处数})。正文已经抹过。"""
    r = r or redact.for_this_machine(paths.config_dir(), projects=private_names(p))
    counts = {}

    def clean(s):
        s, c = r.apply(s)
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v
        return s

    info = events = errors = None
    if p is not None:
        info, events, errors = project_part(p)
    first = (text or '').strip().splitlines()[0] if (text or '').strip() else ''
    if not first and errors:
        last = [x for x in errors[0][1].strip().splitlines() if x.strip()]
        first = last[-1] if last else ''
    if not first and events:
        first = '流程停下了（见事件）'
    title = clean(f'sop self report：{first or "工具包的问题（没写现象）"}')[:120]

    parts = ['<!-- 由 sop self report 生成。登记之前已经自动抹掉了密钥和个人信息（见文末），小白看过。 -->', '',
             '## 现象', '', clean(text.strip()) if (text or '').strip() else '（小白没写）', '',
             '## 工具包版本', '', *[f'- {clean(x)}' for x in toolkit_version()]]
    if info:
        parts += [*[f'- {clean(x)}' for x in info]]
    parts += ['', '## 电脑', '', *[f'- {clean(x)}' for x in machine_info()]]
    if events:
        parts += ['', f'## 本机事件日志里最近记下的问题（最多 {EVENTS} 条）', '', block(clean('\n'.join(events)))]
    if errors:
        parts += ['', f'## 运行日志里最近的报错（最多 {ERR_FILES} 份，每份最后 {ERR_TAIL} 个字）']
        for name, body in errors:
            parts += ['', f'### {clean(name)}', '', block(tail(clean(body), ERR_TAIL))]
    if logs:
        parts += ['', f'## 附上的日志（每份最后 {LOG_TAIL} 个字）']
        for name, body in logs:
            parts += ['', f'### {clean(name)}', '', block(tail(clean(body), LOG_TAIL))]
    body = '\n'.join(parts) + '\n'
    body = clean(body)            # 整份再抹一遍（跨段的、标题里的）；抹过的再抹不会变
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + '\n\n……（太长，后面省略）\n'
    body += '\n## 自动抹掉的\n\n' + summary(counts) + '\n'
    return title, body, counts


def summary(counts):
    if not counts:
        return '- 没有认出要抹的东西'
    return '\n'.join(f'- {k}：{v} 处' for k, v in counts.items())


def private_names(p):
    """私有项目的名字也抹掉（公开项目的名字本来就公开）。"""
    if p is None:
        return ()
    try:
        if p.sop_json(fetch=False).get('visibility') == 'public':
            return ()
    except Exception:     # noqa: BLE001
        pass
    return (p.name,)


# ---------- 草稿 ----------
TITLE_PREFIX = '标题：'


def save_draft(title, body):
    d = reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    f = d / f'{stamp}.md'
    n = 1
    while f.exists():
        n += 1
        f = d / f'{stamp}-{n}.md'
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(f'{TITLE_PREFIX}{title}\n\n{body}')
    return f


def read_draft(f):
    text = pathlib.Path(f).read_text(encoding='utf-8')
    head, _, body = text.partition('\n')
    if not head.startswith(TITLE_PREFIX):
        raise SopError(f'{f} 不是 sop self report 的草稿（第一行要是「{TITLE_PREFIX}…」）')
    return head[len(TITLE_PREFIX):].strip(), body.lstrip('\n')


def sent_file(f):
    return pathlib.Path(f).with_name(pathlib.Path(f).name + '.sent.json')


# ---------- 登记 ----------
def send(draft, slug, *, yes, ask, say, tty, r=None):
    draft = pathlib.Path(draft)
    if not draft.is_file():
        raise SopError(f'找不到草稿 {draft}')
    sf = sent_file(draft)
    if sf.exists():
        raise SopError(f'这份草稿已经登记过了：{json.loads(sf.read_text()).get("url", "")}')
    if not slug:
        raise SopError(f'工具包仓库不在 GitHub 上，登记不了。草稿在 {draft}，可以自己发给维护工具包的人')
    title, body = read_draft(draft)
    r = r or redact.for_this_machine(paths.config_dir())
    t2, c1 = r.apply(title)
    b2, c2 = r.apply(body)
    more = sum(c1.values()) + sum(c2.values())
    if more:      # 小白改草稿时加进来的，或者第一次没抹到的（例如那之后才登记的密钥）
        draft.write_text(f'{TITLE_PREFIX}{t2}\n\n{b2}', encoding='utf-8')
        say(f'登记之前又抹掉了 {more} 处，已经改进草稿 {draft}')
        title, body = t2, b2
    if not yes:
        if not tty:
            say(f'没有登记：要先给你看过。看过草稿 {draft} 之后执行：sop self report --send {draft} --yes')
            return 0
        ans = ask(f'确认把这份问题单登记到 GitHub 上公开的 {slug} 吗？任何人都看得到。要登记输入 y，不登记直接回车：')
        if (ans or '').strip().lower() not in ('y', 'yes', '是'):
            say(f'没有登记。草稿留在 {draft}，想登记时执行：sop self report --send {draft}')
            return 0
    if len(body) > 65536:
        raise SopError(f'草稿正文太长（{len(body)} 个字，GitHub 最多 65536 个字），删掉一些日志再登记')
    from .projectgh import gh
    p = gh('issue', 'create', '--repo', slug, '--title', title, '--body-file', '-', input=body, what='登记问题单')
    url = (p.stdout.strip().splitlines() or [''])[-1]
    fd = os.open(sf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'url': url, 'repo': slug, 'time': datetime.datetime.now().isoformat(timespec='seconds')},
                            ensure_ascii=False) + '\n')
    say(f'问题单登记好了：{url}')
    say('修好之前项目先怎么办：可以等修好再接着做；修好后用 sop self upgrade 换上新版本。')
    return 0


# ---------- 命令 ----------
def parse(argv):
    o = {'text': '', 'logs': [], 'yes': False, 'send': None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--yes':
            o['yes'] = True
        elif a in ('--text', '--log', '--send') and i + 1 < len(argv):
            v = argv[i + 1]
            i += 1
            if a == '--text':
                o['text'] = v
            elif a == '--log':
                o['logs'].append(v)
            else:
                o['send'] = v
        else:
            raise SopError(f'不认识的参数：{a}\n{USAGE}')
        i += 1
    return o


def find_project():
    from .project import Project, find_root
    try:
        return Project(find_root(os.getcwd()))
    except (SopError, ValueError):
        return None


def run(argv, *, ask=input, say=print, tty=None, project=None, r=None):
    tty = sys.stdin.isatty() if tty is None else tty
    o = parse(argv)
    p = project if project is not None else find_project()
    slug, url = toolkit_repo(p)
    r = r or redact.for_this_machine(paths.config_dir(), projects=private_names(p))
    if o['send']:
        return send(o['send'], slug, yes=o['yes'], ask=ask, say=say, tty=tty, r=r)
    logs = []
    for f in o['logs'][:LOG_FILES]:
        try:
            logs.append((os.path.basename(f), read_tail(f)))
        except OSError as e:
            raise SopError(f'读不了日志文件 {f}：{e.strerror}')
    if len(o['logs']) > LOG_FILES:
        say(f'日志最多附 {LOG_FILES} 份，后面的没附上')
    text = o['text']
    if not text and tty and not o['yes']:
        text = ask('用一两句话说说你在做什么、看到了什么（直接回车跳过）：') or ''
    title, body, counts = build(text, logs, p, r=r)
    f = save_draft(title, body)
    total = sum(counts.values())
    say(f'问题单草稿：{f}')
    say(f'标题：{title}')
    say(f'已经自动抹掉 {total} 处：' + ('；'.join(f'{k} {v} 处' for k, v in counts.items()) if counts else '没有认出要抹的东西'))
    say('自动抹不保证抹得干净。登记之后在 GitHub 上公开，任何人都看得到：请打开草稿从头看一遍，'
        '项目名、文件名、报错里带出来的代码也会公开。想改就直接改草稿文件。')
    if not slug:
        say(f'工具包仓库 {url} 不在 GitHub 上，登记不了；可以把草稿自己发给维护工具包的人')
        return 0
    return send(f, slug, yes=o['yes'], ask=ask, say=say, tty=tty, r=r)


def cli(argv):
    if argv[:1] in (['-h'], ['--help']):
        print(USAGE)
        return 0
    return run(argv)
