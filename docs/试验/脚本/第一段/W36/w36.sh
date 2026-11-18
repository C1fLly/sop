#!/bin/bash
# 第一段 W36：在虚拟机里把 nvm、uv 装进 ~/tools，核对 Node、pnpm、Python、靠 Node 运行的命令都正常，且没有东西写到 ~/tools 之外。
set -eo pipefail
. /etc/profile.d/sop-proxy.sh
touch /tmp/w36.mark; sleep 1
T=$HOME/tools; mkdir -p $T/cache
# 终端启动文件里由工具包管理的那一段（4.3：告诉终端去 ~/tools 下找这些工具）
cat >> ~/.bashrc <<'RC'
# >>> SOP 工具包管理的段落（不要手改）>>>
export NVM_DIR="$HOME/tools/nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
export npm_config_cache="$HOME/tools/cache/npm"
# pnpm 12 只认 pnpm_config_ 开头的变量（第一次用 pnpm config set 会写 ~/.config/pnpm，缓存和状态落在 ~/.cache、~/.local/state）
export pnpm_config_store_dir="$HOME/tools/cache/pnpm-store" pnpm_config_cache_dir="$HOME/tools/cache/pnpm" pnpm_config_state_dir="$HOME/tools/cache/pnpm-state"
export PNPM_HOME="$HOME/tools/pnpm"; export PATH="$PNPM_HOME:$PATH"
export UV_INSTALL_DIR="$HOME/tools/uv/bin" UV_CACHE_DIR="$HOME/tools/cache/uv" UV_PYTHON_INSTALL_DIR="$HOME/tools/uv/python" UV_TOOL_DIR="$HOME/tools/uv/tools" UV_TOOL_BIN_DIR="$HOME/tools/uv/bin"
export PATH="$HOME/tools/uv/bin:$PATH"
# <<< SOP 工具包管理的段落 <<<
RC
# 装 nvm：官方安装脚本认 NVM_DIR；PROFILE=/dev/null 让它不再往启动文件里另写一份
mkdir -p $T/nvm
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | NVM_DIR=$T/nvm PROFILE=/dev/null bash >/tmp/nvm-install.log 2>&1
# 装 uv：官方安装脚本认 UV_INSTALL_DIR；UV_NO_MODIFY_PATH 让它不改启动文件
curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=$T/uv/bin UV_NO_MODIFY_PATH=1 sh >/tmp/uv-install.log 2>&1
# 用一个新的登录终端装 Node、pnpm、Python，并核对
bash -ilc '
  nvm install --lts >/tmp/node.log 2>&1 && nvm alias default "lts/*" >/dev/null
  npm install -g pnpm >/tmp/pnpm.log 2>&1
  uv python install 3.13 >/tmp/py.log 2>&1
  echo "node $(node -v)  在 $(command -v node)"
  echo "pnpm $(pnpm -v)  在 $(command -v pnpm)"
  echo "uv $(uv --version | cut -d" " -f2)  在 $(command -v uv)"
  echo "python $(uv run --no-project python -c "import sys;print(sys.version.split()[0], sys.executable)")"
  mkdir -p /tmp/w36p && cd /tmp/w36p && echo "{\"name\":\"w36\",\"version\":\"1.0.0\"}" > package.json && pnpm add -s is-number@7 >/dev/null 2>&1 && echo "pnpm 装依赖：$(node -e "console.log(require(\"is-number\")(5))")（store 在 $(pnpm store path)）"
  mkdir -p ~/.pi-like/bin && printf "#!/usr/bin/env node\nconsole.log(\"靠 Node 运行的命令：正常，node \" + process.version)\n" > ~/.pi-like/bin/pi-like && chmod +x ~/.pi-like/bin/pi-like && ~/.pi-like/bin/pi-like
'
echo "--- ~/tools 之外、这次新出现的文件（不算 .bashrc 和测试用的 .pi-like）："
find $HOME -newer /tmp/w36.mark -type f -not -path "$HOME/tools/*" -not -path "$HOME/.pi-like/*" -not -name .bashrc -not -path "$HOME/.ssh/*" 2>/dev/null | sed "s#$HOME#~#" | head -20
echo "--- ~/tools 各部分大小："; du -sh $T/nvm $T/uv $T/cache $T/pnpm 2>/dev/null | sed "s#$HOME#~#"
