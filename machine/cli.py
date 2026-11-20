"""`sop machine …`：机器级的命令（设计书 4.5、8.5）。不在项目里也能用。

第三段一样一样补：doctor（体检，3-06 做好了）、setup（安装，M2 到 M7 串起来，3-12 做好了）、migrate（环境迁移，3-31 起）；clean 在第 3 期（W31）。
"""
from . import catalog

LATER = {
    'migrate': '环境迁移还没做好（第 1 期第三段的任务 3-31、3-32）',
    'clean': '清理磁盘排在第 3 期（W31）',
}
STEP_NAMES = {'M0': '第零步', 'M2': '安装工具', 'M5': '安装 wt'}

HELP = '''sop machine 的用法：
  sop machine tools     列出工具包要装的基础工具：装在哪、哪一步装、要不要管理员密码
  sop machine doctor    体检：分区、剩余空间、工具在不在规定位置、AI 工具、系统组件、网络连通，出一份大白话的报告
                        加 --readonly 只看不记（不写任何登记）；加 --no-network 不试连网络
  sop machine setup     安装：装工具、登录 GitHub、登录 AI 工具、装 wt、准备受限环境、装全局规则（M2 到 M7），每步做完核对；
                        已经合格的跳过，中途断了再执行一次就接着做。加 --recheck：AI 自检、隔离自检不管变没变都重新真跑一次
  sop machine migrate   环境迁移（还没做好）'''


def show_tools():
    tools = catalog.load()
    print(f'工具包要装的基础工具（{len(tools)} 样，清单在 machine/tools.toml）：')
    for t in tools:
        need = '要输管理员密码' if t.admin else '不用管理员密码'
        ver = f'，版本 {t.version.removeprefix(">=")} 或更新' if t.version else ''
        print(f'  {t.name}：{t.what}')
        print(f'      装在 {t.location}{ver}；在「{STEP_NAMES[t.step]}」那一步装，{need}')
    return 0


def main(argv):
    if not argv or argv[0] in ('help', '-h', '--help'):
        print(HELP)
        return 0
    cmd = argv[0]
    if cmd == 'tools' and len(argv) == 1:
        return show_tools()
    opts = argv[1:]
    if cmd == 'doctor' and len(set(opts)) == len(opts) and set(opts) <= {'--readonly', '--no-network'}:
        from . import doctor
        return doctor.main(readonly='--readonly' in opts, net='--no-network' not in opts)
    if cmd == 'setup' and opts in ([], ['--recheck']):
        from . import setup
        return setup.main(opts)
    if cmd in LATER:
        print(LATER[cmd])
        return 2
    print(f'不认识的命令：sop machine {" ".join(argv)}')
    print(HELP)
    return 2
