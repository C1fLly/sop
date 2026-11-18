"""AI 工具适配器的接口（设计书 10.1）。把「交互启动」「自动调用」「续接」翻译成具体工具的命令。

四个操作：probe（自检）、start_interactive（对话方式）、run_headless（自动调用）、resume（续接并送入补充说明）。
每个操作都在受限环境里做：适配器只说明要往受限环境里放什么（程序、状态目录挂在主目录下哪里、要带进去的环境变量），
放法由受限运行器按步骤的种类定（6.3）。
"""
from dataclasses import dataclass, field


@dataclass
class Outcome:
    rc: int                      # 工具的退出码（只看它不够，9.3）
    cost: float = 0.0            # 工具报告的金额（美元）；报告不了的按适配器的估法
    session: str | None = None   # 会话编号（续接用）
    logs: list = field(default_factory=list)   # 这一步的会话日志（外面的路径），给额度报错的扫描和复盘
    text: str = ''               # 最后的回答（给人看）
    timeout: bool = False


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
        raise NotImplementedError

    def run_headless(self, run_ctx, taskpack, state_dir, timeout=None):
        raise NotImplementedError

    def resume(self, run_ctx, taskpack, state_dir, session, text, timeout=None):
        raise NotImplementedError

    def start_interactive(self, run_ctx, taskpack, state_dir):
        raise NotImplementedError
