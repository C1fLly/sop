"""内核里用的几种错误。message 一律写给小白看的大白话。"""


class SopError(Exception):
    """流程命令停下来的原因。"""


class Busy(SopError):
    """同一个项目已经有一个 sop 在推进流程（设计书 8.4）。"""


class Tampered(SopError):
    """特权侧要用的文件被改过（设计书 6.4 第四层）。"""


class ToolkitBug(SopError):
    """工具包自己的问题（出口检查的脚本崩了、回放对不上等，设计书 16.5）。"""
