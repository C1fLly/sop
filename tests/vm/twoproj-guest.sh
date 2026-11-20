#!/bin/bash
# 在虚拟机里跑（由 twoproj.sh 拷进去、分两段启动）。见 twoproj.sh 的说明。用法：twoproj-guest.sh one|two
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
UNITS=~/.config/systemd/user
A=app; B=app-idle                    # 故意取这两个名字：3-18 的计时器名 sop-docker-app-idle.service 和项目 app-idle 的服务同名
declare -A MEM=([$A]=300M [$B]=400M) # 两个项目的上限故意不同，看各管各的
IDLE=120                             # 为了不等 15 分钟，闲 2 分钟就停（正式的 900 秒）；计时器每分钟看一次，和正式的一样
IMG=debian:stable-slim; WEB=busybox:stable
step() { echo; echo "=== $(date +%T) $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }
py() { (cd $SRC && env $NOPROXY python3 "$@"); }
D() { local p=$1; shift; env DOCKER_HOST=unix://$HOME/tools/docker-sop/$p/run/docker.sock ~/tools/docker/bin/docker "$@"; }
SV() { echo sop-docker-$1.service; }
TM() { echo sop-idle-$1.timer; }
active() { systemctl --user -q is-active "$1"; }
mainpid() { systemctl --user show -p MainPID --value $(SV $1); }
root() { cat ~/fx-$1.root; }
# 像 sop 那样拿着「在用」锁用专用 Docker。hold_bg <记号> <项目>：在后台开始要；hold_wait <记号>：等它拿到通道；let_go <记号>：放开
hold_bg() {
  rm -f /tmp/h-$1.in /tmp/h-$1.out; mkfifo /tmp/h-$1.in
  (cd $SRC && exec env $NOPROXY python3 -m runner.docker.service use $2 "$(root $2)" --memory ${MEM[$2]} --cpu 100% --idle $IDLE \
     < /tmp/h-$1.in > /tmp/h-$1.out 2>&1) &
  eval "exec {fd_$1}>/tmp/h-$1.in"
}
hold_wait() { for k in $(seq 90); do grep -q docker.sock /tmp/h-$1.out 2>/dev/null && return 0; sleep 1; done; cat /tmp/h-$1.out; return 1; }
let_go() { local v=fd_$1; echo >&${!v}; eval "exec ${!v}>&-"; sleep 1; }
wait_stopped() { local t0=$1; for k in $(seq $3); do active $(SV $2) || { echo $(( $(date +%s) - t0 )); return 0; }; sleep 1; done; echo 超时; return 1; }
port() { py -c "from kernel import ports; print(ports.all_allocations()['$1/w0'][0])"; }
get() { curl -s --noproxy '*' -m 5 http://127.0.0.1:$1/; }
cgroup_of() { cat /proc/$1/cgroup; }
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)，内存 $(free -m | awk '/^Mem/{print $2}') MB，$(nproc) 核，开机 $(uptime -s)"
for k in $(seq 30); do systemctl --user show-environment >/dev/null 2>&1 && break; sleep 1; done

if [ "${1:-}" = one ]; then
  step "准备：网络设置、bubblewrap、规定位置的免管理员 Docker（M2）；两个假项目 $A、$B"
  py -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')" && echo "  网络设置写好了"
  py -m machine.install bubblewrap uidmap dbus-user-session docker > /tmp/m2.log 2>&1
  if grep -q '^都装好了' /tmp/m2.log; then echo "  bubblewrap $(bwrap --version)、Docker $(~/tools/docker/bin/docker --version | cut -d, -f1) 装好了"
  else echo "  M2 没装好："; cat /tmp/m2.log; exit 1; fi
  for p in $A $B; do
    rm -rf ~/fx-$p; mkdir -p ~/fx-$p
    py -c "from runner.selftest import make_fixture; print(make_fixture('$HOME/fx-$p')[0])" > ~/fx-$p.root
    echo "项目 $p 的文件" > "$(root $p)/main/只有$p有.txt"
    echo "  项目 $p 的根 $(root $p)"
  done

  step "两个项目的 sop 同时分配端口（各 8 个工作目录）；另有一个别的程序占着 20003（登记里没有）"
  python3 -c 'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",20003)); s.listen(); time.sleep(60)' & other=$!
  sleep 0.5
  pids=()
  for p in $A $B; do
    py -c "import json; from kernel import ports; print(json.dumps([ports.allocate('$p', f'w{i}') for i in range(8)]))" > /tmp/ports-$p.json &
    pids+=($!)
  done
  wait "${pids[@]}"; kill $other 2>/dev/null; wait $other 2>/dev/null
  out=$(python3 - /tmp/ports-$A.json /tmp/ports-$B.json <<'EOF'
import json, sys
a, b = (json.load(open(f)) for f in sys.argv[1:])
flat = [p for blk in a + b for p in blk]
print('各分到', len(a), len(b), '组；', '重复的', len(flat) - len(set(flat)), '个；', '含 20003 的', sum(20003 in blk for blk in a + b), '组；',
      '每组连续 10 个', all(blk == list(range(blk[0], blk[0] + 10)) for blk in a + b))
EOF
)
  echo "  $out"
  must "[ \"$out\" = '各分到 8 8 组； 重复的 0 个； 含 20003 的 0 组； 每组连续 10 个 True' ]" "端口分配不打架：两个项目各 8 组、没有一个端口分了两次、让开了别的程序占着的 20003"
  PA=$(port $A); PB=$(port $B); echo "  $A 的 w0 用 $PA，$B 的 w0 用 $PB"

  step "两个 sop 同时要用：两个专用 Docker 同时起来"
  t=$(date +%s%N); hold_bg A $A; hold_bg B $B
  hold_wait A || fail=1; hold_wait B || fail=1
  echo "  两个都拿到通道：$(cat /tmp/h-A.out)、$(cat /tmp/h-B.out)（$(( ($(date +%s%N) - t) / 1000000 )) 毫秒）"
  for p in $A $B; do must "active $(SV $p) && active $(TM $p) && D $p info >/dev/null 2>&1" "$p：专用 Docker 起来了、答话，闲了停的计时器跟着起来"; done
  ls $UNITS | sed 's/^/    登记文件：/'
  must "[ \$(ls $UNITS | grep -c '^sop-') = 8 ]" "两个项目各四份登记文件、一共 8 份，名字没有撞的"
  must "grep -q '^ExecStart=.*/idle-stop.sh sop-docker-$A.service ' $UNITS/sop-idle-$A.service && grep -q '^ExecStart=.*/idle-stop.sh sop-docker-$B.service ' $UNITS/sop-idle-$B.service" "两个闲了停的计时器各停各的专用 Docker"
  for p in $A $B; do
    sl=$(systemctl --user show -p Slice --value $(SV $p))
    echo "  $p 的分组 $sl，内存上限 $(systemctl --user show -p MemoryMax --value "$sl")"
  done
  must "[ \"\$(systemctl --user show -p MemoryMax --value 'sop-app.slice')\" = 851443712 ] && [ \"\$(systemctl --user show -p MemoryMax --value 'sop-app\\x2didle.slice')\" = 956301312 ]" "两个分组各是各的上限（容器 300M、400M，再各加 512M 给专用 Docker 自己，3-55），app-idle 的分组没挂到 app 下面"

  step "两个专用 Docker 里起同名的容器 web、同名的数据卷 data、同名的网络 net，各自映射自己分到的端口"
  for p in $A $B; do
    D $p image inspect $IMG >/dev/null 2>&1 || D $p pull -q $IMG >/dev/null
    D $p image inspect $WEB >/dev/null 2>&1 || D $p pull -q $WEB >/dev/null
    D $p volume create data >/dev/null; D $p network create net >/dev/null
    D $p run --rm -v data:/www $WEB sh -c "echo 我是$p > /www/index.html"
  done
  for p in $A $B; do
    pp=$([ $p = $A ] && echo $PA || echo $PB)
    D $p run -d --name web --network net --restart unless-stopped -p 127.0.0.1:$pp:80 -v data:/www $WEB httpd -f -p 80 -h /www >/dev/null \
      && echo "  $p：容器 web 起来了，映射 127.0.0.1:$pp"
  done
  sleep 1
  must "[ \"\$(get $PA)\" = 我是$A ] && [ \"\$(get $PB)\" = 我是$B ]" "两个同名的 web 各在自己的端口上答自己的数据（$PA：$(get $PA)，$PB：$(get $PB)）"
  must "[ \"\$(D $A ps --format '{{.Names}}')\" = web ] && [ \"\$(D $B ps --format '{{.Names}}')\" = web ] && [ \"\$(D $A inspect -f '{{.Id}}' web)\" != \"\$(D $B inspect -f '{{.Id}}' web)\" ]" "各自只看得到自己的那一个 web，是两个不同的容器"
  for p in $A $B; do
    pid=$(D $p inspect -f '{{.State.Pid}}' web); echo "  $p 的 web 在宿主上是进程 $pid：$(cgroup_of $pid)"
  done
  must "cgroup_of \$(D $A inspect -f '{{.State.Pid}}' web) | grep -qF '/sop-app.slice/' && cgroup_of \$(D $B inspect -f '{{.State.Pid}}' web) | grep -qF '/sop-app\\x2didle.slice/'" "两个 web 各落在自己项目的分组里"
  out=$(D $B run -d --name thief -p 127.0.0.1:$PA:80 $WEB httpd -f -p 80 2>&1); rc=$?
  echo "  $B 想占 $A 的端口 $PA：退出码 $rc，$(echo "$out" | tail -1 | cut -c1-160)"
  must "[ $rc != 0 ] && [ \"\$(get $PA)\" = 我是$A ]" "另一个项目占不了这个端口（系统层面也撞得出来），$A 的 web 照常"
  D $B rm -f thief >/dev/null 2>&1

  step "视野：一个项目的专用 Docker 看不到另一个项目的根和数据"
  RA=$(root $A); RB=$(root $B)
  out=$(D $A run --rm -v "$RB:/p" $IMG sh -c "cat /p/main/只有$B有.txt 2>&1; ls /p | wc -l" 2>&1); echo "  $A 挂 $B 的根：$(echo $out)"
  must "! echo \"\$out\" | grep -q '项目 $B 的文件'" "$A 的专用 Docker 读不到 $B 的项目文件"
  out=$(D $B run --rm -v "$RA:/p" $IMG sh -c "cat /p/main/只有$A有.txt 2>&1" 2>&1); echo "  $B 挂 $A 的根：$(echo $out)"
  must "! echo \"\$out\" | grep -q '项目 $A 的文件'" "$B 的专用 Docker 读不到 $A 的项目文件"
  out=$(D $B run --rm -v "$HOME/tools/docker-sop/$A:/x" $IMG sh -c 'ls /x/data 2>&1 | head -3' 2>&1); echo "  $B 挂 $A 的数据目录：$(echo $out)"
  must "[ -z \"\$(echo \$out | grep -v 'No such file')\" ]" "$B 的专用 Docker 看不到 $A 的数据目录"
  out=$(D $A run --rm -v "$RA:/p" $IMG cat /p/main/只有$A有.txt 2>&1); must "[ \"$out\" = '项目 $A 的文件' ]" "自己的项目文件照常读得到"

  step "删一个项目的同名容器和数据卷：另一个不受影响"
  D $A run -d --name tmp1 $IMG sleep 999 >/dev/null; D $B run -d --name tmp1 $IMG sleep 999 >/dev/null
  D $A rm -f tmp1 >/dev/null; D $A volume create gone >/dev/null; D $B volume create gone >/dev/null; D $A volume rm gone >/dev/null
  must "[ \"\$(D $B inspect -f '{{.State.Running}}' tmp1)\" = true ] && D $B volume inspect gone >/dev/null 2>&1" "$A 删了自己的 tmp1 和卷 gone，$B 的同名容器还在跑、同名卷还在"
  D $B rm -f tmp1 >/dev/null; D $B volume rm gone >/dev/null

  step "$A 超内存（上限 300M，三次）：只杀 $A 里的；$B 的专用 Docker 和 web 不受影响"
  mb=$(mainpid $B); ma=$(mainpid $A)
  for i in 1 2 3; do D $A run --rm $IMG tail /dev/zero >/dev/null 2>&1; echo "  第 $i 次退出码 $?"; done
  for k in $(seq 30); do D $A info >/dev/null 2>&1 && break; sleep 1; done
  ev=$(awk '/^oom_kill /{print $2}' "/sys/fs/cgroup$(dirname $(systemctl --user show -p ControlGroup --value $(SV $A)))/memory.events")
  echo "  $A 的分组记下被杀 $ev 次；$A 的专用 Docker 主进程 $ma → $(mainpid $A)；$B 的 $mb → $(mainpid $B)"
  must "[ \"$ev\" -ge 3 ]" "$A 的分组按自己的上限杀了"
  must "[ \"\$(mainpid $B)\" = $mb ] && [ \"\$(D $B inspect -f '{{.State.Running}}' web)\" = true ] && [ \"\$(get $PB)\" = 我是$B ]" "$B 的专用 Docker 没换、web 还在跑、还在答话"
  must "[ \"\$(mainpid $A)\" = $ma ]" "$A 的专用 Docker 自己也没事（3-54）"
  must "[ \"\$(D $A inspect -f '{{.State.Running}}' web)\" = true ] && [ \"\$(get $PA)\" = 我是$A ]" "$A 自己的 web 也没跟着停、还在答话（3-55）"
  [ "$(get $PA)" = 我是$A ] || { D $A start web >/dev/null; sleep 1; }

  step "$A 用完放开、$B 还在用：$A 过了闲的时间停了，$B 照常"
  let_go A; t0=$(date +%s)
  e=$(wait_stopped $t0 $A 220); echo "  $A 放开后 $e 秒停了"
  must "[ \"$e\" != 超时 ] && [ $e -ge $((IDLE - 2)) ] && [ $e -le $((IDLE + 75)) ] && ! active $(TM $A)" "$A 在 $IDLE 到 $((IDLE + 75)) 秒之间停了，计时器跟着停"
  must "active $(SV $B) && [ \"\$(mainpid $B)\" = $mb ] && active $(TM $B) && [ \"\$(get $PB)\" = 我是$B ]" "$B 一直开着（主进程没换），它的计时器在，web 还在答话"
  hold_bg A2 $A; hold_wait A2 || fail=1; sleep 2
  must "[ \"\$(get $PA)\" = 我是$A ]" "$A 再要用时起来：web 自己起来了（unless-stopped），还是 $PA、还是自己的数据"

  step "走流程命令的那条路：两个 sop（kernel/engine.py 的 docker()）在受限环境里各经各的通道，只看得到自己的"
  out=$(cd $SRC && env $NOPROXY python3 - "$(root $A)" "$(root $B)" <<'EOF'
import pathlib, sys
from kernel.engine import Engine
from runner import placement, sandbox
from runner.docker import service
mem = {'app': '300M', 'app-idle': '400M'}
def eng(name, root):
    class P:
        pass
    P.name, P.root = name, pathlib.Path(root)
    P.profile = lambda self: {'toolchain': {'docker': {'memory': mem[name], 'cpu': '100%'}}, 'commands': {}}
    return Engine(P(), None, None)
es = [eng('app', sys.argv[1]), eng('app-idle', sys.argv[2])]
for e in es:
    sock = e.docker()
    ctx = placement.Ctx(root=e.p.root, kind='restricted_script', worktree='ticket-a-1-01', feature='a-1',
                        ro=[str(service.docker_bin())], docker_sock=sock)
    d = str(service.docker_bin() / 'docker')
    r = sandbox.run(ctx, ['sh', '-c', f'{d} ps --format "{{{{.Names}}}}"; {d} run --rm -v data:/v busybox:stable cat /v/index.html'],
                    timeout=120)
    print(e.p.name, r.returncode, ' '.join(r.stdout.split()), r.stderr.strip()[-200:])
for e in es:
    e.release_docker()
EOF
)
  echo "$out" | sed 's/^/  /'
  must "echo \"\$out\" | grep -qx 'app 0 web 我是app ' && echo \"\$out\" | grep -qx 'app-idle 0 web 我是app-idle '" "受限环境里：各自只看到自己的 web，读到自己的数据卷"

  step "两个专用 Docker 都开着，准备重启"
  let_go A2; let_go B
  for p in $A $B; do must "active $(SV $p) && [ \"\$(get \$(port $p))\" = 我是$p ]" "$p 开着、web 在答话"; done
  rm -rf ~/units-before; mkdir ~/units-before; cp -p $UNITS/sop-* ~/units-before/   # 原样存一份（分组名里有反斜杠，md5sum 会跳过那一行，所以逐字节比）
  py -c "import json; from kernel import ports; print(json.dumps(ports.all_allocations(), sort_keys=True))" > ~/ports-before.json
else
  step "重启之后：按问题 1 的答案，两个都没自己起来"
  for p in $A $B; do
    must "! active $(SV $p) && ! active $(TM $p)" "$p 的专用 Docker 和计时器都没在跑（$(systemctl --user is-active $(SV $p))）"
  done
  same_units() { [ "$(ls $UNITS | grep '^sop-')" = "$(ls ~/units-before)" ] || return 1
                 for f in ~/units-before/*; do cmp -s "$f" "$UNITS/$(basename "$f")" || return 1; done; }
  must "[ \$(ls ~/units-before | wc -l) = 8 ] && same_units" "8 份登记文件都在、逐字节没变"
  PA=$(port $A); PB=$(port $B)
  now=$(py -c 'import json; from kernel import ports; print(json.dumps(ports.all_allocations(), sort_keys=True))')
  again=$(py -c "from kernel import ports; print(ports.allocate('$A', 'w0')[0])")
  must "[ \"\$now\" = \"\$(cat ~/ports-before.json)\" ] && [ \"$again\" = $PA ]" "端口登记都在，同一个工作目录再要还是原来那组（$again）"
  must "[ -z \"\$(get $PA)\" ] && [ -z \"\$(get $PB)\" ]" "这时 $PA、$PB 都没人答话（容器没起来）"

  step "两个 sop 同时要用：各自起来，镜像、数据卷、容器、端口都在"
  t=$(date +%s%N); hold_bg A $A; hold_bg B $B; hold_wait A || fail=1; hold_wait B || fail=1
  echo "  重启后两个一起起来 $(( ($(date +%s%N) - t) / 1000000 )) 毫秒"
  sleep 2
  for p in $A $B; do
    pp=$(port $p)
    must "active $(SV $p) && active $(TM $p)" "$p 起来了，计时器跟着起来"
    must "D $p image inspect $IMG >/dev/null 2>&1 && D $p image inspect $WEB >/dev/null 2>&1" "$p 的两个镜像都在"
    must "[ \"\$(D $p run --rm -v data:/v $IMG cat /v/index.html)\" = 我是$p ] && D $p network inspect net >/dev/null 2>&1" "$p 的数据卷 data（里面是自己的数据）和网络 net 都在"
    must "[ \"\$(get $pp)\" = 我是$p ]" "$p 的 web 自己起来了，还在 $pp 上答自己的数据"
  done
  let_go A; let_go B

  step "收拾"
  for p in $A $B; do py -m runner.docker.service remove $p; done
  must "[ -z \"\$(ls $UNITS | grep sop-)\" ] && ! active $(SV $A) && ! active $(SV $B)" "两个都停了、8 份登记文件都删了"
  rm -rf ~/units-before; rm -f ~/ports-before.json /tmp/h-* /tmp/ports-*.json
fi

echo
[ $fail = 0 ] && echo "全部对" || echo "有不对的"
exit $fail
