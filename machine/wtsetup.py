"""M5 安装 wt（设计书 4.3、4.5；3-22）：装到规定位置 ~/tools/wt，出口检查「wt doctor 的环境部分通过」。

- 装：照工具清单 tools.toml 里 wt 那一项（安装脚本 machine/install/wt.sh），和 M2 的几样一样先查、再装、再查
  （machine/install.py 的 install_tool）。wt 的仓库是私有的，经 SSH 克隆，所以排在登录 GitHub（M3）之后。
- 出口检查：先按清单查规定位置那一份在不在、版本够不够；再在一个空的临时目录里跑规定位置那一份的 `wt doctor`
  （不在任何项目里，所以它只查环境：bash、Git、gh 和 gh 登录、SSH、Git 的提交身份、全局配置、模板）。
  wt 报「失败」（✖）的一项都没有才算通过；「提醒」（⚠）照实列出来，不算不通过。
  不加 --fix（那会改全局 Git 配置）；跑的时候和工具包平常调 wt 一样：外面带进来的 WT_ 变量去掉，
  WT_TEMPLATE 指向工具包自己的模板，Git 钩子关掉（kernel/wtx.py）。

整个机器流程（M2 到 M7、断了接着做）由 sop machine setup（3-12）串起来；这里只管这一步。
也能直接跑：python3 -m machine.wtsetup（装，再出口检查）；python3 -m machine.wtsetup --check（只检查）
"""
import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kernel import paths, wtx
from . import catalog, install as m2, shellenv

TIMEOUT = 120      # wt doctor 里 SSH 那一项最多试两次、每次 8 秒，gh 查登录也要连网


@dataclasses.dataclass
class Result:
    ok: bool
    failures: list      # wt 报失败的几项（不通过的原因），或者没跑成的原因
    warnings: list      # wt 报提醒的几项
    output: str         # wt doctor 的原文


def doctor_env(tools_dir=None, base=None):
    """跑 wt doctor 的环境：规定位置的工具在 PATH 最前面（gh 用 ~/tools/gh 那一份），
    去掉外面带进来的 WT_ 和 GIT_ 变量，只给工具包自己的模板，Git 钩子关掉。"""
    env = {k: v for k, v in shellenv.environ(tools_dir, base=base).items() if not k.startswith(('WT_', 'GIT_'))}
    env.update({'WT_TEMPLATE': str(wtx.TEMPLATE), 'NO_COLOR': '1', 'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '1',
                'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/dev/null'})
    return env


def parse(output):
    """wt doctor 的输出：环境那一节里失败（✖）和提醒（⚠）各是哪几项。最后那一行总数不算。"""
    fails, warns = [], []
    for line in output.splitlines():
        text = line.removeprefix('wt: ').strip()
        if text.startswith('✖') and '项失败' not in text:
            fails.append(text.removeprefix('✖').strip())
        elif text.startswith('⚠'):
            warns.append(text.removeprefix('⚠').strip())
    return fails, warns


def check(*, timeout=TIMEOUT, base=None):
    """M5 的出口检查。不改任何东西。返回 Result。工具目录是 paths.tools_dir()（和清单的检查命令同一个）。"""
    t = paths.tools_dir()
    tool = catalog.find('wt')
    r = catalog.run_check(tool)
    if not r.installed:
        return Result(False, [f'规定位置 {t / "wt"} 还没有能运行的 wt'], [], r.output)
    if not r.ok:
        return Result(False, [f'规定位置的 wt 版本是 {r.version_text}，不够清单要的 {tool.version}'], [], r.output)
    cwd = Path(tempfile.mkdtemp(prefix='sop-wt-doctor-', dir=os.environ.get('TMPDIR') or '/tmp'))
    env = doctor_env(t, base)
    env['GIT_CEILING_DIRECTORIES'] = str(cwd.parent)     # 不往上找项目：只查环境
    try:
        p = subprocess.run(['bash', str(t / 'wt' / 'wt'), 'doctor'], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Result(False, [f'wt doctor {timeout} 秒没跑完（多半是网络：gh 查登录、SSH 连 GitHub）'], [], '')
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    out = (p.stdout + p.stderr).strip()
    fails, warns = parse(out)
    if '── 环境' not in out:
        return Result(False, [f'wt doctor 没跑成（退出码 {p.returncode}）：{out[-300:]}'], warns, out)
    if '── 项目' in out:
        return Result(False, ['wt doctor 查到了一个项目，不是只查环境（不该出现）'], warns, out)
    if p.returncode != 0 and not fails:
        fails = [f'wt doctor 退出码 {p.returncode}：{out[-300:]}']
    return Result(p.returncode == 0 and not fails, fails, warns, out)


def install(out=None):
    """装（已经合格就跳过）。返回 (装好没有, 一句大白话)。"""
    r, msg = m2.install_tool(catalog.find('wt'), out=out)
    return r.ok, msg


def report(res):
    """出口检查的结果，几句大白话。"""
    if res.ok:
        lines = ['wt 的出口检查（wt doctor 的环境部分）：通过']
    else:
        lines = ['wt 的出口检查（wt doctor 的环境部分）：不通过'] + [f'  不通过：{f}' for f in res.failures]
    lines += [f'  提醒（不影响通过）：{w}' for w in res.warnings]
    return lines


def main(argv):
    if argv not in ([], ['--check']):
        print('用法：python3 -m machine.wtsetup [--check]')
        return 2
    if not argv:
        ok, msg = install()
        print(msg, flush=True)
        if not ok:
            return 1
    res = check()
    print('\n'.join(report(res)))
    return 0 if res.ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
