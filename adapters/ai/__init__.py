"""AI 工具适配器（设计书第 10 节）。流程引擎按名字取适配器：load('claude')。

有哪些：claude（Claude Code，第 1 期唯一的真适配器）；fake（假 AI，只给流程沙箱和自测用，16.2）。
Codex、OpenCode、Pi 的适配器第 5 期做。"""
import importlib

ADAPTERS = {
    'claude': ('adapters.ai.claude.adapter', 'ClaudeAdapter'),
    'fake': ('adapters.ai.fake.adapter', 'FakeAdapter'),
}
REAL = ('claude',)          # 项目的 sop.json 里能写的（假 AI 只能经 SOP_AI 环境变量给流程沙箱、自测用）
DEFAULT = 'claude'


def load(name):
    if name not in ADAPTERS:
        raise KeyError(name)
    mod, cls = ADAPTERS[name]
    return getattr(importlib.import_module(mod), cls)()
