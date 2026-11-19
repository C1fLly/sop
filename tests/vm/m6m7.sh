#!/bin/bash
# 3-11：在一台全新的虚拟机里验 M6（隔离自检：本机那份加专用 Docker 那份，通过后记登记）和 M7（全局规则）。
# 用法：tests/vm/m6m7.sh <虚拟机名字>
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），在里面跑 m6m7-guest.sh：
#   先装 bubblewrap（系统软件包）和规定位置的免管理员 Docker（M2，3-09 的安装脚本），再跑 M6、M7。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-m6m7-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
"$VM" ssh "$n" bash sop-src/tests/vm/m6m7-guest.sh
