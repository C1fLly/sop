"""AI 工具的状态目录（设计书 6.3 三）：按会话分，全新会话的步骤每次从模板现建，用完封存成只读。

放在 ~/tools/sop/state/<项目名>/ai-state/<工具名>/<会话名>/，不在项目根下（经专用 Docker 改得了，审查后实测）。
模板由各工具的适配器给（只含必需的设置，例如 Claude Code 的 5 项）。
"""
import os
import stat

from kernel import paths


def base(project, tool):
    return paths.state_dir(project) / 'ai-state' / tool


def fresh(project, tool, session, template):
    """现建一个状态目录。template(目录) 往里写模板文件。会话名已经用过就加序号，绝不复用旧的。"""
    b = base(project, tool)
    b.mkdir(parents=True, exist_ok=True)
    n = 1
    while (b / f'{session}-{n}').exists():
        n += 1
    d = b / f'{session}-{n}'
    d.mkdir(mode=0o700)
    template(d)
    return d


def sealed(d):
    return not os.access(d, os.W_OK)


def seal(d):
    """封存成只读：只留给复盘（F22）和额度报错的扫描读，不再可写地放进任何受限环境。"""
    for root, dirs, files in os.walk(d, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            if not os.path.islink(p):
                os.chmod(p, stat.S_IMODE(os.lstat(p).st_mode) & ~0o222)
        for x in dirs:
            p = os.path.join(root, x)
            if not os.path.islink(p):
                os.chmod(p, 0o500)
    os.chmod(d, 0o500)
