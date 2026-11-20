# 假的安装脚本（流程沙箱 3-12），见 lib.sh：放的是假 gh（tests/fakes/gh/gh）
. "$(dirname "$0")/lib.sh"
fake_install gh 2.103.3 "$SOP_TOOLS/gh/bin/gh" "$HERE/../../gh/gh"
