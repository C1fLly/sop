#!/bin/bash
# 3-14：离线包（设计书 4.2 第 3 条）在虚拟机里验一遍。3-51 加了发版用的两种用法。
#   tests/vm/offline.sh [--keep]                                  打工作区现在的文件（3-14）
#   tests/vm/offline.sh --repo <仓库地址> [--save <本机目录>]      发版：打这个仓库（例如 https://github.com/C1fLly/sop.git）
#                                                                 的 main，用的是那个提交里的 pack.sh；--save 把离线包另存一份到本机
#   tests/vm/offline.sh --url <下载地址> [--sha256 <校验值>]       验发出去的那份：不打包，能上网的虚拟机从这个地址下载
#                                                                 （例如 Releases 上的地址）；给了 --sha256 就核对下下来的和它一样
# 过程：
#   1. 能上网的虚拟机 offp（全新、one 底盘）：打离线包（或下载）；再在里面做一个 U 盘的镜像（FAT 格式，像普通 U 盘），
#      把离线包拷上去。U 盘镜像拷回本机 /tmp 的临时目录。打包、下载都在那台虚拟机的 /tmp 里，本机只放这个 U 盘镜像
#      （和 --save 的那一份）。
#   2. 断网的虚拟机 offa（全新、one 底盘、vm.sh new --offline：虚拟机连不到本机，也连不到外面），插上 U 盘，
#      在里面跑 offline-guest.sh：先造成像桌面版（卸掉 git、curl），再照小白的做法 bash <U 盘上的离线包>。
#   做完删掉两台虚拟机和 /tmp 的临时目录（--keep 留着看）。虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 已答应）。
#   本机不起任何服务、不用 sudo、不上网（上网的只有虚拟机 offp，经本机的代理 10.0.2.2:7890）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
keep= from_repo= save= url= sha=
while [ $# -gt 0 ]; do
  case $1 in
    --keep) keep=1; shift ;;
    --repo) from_repo=${2:?--repo 后面要给仓库地址}; shift 2 ;;
    --save) save=${2:?--save 后面要给本机目录}; shift 2 ;;
    --url) url=${2:?--url 后面要给下载地址}; shift 2 ;;
    --sha256) sha=${2:?--sha256 后面要给校验值}; shift 2 ;;
    *) echo "不认识的选项：$1" >&2; exit 2 ;;
  esac
done
[ -n "$from_repo" ] && [ -n "$url" ] && { echo "--repo 和 --url 只能给一个" >&2; exit 2; }
[ -n "$save" ] && [ -z "$from_repo" ] && { echo "--save 要和 --repo 一起用" >&2; exit 2; }
[ -n "$sha" ] && [ -z "$url" ] && { echo "--sha256 要和 --url 一起用" >&2; exit 2; }
[ -n "$save" ] && { [ -d "$save" ] || { echo "没有这个目录：$save" >&2; exit 2; }; }
P=offp O=offa
tmp=$(mktemp -d /tmp/sop-offline-vm.XXXXXX)
cleanup() {
  [ -n "$keep" ] && { echo "（留着：$tmp、虚拟机 $P、$O）"; return; }
  for n in $P $O; do "$VM" stop $n >/dev/null 2>&1 || true; "$VM" rm $n >/dev/null 2>&1 || true; done
  rm -rf "$tmp"
}
trap cleanup EXIT
px=http://10.0.2.2:7890
net="env http_proxy=$px https_proxy=$px no_proxy=localhost,127.0.0.1,cn.archive.ubuntu.com,security.ubuntu.com"

"$VM" new $P >/dev/null
"$VM" start $P
if [ -n "$url" ]; then
  echo "=== 1. 能上网的虚拟机 $P 从下载地址取离线包（不打包） ==="
  echo "地址：$url"
  "$VM" ssh $P "set -eo pipefail; mkdir -p /tmp/pkg; cd /tmp/pkg; $net wget --no-hsts -nv -T 30 -t 5 '$url' 2>&1 | sed 's/^/  | /'
    ls -l /tmp/pkg | sed 's/^/  下下来的：/'" || { echo "下载失败"; exit 1; }
elif [ -n "$from_repo" ]; then
  echo "=== 1. 能上网的虚拟机 $P 里打离线包：仓库 $from_repo 的 main，用那个提交里的 pack.sh ==="
  t0=$(date +%s)
  "$VM" ssh $P "set -e; $net git clone -q --branch main '$from_repo' ~/src; echo \"  取到 main：\$(git -C ~/src rev-parse HEAD)\"
    cd /tmp && $net bash ~/src/machine/offline/pack.sh --repo ~/src --out /tmp/pkg/sop-offline-\$(git -C ~/src rev-parse --short=8 HEAD)-amd64.sh 2>&1 | sed 's/^/  | /'
    test \${PIPESTATUS[0]} = 0" || { echo "打包失败"; exit 1; }
  echo "（打包用了 $(( $(date +%s) - t0 )) 秒）"
else
  echo "=== 1. 把工作区现在的文件做成工具包仓库（只有一个提交），在能上网的虚拟机 $P 里打离线包 ==="
  mkdir "$tmp/work"
  (cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -cf -) | tar -xf - -C "$tmp/work"
  id=(env GIT_AUTHOR_NAME=sop-vm GIT_AUTHOR_EMAIL=sop-vm@example.invalid GIT_COMMITTER_NAME=sop-vm GIT_COMMITTER_EMAIL=sop-vm@example.invalid)
  "${id[@]}" git -C "$tmp/work" init -q -b main
  "${id[@]}" git -C "$tmp/work" add -A
  "${id[@]}" git -C "$tmp/work" -c commit.gpgsign=false commit -q -m "工作区 $(git -C "$REPO" rev-parse --short HEAD) 加未提交的改动"
  git clone -q --bare "$tmp/work" "$tmp/sop.git"
  echo "提交 $(git -C "$tmp/sop.git" rev-parse main)"
  "$VM" push $P "$tmp/sop.git" /home/xiaobai/sop.git
  "$VM" push $P "$REPO/machine/offline/pack.sh" /home/xiaobai/pack.sh
  t0=$(date +%s)
  want=$(git -C "$tmp/sop.git" rev-parse main)
  "$VM" ssh $P "cd /tmp && $net bash ~/pack.sh --repo ~/sop.git --out /tmp/pkg/sop-offline-${want:0:8}-amd64.sh 2>&1 | sed 's/^/  | /'; test \${PIPESTATUS[0]} = 0" \
    || { echo "打包失败"; exit 1; }
  echo "（打包用了 $(( $(date +%s) - t0 )) 秒）"
fi
"$VM" ssh $P '[ "$(ls /tmp/pkg/sop-offline-*-amd64.sh | wc -l)" = 1 ]' || { echo "/tmp/pkg 下没有、或者不止一个离线包"; exit 1; }
name=$("$VM" ssh $P 'basename /tmp/pkg/sop-offline-*-amd64.sh')
got=$("$VM" ssh $P "sha256sum /tmp/pkg/$name | cut -d' ' -f1")
# 离线包第 2 行写着它带的工具包提交（machine/offline/header.sh）
want=$("$VM" ssh $P "sed -n 2p /tmp/pkg/$name | grep -oE '[0-9a-f]{40}' | head -1")
[ -n "$want" ] || { echo "离线包第 2 行看不出工具包提交：$name"; exit 1; }
echo "离线包：$name，sha256 $got，工具包提交 $want"
if [ -n "$sha" ]; then
  [ "$got" = "$sha" ] && echo "  对：和给的校验值一样" || { echo "  不对：和给的校验值 $sha 不一样"; exit 1; }
fi
if [ -n "$from_repo" ]; then
  echo "  打包的电脑上 ~ 和 /tmp 里留下的："
  "$VM" ssh $P 'ls -A ~ | tr "\n" " "; echo; ls /tmp | grep -c "^sop-pack" | sed "s/^/  sop-pack 临时目录个数：/"'
fi
if [ -n "$save" ]; then
  "$VM" pull $P "/tmp/pkg/$name" "$save/$name"
  [ "$(sha256sum "$save/$name" | cut -d' ' -f1)" = "$got" ] || { echo "拷回本机的和虚拟机里的不一样"; exit 1; }
  echo "另存到本机：$save/$name"
fi
echo "=== 做 U 盘（FAT 格式，卷标 SOPUSB），把离线包拷上去 ==="
"$VM" ssh $P "set -e; truncate -s 160M /tmp/usb.img; /sbin/mkfs.vfat -n SOPUSB /tmp/usb.img >/dev/null; sudo mkdir -p /mnt/usb
  sudo mount -o loop,uid=\$(id -u) /tmp/usb.img /mnt/usb; cp /tmp/pkg/$name /mnt/usb/; ls -l /mnt/usb | sed 's/^/  U 盘上：/'; sync; sudo umount /mnt/usb"
"$VM" pull $P /tmp/usb.img "$tmp/usb.img"
"$VM" stop $P >/dev/null; "$VM" rm $P >/dev/null
echo "U 盘镜像 $(du -h "$tmp/usb.img" | cut -f1)（能上网的虚拟机已删）"

echo "=== 2. 断网的虚拟机 $O：插上 U 盘，走第零步 ==="
"$VM" new $O --offline
"$VM" start $O --usb "$tmp/usb.img"
"$VM" push $O "$HERE/offline-guest.sh" /home/xiaobai/offline-guest.sh
rc=0
"$VM" ssh $O bash offline-guest.sh "$want" || rc=$?
exit $rc
