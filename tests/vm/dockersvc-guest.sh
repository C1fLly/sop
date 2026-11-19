#!/bin/bash
# 在虚拟机里跑（由 dockersvc.sh 拷进去、启动）。见 dockersvc.sh 的说明。
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
UNITS=~/.config/systemd/user
P=demo-x; SV=sop-docker-$P.service; SL='sop-demo\x2dx.slice'
step() { echo; echo "=== $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }
py() { (cd $SRC && env $NOPROXY python3 "$@"); }
D() { env DOCKER_HOST=unix://$HOME/tools/docker-sop/$P/run/docker.sock ~/tools/docker/bin/docker "$@"; }
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)，内存 $(free -m | awk '/^Mem/{print $2}') MB，$(nproc) 核"

step "准备：网络设置、bubblewrap、规定位置的免管理员 Docker（M2）"
py -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')" && echo "  网络设置写好了"
py -m machine.install bubblewrap uidmap dbus-user-session docker > /tmp/m2.log 2>&1
if grep -q '^都装好了' /tmp/m2.log; then echo "  bubblewrap $(bwrap --version)、Docker $(~/tools/docker/bin/docker --version | cut -d, -f1) 装好了"
else echo "  M2 没装好："; cat /tmp/m2.log; exit 1; fi

step "假项目 $P（和 wt 一样的结构：.git 裸仓库、几个工作目录、.shared 带依赖缓存）"
FX=$(mktemp -d /tmp/sop-dockersvc-fx.XXXXXX)
R=$(py -c "from runner.selftest import make_fixture; print(make_fixture('$FX')[0])")
echo "  项目根 $R"
mkdir -p ~/tools/sop/state/$P && echo 秘密 > ~/tools/sop/state/$P/锁

step "起专用 Docker（正式服务，内存上限 300M、处理器 1 核）"
t0=$(date +%s%N)
sock=$(py -m runner.docker.service start $P "$R" --memory 300M --cpu 100%); rc=$?
echo "  通道 $sock（$(( ($(date +%s%N) - t0) / 1000000 )) 毫秒，退出码 $rc）"
must "[ $rc = 0 ] && [ -S \"$sock\" ]" "起来了、通道在"
echo "  --- $UNITS/$SV ---"; sed 's/^/    /' $UNITS/$SV
echo "  --- $UNITS/$SL ---"; sed 's/^/    /' "$UNITS/$SL"
must "[ \"\$(stat -c %a $UNITS/$SV)\" = 600 ] && [ \"\$(stat -c %a '$UNITS/$SL')\" = 600 ]" "两份登记文件只有自己能读"
must "[ \"\$(systemctl --user show -p Slice --value $SV)\" = '$SL' ]" "服务在分组 $SL 里"
must "[ \"\$(systemctl --user show -p MemoryMax --value '$SL')\" = 314572800 ]" "分组的内存上限 300M 生效"
must "[ \"\$(systemctl --user show -p CPUQuotaPerSecUSec --value '$SL')\" = 1s ]" "分组的处理器上限 1 核生效"
cg=$(systemctl --user show -p ControlGroup --value $SV); echo "  服务的分组路径 $cg"
must "[[ \"$cg\" == */sop.slice/'$SL'/$SV ]]" "分组挂在 sop.slice 下（项目名里的「-」没把它挂到 sop-demo 下面）"
en=$(systemctl --user is-enabled $SV 2>&1); must "[ \"$en\" = static ]" "没设成登录后自己起来（is-enabled：$en，没有 [Install]）"
must "[ ! -e $UNITS/default.target.wants/$SV ]" "default.target.wants 下没有它"
D image inspect debian:stable-slim >/dev/null 2>&1 || D pull -q debian:stable-slim >/dev/null
must "D image inspect debian:stable-slim >/dev/null 2>&1" "经代理拉到 debian:stable-slim"

step "容器的进程落在这个项目的分组里"
D run -d --name sleeper debian:stable-slim sleep 917 >/dev/null
sleep 1; pid=$(pgrep -f 'sleep 917' | head -1)
echo "  容器里的 sleep 在宿主上是进程 $pid：$(cat /proc/$pid/cgroup)"
must "grep -qF '/sop.slice/$SL/' /proc/$pid/cgroup" "容器进程在 $SL 下"
D rm -f sleeper >/dev/null

step "超内存：容器要的比上限（300M）多，被系统杀掉；看专用 Docker 本身在不在（演 6 次）"
wait_up() { for k in $(seq 40); do D info >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
mainpid() { systemctl --user show -p MainPID --value $SV; }
ev0=$(awk '/^oom_kill /{print $2}' "/sys/fs/cgroup$(dirname $cg)/memory.events")
kept=0; died=0; back=0
D run -d --name bystander debian:stable-slim sleep 9999 >/dev/null; bys=0
for i in 1 2 3 4 5 6; do
  case $i in 1|3|5) hog='head -c 600m /dev/zero | tail' ;; *) hog='tail /dev/zero' ;; esac
  m0=$(mainpid); r0=$(systemctl --user show -p NRestarts --value $SV)
  D run --rm debian:stable-slim sh -c "$hog" >/dev/null 2>&1; rc=$?
  sleep 2; up=no; wait_up && up=yes
  m1=$(mainpid); r1=$(systemctl --user show -p NRestarts --value $SV)
  if [ "$m0" = "$m1" ] && [ "$r0" = "$r1" ]; then kept=$((kept+1)); how="专用 Docker 没事"; else died=$((died+1)); how="专用 Docker 自己也被杀了，服务管理器把它重新拉起来了（重启次数 $r0 → $r1）"; fi
  [ $up = yes ] && back=$((back+1))
  [ "$(D inspect -f '{{.State.Running}}' bystander 2>/dev/null)" = true ] || { bys=$((bys+1)); D rm -f bystander >/dev/null 2>&1; D run -d --name bystander debian:stable-slim sleep 9999 >/dev/null; }
  echo "  第 $i 次（$hog）：容器退出码 $rc；$how；之后答话：$up"
done
ev1=$(awk '/^oom_kill /{print $2}' "/sys/fs/cgroup$(dirname $cg)/memory.events")
echo "  6 次里专用 Docker 没事 $kept 次、自己也被杀 $died 次；分组记下的被杀次数 $ev0 → $ev1"
must "[ $((ev1 - ev0)) -ge 6 ]" "每次都被系统按分组的上限杀了（被杀次数至少多 6）"
must "[ $back = 6 ]" "每次之后专用 Docker 都在答话（被杀的那几次由服务管理器自动拉起）"
must "systemctl --user -q is-active $SV" "专用 Docker 的服务在跑"
out=$(D run --rm debian:stable-slim echo 还能起容器 2>&1); must "[ \"$out\" = 还能起容器 ]" "之后还能起容器"
out=$(D run --rm debian:stable-slim sh -c 'head -c 200m /dev/zero | tail > /dev/null; echo 200M 没事' 2>&1)
must "[ \"$out\" = '200M 没事' ]" "上限以内（200M）照常"
D rm -f bystander >/dev/null 2>&1
echo "  同一项目里另一个一直在跑的容器（bystander）跟着停了 $bys 次"
echo "  【没做到，拆到 3-54】专用 Docker 自己也被杀的有 $died 次（6 次里），那几次同一项目在跑的别的容器跟着停；见 3-17 的记录"

step "处理器上限：四个进程一起算，限成 1 核"
burn() { wait_up; local a=$(date +%s%N); D run --rm debian:stable-slim sh -c 'for i in 1 2 3 4; do (i=0; while [ $i -lt 1500000 ]; do i=$((i+1)); done) & done; wait' >/dev/null 2>&1; local z=$(date +%s%N); python3 -c "print(round(($z - $a) / 1e9, 2))"; }
t=$(burn)
echo "  限成 1 核：$t 秒"
py -m runner.docker.service install $P "$R" --memory 300M --cpu 400% >/dev/null
systemctl --user show -p CPUQuotaPerSecUSec --value "$SL" | sed 's/^/  改成 4 核后分组上：/'
t4=$(burn)
echo "  限成 4 核：$t4 秒（不重启专用 Docker，分组的上限当场生效）"
must "awk 'BEGIN{exit !($t > 2 * $t4)}'" "1 核明显慢（$t 对 $t4，至少慢一倍）"
py -m runner.docker.service install $P "$R" --memory 300M --cpu 100% >/dev/null

step "视野：.git、.shared 只读（依赖缓存可写），看不到 ~/tools/sop/state"
wait_up
chk() { D run --rm -v "$R:/p" debian:stable-slim sh -c "$1" >/dev/null 2>&1; }
must "! chk 'touch /p/.git/偷'" ".git 写不了"
must "! chk 'echo x >> /p/feat-a-1/.git'" "工作目录里指向 .git 的小文件写不了"
must "! chk 'echo x >> /p/.shared/hooks/post-create'" ".shared/hooks 写不了"
must "chk 'touch /p/.shared/cache/装依赖 && rm /p/.shared/cache/装依赖'" ".shared/cache 写得了"
must "chk 'touch /p/ticket-a-1-01/新文件 && rm /p/ticket-a-1-01/新文件'" "工作目录写得了"
out=$(D run --rm -v /:/host debian:stable-slim sh -c "ls /host$HOME/tools/sop/state/$P/锁 /host$HOME/tools/sop /host/run/user 2>&1; ls -d /host/usr" 2>&1)
echo "$out" | sed 's/^/    /'
must "! echo \"\$out\" | grep -q -e 秘密 -e '^/host$HOME/tools/sop' -e '^/host/run/user' && echo \"\$out\" | grep -qx /host/usr" "把根挂进去也看不到 state、~/tools/sop、/run/user（看得到 /host/usr）"

step "停掉、删掉登记文件：数据还在"
py -m runner.docker.service remove $P
must "! systemctl --user -q is-active $SV" "服务停了"
must "[ ! -e $UNITS/$SV ] && [ ! -e '$UNITS/$SL' ]" "两份登记文件删了"
must "[ -d ~/tools/docker-sop/$P/data ] && [ \$(du -sm ~/tools/docker-sop/$P/data | cut -f1) -gt 50 ]" "数据目录还在（$(du -sh ~/tools/docker-sop/$P/data | cut -f1)，有拉下来的镜像）"
sock=$(py -m runner.docker.service start $P "$R" --memory 300M --cpu 100%)
must "D image inspect debian:stable-slim >/dev/null 2>&1" "再起来，镜像还在"
py -m runner.docker.service remove $P
rm -rf ~/tools/docker-sop/$P ~/tools/sop/state/$P; chmod -R u+w "$FX"; rm -rf "$FX"

step "隔离自检专用 Docker 那份（用正式服务起）"
py runner/docker/selftest_docker.py > /tmp/sdk.log 2>&1; rc=$?
sed 's/^/  /' /tmp/sdk.log
must "[ $rc = 0 ] && grep -qx '专用 Docker 的隔离自检：13 项，0 项不符合' /tmp/sdk.log" "13 项全过"
must "[ ! -e $UNITS/sop-docker-sopdk.service ] && [ ! -e $UNITS/sop-sopdk.slice ] && ! systemctl --user -q is-active sop-docker-sopdk.service" "跑完服务停了、登记文件删了"
must "[ ! -e ~/tools/sop/state/sopdk ] && ! ls -d /tmp/sop-selftest-docker-* >/dev/null 2>&1" "state/sopdk、/tmp 的假项目都删了"

step "M6（两份合起来，通过后记登记）"
py -m machine.syscheck > /tmp/m6.log 2>&1; rc=$?
tail -2 /tmp/m6.log | sed 's/^/  /'
must "[ $rc = 0 ] && grep -q '^隔离自检通过（172 项，0 项不符合）' /tmp/m6.log" "M6 通过，172 项 0 项不符合"

echo
[ $fail = 0 ] && echo "全部对" || echo "有不对的"
exit $fail
