#!/bin/bash
# 在虚拟机里跑（由 aptlock.sh 拷进去、启动）。见 aptlock.sh 的说明。
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
LISTS=/var/lib/apt/lists/lock ARCH=/var/cache/apt/archives/lock DPKG="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock"
step() { echo; echo "=== $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }
py() { (cd $SRC && env $NOPROXY python3 "$@"); }
installed() { dpkg-query -W -f '${Status}' "$1" 2>/dev/null | grep -q 'ok installed'; }
held_by() {      # 现在谁占着这几把锁（没人占就是空的）
  local f p; for f in $LISTS $ARCH $DPKG; do for p in $(sudo fuser "$f" 2>/dev/null); do   # fuser 结尾不换行，不能用 read
    echo "$(basename "$f")←$(ps -o comm= -p "$p")"; done; done | sort -u | tr '\n' ' '
}
apt_busy() { ps -eo comm,args | grep -E '^(apt|apt-get|apt.systemd.dai|unattended-upgr|dpkg|packagekitd)' | grep -v -e grep -e unattended-upgrade-shutdown | cut -c1-120; }

# 像系统自己在更新那样占住锁：一个后台服务（root）拿住这几把锁，占 $1 秒；拿到了才返回
HOLD_PY='import fcntl, os, sys, time
fds = [os.open(p, os.O_RDWR | os.O_CREAT) for p in sys.argv[2:]]
for fd in fds: fcntl.lockf(fd, fcntl.LOCK_EX)
open("/run/sop-fake-apt.held", "w").close()
time.sleep(float(sys.argv[1]))'
hold() {
  local secs=$1; shift
  sudo rm -f /run/sop-fake-apt.held
  sudo systemd-run --quiet --collect --unit=sop-fake-apt python3 -c "$HOLD_PY" "$secs" "$@"
  local i; for i in $(seq 1 50); do [ -e /run/sop-fake-apt.held ] && return 0; sleep 0.2; done
  echo "  占锁的小程序没起来"; return 1
}
release() { sudo systemctl stop sop-fake-apt 2>/dev/null; sudo rm -f /run/sop-fake-apt.held; }
purge() { release; sudo env DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq "$@" >/dev/null 2>&1; sudo apt-get autoremove -y -qq >/dev/null 2>&1; }

echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，$(apt-get --version | head -1)，开机 $(cut -d. -f1 /proc/uptime) 秒"
py -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')" >/dev/null

if [ "${1:-}" = --boot ]; then
  echo "  一登录进来：占着锁的 $(held_by)；系统里和装软件有关的："; apt_busy | sed 's/^/    /'
  echo "  系统自己的更新任务：$(systemctl list-jobs --no-legend 2>/dev/null | grep -o 'apt[^ ]*' | tr '\n' ' ')"
  t0=$(date +%s)
  py -m machine.install bubblewrap uidmap > /tmp/m2.log 2>&1; r=$?
  t=$(( $(date +%s) - t0 ))
  sed 's/^/    | /' /tmp/m2.log
  waited=没等; grep -q '系统正在自己更新软件' /tmp/m2.log && waited=等了
  echo "  M2 用了 $t 秒（$waited）"
  must "[ $r = 0 ] && installed bubblewrap && installed uidmap" "刚开机就跑 M2：bubblewrap、uidmap 装上了"
  must "! grep -q '密码不对' /tmp/m2.log" "没说成「密码不对」"
  exit $fail
fi

step "1. 占住 apt-get update 要的锁（$LISTS）40 秒，跑 M2 装 bubblewrap"
hold 40 $LISTS
echo "  占着锁的：$(held_by)"
t0=$(date +%s); py -m machine.install bubblewrap > /tmp/c1.log 2>&1; r=$?; t=$(( $(date +%s) - t0 ))
sed 's/^/    | /' /tmp/c1.log
must "[ $r = 0 ] && installed bubblewrap" "等到锁放开后装上了（用了 $t 秒）"
must "[ $t -ge 35 ]" "真的等了（不是一下子就过去了）"
must "grep -q '系统正在自己更新软件' /tmp/c1.log" "等的时候说了一句「系统正在自己更新软件」"
must "! grep -q 'Could not get lock' /tmp/c1.log" "等到了就不打 apt 那几行英文"

step "2. 占住下载要的锁（$ARCH）30 秒，再装一遍"
purge bubblewrap; hold 30 $ARCH
t0=$(date +%s); py -m machine.install bubblewrap > /tmp/c2.log 2>&1; r=$?; t=$(( $(date +%s) - t0 ))
sed 's/^/    | /' /tmp/c2.log
must "[ $r = 0 ] && installed bubblewrap && [ $t -ge 25 ]" "等到了、装上了（用了 $t 秒）"

step "3. 占住 dpkg 的锁（$DPKG）30 秒，再装一遍"
purge bubblewrap; hold 30 $DPKG
t0=$(date +%s); py -m machine.install bubblewrap > /tmp/c3.log 2>&1; r=$?; t=$(( $(date +%s) - t0 ))
sed 's/^/    | /' /tmp/c3.log
must "[ $r = 0 ] && installed bubblewrap && [ $t -ge 25 ]" "等到了、装上了（用了 $t 秒）"

step "4. 一直占着（300 秒），期限改成 20 秒（SOP_APT_WAIT=20）：等不到时怎么说"
purge bubblewrap; hold 300 $LISTS
t0=$(date +%s); (cd $SRC && env $NOPROXY SOP_APT_WAIT=20 python3 -m machine.install bubblewrap) > /tmp/c4.log 2>&1; r=$?; t=$(( $(date +%s) - t0 ))
release
sed 's/^/    | /' /tmp/c4.log
must "[ $r != 0 ] && ! installed bubblewrap" "没装上、明说了（退出码 $r，用了 $t 秒）"
must "[ $t -ge 20 ] && [ $t -le 40 ]" "等到期限就停（不是一下子就停，也没多等）"
must "grep -q '系统正在自己更新软件，等了好几分钟还没做完' /tmp/c4.log" "说的是「系统正在自己更新软件」、过一会儿再执行"
must "! grep -q '密码不对' /tmp/c4.log" "没说成「密码不对」"

step "5. 真让系统自己起更新（apt-daily、apt-daily-upgrade），马上跑 M2"
sudo systemctl start --no-block apt-daily.service apt-daily-upgrade.service
for i in $(seq 1 25); do [ -n "$(held_by)" ] && break; sleep 0.2; done
echo "  占着锁的：$(held_by)"
t0=$(date +%s); py -m machine.install bubblewrap > /tmp/c5.log 2>&1; r=$?; t=$(( $(date +%s) - t0 ))
sed 's/^/    | /' /tmp/c5.log
waited=没碰上锁; grep -q '系统正在自己更新软件' /tmp/c5.log && waited=碰上了、等了
must "[ $r = 0 ] && installed bubblewrap" "装上了（用了 $t 秒，$waited）"
for i in $(seq 1 600); do systemctl -q is-active apt-daily.service apt-daily-upgrade.service || break; sleep 1; done

step "6. 第零步（bootstrap.sh）装 git：占住 $LISTS 30 秒"
NG=$(mktemp -d /tmp/sop-nogit.XXXXXX)       # 一个「没有 git」的 PATH：/usr/bin 里除了 git 都链过来
for f in /usr/bin/*; do [ "$(basename "$f")" = git ] || ln -s "$f" "$NG/"; done
hold 30 $LISTS
t0=$(date +%s)
bash -c ". $SRC/bootstrap.sh; PROXY=$PROXY NOPROXY=localhost; PATH=$NG:/usr/sbin:/sbin; install_apt" > /tmp/c6.log 2>&1; r=$?
t=$(( $(date +%s) - t0 )); rm -rf "$NG"
sed 's/^/    | /' /tmp/c6.log
must "[ $r = 0 ] && grep -q 'git 装好了' /tmp/c6.log && [ $t -ge 25 ]" "等到了、装好了（用了 $t 秒）"
must "grep -q '系统正在自己更新软件' /tmp/c6.log" "等的时候说了一句"
step "6b. 第零步：一直占着、期限 5 秒"
hold 300 $LISTS
NG=$(mktemp -d /tmp/sop-nogit.XXXXXX); for f in /usr/bin/*; do [ "$(basename "$f")" = git ] || ln -s "$f" "$NG/"; done
SOP_APT_WAIT=5 bash -c ". $SRC/bootstrap.sh; PROXY=$PROXY NOPROXY=localhost; PATH=$NG:/usr/sbin:/sbin; install_apt" > /tmp/c6b.log 2>&1; r=$?
rm -rf "$NG"; release
sed 's/^/    | /' /tmp/c6b.log
must "[ $r != 0 ] && grep -q '没装上：系统正在自己更新软件' /tmp/c6b.log && ! grep -q '密码不对' /tmp/c6b.log" "等不到时说的是「系统正在自己更新软件」"

step "7. Docker 的安装脚本（docker-rootless.sh）自己装 uidmap：占住 $LISTS 30 秒"
purge uidmap; hold 30 $LISTS
t0=$(date +%s)
(cd $SRC && env $NOPROXY python3 -c "
import subprocess, sys
from machine import install
sys.exit(subprocess.run(['bash', 'machine/install/docker-rootless.sh'], env=install.script_env(), stdin=subprocess.DEVNULL).returncode)") > /tmp/c7.log 2>&1; r=$?
t=$(( $(date +%s) - t0 ))
grep -v '^\[INFO\]\|^+\|^$' /tmp/c7.log | tail -15 | sed 's/^/    | /'
must "[ $r = 0 ] && installed uidmap && [ -x ~/tools/docker/bin/dockerd ]" "等到了，uidmap 和 Docker 都装上了（用了 $t 秒）"
must "grep -q '系统正在自己更新软件' /tmp/c7.log" "等的时候说了一句"

release
echo
if [ $fail = 0 ]; then echo "全部对"; else echo "有不对的（看上面「不对」）"; fi
exit $fail
