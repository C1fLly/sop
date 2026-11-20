#!/bin/bash
# 3-56：在虚拟机里验「系统正在自己更新软件、占着软件包的锁」时，M2 和第零步装系统软件包会等它（machine/install/apt.sh）。
# 用法：tests/vm/aptlock.sh <虚拟机名字> [--boot <遍数>]
#   虚拟机要先 vm.sh new <名字> 建好。把工作区的代码打包拷进去（~/sop-src），在里面跑 aptlock-guest.sh。
#   不带 --boot：一台全新的虚拟机里，用一个小程序占住三把锁里的一把（像系统自己在更新那样），再装：
#                M2（install.py）三把锁各一遍、等不到时怎么说、真让系统自己起更新（apt-daily）、第零步（bootstrap.sh）、
#                Docker 的安装脚本（docker-rootless.sh）
#   --boot <遍数>：每遍先还原成全新、开机，一登录进去马上跑 M2 装 bubblewrap、uidmap（3-55 就是这样碰到的）
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo）。不进 run_all.py。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
boot=
[ "${1:-}" = --boot ] && boot=${2:?--boot 后面要给遍数}
tmp=$(mktemp -d /tmp/sop-aptlock-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
push() {
  "$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
  "$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
}
rc=0
if [ -z "$boot" ]; then
  "$VM" start "$n"
  push
  "$VM" ssh "$n" bash sop-src/tests/vm/aptlock-guest.sh || rc=$?
  exit $rc
fi
for i in $(seq 1 "$boot"); do
  echo; echo "######## 第 $i 遍：还原成全新、开机、马上跑 M2 ########"
  "$VM" stop "$n" >/dev/null 2>&1 || true
  "$VM" reset "$n" >/dev/null
  "$VM" start "$n" | tail -1
  push
  "$VM" ssh "$n" bash sop-src/tests/vm/aptlock-guest.sh --boot || rc=1
done
exit $rc
