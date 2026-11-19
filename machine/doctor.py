"""`sop machine doctor`：体检（设计书 4.3、4.5 的 M1，任务 3-06），出一份大白话的报告。

查的几样都是只读的：主目录在哪个分区（disks.py）、剩余空间（space.py）、基础工具在不在规定位置、
另有一份不在规定位置的在哪占多大（locate.py）、AI 工具在哪什么版本、系统组件的版本（components.py）。

登记：
- 工具实际位置记进 config/tools.json（基础工具和 AI 工具都记；真实 AI 演练写的版本留着）。
- 系统组件的版本**不在这里记**：只在隔离自检通过之后记（3-07、M6）。体检要是记了，系统升级后先跑一次体检，
  sop 启动时就看不出变化、跳过了隔离自检。这里只说哪几样和上次登记的不一样。
- `--readonly`：只看不记，一个文件都不写（连 config 目录都不建）。

退出码：0 基础工具全部合格；1 有没装好的（报告照样出）；剩余空间不够、往终端塞按键没禁用这些「要注意」的不算。
另有一份不在规定位置的，不算不合格，也不挡流程（4.3）。
"""
import time

from kernel import paths

from . import catalog, components, config, disks, locate, space

STATE_TEXT = {'ok': '合格', 'old': '版本不够', 'missing': '还没装'}
STEP_NAMES = {'M0': '第零步', 'M2': '安装工具', 'M5': '安装 wt'}


def collect(home=None, run=None):
    """只读地查一遍，返回一个字典给 report()、record() 用。run 给了就替换查磁盘用的命令（测试用）。"""
    kw = {'run': run} if run else {}
    parts = components.collect(**kw)
    return {
        'time': time.strftime('%Y-%m-%d %H:%M'),
        'layout': disks.collect(home, **kw),
        'space': space.check(home, **kw),
        'tools': locate.check_tools(home=home, sysdisk=locate.SystemDisk(**kw)),
        'ai': locate.find_ai_tools(home=home),
        'components': parts,
        'changes': config.system_changes(parts),
        'registered_ai': {k: v for k, v in config.tools().items() if v.get('kind') == 'ai'},
    }


def _copy_line(o, home):
    if o.inside:
        return f'{locate.short(o.path, home)}（在 {locate.short(o.inside, home)} 里面，大小算在那边）'
    size = locate.human_size(o.size)
    if o.partial and o.size is not None:
        size = f'至少 {size}，有的地方要管理员权限才看得到'
    disk = {True: '占系统盘', False: '不占系统盘', None: '看不出占不占系统盘'}[o.on_system_disk]
    real = '' if o.real == o.path else f'，实际在 {locate.short(o.real, home)}'
    return f'{locate.short(o.path, home)}（{size}，{disk}{real}）'


def _tool_lines(s, home):
    t, r = s.tool, s.check
    where = locate.short(s.path, home)
    if s.state == 'ok':
        place = where if not t.system_package else '系统软件包' if where == catalog.SYSTEM else f'系统软件包，{where}'
        head = f'{t.name}：合格，{r.version_text}（{place}）。'
    elif s.state == 'old':
        head = (f'{t.name}：版本不够。{where} 上是 {r.version_text}，要 {t.version.removeprefix(">=")} 或更新，'
                f'在「{STEP_NAMES[t.step]}」那一步会换上新的。')
    else:
        place = '用 apt 装的系统软件包' if t.system_package else f'规定位置 {where}'
        head = f'{t.name}：还没装（{place}），在「{STEP_NAMES[t.step]}」那一步装。'
    lines = [head]
    for o in s.others:
        lines.append(f'    另有一份不在规定位置：{_copy_line(o, home)}')
    return lines


def _ai_lines(a, registered, home):
    if not a.found:
        return [f'{a.label}：没找到。']
    ver = a.version or '看不出版本'
    real = '' if a.real == a.path else f'，实际在 {locate.short(a.real, home)}'
    lines = [f'{a.label}：{ver}，在 {locate.short(a.path, home)}{real}。']
    drilled = (registered.get(a.name) or {}).get('drilled_version')
    if drilled and a.version and drilled != a.version:
        lines.append(f'    上次做真实 AI 演练的是 {drilled}，现在是 {a.version}：版本变了，要重跑一次演练（10.1）。')
    return lines


def report(d, home=None, readonly=False):
    """返回 (报告的文字, 没装好的工具的名字, 要注意的事)。"""
    bad = [s.tool.name for s in d['tools'] if s.state != 'ok']
    notes = []
    if d['layout'].kind == 'unknown':
        notes.append('看不出主目录和系统是不是在同一个分区上')
    for s in d['space']:
        if s.low:
            notes.append(f'{space.NAMES[s.which]}剩的空间不到 {s.minimum // space.GB} GB')
    if d['components']['tiocsti'] != '0':
        notes.append('往终端塞按键没有禁用，AI 对话的步骤不会启动')
    if not any(a.found for a in d['ai']):
        notes.append('一个 AI 工具都没找到')
    others = [s for s in d['tools'] if s.others]

    out = [f'体检报告（{d["time"]}）', '']
    out.append('一、结论')
    if bad:
        out.append(f'  有 {len(bad)} 样基础工具还没装好：{"、".join(bad)}。执行 sop machine setup 会装上。')
    else:
        out.append('  基础工具全部合格。')
    if others:
        out.append(f'  {len(others)} 样另有一份不在规定位置（{"、".join(s.tool.name for s in others)}），不算不合格，'
                   '也不挡流程，详见第四项。')
    for n in notes:
        out.append(f'  要注意：{n}。')
    out.append('')
    out.append('二、主目录在哪个分区')
    out += ['  ' + x for x in disks.describe(d['layout']).splitlines()]
    out.append('')
    out.append('三、剩余空间')
    out += ['  ' + x for x in space.describe(d['space']).splitlines()]
    out.append('')
    out.append(f'四、基础工具（{len(d["tools"])} 样，清单在 machine/tools.toml；工具包自己装的都在 '
               f'{locate.short(paths.tools_dir(), home)} 下）')
    for s in d['tools']:
        out += ['  ' + x for x in _tool_lines(s, home)]
    if others:
        out.append('  「另有一份不在规定位置」的：SOP 自己不用它，也不碰它。要不要留着由你决定，'
                   '可以执行 sop machine migrate 逐样选留还是卸（4.8）。')
    out.append('')
    out.append('五、AI 工具（保持各自默认的位置，不归工具包管）')
    for a in d['ai']:
        out += ['  ' + x for x in _ai_lines(a, d['registered_ai'], home)]
    out.append('')
    out.append('六、系统组件')
    out += ['  ' + x for x in components.describe(d['components'], d['changes']).splitlines()]
    out.append('')
    if readonly:
        out.append('这次只看不记（--readonly），没有写任何登记。')
    else:
        out.append(f'工具的位置和版本已记进 {locate.short(paths.config_dir() / "tools.json", home)}。')
    return '\n'.join(out), bad, notes


def record(d):
    """把基础工具和 AI 工具的位置、版本记进 config/tools.json。系统组件不记（见开头）。"""
    entries = {s.tool.name: s.as_record() for s in d['tools']}
    entries.update({a.name: a.as_record() for a in d['ai']})
    return config.record_tools(entries)


def main(readonly=False, home=None):
    d = collect(home)
    if not readonly:
        record(d)
    text, bad, _ = report(d, home, readonly)
    print(text)
    return 1 if bad else 0
