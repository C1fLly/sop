#!/bin/bash
# 第 1 期第一段：验证工具包用的两台虚拟机（QEMU）。磁盘文件都在 ~/sop-vm/（主目录那个分区），只用来验证 SOP 工具包本身。
#   a：主目录单独一块盘（模拟「装系统时把主目录单独分一个区」，和这台电脑一样）
#   b：只有一个分区
# 用法：vm.sh create <a|b> | start <a|b> | stop <a|b> | ssh <a|b> [命令...] | status
# 虚拟机里的账号 xiaobai 免密码 sudo：只在虚拟机里，用来模拟「小白输管理员密码」的那几步。
set -euo pipefail
V=~/sop-vm; IMG=$V/images/ubuntu-26.04-server-cloudimg-amd64.img; KEY=$V/ssh/id_ed25519
port() { case $1 in a) echo 2231;; b) echo 2232;; *) echo "只有 a、b 两台" >&2; exit 2;; esac; }
seedport=8765
SSH() { local p; p=$(port $1); shift; ssh -F /dev/null -i $KEY -p $p -o StrictHostKeyChecking=no -o UserKnownHostsFile=$V/ssh/known_hosts -o ConnectTimeout=5 -o LogLevel=ERROR xiaobai@127.0.0.1 "$@"; }

seed() {   # 写出 cloud-init 的配置（NoCloud，经本机的一个小网页服务给虚拟机）
  local n=$1 d=$V/seed/$1; mkdir -p $d
  echo "instance-id: sop-vm-$n-$(date +%s)" > $d/meta-data
  { echo "#cloud-config"
    echo "hostname: sop-vm-$n"
    echo "users:"
    echo "  - name: xiaobai"
    echo "    shell: /bin/bash"
    echo "    sudo: ALL=(ALL) NOPASSWD:ALL"
    echo "    ssh_authorized_keys: [\"$(cat $KEY.pub)\"]"
    if [ $n = a ]; then
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
  } > $d/user-data
}

case ${1:-} in
  create)
    n=$2; [ -e $V/vm-$n-root.qcow2 ] && { echo "vm-$n 已经有了"; exit 1; }
    qemu-img create -q -f qcow2 -F qcow2 -b $IMG $V/vm-$n-root.qcow2 40G
    [ $n = a ] && qemu-img create -q -f qcow2 $V/vm-$n-home.qcow2 30G
    seed $n; echo "vm-$n 的磁盘已建好" ;;
  start)
    n=$2; p=$(port $n)
    pgrep -f "http.server $seedport --bind 127.0.0.1" >/dev/null || { setsid nohup python3 -m http.server $seedport --bind 127.0.0.1 --directory $V/seed >/dev/null 2>&1 & }
    extra=(); [ $n = a ] && extra=(-drive file=$V/vm-$n-home.qcow2,if=virtio,format=qcow2)
    qemu-system-x86_64 -name sop-vm-$n -machine q35,accel=kvm -cpu host -smp 4 -m 4096 \
      -drive file=$V/vm-$n-root.qcow2,if=virtio,format=qcow2 "${extra[@]}" \
      -netdev user,id=n0,hostfwd=tcp:127.0.0.1:$p-:22 -device virtio-net-pci,netdev=n0 \
      -smbios "type=1,serial=ds=nocloud;s=http://10.0.2.2:$seedport/$n/" \
      -display none -serial file:$V/vm-$n-console.log -daemonize -pidfile $V/vm-$n.pid
    echo "vm-$n 已启动，等它能登录…"
    for i in $(seq 1 90); do SSH $n true 2>/dev/null && { echo "vm-$n 可以登录了（$((i*2)) 秒）"; exit 0; }; sleep 2; done
    echo "180 秒还登录不了，看 $V/vm-$n-console.log"; exit 1 ;;
  stop)
    n=$2; SSH $n sudo poweroff 2>/dev/null || true
    for i in $(seq 1 30); do [ -e $V/vm-$n.pid ] && kill -0 $(cat $V/vm-$n.pid) 2>/dev/null || { echo "vm-$n 已关"; exit 0; }; sleep 2; done
    kill $(cat $V/vm-$n.pid); echo "vm-$n 强制关了" ;;
  ssh) n=$2; shift 2; SSH $n "$@" ;;
  status) for n in a b; do printf 'vm-%s：' $n; [ -e $V/vm-$n.pid ] && kill -0 $(cat $V/vm-$n.pid) 2>/dev/null && echo 开着 || echo 关着; done ;;
  *) sed -n '2,7p' $0; exit 2 ;;
esac
