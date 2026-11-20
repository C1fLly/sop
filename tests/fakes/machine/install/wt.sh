# 假的安装脚本（流程沙箱 3-12），见 lib.sh：放的是假 wt（tests/fakes/machine/wt）
. "$(dirname "$0")/lib.sh"
fake_install wt 1.3.1 "$SOP_TOOLS/wt/wt" "$HERE/../wt"
