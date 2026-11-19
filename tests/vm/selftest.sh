#!/bin/bash
# 3-02 的自测：真的起虚拟机，几分钟。不在 run_all.py 里（那里不开虚拟机）。
#   1. 底盘 one 建一台、开机、写一个文件、关机、还原、再开机，文件没了；新建和还原各用几秒
#   2. 底盘 home 加一块空白盘建一台：/home 在第二块盘上、第三块盘是空的
#   3. 第一段的 vm-a、vm-b 磁盘文件一个字节没变
set -euo pipefail
VM=$(dirname "$0")/vm.sh
V=${SOP_VM_HOME:-~/sop-vm}
t1=selftest-one-$$ t2=selftest-home-$$
fail=0
ok()  { echo "符合   $*"; }
bad() { echo "不符合 $*"; fail=1; }
cleanup() { for n in $t1 $t2; do "$VM" stop $n >/dev/null 2>&1 || true; "$VM" rm $n >/dev/null 2>&1 || true; done; }
trap cleanup EXIT

ab_before=$(cd "$V" && md5sum vm-a-root.qcow2 vm-a-home.qcow2 vm-b-root.qcow2 2>/dev/null || true)

echo "== 1. 新建、写文件、还原 =="
s=$(date +%s); "$VM" new $t1; ok "新建用了 $(( $(date +%s) - s )) 秒（底盘第一次要做的话含做底盘）"
s=$(date +%s); "$VM" start $t1; echo "（开机到能登录 $(( $(date +%s) - s )) 秒）"
[ "$("$VM" ssh $t1 hostname)" = "sop-vm-$t1" ] && ok "主机名是 sop-vm-$t1" || bad "主机名不对：$("$VM" ssh $t1 hostname)"
"$VM" ssh $t1 'sudo -n true' && ok "虚拟机里 sudo 免密码" || bad "虚拟机里 sudo 要密码"
"$VM" ssh $t1 'echo 还原前写的 > ~/marker; sudo sh -c "echo x > /etc/sop-marker"; sync'
"$VM" ssh $t1 'test -f ~/marker && test -f /etc/sop-marker' && ok "写进去了（主目录和系统目录各一个）" || bad "没写进去"
mid1=$("$VM" ssh $t1 cat /etc/machine-id)
"$VM" stop $t1
s=$(date +%s); "$VM" reset $t1; ok "还原用了 $(( $(date +%s) - s )) 秒"
"$VM" start $t1
"$VM" ssh $t1 'test ! -e ~/marker && test ! -e /etc/sop-marker' && ok "还原后两个文件都没了" || bad "还原后文件还在"
mid2=$("$VM" ssh $t1 cat /etc/machine-id)
[ -n "$mid1" ] && [ "$mid1" != "$mid2" ] && ok "还原后机器编号重新生成了" || bad "机器编号没变：$mid1 / $mid2"
"$VM" ssh $t1 '. /etc/profile.d/sop-proxy.sh; curl -sS -o /dev/null -w "%{http_code}" --max-time 20 https://github.com' | grep -q '^[23]' \
  && ok "能经本机代理上网" || bad "上不了网"
lsblk_one=$("$VM" ssh $t1 'findmnt -no SOURCE /; findmnt -no SOURCE /home || echo 无单独挂载')
echo "$lsblk_one" | sed -n 2p | grep -q 无单独挂载 && ok "底盘 one：/home 没有单独分区" || bad "底盘 one 的 /home：$lsblk_one"
"$VM" stop $t1

echo "== 2. 主目录单独一块盘、加一块空白盘 =="
"$VM" new $t2 --layout home --extra 2G
"$VM" start $t2
src=$("$VM" ssh $t2 'findmnt -no SOURCE /home')
[[ $src == /dev/vdb* ]] && ok "/home 在第二块盘上（$src）" || bad "/home 在 $src"
x=$("$VM" ssh $t2 'lsblk -dnbo NAME,SIZE /dev/vdc; lsblk -no NAME /dev/vdc | wc -l')
echo "$x" | head -1 | grep -q '^vdc 2147483648$' && [ "$(echo "$x" | tail -1)" = 1 ] && ok "第三块盘 2G、没分区" || bad "第三块盘：$x"
"$VM" ssh $t2 'test -d ~ && touch ~/w' && ok "xiaobai 的主目录在单独的盘上能写" || bad "主目录写不了"
"$VM" stop $t2

echo "== 3. 第一段的两台没被动过 =="
ab_after=$(cd "$V" && md5sum vm-a-root.qcow2 vm-a-home.qcow2 vm-b-root.qcow2 2>/dev/null || true)
[ "$ab_before" = "$ab_after" ] && ok "vm-a、vm-b 的磁盘文件校验值没变" || bad "vm-a、vm-b 的磁盘文件变了"

[ $fail = 0 ] && echo "全部符合" || { echo "有不符合的"; exit 1; }
