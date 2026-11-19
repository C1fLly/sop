#!/bin/bash
# 装 uv 到 ~/tools/uv/bin（设计书 4.3）。用官方的安装脚本；SOP_UV_VERSION 可以指定版本（如 0.13.9），不给就装最新的。
# UV_UNMANAGED_INSTALL：只放程序，不改终端启动文件、不在 ~/.config/uv 留记录文件
# （留了会顶掉电脑上另一份旧 uv 的记录，旧的「自己升级」就会去升级这一份）。以后升级重跑这个脚本。
# SOP_UV_ARCHIVE：离线包里带的官方压缩包（uv-<处理器>-unknown-linux-gnu.tar.gz，3-14），给了就不下载、直接从它装。
. "$(dirname "$0")/lib.sh"
dest=$SOP_TOOLS/uv/bin
if [ -n "${SOP_UV_ARCHIVE:-}" ]; then
  [ -f "$SOP_UV_ARCHIVE" ] || die "没有 uv 的压缩包：$SOP_UV_ARCHIVE"
  tar -xzf "$SOP_UV_ARCHIVE" -C "$WORK" || die "uv 的压缩包解不开：$SOP_UV_ARCHIVE"
  src=$(find "$WORK" -type f -name uv | head -1)
  [ -n "$src" ] && [ -x "$src" ] || die "uv 的压缩包里没有 uv"
  src=$(dirname "$src")
  mkdir -p "$dest"
  for f in uv uvx; do
    [ -f "$src/$f" ] || continue
    install -m 755 "$src/$f" "$dest/.$f.new" && mv "$dest/.$f.new" "$dest/$f" || die "uv 放不进 $dest"
  done
  "$dest/uv" --version
  exit 0
fi
fetch "https://astral.sh/uv/${SOP_UV_VERSION:+$SOP_UV_VERSION/}install.sh" "$WORK/uv-install.sh"
mkdir -p "$dest"
env UV_UNMANAGED_INSTALL="$dest" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh "$WORK/uv-install.sh" \
  || die "uv 的官方安装脚本出错了"
"$dest/uv" --version
