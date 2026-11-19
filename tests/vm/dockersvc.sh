#!/bin/bash
# 3-17、3-54：在一台全新的虚拟机里验专用 Docker 的正式后台服务和分组（runner/docker/service.py）。
# 用法：tests/vm/dockersvc.sh <虚拟机名字>
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），在里面跑 dockersvc-guest.sh：
#   先装 bubblewrap 和规定位置的免管理员 Docker（M2），再验：服务和分组的样子、容器落在分组里、超内存容器被杀而专用 Docker 还在、
#   处理器上限生效、视野只读、隔离自检专用 Docker 那份 13 项（用正式服务起）、M6 两份合起来。
#   超内存那一步（3-54）连演 OOM_N 次（默认 24）：专用 Docker 一次都不被杀；同项目另一个容器停没停也记下（3-55）。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装 Docker、起停专用 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-dockersvc-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
"$VM" ssh "$n" bash sop-src/tests/vm/dockersvc-guest.sh
