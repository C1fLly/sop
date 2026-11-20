"""AI 工具适配器的接口（设计书 10.1）。把「交互启动」「自动调用」「续接」翻译成具体工具的命令。

四个操作：probe（自检）、start_interactive（对话方式）、run_headless（自动调用）、resume（续接并送入补充说明）。
每个操作都在受限环境里做：适配器只说明要往受限环境里放什么（程序、状态目录挂在主目录下哪里、要带进去的环境变量），
放法由受限运行器按步骤的种类定（6.3）。
"""
from dataclasses import dataclass, field

from machine import config


@dataclass
class Outcome:
    rc: int                      # 工具的退出码（只看它不够，9.3）
    cost: float = 0.0            # 工具报告的金额（美元）；报告不了的按适配器的估法
    session: str | None = None   # 会话编号（续接用）
    logs: list = field(default_factory=list)   # 这一步的会话日志（外面的路径），给额度报错的扫描和复盘
    text: str = ''               # 最后的回答（给人看）
    timeout: bool = False
    cost_basis: str = '工具报告'  # 金额从哪来：工具报告的，或者没读到报告


@dataclass
class ProbeResult:
    ok: bool                     # 装了、真的答得上来、能力声明对得上
    message: str                 # 给人看的一句话
    version: str | None = None
    cost: float = 0.0            # 那一次最短的调用花了多少（美元，工具报告的）
    quota: bool = False          # 服务报了余额不足、额度用完这一类的错：暂停、提示充值，不重试（交接「用户已经定下的事」）
    remind: str = ''             # 版本和上次做真实 AI 演练的不一样（或还没做过）时的提醒（10.1）
    details: dict = field(default_factory=dict)


def drill_reminder(name, version):
    """和机器级登记里「最近一次做过真实 AI 演练的版本」比（10.1）。一样返回空；不一样或还没做过，返回提醒的话。
    演练通过前流程照常能用，只是每次都提醒。"""
    drilled = (config.tools().get(name) or {}).get('drilled_version')
    if not drilled:
        return f'这个 AI 工具（{version}）还没做过真实 AI 演练（16.2），流程照常能用，演练通过后就不再提醒'
    if version and drilled != version:
        return f'上次做真实 AI 演练的是 {drilled}，现在是 {version}：版本变了，要重跑一次演练（10.1），演练通过前流程照常能用'
    return ''


def record_probe(name, *, path, real, version, ok):
    """自检之后把位置、版本记进机器级登记 config/tools.json（10.1）；ok 时另记「真的答得上来的版本」和时间。
    演练写的版本（drilled_version）不动。"""
    with config.editing('tools') as d:
        reg = d.setdefault('tools', {})
        old = reg.get(name) or {}
        e = {**old, **config.tool_entry(path=path, version=version, kind='ai', in_place=True, others=old.get('others'),
                                        real=real, installed=True), 'probe_ok': bool(ok)}
        if ok:
            e['probed_version'], e['probed_at'] = version, config.now()
        reg[name] = e
    return e


def mark_drilled(name, version):
    """真实 AI 演练（16.2）通过之后调：记下演练过的版本。"""
    with config.editing('tools') as d:
        e = d.setdefault('tools', {}).setdefault(name, {'kind': 'ai'})
        e['drilled_version'], e['drilled_at'] = version, config.now()
    return e


class Adapter:
    name = 'base'
    caps = {'interactive': False, 'headless': False, 'resume': False, 'subagents': False, 'budget_flag': False}
    state_home = '.ai'          # 状态目录挂在受限环境里主目录下的哪个位置

    def template(self, state_dir, workdir):
        """往现建的状态目录里写模板（只含必需的设置）。"""

    def sandbox_extras(self):
        """返回 (只读放进去的路径, 要设的环境变量, 从外面原样带进去的环境变量名)。"""
        return [], {}, ()

    def probe(self):
        """返回 ProbeResult。"""
        raise NotImplementedError

    def run_headless(self, run_ctx, taskpack, state_dir, timeout=None):
        raise NotImplementedError

    def resume(self, run_ctx, taskpack, state_dir, session, text, timeout=None):
        raise NotImplementedError

    def start_interactive(self, run_ctx, taskpack, state_dir):
        raise NotImplementedError
