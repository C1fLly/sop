"""从安装的版本目录执行内核：python -I <版本目录>/kernel/main.py <参数>。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from kernel.cli import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
