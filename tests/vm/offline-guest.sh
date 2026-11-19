#!/bin/bash
# 在断网的虚拟机里跑（由 offline.sh 拷进去、启动）。用法：offline-guest.sh <工具包的提交编号>
#   先看断网是真的（GitHub、软件源、本机的代理都连不上），再造成像桌面版（卸掉 git、curl），
#   像桌面那样把 U 盘挂到 /media/xiaobai/SOPUSB，照小白的做法 bash <U 盘上的离线包>；
#   再跑一遍看都跳过；最后拷一份改坏一个字节的，看它停下、什么都不改。
set -uo pipefail
WANT=${1:?}
fails=0
step() { echo; echo "=== $* ==="; }
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fails=$((fails + 1)); fi; }
clean_env=(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY -u all_proxy -u ALL_PROXY)
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")"

step "断网是真的"
must "! ${clean_env[*]} wget --no-hsts -q --spider -T 5 -t 1 https://github.com/" "直连 GitHub 连不上"
must "! ${clean_env[*]} wget --no-hsts -q --spider -T 5 -t 1 http://cn.archive.ubuntu.com/ubuntu/" "直连软件源连不上"
must "! ${clean_env[*]} https_proxy=http://10.0.2.2:7890 wget --no-hsts -q --spider -T 5 -t 1 https://github.com/" "经本机的代理也连不上"
must "! ip route | grep -q default || ! ${clean_env[*]} wget --no-hsts -q -T 5 -t 1 -O /dev/null http://10.0.2.2:7890/" "连不到本机"

step "造成像桌面版：卸掉 git、curl"
sudo env DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq git curl 2>&1 | grep -E '^(Removing|Purging)' | sed 's/^/  /'
must '! command -v git >/dev/null && ! command -v curl >/dev/null' "git、curl 都没了"
must '[ ! -e ~/tools ]' "~/tools 还没有"

step "插上的 U 盘：像桌面那样挂到 /media/xiaobai/SOPUSB"
dev=$(readlink -f /dev/disk/by-label/SOPUSB 2>/dev/null)
must '[ -b "$dev" ]' "认出 U 盘（$dev，$(lsblk -no TRAN,RM "$(echo "$dev" | sed "s/[0-9]*$//")" 2>/dev/null | head -1)）"
sudo mkdir -p /media/xiaobai/SOPUSB
sudo mount -o uid=$(id -u),gid=$(id -g) "$dev" /media/xiaobai/SOPUSB
pkg=$(ls /media/xiaobai/SOPUSB/sop-offline-*.sh 2>/dev/null | head -1)
must '[ -f "$pkg" ]' "U 盘上有离线包（$(basename "$pkg")，$(du -h "$pkg" | cut -f1)）"
apt_before=$(sudo find /etc/apt /var/lib/apt/lists -newer /etc/hostname -printf '%p\n' 2>/dev/null | sort | md5sum)
sources_before=$(cat /etc/apt/sources.list.d/* 2>/dev/null | md5sum)
sleep 1; touch /tmp/off.mark; sleep 1

step "第零步：bash <U 盘上的离线包>（小白什么都不用答，只输一次管理员密码）"
t0=$(date +%s)
"${clean_env[@]}" bash "$pkg" </dev/null > /tmp/off-1.log 2>&1
rc=$?
sed 's/^/  | /' /tmp/off-1.log
echo "（退出码 $rc，用了 $(( $(date +%s) - t0 )) 秒）"
must "[ $rc = 0 ]" "第零步做完了"

step "做完之后看"
S=~/tools/sop
must '[ "$(cat $S/versions/latest 2>/dev/null)" = "$WANT" ]' "versions/latest 是 ${WANT:0:8}"
must '[ "$(git -C $S/versions/$WANT rev-parse HEAD 2>/dev/null)" = "$WANT" ]' "~/tools/sop/versions/<提交编号> 就是这个提交"
must '[ -z "$(git -C $S/versions/$WANT status --porcelain --untracked-files=no 2>/dev/null)" ]' "版本目录没被改过"
must '[ -x ~/tools/uv/bin/uv ]' "uv 在 ~/tools/uv/bin（$(~/tools/uv/bin/uv --version 2>/dev/null)）"
must 'command -v git >/dev/null && command -v curl >/dev/null' "git、curl 装上了（$(git --version 2>/dev/null)，$(curl --version 2>/dev/null | head -1 | cut -d' ' -f1-2)）"
echo "  网络设置："; sed 's/^/    /' $S/config/network.json
must "! grep -q proxy $S/config/network.json" "网络设置记的是「不用代理」"
must "grep -q '用的是离线包' /tmp/off-1.log && ! grep -q '连得上\|连不上' /tmp/off-1.log" "没试连网络、没问代理"
must "grep -q '主目录不在系统盘上\|只有一个能用的 Linux 分区\|另有分区没用上\|看不出来' /tmp/off-1.log" "报告了主目录在哪个分区"
must "grep -q 'sop machine setup' /tmp/off-1.log" "最后提示 sop machine setup"
must "! grep -q '^W: \|^E: ' /tmp/off-1.log" "apt 没报警告或错误"
must '[ -z "$(ls -d /tmp/sop-offline.* /tmp/sop-offline-apt.* 2>/dev/null)" ]' "解开的临时目录、apt 的临时目录都删了"
must '[ "$(cat /etc/apt/sources.list.d/* 2>/dev/null | md5sum)" = "$sources_before" ] && [ ! -e /etc/apt/sources.list.d/sop-offline.list ]' "系统的软件源设置没动"
must '[ -z "$(sudo find /var/lib/apt/lists -newer /tmp/off.mark 2>/dev/null)" ]' "系统的软件源索引没动（没换成离线包的）"

step "新开一个终端（读 ~/.bashrc）：敲 sop 能用（还是断网）"
bash -ic 'echo "sop → $(command -v sop)；uv → $(command -v uv)"; sop machine tools | head -3' 2>&1 | grep -v -e 'terminal process group' -e 'job control' | sed 's/^/  /'
must "bash -ic 'sop machine tools' >/dev/null 2>&1" "新开的终端里 sop machine tools 能运行"
echo "  体检（只看不记）的前几行："
bash -ic 'sop machine doctor --readonly' 2>&1 | grep -v -e 'terminal process group' -e 'job control' | head -12 | sed 's/^/    /'

step "~/tools 之外，这次新出现或改动过的东西（主目录里）"
find ~ -newer /tmp/off.mark -not -path "$HOME/tools/*" -not -path "$HOME/.ssh*" -not -name offline-guest.sh -printf '%y %p\n' | sed "s#$HOME#~#"
echo "  ~/tools 下：$(ls ~/tools | tr '\n' ' ')；大小 $(du -sh ~/tools | cut -f1)"

step "再跑一遍离线包：都跳过、不要密码"
before=$(stat -c '%n %Y' ~/.bashrc $S/sop $S/launcher.py $S/versions/latest)
sleep 1
"${clean_env[@]}" bash "$pkg" </dev/null > /tmp/off-2.log 2>&1
rc=$?
grep -e '跳过' -e '没改' -e '没做完' -e 'sop 能运行' /tmp/off-2.log | sed 's/^/  | /'
must "[ $rc = 0 ]" "第二遍也做完了"
must "grep -q 'git、curl 都有了，跳过' /tmp/off-2.log && grep -q '已经有了，跳过' /tmp/off-2.log && grep -q 'uv 已经有了' /tmp/off-2.log" "git/curl、工具包、uv 都跳过"
must "! grep -q '登录密码' /tmp/off-2.log" "没要管理员密码"
must "[ \"$before\" = \"\$(stat -c '%n %Y' ~/.bashrc $S/sop $S/launcher.py $S/versions/latest)\" ]" "启动器、版本、~/.bashrc 没重写"

step "拷坏了的离线包（改一个字节）：停下、什么都不改"
cp "$pkg" /tmp/bad.sh
size=$(stat -c %s /tmp/bad.sh)
printf 'X' | dd of=/tmp/bad.sh bs=1 seek=$((size - 1000)) conv=notrunc status=none
mv ~/tools ~/tools.ok
"${clean_env[@]}" bash /tmp/bad.sh </dev/null > /tmp/off-3.log 2>&1
rc=$?
sed 's/^/  | /' /tmp/off-3.log
must "[ $rc != 0 ] && grep -q '拷坏了' /tmp/off-3.log" "说拷坏了、停下"
must '[ ! -e ~/tools ]' "什么都没装"
mv ~/tools.ok ~/tools; rm -f /tmp/bad.sh
sudo umount /media/xiaobai/SOPUSB

[ $fails = 0 ] && echo && echo "全部对" || { echo; echo "有 $fails 处不对"; }
exit $fails
