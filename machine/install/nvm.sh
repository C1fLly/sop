#!/bin/bash
# 装 nvm 到 ~/tools/nvm（设计书 4.3）。用官方的安装脚本；SOP_NVM_VERSION 可以指定版本（如 v0.40.3），不给就装最新发布的。
# PROFILE=/dev/null：不改终端启动文件；METHOD=script：只下载那几个脚本文件，不用 git。
. "$(dirname "$0")/lib.sh"
tag=${SOP_NVM_VERSION:-$(latest_tag nvm-sh/nvm)}
fetch "https://raw.githubusercontent.com/nvm-sh/nvm/$tag/install.sh" "$WORK/nvm-install.sh"
mkdir -p "$SOP_TOOLS/nvm"
env NVM_DIR="$SOP_TOOLS/nvm" PROFILE=/dev/null METHOD=script bash "$WORK/nvm-install.sh" \
  || die "nvm 的官方安装脚本出错了"
use_nvm
nvm --version || die "装完了却载入不了 nvm"
