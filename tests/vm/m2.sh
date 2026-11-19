#!/bin/bash
# 3-08：在一台全新的虚拟机里验 M2 安装的 uv、nvm、Node、pnpm、gh，缓存目录，终端启动文件里那一段。
# 用法：tests/vm/m2.sh <虚拟机名字> [--old]
#   虚拟机要先 vm.sh new <名字> 建好（会自己开机）。把工作区的代码打包拷进去（~/sop-src），在里面跑 m2-guest.sh。
#   --old：先用各工具官方的默认装法装一份旧的（~/.nvm、~/.local/bin/uv、~/.local/share/pnpm），看新的照装不误、旧的不动。
# 只开虚拟机，不用 sudo（虚拟机里也不用）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-m2.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
"$VM" ssh "$n" bash sop-src/tests/vm/m2-guest.sh "$@"
