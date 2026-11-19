#!/bin/bash
# 3-14：离线包（设计书 4.2 第 3 条）在虚拟机里验一遍。用法：tests/vm/offline.sh [--keep]
#   1. 能上网的虚拟机 offp（全新、one 底盘）：把工作区现在的文件做成只有一个提交的 Git 仓库拷进去，
#      在里面运行 machine/offline/pack.sh 打离线包；再在里面做一个 U 盘的镜像（FAT 格式，像普通 U 盘），把离线包拷上去。
#      U 盘镜像拷回本机 /tmp 的临时目录。打包用的下载都在那台虚拟机的 /tmp 里，本机只放这个 U 盘镜像。
#   2. 断网的虚拟机 offa（全新、one 底盘、vm.sh new --offline：虚拟机连不到本机，也连不到外面），插上 U 盘，
#      在里面跑 offline-guest.sh：先造成像桌面版（卸掉 git、curl），再照小白的做法 bash <U 盘上的离线包>。
#   做完删掉两台虚拟机和 /tmp 的临时目录（--keep 留着看）。虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 已答应）。
#   本机不起任何服务、不用 sudo、不上网（上网的只有虚拟机 offp，经本机的代理 10.0.2.2:7890）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
keep=; [ "${1:-}" = --keep ] && keep=1
P=offp O=offa
tmp=$(mktemp -d /tmp/sop-offline-vm.XXXXXX)
cleanup() {
  [ -n "$keep" ] && { echo "（留着：$tmp、虚拟机 $P、$O）"; return; }
  for n in $P $O; do "$VM" stop $n >/dev/null 2>&1 || true; "$VM" rm $n >/dev/null 2>&1 || true; done
  rm -rf "$tmp"
}
trap cleanup EXIT

echo "=== 1. 把工作区现在的文件做成工具包仓库（只有一个提交） ==="
mkdir "$tmp/work"
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -cf -) | tar -xf - -C "$tmp/work"
id=(env GIT_AUTHOR_NAME=sop-vm GIT_AUTHOR_EMAIL=sop-vm@example.invalid GIT_COMMITTER_NAME=sop-vm GIT_COMMITTER_EMAIL=sop-vm@example.invalid)
"${id[@]}" git -C "$tmp/work" init -q -b main
"${id[@]}" git -C "$tmp/work" add -A
"${id[@]}" git -C "$tmp/work" -c commit.gpgsign=false commit -q -m "工作区 $(git -C "$REPO" rev-parse --short HEAD) 加未提交的改动"
git clone -q --bare "$tmp/work" "$tmp/sop.git"
want=$(git -C "$tmp/sop.git" rev-parse main)
echo "提交 $want"

echo "=== 2. 能上网的虚拟机 $P 里打离线包 ==="
"$VM" new $P >/dev/null
"$VM" start $P
"$VM" push $P "$tmp/sop.git" /home/xiaobai/sop.git
"$VM" push $P "$REPO/machine/offline/pack.sh" /home/xiaobai/pack.sh
px=http://10.0.2.2:7890
t0=$(date +%s)
"$VM" ssh $P "cd /tmp && env http_proxy=$px https_proxy=$px no_proxy=localhost,127.0.0.1,cn.archive.ubuntu.com,security.ubuntu.com \
  bash ~/pack.sh --repo ~/sop.git --out /tmp/pkg/sop-offline-${want:0:8}-amd64.sh 2>&1 | sed 's/^/  | /'; test \${PIPESTATUS[0]} = 0" \
  || { echo "打包失败"; exit 1; }
echo "（打包用了 $(( $(date +%s) - t0 )) 秒）"
echo "  打包的电脑上 ~ 和 /tmp 里留下的："
"$VM" ssh $P 'ls -A ~ | tr "\n" " "; echo; ls /tmp | grep -c "^sop-pack" | sed "s/^/  sop-pack 临时目录个数：/"'
echo "=== 做 U 盘（FAT 格式，卷标 SOPUSB），把离线包拷上去 ==="
"$VM" ssh $P "set -e; truncate -s 160M /tmp/usb.img; /sbin/mkfs.vfat -n SOPUSB /tmp/usb.img >/dev/null; sudo mkdir -p /mnt/usb
  sudo mount -o loop,uid=\$(id -u) /tmp/usb.img /mnt/usb; cp /tmp/pkg/*.sh /mnt/usb/; ls -l /mnt/usb | sed 's/^/  U 盘上：/'; sync; sudo umount /mnt/usb"
"$VM" pull $P /tmp/usb.img "$tmp/usb.img"
"$VM" stop $P >/dev/null; "$VM" rm $P >/dev/null
echo "U 盘镜像 $(du -h "$tmp/usb.img" | cut -f1)（打包的虚拟机已删）"

echo "=== 3. 断网的虚拟机 $O：插上 U 盘，走第零步 ==="
"$VM" new $O --offline
"$VM" start $O --usb "$tmp/usb.img"
"$VM" push $O "$HERE/offline-guest.sh" /home/xiaobai/offline-guest.sh
rc=0
"$VM" ssh $O bash offline-guest.sh "$want" || rc=$?
exit $rc
