#!/bin/bash
# 在虚拟机里跑（由 docker.sh 拷进去、启动）。见 docker.sh 的说明。
set -uo pipefail
SRC=~/sop-src
T=~/tools/docker
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
step() { echo; echo "=== $* ==="; }
mode=; after=; prepare=
broken=
for a in "$@"; do case $a in --system) mode=system ;; --rootless) mode=rootless ;; --after-reboot) after=1 ;; --prepare) prepare=1 ;; --broken) broken=1 ;; esac; done
# 在「新开的终端」里跑（交互、不是登录的那种，和桌面上开一个终端一样，会读 ~/.bashrc）
term() { bash -ic "$1" 2>&1 | grep -v -e 'cannot set terminal process group' -e 'no job control in this shell'; }
OLDD="env DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock $HOME/bin/docker"
NEW() { env -u DOCKER_CONTEXT DOCKER_HOST="$(cat $T/etc/docker-host)" $T/bin/docker "$@"; }
fail=0
# 端口映射（要 iptables 和网络模块）：容器里起一个小网页服务，映射到 18080，本机能取到
port_test() {
  NEW pull -q busybox:1.36 >/dev/null 2>&1
  NEW rm -f sop-port >/dev/null 2>&1
  NEW run -d --name sop-port -p 127.0.0.1:18080:80 busybox:1.36 sh -c 'echo 端口映射能用 > /index.html; httpd -f -p 80 -h /' >/dev/null
  sleep 2; local got; got=$(curl -s --noproxy '*' --max-time 5 http://127.0.0.1:18080/index.html)
  NEW rm -f sop-port >/dev/null 2>&1
  must "[ \"$got\" = 端口映射能用 ]" "端口映射能用（容器里的网页服务映射到本机 18080）"
}
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }

if [ -n "$after" ]; then
  step "重启之后（ssh 登录进来，没手动起任何东西）"
  unit=docker; [ -f ~/.config/systemd/user/sop-docker.service ] && unit=sop-docker
  for i in $(seq 1 30); do NEW info >/dev/null 2>&1 && break; sleep 1; done
  must "systemctl --user -q is-active $unit" "后台服务 $unit 登录后自己起来了"
  must "grep -qw '^nf_tables' /proc/modules" "网络模块 nf_tables 由系统自动载入了（没写开机配置）"
  NEW pull -q alpine:3.20 >/dev/null 2>&1
  out=$(NEW run --rm alpine:3.20 echo 重启后容器能跑 2>&1); echo "  $out"
  must "[ \"$out\" = 重启后容器能跑 ]" "重启后规定位置的 Docker 能起容器"
  port_test
  case $mode in
    system) must "sudo docker ps --format '{{.Names}}' | grep -qx old-web" "系统自带的那份和它的容器照常（重启后按它自己的设置起来）" ;;
    rootless) must "$OLDD ps --format '{{.Names}}' | grep -qx old-web" "旧的免管理员那份和它的容器照常" ;;
  esac
  exit $fail
fi

echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"

# --prepare：先造「电脑上原来就有一份」（单独一次登录做，下一次登录 docker 组才生效）
if [ -n "$prepare" ] && [ "$mode" = system ]; then
  step "先用 Ubuntu 软件源装一份系统自带的 docker.io，小白加进 docker 组（能直接用），起一个容器"
  sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >/dev/null
  sudo mkdir -p /etc/systemd/system/docker.service.d
  printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
  sudo systemctl daemon-reload; sudo systemctl restart docker
  sudo usermod -aG docker xiaobai
  sudo docker run -d --name old-web --restart unless-stopped busybox:1.36 sleep 1d >/dev/null
  echo "旧的：$(dpkg-query -W -f '${Package} ${Version}' docker.io)，容器 $(sudo docker ps --format '{{.Names}}')；/var/run/docker.sock $(sg docker -c 'test -w /var/run/docker.sock' && echo 小白能写 || echo 小白不能写)"
fi
if [ -n "$prepare" ] && [ "$mode" = rootless ]; then
  step "先照官方一条命令的装法装一份免管理员的（程序在 ~/bin，服务名 docker，数据在 ~/.local/share/docker），起一个容器"
  export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq uidmap >/dev/null
  printf 'abi <abi/4.0>,\ninclude <tunables/global>\n\n"%s/bin/rootlesskit" flags=(unconfined) {\n  userns,\n}\n' "$HOME" | sudo tee /etc/apparmor.d/home.xiaobai.bin.rootlesskit >/dev/null
  sudo apparmor_parser -r /etc/apparmor.d/home.xiaobai.bin.rootlesskit
  curl -fsSL https://get.docker.com/rootless -o /tmp/rootless.sh
  SKIP_IPTABLES=1 FORCE_ROOTLESS_INSTALL=1 sh /tmp/rootless.sh >/tmp/rootless-install.log 2>&1 || { tail /tmp/rootless-install.log; }
  mkdir -p ~/.config/systemd/user/docker.service.d
  printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY > ~/.config/systemd/user/docker.service.d/proxy.conf
  systemctl --user daemon-reload; systemctl --user restart docker; sleep 3
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  $OLDD run -d --name old-web --restart unless-stopped busybox:1.36 sleep 1d >/dev/null
  echo "旧的：$($OLDD version --format '{{.Server.Version}}')，数据在 $($OLDD info --format '{{.DockerRootDir}}')，容器 $($OLDD ps --format '{{.Names}}')；默认指向 $(~/bin/docker context show)"
  cat >> ~/.bashrc <<'EOF'
export PATH=$HOME/bin:$PATH
export DOCKER_HOST=unix:///run/user/1000/docker.sock
EOF
  echo "（照官方装完的提示，在 ~/.bashrc 里加了 PATH 和 DOCKER_HOST 两行）"
fi
[ -n "$prepare" ] && exit 0
if [ -n "$mode" ]; then
  if [ "$mode" = system ]; then OLDS="/var/lib/docker /etc/docker /usr/bin/docker /usr/sbin/dockerd"
  else OLDS="$HOME/bin $HOME/.local/share/docker $HOME/.config/systemd/user/docker.service $HOME/.config/systemd/user/docker.service.d $HOME/.docker"; fi
  sudo find $OLDS -maxdepth 2 -printf '%p %y %s %T@ %m\n' 2>/dev/null | sort > /tmp/old-before.txt
  ctx_before=$(env -u DOCKER_HOST docker context show 2>/dev/null || ~/bin/docker context show)
  echo "装之前：docker 命令的默认指向是「$ctx_before」；旧的那几处记下了 $(wc -l < /tmp/old-before.txt) 项"
fi

[ "$mode" = system ] && echo "这一次登录：/var/run/docker.sock $([ -w /var/run/docker.sock ] && echo 小白能写 || echo 小白不能写)"
sleep 1; touch /tmp/docker.mark; sleep 1

step "写网络设置（第零步会写的那一份 ~/tools/sop/config/network.json）"
(cd $SRC && env $NOPROXY python3 -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')") && echo 写好了

if [ -n "$broken" ]; then
  step "先让它装到一半失败一次：给用户级后台服务设一个坏的网络设置，Docker 起不来"
  systemctl --user set-environment DOCKERD_ROOTLESS_ROOTLESSKIT_NET=no-such-driver
  term "cd $SRC && env $NOPROXY python3 -m machine.install uidmap dbus-user-session docker" > /tmp/docker-broken.log
  grep -e '没装好' -e '出错' -e '收拾' -e '没装完' /tmp/docker-broken.log | sed 's/^/  /'
  must "! grep -q '^都装好了' /tmp/docker-broken.log" "这一次没装好，明说了"
  must "[ ! -e $T/bin ] && [ ! -e ~/.config/systemd/user/docker.service ]" "这一次新放的程序、服务登记文件拿掉了"
  must "! systemctl --user -q is-active docker" "没留下在跑的服务"
  must "[ \"\$(python3 -c 'import json;print(json.load(open(\"$HOME/.docker/config.json\")).get(\"currentContext\") or \"default\")' 2>/dev/null || echo default)\" = default ]" "默认指向没留在新的那份上"
  must "[ -f /etc/apparmor.d/home.xiaobai.tools.docker.bin.rootlesskit ]" "系统规则留着（重装还要用）"
  systemctl --user unset-environment DOCKERD_ROOTLESS_ROOTLESSKIT_NET
  echo "  把坏的设置去掉，接着正常装："
fi

step "M2 安装免管理员的 Docker（在新开的终端里跑，代理只从网络设置来）"
t0=$(date +%s)
term "cd $SRC && env $NOPROXY python3 -m machine.install uidmap dbus-user-session docker" > /tmp/docker-install.log
if grep -q '^都装好了' /tmp/docker-install.log; then grep -v -e '^\s*$' /tmp/docker-install.log | tail -20
else fail=1; echo "没装好，完整输出："; cat /tmp/docker-install.log; fi
echo "（用了 $(( $(date +%s) - t0 )) 秒；完整输出在虚拟机的 /tmp/docker-install.log）"

step "核对"
unit=docker; [ "$mode" = rootless ] && unit=sop-docker
must "grep -qs '要管理员权限' /tmp/docker-broken.log /tmp/docker-install.log && grep -qs '登录密码' /tmp/docker-broken.log /tmp/docker-install.log" "要管理员密码的那一步先用大白话说了"
must "systemctl --user -q is-active $unit && systemctl --user -q is-enabled $unit" "后台服务 $unit 在跑、登录后自己起来"
echo "  通道：$(cat $T/etc/docker-host)"
must "[ \"\$(NEW info --format '{{.DockerRootDir}}')\" = $T/data ]" "数据在 ~/tools/docker/data"
must "NEW info --format '{{.SecurityOptions}}' | grep -q rootless" "是免管理员的"
NEW pull -q alpine:3.20 >/dev/null 2>&1
out=$(NEW run --rm alpine:3.20 sh -c 'echo 容器能跑：$(cat /etc/alpine-release)' 2>&1); echo "  $out"
must "echo \"$out\" | grep -q 容器能跑" "能拉镜像、起一个容器（经网络设置里的代理）"
must "[ -n \"\$(find $T/data -maxdepth 3 -name '*.json' -path '*image*' 2>/dev/null | head -1)\" ] || [ -d $T/data/image ]" "镜像存在 ~/tools/docker/data 下"
must "[ ! -e ~/.local/share/docker ] || [ \"$mode\" = rootless ]" "没有用默认的数据位置 ~/.local/share/docker"
must "grep -q '\"data-root\": \"$T/data\"' $T/etc/daemon.json && grep -q http-proxy $T/etc/daemon.json" "设置文件里写了数据位置和代理"
du -sh $T/bin $T/data 2>/dev/null | sed "s#$HOME#~#; s/^/  大小 /"
echo "  系统上加了的：$(ls /etc/apparmor.d/ | grep tools.docker)；uidmap $(dpkg-query -W -f '${Version}' uidmap)；网络模块 nf_tables $(grep -qw '^nf_tables' /proc/modules && echo 已载入)"
port_test
echo "  体检看到的系统规则：$(cd $SRC && python3 -c 'from machine import components; print(components.collect()["userns_rule"])')"
(cd $SRC && python3 -c '
from machine import catalog
for n in ("uidmap", "dbus-user-session", "docker"):
    r = catalog.run_check(catalog.find(n)); print("  清单的检查命令", n, "合格" if r.ok else "不合格", r.version_text)')

step "新开一个终端，不加 sudo 敲 docker"
term 'echo "  docker → $(command -v docker)；默认指向 $(docker context show)；连到的 Docker：$(docker info --format "{{.DockerRootDir}}" 2>&1 | tail -1)"; docker ps --format "  容器 {{.Names}}" 2>&1 | head -5' | tee /tmp/term.txt
case $mode in
  "") must "grep -q '默认指向 rootless' /tmp/term.txt && grep -q '连到的 Docker：$T/data' /tmp/term.txt" "电脑上只有这一份：敲 docker 用的就是它" ;;
  system) must "grep -q 'force' /tmp/docker-install.log" "系统自带的在运行、小白能写它的通道：官方脚本加了 --force"
          must "grep -q '已切回原来的「default」' /tmp/docker-install.log" "装完把默认指向切回了原来那份"
          must "grep -q '连到的 Docker：/var/lib/docker' /tmp/term.txt && grep -q '容器 old-web' /tmp/term.txt" "敲 docker 看到的还是系统自带的那份和它的容器" ;;
  rootless) must "grep -q 'sop-docker' /tmp/docker-install.log" "docker 这个服务名被旧的占了：规定位置的用 sop-docker"
            must "systemctl --user -q is-active docker" "旧的 docker 服务照常在跑"
            must "grep -q '容器 old-web' /tmp/term.txt" "敲 docker 看到的还是旧的那份和它的容器"
            must "[ \"\$(~/bin/docker context show)\" = \"$ctx_before\" ]" "默认指向没动（还是「$ctx_before」）" ;;
esac

step "~/tools 之外，这次新出现或改动过的东西（不算拷进来的代码、/tmp）"
find ~ -newer /tmp/docker.mark -not -path "$HOME/tools/*" -not -path "$HOME/sop-src*" -not -path "$HOME/.ssh*" -printf '  %y %p\n' 2>/dev/null | sed "s#$HOME#~#" | head -30
echo "  系统目录里："
sudo find /etc /usr/local /var/lib/docker /opt -xdev -newer /tmp/docker.mark -printf '  %y %p\n' 2>/dev/null | grep -v -e '/etc/ld.so.cache' | head -30
echo "  新装的系统软件包：$(grep -h ' install ' /var/log/dpkg.log | awk -v t="$(date -r /tmp/docker.mark '+%Y-%m-%d %H:%M:%S')" '$1" "$2 >= t {print $4}' | tr '\n' ' ')"

if [ -n "$mode" ]; then
  step "旧的动没动"
  sudo find $OLDS -maxdepth 2 -printf '%p %y %s %T@ %m\n' 2>/dev/null | sort > /tmp/old-after.txt
  if diff -q /tmp/old-before.txt /tmp/old-after.txt >/dev/null; then echo "  旧的那几处（$(wc -l < /tmp/old-after.txt) 项）大小、修改时间、权限都一样"
  else echo "  旧的那几处有变化（下面是差别；容器在跑，数据目录里的运行文件会变）："; diff /tmp/old-before.txt /tmp/old-after.txt | head -12 | sed 's/^/    /'; fi
fi

step "再装一次：应该跳过"
before=$(stat -c '%Y %s' ~/.bashrc $T/etc/daemon.json ~/.config/systemd/user/$unit.service | tr '\n' ' ')
term "cd $SRC && env $NOPROXY python3 -m machine.install uidmap dbus-user-session docker" | grep -e '跳过' -e '没装完' -e '都装好了' -e '管理员' | sed 's/^/  /'
after=$(stat -c '%Y %s' ~/.bashrc $T/etc/daemon.json ~/.config/systemd/user/$unit.service | tr '\n' ' ')
must "[ \"$before\" = \"$after\" ]" "终端启动文件、设置文件、服务登记文件都没被再改"

step "直接再跑一遍安装脚本（模拟重装、升级）：不要密码，服务停一下再起来，数据还在"
NEW pull -q busybox:1.36 >/dev/null
(cd $SRC && env $NOPROXY python3 -c "
import subprocess, sys
from machine import install
sys.exit(subprocess.run(['bash', 'machine/install/docker-rootless.sh'], env=install.script_env(), stdin=subprocess.DEVNULL).returncode)") > /tmp/docker-reinstall.log 2>&1
rrc=$?
tail -3 /tmp/docker-reinstall.log | sed 's/^/  /'
must "[ $rrc = 0 ]" "重装成功"
must "! grep -q 管理员权限 /tmp/docker-reinstall.log" "系统规则已经在了，重装不要密码"
must "NEW image inspect busybox:1.36 >/dev/null 2>&1" "重装前拉的镜像还在"
case $mode in system) must "env -u DOCKER_HOST docker context show | grep -qx default" "重装后默认指向还是原来那份" ;; esac
exit $fail
