#!/bin/bash
# 第三段（3-02）：按名字现建、一键还原的验证用虚拟机（QEMU）。只用来验证 SOP 工具包本身，不用 sudo。
#
# 做法：每种「分区样子」先做一次底盘（云镜像起一次、首次初始化做完、关机、设成只读）；
# 按名字建的每台虚拟机只是底盘上面的一层覆盖层，新建、还原都是把这层删掉重建，几秒钟。
#   底盘 one ：只有一个分区（系统和主目录在同一个分区）
#   底盘 home：主目录单独一块盘（模拟「装系统时把主目录单独分一个区」）
# 另可加一块空白盘（--extra 大小），给造分区的验证用（例如加密加逻辑卷、btrfs 子卷）。
#
# 用法：
#   vm.sh new <名字> [--layout one|home] [--extra 10G] [--mem 4096] [--offline]
#                                                                       建一台（底盘没有就先做底盘，第一次约两三分钟）
#                                                                       --offline：断网（3-14）。QEMU 的 restrict=on：虚拟机连不到
#                                                                       本机、也连不到外面，只留本机进虚拟机登录的那一个口
#   vm.sh start <名字> [--usb <镜像文件>]                                起；--usb 把一个磁盘镜像当成 U 盘插上（3-14）
#   vm.sh stop <名字> | reset <名字> | rm <名字>                         关、还原成全新（要先关）、删掉
#   vm.sh ssh <名字> [命令...]                                           登进去（账号 xiaobai，虚拟机里免密码 sudo）
#   vm.sh push <名字> <本机路径> <虚拟机里的路径>                        拷文件或目录进去
#   vm.sh pull <名字> <虚拟机里的路径> <本机路径>                        拷文件出来
#   vm.sh list                                                           列出所有按名字建的虚拟机
#   vm.sh base <one|home>                                                重做底盘（要先删掉用它的虚拟机）
#
# 磁盘文件都在 ~/sop-vm/（主目录那个分区）：底盘在 bases/，各台在 vms/<名字>/。
# 第一段的 vm-a、vm-b 用 docs/试验/脚本/第一段/虚拟机/vm.sh 管，这个脚本不碰它们（名字 a、b 不许用）。
set -euo pipefail
V=${SOP_VM_HOME:-~/sop-vm}
IMG=$V/images/ubuntu-26.04-server-cloudimg-amd64.img
KEY=$V/ssh/id_ed25519
BASES=$V/bases; VMS=$V/vms
BASE_PORT=2239; SEED_PORT=8766; FIRST_PORT=2240

die() { echo "$*" >&2; exit 1; }
need_name() {
  [ -n "${1:-}" ] || die "要给虚拟机的名字"
  [[ $1 =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]] || die "名字只能用小写字母、数字、减号：$1"
  case $1 in a|b) die "a、b 是第一段的两台，用第一段的脚本管";; esac
}
conf() { sed -n "s/^$2=//p" "$VMS/$1/conf"; }
exists() { [ -f "$VMS/$1/conf" ] || die "没有叫 $1 的虚拟机（vm.sh list 看有哪些）"; }
running() { local f=$1; [ -e "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; }
ssh_opts() { echo "-F /dev/null -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=$1 -o ConnectTimeout=5 -o LogLevel=ERROR"; }
SSHP() { local port=$1 kh=$2; shift 2; ssh $(ssh_opts "$kh") -p "$port" xiaobai@127.0.0.1 "$@"; }
SSH() { local n=$1; shift; SSHP "$(conf $n port)" "$VMS/$n/known_hosts" "$@"; }

wait_login() {   # 端口 known_hosts 秒数
  local i; for i in $(seq 1 $(($3 / 2))); do SSHP "$1" "$2" true 2>/dev/null && { echo "可以登录了（约 $((i * 2)) 秒）"; return 0; }; sleep 2; done
  return 1
}
qemu_run() {     # 名字 端口 内存 pid文件 控制台日志 磁盘... [-- 其余参数原样给 qemu]
  local name=$1 port=$2 mem=$3 pid=$4 log=$5; shift 5
  local drives=()
  while [ $# -gt 0 ] && [ "$1" != -- ]; do drives+=(-drive "file=$1,if=virtio,format=qcow2"); shift; done
  [ $# -gt 0 ] && shift
  drives+=("$@")
  qemu-system-x86_64 -name "$name" -machine q35,accel=kvm -cpu host -smp 4 -m "$mem" \
    "${drives[@]}" \
    -netdev user,id=n0${NET_RESTRICT:+,restrict=on},hostfwd=tcp:127.0.0.1:$port-:22 -device virtio-net-pci,netdev=n0 \
    -display none -serial file:"$log" -daemonize -pidfile "$pid"
}
stop_by() {      # 端口 known_hosts pid文件
  SSHP "$1" "$2" sudo poweroff 2>/dev/null || true
  local i; for i in $(seq 1 30); do running "$3" || { rm -f "$3"; return 0; }; sleep 2; done
  kill "$(cat "$3")"; sleep 1; rm -f "$3"; echo "（等了 60 秒没关上，强制关了）"
}

seed() {         # cloud-init 的配置（NoCloud，经本机一个临时的小网页服务给虚拟机）
  local L=$1 d=$BASES/$1/seed; mkdir -p "$d"
  echo "instance-id: sop-base-$L-$(date +%s)" > "$d/meta-data"
  { echo "#cloud-config"
    echo "hostname: sop-base-$L"
    echo "manage_etc_hosts: true"
    echo "users:"
    echo "  - name: xiaobai"
    echo "    shell: /bin/bash"
    echo "    sudo: ALL=(ALL) NOPASSWD:ALL"
    echo "    ssh_authorized_keys: [\"$(cat $KEY.pub)\"]"
    if [ "$L" = home ]; then
      echo "disk_setup:"
      echo "  /dev/vdb: {table_type: gpt, layout: true, overwrite: false}"
      echo "fs_setup:"
      echo "  - {label: home, filesystem: ext4, device: /dev/vdb, partition: auto}"
      echo "mounts:"
      echo "  - [LABEL=home, /home, ext4, \"defaults\", \"0\", \"2\"]"
    fi
    echo "apt:"
    echo "  primary: [{arches: [default], uri: \"http://cn.archive.ubuntu.com/ubuntu/\"}]"
    echo "write_files:"
    echo "  - path: /etc/profile.d/sop-proxy.sh"
    echo "    content: |"
    echo "      # 这台试验电脑上网走本机的代理；虚拟机里 10.0.2.2 就是本机"
    echo "      export http_proxy=http://10.0.2.2:7890 https_proxy=http://10.0.2.2:7890 HTTP_PROXY=http://10.0.2.2:7890 HTTPS_PROXY=http://10.0.2.2:7890"
    echo "      export no_proxy=localhost,127.0.0.1,cn.archive.ubuntu.com,security.ubuntu.com NO_PROXY=localhost,127.0.0.1,cn.archive.ubuntu.com,security.ubuntu.com"
  } > "$d/user-data"
}

make_base() {
  local L=$1 B=$BASES/$1
  case $L in one|home) ;; *) die "底盘只有 one、home 两种";; esac
  [ -f "$IMG" ] || die "没有云镜像 $IMG"
  if [ -d "$VMS" ] && grep -lqx "layout=$L" "$VMS"/*/conf 2>/dev/null; then die "还有虚拟机用着底盘 $L，先删掉它们"; fi
  [ -d "$B" ] && { chmod -R u+w "$B"; rm -rf "$B"; }
  mkdir -p "$B"
  qemu-img create -q -f qcow2 -F qcow2 -b "$IMG" "$B/root.qcow2" 40G
  local disks=("$B/root.qcow2")
  [ "$L" = home ] && { qemu-img create -q -f qcow2 "$B/home.qcow2" 30G; disks+=("$B/home.qcow2"); }
  seed "$L"
  python3 -m http.server $SEED_PORT --bind 127.0.0.1 --directory "$B/seed" >/dev/null 2>&1 &
  local web=$!
  trap "kill $web 2>/dev/null || true" EXIT
  echo "做底盘 $L：从云镜像起一次，等首次初始化…"
  qemu_run "sop-base-$L" $BASE_PORT 4096 "$B/pid" "$B/console.log" "${disks[@]}" -- \
    -smbios "type=1,serial=ds=nocloud;s=http://10.0.2.2:$SEED_PORT/"
  wait_login $BASE_PORT "$B/known_hosts" 300 || { stop_by $BASE_PORT "$B/known_hosts" "$B/pid"; die "300 秒还登录不了，看 $B/console.log"; }
  SSHP $BASE_PORT "$B/known_hosts" 'cloud-init status --wait >/dev/null; cloud-init status' || true
  # 之后从底盘派生的各台不再跑首次初始化；每台第一次开机重新生成自己的机器编号
  SSHP $BASE_PORT "$B/known_hosts" 'sudo touch /etc/cloud/cloud-init.disabled && sudo truncate -s 0 /etc/machine-id && sudo rm -f /var/lib/dbus/machine-id && sync'
  stop_by $BASE_PORT "$B/known_hosts" "$B/pid"
  rm -f "$B/known_hosts"
  chmod a-w "$B"/*.qcow2
  echo "$L" > "$B/done"
  kill $web 2>/dev/null || true; trap - EXIT
  echo "底盘 $L 做好了"
}

mkdisks() {      # 名字：按 conf 现建覆盖层和空白盘
  local n=$1 D=$VMS/$1 L; L=$(conf $1 layout)
  rm -f "$D"/*.qcow2 "$D/known_hosts" "$D/console.log"
  qemu-img create -q -f qcow2 -F qcow2 -b "$BASES/$L/root.qcow2" "$D/root.qcow2"
  [ "$L" = home ] && qemu-img create -q -f qcow2 -F qcow2 -b "$BASES/$L/home.qcow2" "$D/home.qcow2"
  local x; x=$(conf $n extra); [ -n "$x" ] && qemu-img create -q -f qcow2 "$D/extra.qcow2" "$x"
  return 0
}

free_port() {
  local p=$FIRST_PORT
  while grep -qx "port=$p" "$VMS"/*/conf 2>/dev/null || (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; do p=$((p + 1)); done
  echo $p
}

cmd=${1:-}; shift || true
case $cmd in
  new)
    n=${1:-}; need_name "$n"; shift
    [ -e "$VMS/$n" ] && die "已经有叫 $n 的虚拟机了（要回到全新用 reset）"
    L=one extra= mem=4096 net=
    while [ $# -gt 0 ]; do case $1 in
      --layout) L=$2; shift 2;; --extra) extra=$2; shift 2;; --mem) mem=$2; shift 2;; --offline) net=offline; shift;;
      *) die "不认识的选项：$1";; esac; done
    case $L in one|home) ;; *) die "--layout 只有 one、home";; esac
    [ -f "$BASES/$L/done" ] || make_base "$L"
    mkdir -p "$VMS/$n"
    printf 'layout=%s\nport=%s\nextra=%s\nmem=%s\nnet=%s\n' "$L" "$(free_port)" "$extra" "$mem" "$net" > "$VMS/$n/conf"
    mkdisks "$n"
    echo "虚拟机 $n 建好了（底盘 $L$([ -n "$extra" ] && echo "，另加一块 $extra 的空白盘")$([ -n "$net" ] && echo "，断网")，登录端口 $(conf $n port)）" ;;
  start)
    n=${1:-}; need_name "$n"; exists "$n"; D=$VMS/$n; shift
    usb=
    while [ $# -gt 0 ]; do case $1 in --usb) usb=$2; shift 2;; *) die "不认识的选项：$1";; esac; done
    running "$D/pid" && { [ -n "$usb" ] && die "$n 已经开着，要插 U 盘得先关"; echo "$n 已经开着"; exit 0; }
    disks=("$D/root.qcow2"); [ -f "$D/home.qcow2" ] && disks+=("$D/home.qcow2"); [ -f "$D/extra.qcow2" ] && disks+=("$D/extra.qcow2")
    more=()
    if [ -n "$usb" ]; then
      [ -f "$usb" ] || die "没有 U 盘的镜像文件：$usb"
      more=(-- -device qemu-xhci,id=xhci -drive "if=none,id=usbstick,format=raw,file=$usb" -device usb-storage,bus=xhci.0,drive=usbstick,removable=on)
    fi
    [ "$(conf $n net)" = offline ] && export NET_RESTRICT=1
    qemu_run "sop-vm-$n" "$(conf $n port)" "$(conf $n mem)" "$D/pid" "$D/console.log" "${disks[@]}" "${more[@]}"
    echo "$n 已启动，等它能登录…"
    wait_login "$(conf $n port)" "$D/known_hosts" 180 || die "180 秒还登录不了，看 $D/console.log"
    # 主机名改成虚拟机的名字（底盘里是 sop-base-…）
    SSH "$n" "[ \"\$(hostname)\" = sop-vm-$n ] || { sudo hostnamectl set-hostname sop-vm-$n; sudo sed -i 's/sop-base-[a-z]*/sop-vm-$n/g' /etc/hosts; }" ;;
  stop)
    n=${1:-}; need_name "$n"; exists "$n"; D=$VMS/$n
    running "$D/pid" || { echo "$n 本来就关着"; exit 0; }
    stop_by "$(conf $n port)" "$D/known_hosts" "$D/pid"; echo "$n 已关" ;;
  reset)
    n=${1:-}; need_name "$n"; exists "$n"
    running "$VMS/$n/pid" && die "$n 还开着，先 vm.sh stop $n"
    mkdisks "$n"; echo "$n 已还原成全新" ;;
  rm)
    n=${1:-}; need_name "$n"; exists "$n"
    running "$VMS/$n/pid" && die "$n 还开着，先 vm.sh stop $n"
    rm -rf "${VMS:?}/$n"; echo "$n 删掉了" ;;
  ssh) n=${1:-}; need_name "$n"; exists "$n"; shift; SSH "$n" "$@" ;;
  push)
    n=${1:-}; need_name "$n"; exists "$n"; [ $# -eq 3 ] || die "用法：vm.sh push <名字> <本机路径> <虚拟机里的路径>"
    scp -q -r $(ssh_opts "$VMS/$n/known_hosts") -P "$(conf $n port)" "$2" "xiaobai@127.0.0.1:$3" ;;
  pull)
    n=${1:-}; need_name "$n"; exists "$n"; [ $# -eq 3 ] || die "用法：vm.sh pull <名字> <虚拟机里的路径> <本机路径>"
    scp -q $(ssh_opts "$VMS/$n/known_hosts") -P "$(conf $n port)" "xiaobai@127.0.0.1:$2" "$3" ;;
  list)
    [ -d "$VMS" ] || { echo "（还没有）"; exit 0; }
    for c in "$VMS"/*/conf; do
      [ -f "$c" ] || continue; n=$(basename "$(dirname "$c")")
      printf '%-16s 底盘 %-4s 端口 %s 空白盘 %-5s %s\n' "$n" "$(conf $n layout)" "$(conf $n port)" "$(conf $n extra || true)" \
        "$(running "$VMS/$n/pid" && echo 开着 || echo 关着)"
    done ;;
  base) make_base "${1:-}" ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
