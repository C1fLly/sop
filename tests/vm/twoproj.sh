#!/bin/bash
# 3-19：验收「两个项目同时开」。在一台全新的虚拟机里跑两个项目（名字故意取 app 和 app-idle：3-18 的计时器名在这两个名字上撞过），
# 用法：tests/vm/twoproj.sh <虚拟机名字>
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），分两段跑 twoproj-guest.sh：
#   第一段：装 M2；两个项目同时分配端口（不打架，登记外被占的端口也让开）；两个专用 Docker 同时起，里面起同名的容器、数据卷、网络，
#           各自映射自己分到的端口，互不影响（看得到的、数据、删一个、超内存都只管自己）；受限环境里经各自的通道只看到自己的；
#           一个放开后按时停、另一个照常；最后两个都开着；
#   重启虚拟机（两个专用 Docker 都开着时）；
#   第二段：按问题 1 的答案验：重启后两个都不自己起来；两个同时要用时各自起来，镜像、数据卷、容器、端口登记都在；收拾干净。
#   为了不等 15 分钟，闲多久停用 --idle 120（2 分钟）；计时器每分钟看一次，和正式的一样。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装 Docker、起停专用 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-twoproj-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
rc=0
"$VM" ssh "$n" bash sop-src/tests/vm/twoproj-guest.sh one || rc=1
echo; echo "=== 重启虚拟机（两个专用 Docker 都开着）==="
"$VM" stop "$n"
"$VM" start "$n"
"$VM" ssh "$n" bash sop-src/tests/vm/twoproj-guest.sh two || rc=1
exit $rc
