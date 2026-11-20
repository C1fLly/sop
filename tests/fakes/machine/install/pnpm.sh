# 假的安装脚本（流程沙箱 3-12），见 lib.sh
. "$(dirname "$0")/lib.sh"
fake_install pnpm 12.21.0 "$SOP_TOOLS/nvm/bin/pnpm"
