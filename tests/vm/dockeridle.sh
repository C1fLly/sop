#!/bin/bash
# 3-18：在一台全新的虚拟机里验专用 Docker「用时才起、闲了停」（runner/docker/service.py 的 use()、闲了停的计时器）。
# 用法：tests/vm/dockeridle.sh <虚拟机名字>
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），分两段跑 dockeridle-guest.sh：
#   第一段：装 M2；起、拿着用（超过闲的时间也不停）、放开后按时停、再起数据都在、sop 被强制结束也会停、
#           正在停的时候 sop 要用（等停完再起）、两个 sop 同时用、走 kernel/engine.py 的 docker()、没经 sop 用过的不停；
#   重启虚拟机；
#   第二段：重启后没有自己起来，要用时起来，镜像、数据卷、容器都在；收拾干净。
#   为了不等 15 分钟，闲多久停用 --idle 120（2 分钟）；计时器每分钟看一次，和正式的一样。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装 Docker、起停专用 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-dockeridle-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
rc=0
"$VM" ssh "$n" bash sop-src/tests/vm/dockeridle-guest.sh one || rc=1
echo; echo "=== 重启虚拟机 ==="
"$VM" stop "$n"
"$VM" start "$n"
"$VM" ssh "$n" bash sop-src/tests/vm/dockeridle-guest.sh two || rc=1
exit $rc
