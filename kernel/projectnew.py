"""sop project new（设计书 7.2 项目初始化流程）。这里做本机的几步：I0 红线预问、I1 选公开还是私有、I3 写项目模板、
I4 装技能和技能配置；GitHub 那几步（I2 建仓库和目录、I5 首次推主线、I6 建日志分支和开保护、I7 四个试验 PR）在
kernel/projectgh.py（3-24），接口是 GitHubSide。

顺序（7.2）：I0、I1 先问，命中红线就停，这时候还没有建任何仓库、项目根也没有建；I2 用 wt init --create 建 GitHub 仓库和本机的
项目根（GitHub 建仓库时带一个 README 提交，wt 把它取下来放在 main/）；I3、I4 往 main/ 里写，出口检查是目录结构检查
（checks/project_layout），写完在本机提交一次（关钩子）；I5 才推送。

I0、I1 的回答暂存本机：~/tools/sop/state/<项目名>/init/redline.json、visibility.json（P1 风险分级沿用 I0 的答案）。
公开还是私有另写进 sop.json 的 visibility。

断了重跑（3-24）：进度记在 state/<项目名>/init/progress.json。再执行 sop project new <项目名> 时不再问 I0、I1（回答已经记下），
从没做完的那一步接着做：I2 由 GitHub 那一边自己认（仓库建了没有、本机目录建到哪了）；I3、I4 写到一半的（main/ 上还没有提交）
先把 main/ 恢复成刚取下来的样子再写，已经提交了的不重写；I5 到 I7 见 kernel/projectgh.py。
"""
import datetime
import json
import os
import pathlib
import stat
import sys

from checks.project_layout import check as layout_check, core as layout

from . import paths, projectgh
from .errors import SopError
from .gitx import Git

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_REPO = ''      # 3-41：工具包的公开仓库建好后改成 https://github.com/C1fLly/sop.git（和 bootstrap.sh 一样）
SCOPE = 'project'


class RedLine(SopError):
    """命中红线（1.3）：停下，说明原因和可以找哪类专业服务。"""


# ---------- I0 红线预问（1.3；不依赖仓库的那几问，7.2） ----------
# 每一问：编号、问题、选项（按顺序编号 1、2、3……）、命中红线的选项、命中时的原因和可以找的专业服务。
# 规模三问的换算（1.3 第二条「由脚本换算」）：本工具包撑得住的是单一机房里能水平扩展的系统；用户在几百万以上、最忙时同时十万人以上、
# 停一小时就是大事故必须马上在另一处顶上，三样有一样就算超出（要多机房容灾或分布式架构）。这几个分界是 3-23 定的，留给 3-48 写进设计书。
REDLINE = (
    {'id': 'regulated', 'question': '这个系统要不要处理下面任何一种？',
     'show': ['持牌的金融业务（银行、证券、保险、贷款、基金）', '病历、诊断、处方这类医疗数据', '未满 18 岁的人的个人信息'],
     'options': ['不要', '要（哪怕只有一种）'], 'hit': [2],
     'why': '属于受监管的业务（持牌金融、医疗数据、未成年人数据）',
     'service': '有这类业务资质的开发公司，加上金融、医疗或未成年人保护方面的合规顾问'},
    {'id': 'users', 'question': '大概会有多少人用这个系统？',
     'options': ['几十人以内', '几百到几千人', '几万到几十万人', '几百万人以上'], 'hit': [4],
     'why': '用的人太多，要多机房容灾或分布式架构',
     'service': '做大型分布式系统的专业团队，或云服务商的架构咨询'},
    {'id': 'peak', 'question': '最忙的时候，同一时间大概有多少人在用？',
     'options': ['几十人以内', '几百人', '几千到几万人', '十万人以上'], 'hit': [4],
     'why': '同时在用的人太多，要多机房容灾或分布式架构',
     'service': '做大型分布式系统的专业团队，或云服务商的架构咨询'},
    {'id': 'downtime', 'question': '系统停一小时，损失有多大？',
     'options': ['不要紧，修好接着用', '有损失，但能补回来', '是大事故，必须几分钟内在另一个地方顶上'], 'hit': [3],
     'why': '停不起，要多机房容灾',
     'service': '做容灾和高可用的专业团队，或云服务商的架构咨询'},
    {'id': 'money', 'question': '系统里的钱怎么走？',
     'options': ['不收钱，或者只接现成的收款服务（微信支付、支付宝、银行卡收款）', '要自己做清算、分账、替别人收钱付钱'], 'hit': [2],
     'why': '要自己写支付清算的逻辑',
     'service': '持牌的支付服务商，或者做支付系统的专业公司'},
    {'id': 'security', 'question': '有没有人（客户、监管、合同）要求你们必须自己发放登录凭证、自己做加密，而不是用常见的登录方式？',
     'options': ['没有', '有'], 'hit': [2],
     'why': '要手写密码处理、令牌签发或加密算法',
     'service': '做安全和身份认证的专业公司，或者现成的身份认证服务'},
)

# ---------- I1 选公开还是私有（7.2 的对比表） ----------
VISIBILITY_TABLE = (
    ('谁能看到代码', '所有人', '只有你'),
    ('谁能看到进度日志（含花费、你的确认记录）', '所有人', '只有你'),
    ('没通过检查的改动能不能合进主线', '合不进，GitHub 拦着', 'GitHub 不拦。靠工具包自己查，加上你在网页上看颜色'),
    ('合并到主线', '工具包做', '每个功能你到网页上点一次'),
    ('进度日志能不能被改写', '不能，GitHub 拦着', 'GitHub 不拦，靠本机的隔离'),
    ('每月的检查时长', '不计', '有免费额度，够做几个功能还不知道'),
)
VISIBILITY_NOTE = '企业项目多半只能选私有。选私有时，GitHub 那一头的几道拦截都没有，全靠本机。'


def _record_dir(name):
    d = paths.state_dir(name) / 'init'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now():
    return datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_json(f, data):
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, f)


def _choose(human, step, question, options, show=()):
    lines = list(show) + [f'{i}. {o}' for i, o in enumerate(options, 1)]
    choices = [str(i) for i in range(1, len(options) + 1)]
    while True:
        a = str(human.ask(SCOPE, step, question, {'show': lines, 'choices': choices}).get('answer', '')).strip()
        if a in choices:
            return int(a)
        print(f'请回答 {"、".join(choices)} 中的一个')


def ask_redlines(name, human):
    """I0：一问一问地问，答完写记录；命中红线抛 RedLine（记录照样写下，hits 里列着命中的）。"""
    answers, hits = {}, []
    for q in REDLINE:
        n = _choose(human, f'I0-{q["id"]}', q['question'], q['options'], q.get('show', ()))
        answers[q['id']] = {'question': q['question'], 'answer': q['options'][n - 1], 'choice': n}
        if n in q['hit']:
            hits.append({'id': q['id'], 'why': q['why'], 'service': q['service']})
    rec = {'time': _now(), 'answers': answers, 'hits': hits}
    _write_json(_record_dir(name) / 'redline.json', rec)
    if hits:
        lines = [f'- {h["why"]}。可以找：{h["service"]}' for h in hits]
        raise RedLine('这个项目超出了本工具包能做的范围（红线，设计书 1.3），已停下，没有建任何仓库：\n' + '\n'.join(lines))
    return rec


def visibility_lines():
    out = []
    for what, pub, priv in VISIBILITY_TABLE:
        out.append(f'· {what}：公开——{pub}；私有——{priv}')
    return out + [VISIBILITY_NOTE]


def ask_visibility(name, human):
    """I1：把对比表摆出来，选公开还是私有，写选择记录。返回 'public' 或 'private'。"""
    n = _choose(human, 'I1', '项目的仓库要公开还是私有？两种的区别：', ['公开', '私有'], visibility_lines())
    vis = ('public', 'private')[n - 1]
    _write_json(_record_dir(name) / 'visibility.json', {'time': _now(), 'visibility': vis})
    return vis


# ---------- I3 写项目模板、I4 装技能和技能配置 ----------
def _copy_file(src, dest):
    """逐字节复制，执行权限按原文件（Git 只记能不能执行这一位）；目标已经有东西就停，不覆盖。"""
    dest = pathlib.Path(dest)
    if os.path.lexists(dest):
        raise SopError(f'{dest} 已经有了，不覆盖')
    st = os.lstat(src)
    if not stat.S_ISREG(st.st_mode):
        raise SopError(f'{src} 不是普通文件，不复制')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(src, 'rb') as f:
        data = f.read()
    with open(dest, 'xb') as f:
        f.write(data)
    os.chmod(dest, 0o755 if st.st_mode & 0o100 else 0o644)


def _copy_tree(src, dest):
    for base, dirs, names in os.walk(src):
        dirs.sort()
        rel = os.path.relpath(base, src)
        for n in sorted(names):
            _copy_file(os.path.join(base, n), pathlib.Path(dest) / rel / n)


def write_template(dest, name, visibility, repo, version, toolkit=TOOLKIT):
    """I3：把 templates/project/ 原样复制进 dest（项目的 main/ 目录），再写 sop.json（项目名、工具包的仓库和版本、
    还没有档案、公开还是私有；风险等级等 P1 再写）。"""
    paths.check_project_name(name)
    if visibility not in layout.VISIBILITY:
        raise SopError(f'公开还是私有只能是 public 或 private：{visibility!r}')
    if not repo or not version:
        raise SopError('不知道工具包的仓库和版本，写不了 sop.json')
    _copy_tree(layout.template_dir(toolkit), dest)
    sop = {'project': name, 'toolkit': {'repo': str(repo), 'version': str(version)},
           'profiles': {'stack': [], 'end': []}, 'visibility': visibility}
    f = pathlib.Path(dest) / 'sop.json'
    if os.path.lexists(f):
        raise SopError(f'{f} 已经有了，不覆盖')
    f.write_text(json.dumps(sop, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def install_skills(dest, toolkit=TOOLKIT):
    """I4：要装的技能（附录 B 加原文里查出的依赖）逐字复制到 .claude/skills/<技能>/、.agents/skills/<技能>/（去掉分类那一层），
    许可文件原样放在技能目录之外，docs/agents/ 写 setup-matt-pocock-skills 的那几份种子文件。返回装了哪些技能。"""
    dest = pathlib.Path(dest)
    wanted = layout.install_list(str(toolkit))
    for base in layout.SKILL_DIRS:
        for n, src in wanted.items():
            _copy_tree(src, dest / base / n)
    for d in layout.LICENSE_DEST:
        _copy_file(pathlib.Path(toolkit) / layout.LICENSE_SRC, dest / d)
    for d, src in layout.agent_docs(str(toolkit)).items():
        _copy_file(src, dest / d)
    return sorted(wanted)


def verify_layout(dest, toolkit=TOOLKIT, root=None):
    """I3、I4 的出口检查：目录结构检查（checks/project_layout）。不过就抛错。"""
    ok, line, rep = layout_check.run(str(dest), str(toolkit), str(root) if root else None)
    if not ok:
        raise SopError(line)
    return line


INITIAL_MESSAGE = 'chore: 项目初始内容（工具包的项目模板、技能和技能配置）'


def write_initial(root, name, visibility, repo, version, toolkit=TOOLKIT):
    """I3、I4：往项目根的 main/ 里写，过出口检查，在本机提交一次（关钩子，特权侧自己的 Git），推送是 I5 的事。
    重跑时：main/ 上已经有这一次提交的，只再过一遍出口检查；还没有提交、写到一半的，先把 main/ 恢复成刚取下来的样子
    （改过的文件恢复、新加的文件删掉；被 Git 忽略的不动）再写。"""
    root = pathlib.Path(root)
    main = root / 'main'
    g = Git(root / '.git' / 'worktrees' / 'main', main)
    got, head = g.rev('refs/remotes/origin/main'), g.rev('HEAD')
    if head and head != got:
        if g.rev('HEAD~1') == got and g('log', '-1', '--format=%s') == INITIAL_MESSAGE:
            return verify_layout(main, toolkit, root)
        raise SopError(f'{main} 上有不认识的提交，不接着往里写。启动维修窗口（sop repair）看一下。')
    if g('status', '--porcelain'):
        g('checkout', '-q', '--', '.')
        g('clean', '-q', '-fd')
    write_template(main, name, visibility, repo, version, toolkit)
    projectgh.test_break('mid-I3I4')
    install_skills(main, toolkit)
    line = verify_layout(main, toolkit, root)
    g('add', '-A')
    g('commit', '-q', '--no-verify', '-m', INITIAL_MESSAGE)
    return line


# ---------- GitHub 那一半（kernel/projectgh.py，3-24） ----------
class GitHubSide:
    """I2、I5、I6、I7 的接口：create(项目名, 项目根, 公开还是私有) 建 GitHub 仓库和项目根（I2），在 I3、I4 之前；
    publish(项目根, 公开还是私有) 做首次推主线、建日志分支、开保护、设事件规则、四个试验 PR（I5 到 I7），在之后。
    真的那一份是 kernel/projectgh.GitHub；自测可以换成替身。"""

    def create(self, name, root, visibility):
        raise NotImplementedError

    def publish(self, project_root, visibility):
        raise NotImplementedError


def toolkit_source(toolkit=TOOLKIT):
    """sop.json 里要写的工具包仓库和版本：版本是正在运行的这一份工具包的提交编号（启动器已核对过它没被改，3.2），
    仓库地址取 SOP_TOOLKIT_REPO，没有时用 DEFAULT_REPO（3-41 定）。"""
    repo = os.environ.get('SOP_TOOLKIT_REPO') or DEFAULT_REPO
    if not repo:
        raise SopError('工具包仓库的地址还没定（GitHub 上的工具包仓库在任务 3-41 建），写不了 sop.json')
    version = Git(pathlib.Path(toolkit) / '.git').rev('HEAD')
    if not version:
        raise SopError(f'{toolkit} 不是一份装好的工具包（找不到它的提交编号）')
    return repo, version


def git_identity():
    """Git 的提交身份设了没有（名字、邮箱都要有；3-22 发现新电脑上没人设，3-10 设）。"""
    import subprocess
    from .gitx import clean_env
    got = [subprocess.run(['git', 'config', '--get', k], capture_output=True, text=True, env=clean_env(),
                          stdin=subprocess.DEVNULL).stdout.strip() for k in ('user.name', 'user.email')]
    return all(got)


def _resumable(name):
    """上次没做完的进度（I0 没命中红线、I1 选好了才会有）。"""
    prog = projectgh.load_progress(name)
    if not prog:
        return None
    d = paths.state_dir(name) / 'init'
    try:
        red = json.loads((d / 'redline.json').read_text(encoding='utf-8'))
        vis = json.loads((d / 'visibility.json').read_text(encoding='utf-8'))['visibility']
    except (OSError, ValueError, KeyError):
        raise SopError(f'项目 {name} 上次的进度记录不全（{d}），没法接着做。启动维修窗口（sop repair）看一下。')
    if red.get('hits') or vis != prog.get('visibility'):
        raise SopError(f'项目 {name} 上次的进度记录对不上（{d}），没法接着做。启动维修窗口（sop repair）看一下。')
    return prog


def new_project(name, human, github=None, toolkit=TOOLKIT):
    """sop project new 的全过程。返回项目根。断了重跑时从没做完的那一步接着做。"""
    paths.check_project_name(name)
    root = paths.projects_dir() / name
    prog = _resumable(name)
    if prog and prog.get('finished'):
        raise SopError(f'项目 {name} 已经建好了：{root}')
    if prog:
        vis = prog['visibility']
        print(f'项目 {name} 上次没建完，接着做（前面几个问题的回答已经记下，不再问）。')
    else:
        if os.path.lexists(root) and (not root.is_dir() or any(root.iterdir())):
            raise SopError(f'{root} 已经有东西了，换一个项目名，或者先把它挪走')
        if not human.can(SCOPE, f'I0-{REDLINE[0]["id"]}'):
            raise SopError('sop project new 要在终端里回答几个问题，请在终端里直接执行')
        print('先问几个问题，看这个项目在不在本工具包能做的范围里（不用懂技术，按实际情况选）。')
        ask_redlines(name, human)
        vis = ask_visibility(name, human)
    repo, version = toolkit_source(toolkit)
    if not git_identity():
        raise SopError('这台电脑上 Git 的提交身份（名字和邮箱）还没设，项目的第一次提交做不了。'
                       '先做机器准备里登录 GitHub 那一步（sop machine setup），它会设好。还没有建任何仓库。')
    if not prog:
        projectgh.save_progress(name, visibility=vis, done=[], started=_now())
    github = github or projectgh.GitHub()
    if not projectgh.is_done(name, 'I2'):
        github.create(name, root, vis)                                 # I2
        projectgh.mark_done(name, 'I2')
        projectgh.test_break('after-I2')
    if not projectgh.is_done(name, 'I3I4'):
        line = write_initial(root, name, vis, repo, version, toolkit)  # I3、I4
        projectgh.mark_done(name, 'I3I4')
        print(line)
    github.publish(root, vis)                                          # I5 到 I7
    projectgh.save_progress(name, finished=_now())
    return root


def cli(argv):
    if len(argv) != 1 or argv[0].startswith('-'):
        print('用法：sop project new <项目名>（项目名只用小写字母、数字和「-」）')
        return 2
    from .human import NoHuman, ScriptedHuman, TtyHuman
    name = argv[0]
    try:
        paths.check_project_name(name)
    except ValueError as e:
        print(str(e)); return 2
    s = os.environ.get('SOP_HUMAN_SCRIPT')
    human = ScriptedHuman(name, s) if s else (TtyHuman() if sys.stdin.isatty() else NoHuman())
    root = new_project(name, human)
    print(f'项目已建好：{root}')
    return 0
