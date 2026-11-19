#!/bin/bash
# 3-09：在一台全新的虚拟机里验 M2 安装免管理员的 Docker（machine/install/docker-rootless.sh）。
# 用法：tests/vm/docker.sh <虚拟机名字> [--system | --rootless] [--broken] [--reboot]
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），在里面跑 docker-guest.sh。
#   --system  ：先用 Ubuntu 软件源装一份系统自带的 docker.io（小白在 docker 组里，能直接用），起一个容器，看 --force 和默认指向切回
#   --rootless：先照官方一条命令的装法装一份免管理员的（程序在 ~/bin，服务名 docker），起一个容器，看服务名被占时另起 sop-docker
#   --broken  ：先让它装到一半失败一次（Docker 起不来），看收拾干净了、再正常装
#   --reboot  ：装完重启一次虚拟机，看登录后 Docker 自己起来、网络模块还在、容器能跑
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装和卸 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
mode=; reboot=; broken=
for a in "$@"; do case $a in --system|--rootless) mode=$a ;; --reboot) reboot=1 ;; --broken) broken=--broken ;; *) echo "不认识：$a" >&2; exit 2 ;; esac; done
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-docker-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
rc=0
[ -n "$mode" ] && "$VM" ssh "$n" bash sop-src/tests/vm/docker-guest.sh --prepare $mode
"$VM" ssh "$n" bash sop-src/tests/vm/docker-guest.sh $mode $broken || rc=$?
if [ -n "$reboot" ]; then
  echo; echo "=== 重启虚拟机，看登录后 Docker 自己起来 ==="
  "$VM" stop "$n"; "$VM" start "$n"
  "$VM" ssh "$n" bash sop-src/tests/vm/docker-guest.sh --after-reboot $mode || rc=$?
fi
exit $rc
