#!/bin/bash
# 3-37：在虚拟机里造「加密磁盘、系统和主目录是两个逻辑卷」「btrfs 两个子卷」两种，看体检（machine/disks.py、
# machine/space.py、sop machine doctor）判得对不对、剩余空间提醒出不出来。
# 用法：tests/vm/disks.sh <虚拟机名字> [--capture <本机目录>]
#   虚拟机要先建好、带一块空白盘：tests/vm/vm.sh new <名字> --extra 80G（底盘 one）。脚本只动那块空白盘，
#   跑过一遍之后要再跑，先 vm.sh stop、vm.sh reset。--capture 把每一种的 lsblk、findmnt 原样输出和体检报告取回本机
#   （单元测试 tests/unit/test_machine_disks.py 的真输出样例从这里来，放在 tests/fakes/disks/）。
# 做法见 disks-guest.sh 开头：系统「装在」逻辑卷或子卷上，是新开一个挂载空间换根造的，不是真从那里开机。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
out=
[ "${1:-}" = --capture ] && out=${2:?要给本机目录}
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-dk-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
rc=0
"$VM" ssh "$n" bash sop-src/tests/vm/disks-guest.sh || rc=$?
if [ -n "$out" ]; then
  "$VM" ssh "$n" 'tar -czf ~/dk-out.tgz -C ~ dk-out'
  mkdir -p "$out"; "$VM" pull "$n" /home/xiaobai/dk-out.tgz "$tmp/dk-out.tgz"; tar -xzf "$tmp/dk-out.tgz" -C "$out"
  echo "取回到 $out/dk-out"
fi
exit $rc
