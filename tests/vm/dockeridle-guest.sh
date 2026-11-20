#!/bin/bash
# 在虚拟机里跑（由 dockeridle.sh 拷进去、分两段启动）。见 dockeridle.sh 的说明。用法：dockeridle-guest.sh one|two
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
UNITS=~/.config/systemd/user
P=demo-x; SV=sop-docker-$P.service; TM=sop-docker-$P-idle.timer; ISV=sop-docker-$P-idle.service
LOCK=~/tools/sop/state/$P/docker.lock
FX=~/fx                              # 假项目放在主目录下：重启后还要用（/tmp 重启就没了）
IDLE=120                             # 为了不等 15 分钟，闲 2 分钟就停（正式的 900 秒）；计时器每分钟看一次，和正式的一样
step() { echo; echo "=== $(date +%T) $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }
py() { (cd $SRC && env $NOPROXY python3 "$@"); }
D() { env DOCKER_HOST=unix://$HOME/tools/docker-sop/$P/run/docker.sock ~/tools/docker/bin/docker "$@"; }
active() { systemctl --user -q is-active "$1"; }
mainpid() { systemctl --user show -p MainPID --value $SV; }
# 像 sop 那样拿着「在用」锁用专用 Docker：hold <名字>，放开：let_go <名字>（往它的输入写一行）
hold() {
  rm -f /tmp/h-$1.in /tmp/h-$1.out; mkfifo /tmp/h-$1.in
  (cd $SRC && exec env $NOPROXY python3 -m runner.docker.service use $P "$R" --memory 300M --cpu 100% --idle $IDLE \
     < /tmp/h-$1.in > /tmp/h-$1.out 2>&1) &
  eval "exec {fd_$1}>/tmp/h-$1.in"
  for k in $(seq 90); do grep -q docker.sock /tmp/h-$1.out 2>/dev/null && return 0; sleep 1; done
  cat /tmp/h-$1.out; return 1
}
let_go() { local v=fd_$1; echo >&${!v}; eval "exec ${!v}>&-"; sleep 1; }
# 等到专用 Docker 停了，打印从 $1（秒）起过了多少秒；最多等 $2 秒
wait_stopped() { local t0=$1; for k in $(seq $2); do active $SV || { echo $(( $(date +%s) - t0 )); return 0; }; sleep 1; done; echo 超时; return 1; }
lock_free() { flock -n -x "$LOCK" true; }
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)，内存 $(free -m | awk '/^Mem/{print $2}') MB，$(nproc) 核，开机 $(uptime -s)"
for k in $(seq 30); do systemctl --user is-system-running >/dev/null 2>&1 && break; systemctl --user show-environment >/dev/null 2>&1 && break; sleep 1; done

if [ "${1:-}" = one ]; then
  step "准备：网络设置、bubblewrap、规定位置的免管理员 Docker（M2）"
  py -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')" && echo "  网络设置写好了"
  py -m machine.install bubblewrap uidmap dbus-user-session docker > /tmp/m2.log 2>&1
  if grep -q '^都装好了' /tmp/m2.log; then echo "  bubblewrap $(bwrap --version)、Docker $(~/tools/docker/bin/docker --version | cut -d, -f1) 装好了"
  else echo "  M2 没装好："; cat /tmp/m2.log; exit 1; fi
  rm -rf $FX; mkdir -p $FX
  R=$(py -c "from runner.selftest import make_fixture; print(make_fixture('$FX')[0])"); echo "$R" > ~/fx.root
  echo "  假项目根 $R（项目名 $P）"

  step "没用之前：什么都没起"
  must "! active $SV && [ ! -e $UNITS/$SV ]" "没有专用 Docker 的服务，也没在跑"

  step "两个 sop 同时要用（A、B）：用时才起，等它答话再用"
  t=$(date +%s%N); hold A || fail=1; echo "  A 拿到通道：$(cat /tmp/h-A.out)（$(( ($(date +%s%N) - t) / 1000000 )) 毫秒）"
  hold B || fail=1; echo "  B 拿到通道：$(cat /tmp/h-B.out)"
  must "active $SV && D info >/dev/null 2>&1" "专用 Docker 起来了、答话"
  must "active $TM" "闲了停的计时器跟着起来了"
  for u in $SV $TM $ISV; do e=$(systemctl --user is-enabled $u 2>&1); must "[ \"$e\" = static ]" "$u 没设成登录后自己起来（$e）"; done
  must "[ \"\$(stat -c %a $LOCK)\" = 600 ] && [ \"\$(stat -c %a $UNITS/$TM)\" = 600 ] && [ \"\$(stat -c %a $UNITS/$ISV)\" = 600 ]" "「在用」锁和两份新登记文件只有自己能读"
  echo "  --- $UNITS/$TM ---"; sed 's/^/    /' $UNITS/$TM
  echo "  --- $UNITS/$ISV ---"; sed 's/^/    /' $UNITS/$ISV
  must "! lock_free" "有 sop 在用：拿不到独占锁"
  D image inspect debian:stable-slim >/dev/null 2>&1 || D pull -q debian:stable-slim >/dev/null
  D volume create keep >/dev/null && D run --rm -v keep:/v debian:stable-slim sh -c 'echo 数据卷里的数据 > /v/f'
  D create --name keepme -v keep:/v debian:stable-slim cat /v/f >/dev/null
  must "D image inspect debian:stable-slim >/dev/null 2>&1 && [ \"\$(D run --rm -v keep:/v debian:stable-slim cat /v/f)\" = 数据卷里的数据 ]" "拉了镜像、数据卷里写了数据、建了一个停着的容器 keepme"
  m0=$(mainpid)

  step "A 用完放开，B 还在用：过了闲的时间（$IDLE 秒）也不停（等 200 秒）"
  let_go A
  sleep 200
  must "active $SV && [ \"\$(mainpid)\" = $m0 ]" "B 还在用，专用 Docker 一直开着（主进程没换）"
  echo "  这 200 秒里闲了停的脚本跑过（看系统日志）：$(journalctl --user -u $ISV --since '-200s' --no-pager -o short-precise | tail -3 | sed 's/^/      /')"

  step "B 也放开：不到 $IDLE 秒不停，过了 $IDLE 秒、计时器下一次看的时候停"
  let_go B; t0=$(date +%s)
  must "lock_free" "都放开了：拿得到独占锁"
  sleep 90
  must "active $SV" "放开 90 秒：还开着"
  e=$(wait_stopped $t0 200); echo "  放开后 $e 秒停了"
  must "[ \"$e\" != 超时 ] && [ $e -ge $((IDLE - 2)) ] && [ $e -le $((IDLE + 75)) ]" "在 $IDLE 到 $((IDLE + 75)) 秒之间停了"
  must "! active $TM" "计时器跟着停了"
  journalctl --user -u $ISV --no-pager -o cat | grep '停掉' | tail -1 | sed 's/^/  系统日志：/'
  must "[ -d ~/tools/docker-sop/$P/data ] && [ -e $UNITS/$SV ]" "停了以后数据目录、登记文件都在"

  step "再要用：起来，镜像、数据卷、容器都在"
  t=$(date +%s%N); hold C || fail=1; echo "  再起来 $(( ($(date +%s%N) - t) / 1000000 )) 毫秒"
  must "D image inspect debian:stable-slim >/dev/null 2>&1" "镜像还在"
  must "[ \"\$(D run --rm -v keep:/v debian:stable-slim cat /v/f)\" = 数据卷里的数据 ]" "数据卷和里面的数据还在"
  must "[ \"\$(D start -a keepme)\" = 数据卷里的数据 ]" "停着的容器 keepme 还在、起得来"

  step "sop 被强制结束（kill -9，来不及放开）：系统放开锁，按它开始用的时间算，过了 $IDLE 秒也停"
  t0=$(stat -c %Y $LOCK)
  pkill -9 -f "runner.docker.service use $P"; sleep 1; eval "exec ${fd_C}>&-"
  must "lock_free" "强制结束后锁被系统放开了"
  e=$(wait_stopped $t0 260); echo "  从它开始用算起 $e 秒停了"
  must "[ \"$e\" != 超时 ] && [ $e -ge $((IDLE - 2)) ] && [ $e -le $((IDLE + 75)) ]" "在 $IDLE 到 $((IDLE + 75)) 秒之间停了"

  step "正在停的时候 sop 要用：等它停完再起，起来能用"
  py -m runner.docker.service start $P "$R" --memory 300M --cpu 100% --idle $IDLE >/dev/null
  m1=$(mainpid); touch -d '-1 hour' $LOCK
  systemctl --user start --no-block $ISV
  for k in $(seq 200); do [ "$(systemctl --user show -p ActiveState --value $SV)" != active ] && break; sleep 0.05; done
  echo "  闲了停的脚本开始停了（专用 Docker：$(systemctl --user show -p ActiveState --value $SV)），这时 sop 要用"
  hold E || fail=1
  must "active $SV && D info >/dev/null 2>&1 && [ \"\$(mainpid)\" != $m1 ]" "停完又起来了（主进程 $m1 → $(mainpid)），答话"
  journalctl --user -u $ISV --no-pager -o cat | grep '停掉' | tail -1 | sed 's/^/  系统日志：/'
  sleep 70
  must "active $SV" "E 在用：之后计时器看了也不停"
  let_go E

  step "走流程命令的那条路（kernel/engine.py 的 docker()）：受限环境里经通道用专用 Docker，退出时放开"
  out=$(cd $SRC && env $NOPROXY python3 - "$R" <<'EOF'
import os, pathlib, sys, time
from kernel.engine import Engine
from runner import placement, sandbox
from runner.docker import service
R = pathlib.Path(sys.argv[1])
class P:
    name, root = 'demo-x', R
    def profile(self):
        return {'toolchain': {'docker': {'memory': '300M', 'cpu': '100%'}}, 'commands': {}}
e = Engine(P(), None, None)
sock = e.docker()
ctx = placement.Ctx(root=R, kind='restricted_script', worktree='ticket-a-1-01', feature='a-1', ro=[str(service.docker_bin())],
                    docker_sock=sock)
r = sandbox.run(ctx, [str(service.docker_bin() / 'docker'), 'run', '--rm', '-v', 'keep:/v', 'debian:stable-slim', 'cat', '/v/f'], timeout=120)
print('受限环境里：', r.returncode, r.stdout.strip(), r.stderr.strip()[-200:])
print('第二次要用同一条通道：', e.docker() == sock)
t = time.time(); time.sleep(1)
e.release_docker()
print('放开后修改时间是刚才的：', os.stat(service.lease_file('demo-x')).st_mtime >= t)
EOF
)
  echo "$out" | sed 's/^/  /'
  must "echo \"\$out\" | grep -qx '受限环境里： 0 数据卷里的数据 '" "受限环境里经通道起了容器、读到数据卷"
  must "echo \"\$out\" | grep -qx '第二次要用同一条通道： True' && echo \"\$out\" | grep -qx '放开后修改时间是刚才的： True'" "一个 sop 只起一次；退出时记下最后一次用完"
  must "lock_free" "放开了"
  e=$(systemctl --user show -p ExecStart --value $ISV | grep -o 'docker.lock [0-9]*' | cut -d' ' -f2)
  must "[ \"$e\" = 900 ]" "流程命令用的是正式的 15 分钟（$e 秒）"
  echo "  第一段结束时专用 Docker：$(systemctl --user is-active $SV)。接下来重启虚拟机"
else
  R=$(cat ~/fx.root)
  step "重启之后：没有自己起来"
  must "! active $SV && ! active $TM" "专用 Docker 和计时器都没在跑（$(systemctl --user is-active $SV)）"
  must "[ -e $UNITS/$SV ] && [ -d ~/tools/docker-sop/$P/data ]" "登记文件和数据都在"

  step "要用时起来：镜像、数据卷、容器都在"
  t=$(date +%s%N); hold F || fail=1; echo "  重启后第一次起来 $(( ($(date +%s%N) - t) / 1000000 )) 毫秒"
  must "D image inspect debian:stable-slim >/dev/null 2>&1" "镜像还在"
  must "[ \"\$(D run --rm -v keep:/v debian:stable-slim cat /v/f)\" = 数据卷里的数据 ]" "数据卷和里面的数据还在"
  must "[ \"\$(D start -a keepme)\" = 数据卷里的数据 ]" "停着的容器 keepme 还在、起得来"
  must "active $TM" "计时器跟着起来了"
  let_go F

  step "收拾"
  py -m runner.docker.service remove $P
  must "! active $SV && ! active $TM && [ -z \"\$(ls $UNITS | grep sop-)\" ]" "服务停了、四份登记文件都删了"
  rm -rf ~/tools/docker-sop/$P ~/tools/sop/state/$P ~/fx.root; chmod -R u+w $FX; rm -rf $FX /tmp/h-*
fi

echo
[ $fail = 0 ] && echo "全部对" || echo "有不对的"
exit $fail
