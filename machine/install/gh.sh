#!/bin/bash
# 装 GitHub 的命令行 gh 到 ~/tools/gh（官方发布的压缩包，不用管理员密码；3-03 定的位置）。
# 下载后按官方的校验值核对。SOP_GH_VERSION 可以指定版本（如 2.83.0），不给就装最新发布的。
. "$(dirname "$0")/lib.sh"
case $(uname -m) in
  x86_64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) die "不支持这种处理器：$(uname -m)" ;;
esac
v=${SOP_GH_VERSION:-$(latest_tag cli/cli)}; v=${v#v}
name=gh_${v}_linux_$arch
base=https://github.com/cli/cli/releases/download/v$v
fetch "$base/$name.tar.gz" "$WORK/$name.tar.gz"
fetch "$base/gh_${v}_checksums.txt" "$WORK/sums.txt"
want=$(awk -v f="$name.tar.gz" '$2 == f {print $1}' "$WORK/sums.txt")
[ -n "$want" ] || die "官方的校验值里没有 $name.tar.gz"
(cd "$WORK" && echo "$want  $name.tar.gz" | sha256sum -c --quiet -) || die "下载的 gh 和官方的校验值对不上"
tar -xzf "$WORK/$name.tar.gz" -C "$WORK"
[ -x "$WORK/$name/bin/gh" ] || die "压缩包里没有 bin/gh"
# 先放到旁边，再换名顶上去：装到一半断了，原来那一份还在
dest=$SOP_TOOLS/gh new=$SOP_TOOLS/.gh.new.$$ old=$SOP_TOOLS/.gh.old.$$
rm -rf "$new" "$old"
cp -a "$WORK/$name" "$new"
[ -e "$dest" ] && mv "$dest" "$old"
mv "$new" "$dest"
rm -rf "$old"
GH_TELEMETRY=0 GH_NO_UPDATE_NOTIFIER=1 "$dest/bin/gh" --version
