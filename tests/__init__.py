# 自测的保险（3-59）：tests 这个包一被导入，整个测试进程就换成 /tmp 下的假主目录，见 safehome.py。
from . import safehome  # noqa: F401
