#!/bin/bash
# 3-37：在虚拟机里跑（由 disks.sh 拷进去、启动）。见 disks.sh 的说明。
# 只动另加的那块空白盘 /dev/vdb；系统盘只读。虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo）。
set -uo pipefail
SRC=~/sop-src
X=/dev/vdb                          # 另加的空白盘
PASS=sop-3-37-test                  # 加密盘的口令（试验用，虚拟机用完就删）
VG=ubuntu-vg                        # 卷组、逻辑卷、加密层的名字照 Ubuntu 安装程序的起法（名字里的「-」到 /dev/mapper 里变成「--」）
CRYPT=dm_crypt-0
O=/run/sop37                        # 结果先放这里：/run 在换了根的挂载空间里也看得到，最后拷回 ~/dk-out
NR=/mnt/sop37-root; MX=/mnt/sop37-x
GB=1000000000
fail=0
step() { echo; echo "=== $* ==="; }
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }

# ---------- 查一遍：正式代码的分区判断、剩余空间（只读），连同 lsblk、findmnt 的原样输出存成样例；再跑一遍真的体检命令 ----------
probe() {   # $1 = 这一种的名字
  ( cd ~/sop-src && python3 - "$1" "$O" <<'EOF'
import json, os, subprocess, sys
from machine import disks, space
name, out = sys.argv[1], sys.argv[2]
home = os.path.expanduser('~')
run = subprocess.run
ls = json.loads(run(disks.LSBLK, capture_output=True, text=True, check=True).stdout)
lay = disks.collect(home)
sp = space.check(home)
res = {'name': name, 'home_dir': home,
       'root_source': disks._findmnt_source(run, '/'), 'home_source': disks._findmnt_source(run, home),
       'kind': lay.kind, 'root': lay.root, 'home': lay.home, 'others': [o['path'] for o in lay.others],
       'notes': lay.notes, 'why': lay.why,
       'space': [{'which': s.which, 'path': s.path, 'free': s.free, 'total': s.total, 'low': s.low} for s in sp],
       'lsblk': ls}
with open(f'{out}/{name}.json', 'w') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('  正式代码判成：' + json.dumps({k: res[k] for k in ('root_source', 'home_source', 'kind', 'root', 'home', 'others', 'notes')}, ensure_ascii=False))
print('  剩余空间：' + '；'.join(f"{s['which']} {s['path']} 剩 {s['free'] / 1e9:.1f} GB{'（低于提醒线）' if s['low'] else ''}" for s in res['space']))
EOF
  )
  ( cd ~/sop-src && python3 -m kernel.cli machine doctor --readonly --no-network > "$O/$1-doctor.txt" 2>&1 )
  sed -n '/^二、/,/^四、/p' "$O/$1-doctor.txt" | sed '$d' | sed 's/^/    /'
  sed -n '/^一、/,/^二、/p' "$O/$1-doctor.txt" | grep '要注意' | sed 's/^/    /'
}

if [ "${1:-}" = --probe ]; then probe "$2"; exit; fi   # 在换了根的挂载空间里由 inns 调

case $(hostname) in sop-vm-*) ;; *) echo "不在验证用的虚拟机里（主机名 $(hostname)），不做"; exit 1;; esac
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"
[ -b $X ] || { echo "没有另加的空白盘 $X（vm.sh new 时要 --extra）"; exit 1; }
if [ -n "$(lsblk -no FSTYPE,PTTYPE $X | tr -d ' \n')" ] || [ -n "$(lsblk -no NAME $X | sed 1d)" ]; then
  echo "$X 上已经有东西了，这个脚本只在全新的虚拟机上跑（vm.sh reset 之后再来）"; exit 1
fi
sudo rm -rf $O; sudo mkdir -p $O; sudo chown "$(id -u):$(id -g)" $O

# 核对：$1 名字  $2 结论  $3 系统所在分区  $4 主目录所在分区  $5 另外能用的分区（逗号隔开，可空）  $6 剩余空间（如 system:ok,home:low）
expect() {
  local r
  r=$(python3 - "$O/$1.json" "$2" "$3" "$4" "$5" "$6" <<'EOF'
import json, sys
f, kind, root, home, others, sp = sys.argv[1:]
d = json.load(open(f))
want = {'kind': kind, 'root': [root] if root else [], 'home': [home] if home else [],
        'others': sorted(x for x in others.split(',') if x),
        'space': [tuple(x.split(':')) for x in sp.split(',')]}
got = {'kind': d['kind'], 'root': d['root'], 'home': d['home'], 'others': sorted(d['others']),
       'space': [(s['which'], 'low' if s['low'] else 'ok') for s in d['space']]}
bad = [f'{k} 应是 {want[k]}，实际 {got[k]}' for k in want if want[k] != got[k]]
print('；'.join(bad) or 'ok')
EOF
)
  must '[ "$r" = ok ]' "$1：结论 $2，系统 $3、主目录 $4，另外 [${5:-无}]，空间 $6${r:+$([ "$r" = ok ] || echo "（$r）")}"
}

doctor_has() { must "grep -qF -- \"$2\" \"$O/$1-doctor.txt\"" "$1：体检报告里有「$2」"; }
doctor_not() { must "! grep -qF -- \"$2\" \"$O/$1-doctor.txt\"" "$1：体检报告里没有「$2」"; }

# 新开一个挂载空间，在里面以小白的身份跑命令。$1 = pivot（换根：/ 是 $2，/home 是 $4）或 home（只把 /home 换成 $4）
#   $2 $3 系统的设备和挂载选项；$4 $5 主目录的设备和挂载选项；其余是要跑的命令
# 换根的做法和真从那里开机时，lsblk、findmnt 看到的一样（都读本进程的 /proc/self/mountinfo 和 /sys）：
#   / 是那个逻辑卷或子卷，/home 是另一个，/boot、/boot/efi 照这台的 fstab 挂，原来的系统分区不再挂着。
inns() {
  sudo unshare --mount --propagation private /bin/bash -s "$@" <<'EOF'
set -eu
mode=$1 sysdev=$2 sysopt=$3 homedev=$4 homeopt=$5; shift 5
if [ "$mode" = pivot ]; then
  R=/mnt/sop37-root
  mount -o "$sysopt" "$sysdev" $R
  mount -o "$homeopt" "$homedev" $R/home
  for m in /boot /boot/efi; do s=$(findmnt -s -no SOURCE $m || true); [ -z "$s" ] || mount "$s" $R$m; done   # 照这台的 fstab 挂
  mount --rbind /dev $R/dev; mount -t proc proc $R/proc; mount --rbind /sys $R/sys; mount --rbind /run $R/run
  mount -t tmpfs tmpfs $R/tmp
  mkdir -p $R/.oldroot; cd $R; pivot_root . .oldroot; cd /; umount -l /.oldroot; rmdir /.oldroot
else
  mount -o "$homeopt" "$homedev" /home
fi
exec setpriv --reuid=1000 --regid=1000 --init-groups env -i HOME=/home/xiaobai USER=xiaobai LOGNAME=xiaobai LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin O=/run/sop37 /bin/bash -c "cd ~ && $*"
EOF
}

# 往一个文件系统里塞一个大文件，剩到 $3 GB（fallocate 只记账不真写，虚拟机的磁盘文件不会跟着变大）
fill_to() {   # $1 设备 $2 挂载选项 $3 剩多少 GB
  sudo mount -o "$2" "$1" $MX
  local free need
  free=$(python3 -c "import os; s = os.statvfs('$MX'); print(s.f_bavail * s.f_frsize)")
  need=$(( free - $3 * GB ))
  if [ $need -gt 0 ]; then sudo fallocate -l $need "$MX/sop37-塞满用的大文件.bin"; fi
  sync; sudo umount $MX
}

# ================================================================================================
step "0. 原样（一个分区，另加的盘是空白的）"
probe 0-原样
expect 0-原样 single /dev/vda1 /dev/vda1 "" both:ok
doctor_has 0-原样 "合格：整台电脑只有一个能用的 Linux 分区"

step "1. 装造分区要用的软件（cryptsetup、lvm2、btrfs-progs）"
sudo sh -c ". $SRC/machine/install/apt.sh; export DEBIAN_FRONTEND=noninteractive; sop_apt update -qq && sop_apt install -y -qq -o DPkg::Lock::Timeout=600 cryptsetup-bin lvm2 btrfs-progs rsync" \
  || { echo "装软件失败"; exit 1; }
for c in cryptsetup lvm mkfs.btrfs rsync; do command -v $c >/dev/null || sudo test -x /usr/sbin/$c || { echo "没装上 $c"; exit 1; }; done

step "2. 在另加的盘上分两个区：vdb1 做加密加两个逻辑卷，vdb2 做 btrfs 两个子卷"
printf 'label: gpt\nsize=44GiB, type=linux, name=crypt\ntype=linux, name=btrfs\n' | sudo sfdisk -q $X
sudo udevadm settle
printf %s "$PASS" | sudo cryptsetup luksFormat -q --type luks2 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 ${X}1 -
printf %s "$PASS" | sudo cryptsetup open --key-file=- ${X}1 $CRYPT
sudo pvcreate -q /dev/mapper/$CRYPT
sudo vgcreate -q $VG /dev/mapper/$CRYPT
sudo lvcreate -q -y -L 16G -n ubuntu-lv $VG
sudo lvcreate -q -y -l 100%FREE -n home-lv $VG
SYSLV=/dev/mapper/ubuntu--vg-ubuntu--lv; HOMELV=/dev/mapper/ubuntu--vg-home--lv
sudo mkfs.ext4 -q $SYSLV; sudo mkfs.ext4 -q $HOMELV
sudo mkfs.btrfs -q -f ${X}2
sudo udevadm settle
lsblk -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS $X | sed 's/^/    /'

step "3. 把这台的系统、主目录拷进去（系统拷进 ubuntu-lv 和 @，主目录拷进 home-lv 和 @home）"
sudo mkdir -p $NR $MX
copy_sys() {   # $1 设备 $2 挂载选项
  sudo mount -o "$2" "$1" $MX
  sudo rsync -aHAX --one-file-system --exclude='/home/*' --exclude='/run/*' --exclude='/tmp/*' / $MX/
  sudo umount $MX
}
copy_home() {
  sudo mount -o "$2" "$1" $MX
  sudo rsync -aHAX --one-file-system /home/ $MX/
  sudo umount $MX
}
copy_sys $SYSLV defaults; copy_home $HOMELV defaults
sudo mount ${X}2 $MX; sudo btrfs -q subvolume create $MX/@; sudo btrfs -q subvolume create $MX/@home; sudo umount $MX
copy_sys ${X}2 subvol=@; copy_home ${X}2 subvol=@home
echo "  拷好了"

# ================================================================================================
step "4. 系统还在原来的分区上：另加的盘上这两种都算「另外能用的分区」（第三种）"
probe 4-另有两处
expect 4-另有两处 extra /dev/vda1 /dev/vda1 /dev/vdb1,/dev/vdb2 both:ok
doctor_has 4-另有两处 "合格：主目录在系统盘上，照常装在主目录下"
sudo vgchange -q -an $VG >/dev/null; sudo cryptsetup close $CRYPT; sudo udevadm settle
probe 4-加密没打开
expect 4-加密没打开 extra /dev/vda1 /dev/vda1 /dev/vdb2 both:ok
doctor_has 4-加密没打开 "/dev/vdb1 是加密的、没打开，看不出里面是什么，没算进去"
printf %s "$PASS" | sudo cryptsetup open --key-file=- ${X}1 $CRYPT; sudo vgchange -q -ay $VG >/dev/null; sudo udevadm settle

# ================================================================================================
step "5. 加密磁盘、系统和主目录是两个逻辑卷（换根：/ 是 ubuntu-lv，/home 是 home-lv）"
inns pivot $SYSLV defaults $HOMELV defaults "bash ~/sop-src/tests/vm/disks-guest.sh --probe 5-加密两个逻辑卷"
# 系统和主目录底下是同一个分区 vdb1（不是第一种）；原来的系统分区 vda1 这时没挂着，是一个另外能用的 ext4 分区，vdb2 也是
expect 5-加密两个逻辑卷 extra /dev/vdb1 /dev/vdb1 /dev/vda1,/dev/vdb2 system:ok,home:ok
doctor_has 5-加密两个逻辑卷 "系统在 /dev/vdb1；主目录在 /dev/vdb1。"
doctor_not 5-加密两个逻辑卷 "主目录不在系统盘上"
must "grep -q '\"root_source\": \"$SYSLV\"' $O/5-加密两个逻辑卷.json" "5：findmnt 看到的系统来源是 $SYSLV（和真开机一样是 /dev/mapper 的名字）"

step "5a. 主目录那个逻辑卷塞到剩 15 GB：只提醒主目录那一边（两个逻辑卷各按各的线）"
fill_to $HOMELV defaults 15
inns pivot $SYSLV defaults $HOMELV defaults "bash ~/sop-src/tests/vm/disks-guest.sh --probe 5a-主目录塞满"
expect 5a-主目录塞满 extra /dev/vdb1 /dev/vdb1 /dev/vda1,/dev/vdb2 system:ok,home:low
doctor_has 5a-主目录塞满 "要注意：主目录所在的分区（/home/xiaobai）只剩"
doctor_has 5a-主目录塞满 "sop machine clean"
doctor_not 5a-主目录塞满 "要注意：系统盘"

step "5b. 系统那个逻辑卷也塞到剩 8 GB：两边都提醒"
fill_to $SYSLV defaults 8
inns pivot $SYSLV defaults $HOMELV defaults "bash ~/sop-src/tests/vm/disks-guest.sh --probe 5b-两边都塞满"
expect 5b-两边都塞满 extra /dev/vdb1 /dev/vdb1 /dev/vda1,/dev/vdb2 system:low,home:low
doctor_has 5b-两边都塞满 "要注意：系统盘（/）只剩"
doctor_has 5b-两边都塞满 "低于 10 GB 的提醒线"

step "6. 系统在原来的分区、主目录在加密的逻辑卷上（只换 /home）：第一种"
inns home - - $HOMELV defaults "bash ~/sop-src/tests/vm/disks-guest.sh --probe 6-主目录在加密逻辑卷"
expect 6-主目录在加密逻辑卷 separate /dev/vda1 /dev/vdb1 /dev/vdb2 system:ok,home:low
doctor_has 6-主目录在加密逻辑卷 "合格：主目录不在系统盘上"

# ================================================================================================
step "7. btrfs 两个子卷（换根：/ 是 @，/home 是 @home；加密盘关上）"
sudo vgchange -q -an $VG >/dev/null; sudo cryptsetup close $CRYPT; sudo udevadm settle
inns pivot ${X}2 subvol=@ ${X}2 subvol=@home "bash ~/sop-src/tests/vm/disks-guest.sh --probe 7-btrfs两个子卷"
expect 7-btrfs两个子卷 extra /dev/vdb2 /dev/vdb2 /dev/vda1 both:ok
doctor_has 7-btrfs两个子卷 "系统在 /dev/vdb2；主目录在 /dev/vdb2。"
doctor_has 7-btrfs两个子卷 "系统盘（主目录也在上面）"
doctor_has 7-btrfs两个子卷 "/dev/vdb1 是加密的、没打开"
must "grep -q '\"home_source\": \"/dev/vdb2\[/@home\]\"' $O/7-btrfs两个子卷.json" "7：findmnt 看到的主目录来源带子卷后缀 /dev/vdb2[/@home]"

step "7a. btrfs 塞到剩 15 GB：只报一行，按 20 GB 提醒（子卷共用一个池子）"
fill_to ${X}2 subvol=@home 15
inns pivot ${X}2 subvol=@ ${X}2 subvol=@home "bash ~/sop-src/tests/vm/disks-guest.sh --probe 7a-btrfs塞满"
expect 7a-btrfs塞满 extra /dev/vdb2 /dev/vdb2 /dev/vda1 both:low
doctor_has 7a-btrfs塞满 "要注意：系统盘（主目录也在上面）（/home/xiaobai）只剩"
doctor_has 7a-btrfs塞满 "低于 20 GB 的提醒线"

# ================================================================================================
step "8. 看不出来的一种：主目录挂在回环设备上（一个磁盘镜像文件），照实说看不出来、不猜"
sudo truncate -s 2G /var/tmp/sop37-home.img; sudo mkfs.ext4 -q -F /var/tmp/sop37-home.img
LOOP=$(sudo losetup --show -f /var/tmp/sop37-home.img)
sudo mount $LOOP $MX; sudo rsync -aHAX /home/ $MX/; sudo umount $MX
inns home - - $LOOP defaults "bash ~/sop-src/tests/vm/disks-guest.sh --probe 8-回环设备"
expect 8-回环设备 unknown /dev/vda1 "" "" system:ok,home:low
doctor_has 8-回环设备 "看不出来主目录和系统是不是在同一个分区上"
doctor_has 8-回环设备 "要注意：看不出主目录和系统是不是在同一个分区上"
sudo losetup -d $LOOP; sudo rm -f /var/tmp/sop37-home.img

# ================================================================================================
step "9. 收尾：原来的系统盘没被动过"
must "[ \"\$(findmnt -no SOURCE /)\" = /dev/vda1 ] && [ \"\$(findmnt -no SOURCE /home)\" = '' ]" "这台本身的 / 还是 /dev/vda1，/home 没另外挂东西"
must "! mount | grep -q sop37" "造的那几样在这台本身的挂载里一样都没留下"
rm -rf ~/dk-out; cp -r $O ~/dk-out
echo
if [ $fail = 0 ]; then echo "全部对"; else echo "有不对的"; fi
exit $fail
