"""第零步（bootstrap.sh，设计书 4.2、4.5 的 M0；任务 3-13）里要用 Python 做的两样。

bootstrap.sh 取到工具包、装好 uv 之后，用 uv 和系统自带的 Python 跑这个文件：
  layout                                   报告主目录在哪个分区（只报告、不问，4.3；用体检那一份判断 disks.py）
  finish <提交编号> --source detected|user [--proxy 地址] [--no-proxy 地址]
                                           记下网络设置（config/network.json）、写启动器 ~/tools/sop/sop、
                                           往 ~/.bashrc 末尾写工具包那一段（新开的终端找得到 sop、uv）
内容没变的文件不重写。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # python -I 不会把脚本所在的目录加进来

from kernel import paths  # noqa: E402
from kernel.errors import SopError  # noqa: E402

from machine import config, disks, shellenv  # noqa: E402

USAGE = 'python machine/bootstrap.py layout | finish <提交编号> --source detected|user [--proxy 地址] [--no-proxy 地址]'


def layout():
    print(disks.describe(disks.collect()))
    return 0


def finish(version, source, proxy=None, no_proxy=None):
    from kernel import version as V
    net = config.set_network(http_proxy=proxy or None, https_proxy=proxy or None, no_proxy=no_proxy or None, source=source)
    print(f'网络设置记在 {paths.config_dir() / "network.json"}' + (f'（代理 {proxy}）' if proxy else '（不用代理）'))
    V.write_launcher(version)
    print(f'sop 命令在 {paths.sop_home() / "sop"}，用的工具包版本 {version[:8]}')
    changed = shellenv.install_block(None, paths.tools_dir(), net)
    print(f'终端启动文件 {shellenv.rc_file()} 里工具包那一段' + ('写好了（新开的终端才生效）' if changed else '本来就是最新的，没改'))
    return 0


def main(argv):
    try:
        if argv == ['layout']:
            return layout()
        if len(argv) >= 2 and argv[0] == 'finish':
            opts, rest = {}, argv[2:]
            while rest:
                if len(rest) < 2 or rest[0] not in ('--source', '--proxy', '--no-proxy'):
                    break
                opts[rest[0]] = rest[1]
                rest = rest[2:]
            if not rest and '--source' in opts:
                return finish(argv[1], opts['--source'], opts.get('--proxy'), opts.get('--no-proxy'))
    except SopError as e:
        print(e)
        return 1
    print(USAGE)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
