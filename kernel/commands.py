"""命令表（3-62）：`sop` 现在真有哪些命令，设计书里写了、还没做的排在哪。

- 文档检查（checks/doc_refs，设计书 16.2）按这张表核对文档里写的 `sop …`：在 DONE 或 PLANNED 里才算存在。
- tests/unit/test_commands.py 核对这张表和 kernel/cli.py、machine/cli.py、kernel/version.py 真分派的一致：
  DONE 里的每一条真的分派到了处理函数，PLANNED 里的每一条现在都还分派不到（做好了就要从 PLANNED 挪到 DONE）。
- 只用标准库、没有导入别的模块：文档检查直接按文件读它。

每一条写成用法：命令的词，后面 <…> 是要填的参数，[…] 是可以不填的。
"""

# 现在代码里真有的
DONE = {
    '': '显示当前位置并继续执行（8.5）',
    'answer': '同 sop，在终端里时可以回答提问',
    'chat': '同 sop，在终端里时可以回答提问',
    'status': '只显示当前位置和事件，不执行（8.5）',
    'cost': '显示 AI 花费（8.5）',
    'feature new <功能名>': '开始一个功能（8.5）',
    'feature drop': '放弃进行中的功能（7.12）',
    'machine': '列出 sop machine 的用法',
    'machine tools': '列出工具包要装的基础工具（3-03）',
    'machine doctor': '体检（4.5，3-06）',
    'machine setup': '安装 M2 到 M7（4.5，3-12）',
    'machine migrate': '环境迁移（4.8，3-31、3-32、3-61）',
    'project new <项目名>': '新建项目（7.2，3-23、3-24）',
    'project clone <所有者/项目名>': '克隆已有项目（4.6、4.7，3-25）',
    'self install <版本目录> <提交编号>': '安装工具包的一个版本（3.2）',
    'self upgrade <提交编号>': '升级这个项目用的工具包版本（7.11）',
}

# 不给小白用的：只给第零步、自测用。文档里写到也算存在
INTERNAL = {
    'self bootstrap <版本目录> <提交编号>': '第零步装第一个版本（bootstrap.sh 调）',
    'init-project': '第二段的流程沙箱建日志分支、记指纹用（正式的是 sop project new）',
}

# 设计书里写了、还没做的：排在哪个任务或哪一期。做好了挪到 DONE（单元测试会提醒）
PLANNED = {
    'check [步骤]': '设计书 8.5；还没排进任务清单',
    'accept': '第 2a 期（验收环境）',
    'profile test <档案>': '第 2a 期（档案合规测试，11.4）',
    'guide': '第 2b 期（带路窗口）',
    'standards': '第 2b 期（规范变更）',
    'feature change': '第 2b 期（功能的变更，7.12）',
    'feature revert': '第 2b 期（退掉一个已合入的功能，7.12）',
    'self report': '3-42',
    'self rollback': '3-43',
    'self fix <问题单>': '3-45',
    'repair': '第 3 期（维修窗口，17.1）',
    'health': '第 3 期（体检流程，7.10）',
    'backup': '第 3 期（随体检流程，4.7）',
    'backup restore <备份文件>': '第 3 期（随体检流程，4.7）',
    'machine clean': '第 3 期（W31）',
    'project remove': '第 3 期（W31）',
    'self uninstall': '第 3 期（W31）',
    'release': '第 3 期，部署相关暂缓（7.7）',
    'incident': '第 3 期，部署相关暂缓（7.8）',
    'prod doctor': '第 3 期，部署相关暂缓（7.9）',
}


def words(usage):
    """用法里命令的那几个词，例如 'feature new <功能名>' -> ('feature', 'new')。"""
    out = []
    for w in usage.split():
        if w[0] in '<[-':
            break
        out.append(w)
    return tuple(out)


def takes_args(usage):
    return any(w[0] in '<[' for w in usage.split())
