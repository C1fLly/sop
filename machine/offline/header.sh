#!/bin/bash
# SOP 工具包的离线包（设计书 4.2 第 3 条；任务 3-14）。工具包提交 @VERSION@，Ubuntu 26.04（@ARCH@）用。
#
# 给完全连不上外网的电脑用：在另一台能上网的电脑上下载这个文件，用 U 盘拷过来，在终端里执行
#   bash <这个文件>
# （可以把文件从文件管理器拖进终端，路径就填好了。）
# 它先核对文件有没有拷坏，再解到 /tmp 下的临时目录，运行里面的第零步（bootstrap.sh --offline）；做完把临时目录删掉。
# 里面有：第零步、git 和 curl 的系统软件包（连同它们要的）、uv、工具包本身（Git 打包文件）。
set -uo pipefail
SHA=@PAYLOAD_SHA256@
die() { printf '\n没做完：%s\n' "$*" >&2; exit 1; }
self=$0
[ -f "$self" ] && [ -r "$self" ] || die "读不到离线包文件：$self（要用 bash <文件> 运行，不要用管道）"
line=$(awk '/^__SOP_PAYLOAD_BELOW__$/ { print NR + 1; exit }' "$self")
[ -n "$line" ] || die "这个文件不是完整的离线包：重新从另一台电脑拷一次"
printf '核对离线包有没有拷坏……\n'
got=$(tail -n +"$line" "$self" | sha256sum | cut -d' ' -f1)
[ "$got" = "$SHA" ] || die "离线包拷坏了或者没拷完：重新从另一台电脑拷一次（拷完在 U 盘上点「弹出」再拔）"
dir=$(mktemp -d /tmp/sop-offline.XXXXXX) || die "在 /tmp 下建不了临时目录"
trap 'rm -rf "$dir"' EXIT
chmod 755 "$dir"      # 装系统软件包时，系统的下载程序（_apt 账号）要读得到里面的软件包
tail -n +"$line" "$self" | tar -xf - -C "$dir" || die "离线包解不开（/tmp 的空间不够？）"
bash "$dir/bootstrap.sh" --offline "$dir" "$@"
exit $?
__SOP_PAYLOAD_BELOW__
