#!/bin/bash
# 装 uv 到 ~/tools/uv/bin（设计书 4.3）。用官方的安装脚本；SOP_UV_VERSION 可以指定版本（如 0.13.9），不给就装最新的。
# UV_UNMANAGED_INSTALL：只放程序，不改终端启动文件、不在 ~/.config/uv 留记录文件
# （留了会顶掉电脑上另一份旧 uv 的记录，旧的「自己升级」就会去升级这一份）。以后升级重跑这个脚本。
. "$(dirname "$0")/lib.sh"
dest=$SOP_TOOLS/uv/bin
fetch "https://astral.sh/uv/${SOP_UV_VERSION:+$SOP_UV_VERSION/}install.sh" "$WORK/uv-install.sh"
mkdir -p "$dest"
env UV_UNMANAGED_INSTALL="$dest" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh "$WORK/uv-install.sh" \
  || die "uv 的官方安装脚本出错了"
"$dest/uv" --version
