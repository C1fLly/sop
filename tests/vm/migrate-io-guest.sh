#!/bin/bash
# 3-33：在虚拟机里跑（由 migrate-io.sh 拷进去、启动）。见 migrate-io.sh 的说明。3-34 加了 docker-ce（--prepare ce），
# 3-35 加了免管理员但位置不对的（--prepare rl）。
#   --prepare [io|ce|rl]：先记下装旧 Docker 之前系统里有哪些文件、哪些软件包；再装 docker.io（io，默认）或照 Docker 官网装 docker-ce（ce）、
#              或照 Docker 官网的免管理员装法装一份（rl：程序在 ~/bin、服务名 docker、数据在 ~/.local/share/docker）、
#              放镜像数据卷容器（单独一次登录做，下一次登录 docker 组才生效）。装的是哪种记在 ~/io-base/kind，后面几步照它核对。
#              ce 先造得像桌面版（卸掉 git、curl：桌面版不带），官网的步骤会装回 curl，git 由 docker-ce 推荐装进来（自动装的）
#              rl：规定位置那份装的时候应该另起服务名 sop-docker、两份并存；Q6 先删数据（借旧的 rootlesskit）再删程序，
#              卸完规定位置那份接过 docker 这个服务名和通道
#   --run1   ：第一遍 sop machine migrate：Q2 装规定位置的 Docker，Q3 选卸 docker.io、带走数据，Q4 停了旧容器、正在打包时强制结束整个 sop；
#              看旧容器停着；再执行一次别的 sop 命令，看起回来、临时小镜像删掉
#   --run2   ：先把默认指向手动切到新的（模拟小白切过）；第二遍走完 Q1 到 Q6，Q6 切回原来那份之后暂停整个 sop，看不加 sudo 敲 docker
#              是原来那份；卸完核对残留清单逐项为空、和装 docker.io 之前的系统比、敲 docker 是规定位置那份、带走的数据一致
#   --look <文件>：新开一个终端，不加 sudo 敲 docker，看到的写进文件（run2 暂停时由驱动调）
set -uo pipefail
SRC=~/sop-src
T=~/tools/docker
B=~/io-base                          # 装旧 Docker 之前的样子、旧数据的校验值、装的是哪种（kind）
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
SOP="python3 -I $SRC/kernel/main.py"   # 启动器执行的就是这一句（kernel/launcher.py、kernel/main.py）
DRIVE="python3 -I $SRC/tests/vm/migrate-drive.py"
U=$(id -u)
NEW() { env -u DOCKER_CONTEXT DOCKER_HOST="$(cat $T/etc/docker-host)" $T/bin/docker "$@"; }
term() { bash -ic "$1" 2>&1 | grep -v -e 'cannot set terminal process group' -e 'no job control in this shell'; }
step() { echo; echo "=== $* ==="; }
KIND=$(cat $B/kind 2>/dev/null || echo docker.io)     # docker.io、docker-ce 或 rootless（--prepare 写的）
kind_vars() {   # 原来那份怎么连、数据在哪、默认指向叫什么、清点里叫什么、Q3 的问题怎么认
  if [ "$KIND" = rootless ]; then
    OLD="env -u DOCKER_HOST -u DOCKER_CONTEXT $HOME/bin/docker --host unix:///run/user/$U/docker.sock"
    OLD_ROOT=$HOME/.local/share/docker; OLD_CTX=rootless; LABEL='免管理员的 Docker，但不在规定位置'; QRE="$LABEL[^\n]*合计"
  else
    OLD="env -u DOCKER_HOST -u DOCKER_CONTEXT /usr/bin/docker --host unix:///var/run/docker.sock"
    OLD_ROOT=/var/lib/docker; OLD_CTX=default; LABEL=$KIND; QRE="$KIND）[^\n]*合计"
  fi
}
kind_vars
KEEP="git curl wget iptables uidmap dbus-user-session"   # 工具包自己要用的系统软件包（卸旧 Docker 不能连带卸掉，3-34）
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }

sysfiles() {   # 系统里的文件（只要路径）；apt 的索引、dpkg 自己的库、缓存不算
  sudo find /etc /usr /var/lib /opt /srv -xdev \( -path /var/lib/apt/lists -o -path /var/lib/dpkg -o -path /var/lib/systemd \
    -o -path /var/lib/ubuntu-advantage -o -path /var/lib/update-notifier -o -path /var/lib/cloud -o -name __pycache__ \) -prune -o -print 2>/dev/null | sort
}
pkgs() { dpkg-query -W -f '${Package} ${db:Status-Abbrev}\n' | awk '$2 ~ /^ii/ {print $1}' | sort; }
homefiles() {   # 主目录里的全部（只要路径）；工具包自己的、试验脚本的、缓存不算；旧的数据目录只列它自己（里面有读不了的）
  find ~ -xdev \( -path "$HOME/.local/share/docker" -print -prune \) -o \( -path "$HOME/sop-src" -o -path "$HOME/io-base" \
    -o -path "$HOME/tools" -o -path "$HOME/.cache" \) -prune -o -print 2>/dev/null | sed "s#^$HOME#~#" | sort
}
ROOTLESS_BINS="containerd containerd-shim-runc-v2 ctr docker docker-init docker-proxy dockerd dockerd-rootless-setuptool.sh dockerd-rootless.sh rootlesskit runc"

if [ "${1:-}" = --look ]; then
  term 'echo "docker → $(command -v docker)；默认指向 $(docker context show 2>&1)；连到的 Docker 数据在 $(docker info --format "{{.DockerRootDir}}" 2>&1 | tail -1)"; docker ps --format "容器 {{.Names}}" 2>&1 | head -5' > "$2"
  exit 0
fi

if [ "${1:-}" = --prepare ]; then
  case ${2:-io} in io) KIND=docker.io ;; ce) KIND=docker-ce ;; rl) KIND=rootless ;; *) echo "用法：--prepare [io|ce|rl]"; exit 2 ;; esac
  kind_vars
  echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"
  rm -rf $B; mkdir -p $B; echo $KIND > $B/kind
  if [ $KIND = docker-ce ]; then
    step "先造得像桌面版的小白电脑：卸掉 git、curl（桌面版不带）"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq git curl 2>&1 | grep -E '^(Removing|Purging)' | sed 's/^/  /'
    must '! command -v git >/dev/null && ! command -v curl >/dev/null' "git、curl 都没了"
    # 这台试验电脑只有经本机代理才连得上 download.docker.com（Ubuntu 的软件源直连）；这是「电脑原来的网络设置」，在记样子之前写好
    printf 'Acquire::https::Proxy::download.docker.com "%s";\n' $PROXY | sudo tee /etc/apt/apt.conf.d/95proxy >/dev/null
  fi
  step "记下装 $KIND 之前的样子（系统文件路径、装着的软件包、主目录里的东西）"
  sysfiles > $B/files.txt; pkgs > $B/pkgs.txt
  find ~ -mindepth 1 -maxdepth 3 -not -path "$HOME/sop-src*" -not -path "$HOME/io-base*" | sort > $B/home.txt
  homefiles > $B/homefiles.txt; cp ~/.bashrc $B/bashrc
  echo "  系统文件 $(wc -l < $B/files.txt) 个，软件包 $(wc -l < $B/pkgs.txt) 个，主目录里 $(wc -l < $B/homefiles.txt) 项"
  if [ $KIND = rootless ]; then
    step "照 Docker 官网的免管理员装法装一份（https://docs.docker.com/engine/security/rootless/）：程序在 ~/bin、服务名 docker"
    sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq uidmap >/dev/null || exit 1
    # Ubuntu 24.04 起不许普通程序建隔离空间，官网让给 ~/bin/rootlesskit 加这一条系统安全规则（官网原文）
    cat <<EOT | sudo tee "/etc/apparmor.d/home.$USER.bin.rootlesskit" >/dev/null
# ref: https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces
abi <abi/4.0>,
include <tunables/global>

"$HOME/bin/rootlesskit" flags=(unconfined) {
  userns,

  # Site-specific additions and overrides. See local/README for details.
  include if exists <local/home.$USER.bin.rootlesskit>
}
EOT
    sudo systemctl restart apparmor.service
    # curl -fsSL https://get.docker.com/rootless | sh（这台试验电脑只有经本机代理才连得上 Docker 官网）
    env https_proxy=$PROXY curl -fsSL https://get.docker.com/rootless -o /tmp/rootless.sh || { echo "取不到官方的安装脚本，不重试"; exit 1; }
    for try in 1 2; do
      env http_proxy=$PROXY https_proxy=$PROXY sh /tmp/rootless.sh > /tmp/rl-install.log 2>&1 && break
      if [ $try = 1 ] && grep -q 'Missing system requirements' /tmp/rl-install.log; then
        cmds=$(sed -n '/^cat <<EOF | sudo sh -x$/,/^EOF$/{//!p}' /tmp/rl-install.log | grep .)
        echo "  官方脚本说缺系统要求，照它给的命令做（要管理员）：$cmds"
        echo "$cmds" | sudo sh -x 2>&1 | sed 's/^/    /'
      else
        tail -15 /tmp/rl-install.log; echo "官方脚本没装好"; exit 1
      fi
    done
    sed 's/\x1b\[[0-9;]*m//g' /tmp/rl-install.log | grep -e '^\[INFO\]' | sed 's/^/  官方脚本：/'
    # 照它最后的提示往 ~/.bashrc 加（「Make sure the following environment variable(s) are set (or add them to ~/.bashrc)」下面那几行）
    sed 's/\x1b\[[0-9;]*m//g' /tmp/rl-install.log | sed -n '/add them to ~\/.bashrc/,/^$/p' | grep '^export ' > $B/bashrc-add
    must "[ -s $B/bashrc-add ]" "官方脚本最后提示往 ~/.bashrc 加：$(tr '\n' ' ' < $B/bashrc-add)"
    cat $B/bashrc-add >> ~/.bashrc
    # 拉镜像要经本机代理（官网写的用户级服务加代理的办法）；照网上教程限制日志大小（官网写的免管理员设置文件 ~/.config/docker/daemon.json）
    mkdir -p ~/.config/systemd/user/docker.service.d ~/.config/docker
    printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY > ~/.config/systemd/user/docker.service.d/proxy.conf
    printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "10m", "max-file": "3"}\n}\n' > ~/.config/docker/daemon.json
    systemctl --user daemon-reload; systemctl --user restart docker.service
    for i in $(seq 1 30); do $OLD version >/dev/null 2>&1 && break; sleep 1; done
    must "[ \"\$($OLD info --format '{{.DockerRootDir}}')\" = $OLD_ROOT ]" "装好了：数据在 ~/.local/share/docker，后台服务 docker（$(systemctl --user is-active docker.service)）"
    must "[ \"\$(env -u DOCKER_HOST -u DOCKER_CONTEXT $HOME/bin/docker context show)\" = rootless ]" "官方脚本把默认指向切到了它建的 rootless"
    cp ~/.config/systemd/user/docker.service $B/old-unit
  elif [ $KIND = docker.io ]; then
    step "用 Ubuntu 软件源装一份系统自带的 docker.io，小白加进 docker 组"
    sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >/dev/null || exit 1
  else
    step "照 Docker 官网的步骤装 docker-ce（官方软件源 docker.sources、钥匙文件 docker.asc），小白加进 docker 组"
    sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl >/dev/null || exit 1
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo env https_proxy=$PROXY curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc || { echo "取不到钥匙文件，不重试"; exit 1; }
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    code=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
    printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$code" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
    sudo apt-get update -qq 2>&1 | grep -v -e '^$' -e 'outdated' | tail -3
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null || { echo "装 docker-ce 失败"; exit 1; }
    echo "  随 docker-ce 进来的「自动装的」：$(apt-mark showauto | grep -x -e git -e pigz -e git-man -e liberror-perl | tr '\n' ' ')"
  fi
  if [ $KIND = rootless ]; then
    D=$OLD
  else
    sudo mkdir -p /etc/systemd/system/docker.service.d       # 虚拟机只能经本机代理拉镜像；小白照网上教程也常这样加
    printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
    sudo systemctl daemon-reload; sudo systemctl restart docker
    sudo usermod -aG docker xiaobai
    D="sudo $OLD"
  fi
  step "往旧的里放东西：两个镜像（一个拉的、一个自己做的带项目标签）、带标签的卷、普通卷、匿名卷；在跑的数据库样子的容器、停了的容器"
  $D pull -q busybox:1.36 >/dev/null || { echo "拉镜像 busybox 失败，不重试"; exit 1; }
  $D volume create --label com.docker.compose.project=shop --label com.docker.compose.volume=pgdata shop_pgdata >/dev/null
  $D volume create notes >/dev/null
  $D run -d --name shop-db-1 --restart unless-stopped --label com.docker.compose.project=shop --label com.docker.compose.service=db \
    -v shop_pgdata:/data busybox:1.36 sh -c '[ -e /data/ready ] || { dd if=/dev/urandom of=/data/blob bs=1M count=12 2>/dev/null; mkdir -p /data/sub; ln -s ../blob /data/sub/link; chown -R 70:70 /data; chmod 0700 /data/sub; touch /data/ready; }; exec sleep 1d' >/dev/null
  $D run --name old-tool -v notes:/notes -v /scratch busybox:1.36 sh -c 'echo 笔记 > /notes/a.txt; chmod 0640 /notes/a.txt; dd if=/dev/zero of=/big bs=1M count=3 2>/dev/null; echo x > /scratch/y' >/dev/null
  $D commit --change 'LABEL com.docker.compose.project=shop' old-tool shop-web:dev >/dev/null
  for i in $(seq 1 20); do $D exec shop-db-1 test -e /data/ready 2>/dev/null && break; sleep 1; done
  $D run --rm -v shop_pgdata:/data:ro -v notes:/notes:ro busybox:1.36 sh -c 'cd /data && sha256sum blob && stat -c "%n %u:%g %a" . blob sub sub/link && readlink sub/link && sha256sum sub/link && cat /notes/a.txt && stat -c "%n %a" /notes/a.txt' > $B/data.txt
  sed 's/^/  旧数据：/' $B/data.txt
  echo "  旧的里面：镜像 $($D image ls --format '{{.Repository}}:{{.Tag}}' | tr '\n' ' ')；卷 $($D volume ls -q | wc -l) 个；容器 $($D ps -a --format '{{.Names}}({{.State}})' | tr '\n' ' ')"
  if [ $KIND = rootless ]; then
    echo "  装好的：免管理员的 Docker $($OLD version --format '{{.Server.Version}}')（~/bin），后台服务 docker，通道 unix:///run/user/$U/docker.sock"
  else
    echo "  装好的：$(dpkg-query -W -f '${Package} ${Version}, ' $KIND $( [ $KIND = docker-ce ] && echo docker-ce-cli containerd.io))"
  fi
  exit $fail
fi

net() { (cd $SRC && env -u http_proxy -u https_proxy python3 -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')"); }
state_of() { $OLD inspect -f '{{.State.Status}}' "$1" 2>/dev/null || echo 没有; }
rules() {    # $1 = 文件；$2 = 1 表示还要回答「确定现在卸掉它吗」、在切回原来那份之后暂停；否则在打包时强制结束
  python3 - "$1" "$2" "$QRE" <<'EOF'
import json, sys, os, re
f, q6, qre = sys.argv[1], sys.argv[2] == '1', sys.argv[3]
ans = [{'q': qre, 'a': '2'}, {'q': r'匿名卷[^\n]*：', 'a': '2'}, {'q': '现在停一下吗', 'a': 'y'}]
ev = [{'on': '打包数据卷', 'do': 'kill'}]
if q6:
    ans.append({'q': '确定现在卸掉它吗', 'a': 'y'})
    ev = [{'on': '先切回原来那份', 'do': 'pause', 'run': f'bash {os.path.expanduser("~/sop-src/tests/vm/migrate-io-guest.sh")} --look /tmp/io-mid.txt'}]
json.dump({'answers': ans, 'events': ev, 'timeout': 2400}, open(f, 'w'), ensure_ascii=False)
EOF
}

if [ "${1:-}" = --run1 ]; then
  if [ $KIND = rootless ]; then
    step "这一次登录：原来那份免管理员的在跑（后台服务 docker：$(systemctl --user is-active docker.service)）"
  else
    step "这一次登录：小白在 docker 组里（$(id -nG | tr ' ' '\n' | grep -x docker || echo 不在)），不加 sudo 能连系统自带的那份"
  fi
  must "$OLD version >/dev/null 2>&1" "不加 sudo 连得上原来那份"
  must "[ ! -e $T ]" "规定位置的 Docker 还没装（让 Q2 去装）"
  net && echo "  写好网络设置（第零步会写的那一份）"
  rules /tmp/io-rules1.json 0
  step "第一遍 sop machine migrate（在模拟终端里，像小白一样回答；Q4 打包时强制结束）"
  cd ~ && $DRIVE /tmp/io-rules1.json /tmp/io-run1.log -- $SOP machine migrate >/dev/null; rc=$?
  grep -v -e '^\s*$' /tmp/io-run1.log | tail -25 | sed 's/^/  | /'
  must "[ $rc = 137 ]" "在 Q4 打包时被强制结束了（kill -9 整组）"
  must "grep -q 'docker：装好了' /tmp/io-run1.log && [ -x $T/bin/docker ] && NEW version >/dev/null 2>&1" "Q2 装好了规定位置的 Docker，能连上"
  if [ $KIND = rootless ]; then
    must "grep -q '占着 docker 这个服务名，规定位置的这份用 sop-docker' /tmp/io-run1.log" "Q2 看到 docker 这个服务名被原来那份占着，规定位置这份另起服务名 sop-docker"
    must "[ \"\$(cat $T/etc/docker-host)\" = unix:///run/user/$U/sop-docker/docker.sock ]" "规定位置这份的通道是 /run/user/$U/sop-docker/docker.sock（不和原来那份抢）"
    must "systemctl --user -q is-active sop-docker.service && [ \"\$(systemctl --user is-enabled sop-docker.service)\" = enabled ]" "sop-docker 在跑、登录后自己起来"
    must "cmp -s $B/old-unit ~/.config/systemd/user/docker.service && systemctl --user -q is-active docker.service" "原来那份的服务登记一个字没动、照样在跑（两份并存）"
    must "[ \"\$(NEW info --format '{{.DockerRootDir}}')\" = \"\$(realpath $T/data)\" ] && [ \"\$($OLD info --format '{{.DockerRootDir}}')\" = $OLD_ROOT ]" "两份同时连得上，各用各的数据目录"
    must "[ \"\$(env -u DOCKER_HOST -u DOCKER_CONTEXT $T/bin/docker context show)\" = rootless ] && [ \"\$(env -u DOCKER_HOST -u DOCKER_CONTEXT $T/bin/docker context inspect rootless --format '{{.Endpoints.docker.Host}}')\" = unix:///run/user/$U/docker.sock ]" \
      "默认指向还是原来那份的 rootless（指着 /run/user/$U/docker.sock），没被改"
  else
    must "grep -q '已切回原来的「default」' /tmp/io-run1.log" "Q2 装完把默认指向切回了原来那份"
  fi
  must "grep -q '旧 Docker 里临时放一个打包用的小镜像' /tmp/io-run1.log" "旧的里没有打包用的小镜像，从新的那份导过去了（记进了记录）"
  sleep 5      # 打包用的临时容器在客户端被杀后自己退出、自己删掉
  st=$(state_of shop-db-1)
  must "[ \"$st\" = exited ]" "旧容器 shop-db-1 被停着（$st）"
  must "[ -f ~/tools/sop/config/migrate/stopped.json ] && grep -q shop-db-1 ~/tools/sop/config/migrate/stopped.json" "停容器之前写下了记录 stopped.json"
  echo "  记录：$(tr -d '\n ' < ~/tools/sop/config/migrate/stopped.json 2>/dev/null)"
  echo "  旧的里现在的容器：$($OLD ps -a --format '{{.Names}}({{.State}})' | tr '\n' ' ')"
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-after-q2.txt; sed 's/^/  新开终端：/' /tmp/io-after-q2.txt
  must "grep -q '数据在 $OLD_ROOT' /tmp/io-after-q2.txt && grep -q '默认指向 $OLD_CTX' /tmp/io-after-q2.txt" "Q2 之后新开终端不加 sudo 敲 docker，看到的是原来那份"
  step "强制结束之后执行一次别的 sop 命令（sop machine tools）"
  $SOP machine tools > /tmp/io-recover.log 2>&1; rrc=$?
  grep -e '起回来' -e '小镜像' -e '提醒' /tmp/io-recover.log | sed 's/^/  | /'
  must "[ $rrc = 0 ] && grep -q '已经起回来了' /tmp/io-recover.log" "sop 一启动先把旧容器起回来了，接着照常做它的事"
  st=$(state_of shop-db-1)
  must "[ \"$st\" = running ]" "旧容器 shop-db-1 在跑（$st）"
  must "[ ! -e ~/tools/sop/config/migrate/stopped.json ]" "记录删了"
  must "! $OLD image inspect alpine:3.20 >/dev/null 2>&1" "临时放进旧的那个小镜像 alpine:3.20 删了"
  must "[ \"\$($OLD ps -a --format '{{.Names}}' | sort | tr '\n' ' ')\" = 'old-tool shop-db-1 ' ]" "旧的里只有原来那两个容器（打包用的临时容器没留下）"
  $SOP machine tools > /tmp/io-recover2.log 2>&1
  must "! grep -q '起回来' /tmp/io-recover2.log" "再执行一次 sop 不再提"
  exit $fail
fi

if [ "${1:-}" = --run2 ]; then
  step "先把默认指向切到新的（模拟小白自己切过），看 Q6 卸之前切回原来那份"
  if [ $KIND = rootless ]; then    # 规定位置这份用的是 sop-docker，没有指着它的默认指向：小白自己建一个再切
    newctx=sop-new
    env -u DOCKER_HOST $T/bin/docker context create $newctx --docker host=$(cat $T/etc/docker-host) >/dev/null
  else
    newctx=rootless
  fi
  env -u DOCKER_HOST $T/bin/docker context use $newctx >/dev/null
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-before.txt; sed 's/^/  新开终端：/' /tmp/io-before.txt
  must "grep -q '默认指向 $newctx' /tmp/io-before.txt && grep -q \"数据在 $T/data\" /tmp/io-before.txt" "切过去了：敲 docker 现在是规定位置那份"
  rules /tmp/io-rules2.json 1
  step "第二遍 sop machine migrate（走完 Q1 到 Q6；Q6 切回原来那份之后暂停一下看）"
  cd ~ && $DRIVE /tmp/io-rules2.json /tmp/io-run2.log -- $SOP machine migrate >/dev/null; rc=$?
  sed -n '/^Q3 /,$p' /tmp/io-run2.log | grep -v -e '^\s*$' | sed 's/^/  | /'
  must "[ $rc = 0 ]" "sop machine migrate 正常结束（退出码 0）"
  must "! grep -q '驱动：这些问题没出现' /tmp/io-run2.log" "该问的都问了（选卸、匿名卷不要了、停容器、确认卸载）"
  sed 's/^/  暂停时新开终端：/' /tmp/io-mid.txt
  must "grep -q '数据在 $OLD_ROOT' /tmp/io-mid.txt && grep -q '默认指向 $OLD_CTX' /tmp/io-mid.txt && grep -q '容器 shop-db-1' /tmp/io-mid.txt" \
    "Q6 切回之后、卸之前：不加 sudo 敲 docker 看到的是原来那份和它的容器"
  must "grep -q '都没有了' /tmp/io-run2.log && ! grep -q '没卸干净' /tmp/io-run2.log" "残留清单逐项又看了一遍都没有了（sop 自己说的）"
  must "grep -q '规定位置的 Docker 仍然正常' /tmp/io-run2.log" "规定位置那份仍然正常（sop 自己说的）"

  step "自己逐项再核对残留清单（按 Q1 存的 inventory.json）"
  KIND=$KIND python3 - > /tmp/io-residue.txt <<'EOF'
import json, os
inv = json.load(open(os.path.expanduser('~/tools/sop/config/migrate/inventory.json')))
d = next(d for d in inv['docker'] if d['kind'] == os.environ['KIND'])
for r in d['residue']:
    print(r['kind'], r['what'], r.get('file', ''))
EOF
  n=0; left=0
  while read -r kind what file; do
    n=$((n + 1))
    case $kind in
      package) s=$(dpkg-query -W -f '${db:Status-Abbrev}' "$what" 2>/dev/null); case $s in ''|un*) ;; *) echo "  还在：软件包 $what（$s）"; left=1 ;; esac ;;
      service) s=$(systemctl show -p LoadState --value "$what"); [ "$s" = not-found ] || { echo "  还在：服务 $what（$s）"; left=1; } ;;
      group) ! getent group "$what" >/dev/null || { echo "  还在：用户组 $what"; left=1; } ;;
      path) p=${what/#\~/$HOME}
            if [ $KIND = rootless ] && [ -e "$p" ] && case $what in */systemd/user/docker.service|*/default.target.wants/docker.service) true ;; *) false ;; esac \
               && grep -qx "ExecStart=$T/bin/dockerd-rootless.sh --config-file $T/etc/daemon.json" "$p" 2>/dev/null; then
              echo "  $what 在，是规定位置那份接过服务名以后的（启动的是 ~/tools/docker 的程序）"
            elif sudo test -e "$p" || [ -L "$p" ]; then echo "  还在：$what"; left=1; fi ;;
      apt-line) ! grep -qs '^[^#]*download\.docker\.com' "$file" || { echo "  还在：$file 里的软件源"; left=1; } ;;
      *) echo "  不认识：$kind $what"; left=1 ;;
    esac
  done < /tmp/io-residue.txt
  echo "  残留清单 $n 项：$(awk '{printf "%s%s %s", (NR > 1 ? "，" : ""), $1, $2}' /tmp/io-residue.txt)"
  must "[ $n -gt 5 ] && [ $left = 0 ]" "残留清单 $n 项逐项为空"

  step "和装 $KIND 之前的系统比（独立于残留清单）"
  pkgs > /tmp/io-pkgs-after.txt
  added_pk=$(comm -13 $B/pkgs.txt /tmp/io-pkgs-after.txt | tr '\n' ' '); gone_pk=$(comm -23 $B/pkgs.txt /tmp/io-pkgs-after.txt | tr '\n' ' ')
  echo "  比装之前多的软件包：${added_pk:-无}；少的：${gone_pk:-无}"
  must "[ -z \"$gone_pk\" ]" "原来就有的软件包一个没少"
  must "! echo \"$added_pk\" | grep -qiw -e 'docker[^ ]*' -e containerd -e runc -e 'docker.io'" "多出来的软件包里没有 Docker 的（只有规定位置那份要的）"
  sysfiles > /tmp/io-files-after.txt
  owned=$(for p in $added_pk; do dpkg -L "$p" 2>/dev/null; done | sort -u)
  comm -13 $B/files.txt /tmp/io-files-after.txt | comm -23 - <(echo "$owned") > /tmp/io-added.txt
  comm -23 $B/files.txt /tmp/io-files-after.txt > /tmp/io-removed.txt
  echo "  比装之前多出来、又不属于新装的软件包的文件 $(wc -l < /tmp/io-added.txt) 个："; head -40 /tmp/io-added.txt | sed 's/^/    /'
  echo "  比装之前少了的文件 $(wc -l < /tmp/io-removed.txt) 个："; head -20 /tmp/io-removed.txt | sed 's/^/    /'
  must "! grep -i -e docker -e containerd -e runc /tmp/io-added.txt | grep -v -x '/etc/apparmor.d/home.xiaobai.tools.docker.bin.rootlesskit' | grep -q ." \
    "多出来的文件里没有旧 Docker 的（规定位置那份的系统安全规则除外）"
  for p in /var/run/docker.sock /run/docker /run/containerd /run/docker.pid; do sudo test -e $p && echo "  /run 下还在（内存里，重启就没）：$p"; done
  must "! sudo test -e /var/run/docker.sock" "系统那条通道 /var/run/docker.sock 没了"
  find ~ -mindepth 1 -maxdepth 3 -not -path "$HOME/sop-src*" -not -path "$HOME/io-base*" | sort > /tmp/io-home-after.txt
  echo "  主目录里比装之前多的（前 3 层，不算 ~/tools 里的）："; comm -13 $B/home.txt /tmp/io-home-after.txt | grep -v "^$HOME/tools" | sed "s#$HOME#~#; s/^/    /"

  step "工具包自己要用的系统软件包都还在，也没被当成「用不着的」（3-34）"
  for p in $KEEP; do
    s=$(dpkg-query -W -f '${db:Status-Abbrev}' $p 2>/dev/null)
    must "[ \"${s:0:2}\" = ii ]" "$p 装着（${s:-没装}）"
  done
  must "command -v git >/dev/null && git --version >/dev/null" "git 能用"
  orphan=$(apt-get -s autoremove 2>/dev/null | awk '/^(Remv|Purg) /{print $2}' | tr '\n' ' ')
  echo "  系统现在当成「用不着、可以清掉」的软件包：${orphan:-无}；手动装的里有：$(apt-mark showmanual | grep -x -e git -e curl | tr '\n' ' ')"
  must "! echo \" $orphan \" | grep -qw -e git -e git-man -e curl -e wget -e iptables -e uidmap -e dbus-user-session" \
    "里面没有工具包要用的（以后系统清理用不着的软件包时也不会删掉它们）"

  if [ $KIND = rootless ]; then
    L=/tmp/io-run2.log
    ln_of() { grep -n -m1 -F "$1" $L | cut -d: -f1; }
    step "免管理员那种另看：先停、先删数据再删程序、系统安全规则、接过 docker 这个服务名和通道"
    a=$(ln_of '停掉旧的这份 Docker'); b=$(ln_of '删掉数据目录 ~/.local/share/docker'); c=$(ln_of '删掉旧的程序和服务登记')
    e=$(ln_of '删掉系统安全规则'); f=$(ln_of '接过来了：服务名 docker')
    echo "  sop 说这几句的先后（第几行）：停 $a，删数据 $b，删程序 $c，删系统安全规则 $e，接过服务名 $f"
    must "[ -n \"$a\" ] && [ -n \"$b\" ] && [ -n \"$c\" ] && [ -n \"$e\" ] && [ -n \"$f\" ] && [ $a -lt $b ] && [ $b -lt $c ] && [ $c -lt $e ] && [ $e -lt $f ]" \
      "先停旧的 → 先删数据 → 再删程序和服务登记 → 删系统安全规则 → 接过服务名"
    must "grep -q '借 ~/bin/rootlesskit 删' $L" "数据目录里有属于容器内部账号的文件，自己删不掉，借旧的 ~/bin/rootlesskit 删的（所以数据要比程序先删）"
    must "[ ! -e ~/.local/share/docker ]" "旧的数据目录 ~/.local/share/docker 没了"
    leftbins=$(for b in $ROOTLESS_BINS; do [ -e ~/bin/$b ] && echo $b; done | tr '\n' ' ')
    must "[ -z \"$leftbins\" ]" "~/bin 里官方装的 11 个程序都没了${leftbins:+（还有 $leftbins）}"
    must "[ ! -e ~/.config/docker ]" "旧的那份的设置目录 ~/.config/docker（daemon.json）没了"
    must "[ ! -e /etc/apparmor.d/home.$USER.bin.rootlesskit ] && ! sudo grep -qF \"$HOME/bin/rootlesskit\" /sys/kernel/security/apparmor/profiles" \
      "官方装法要的那条系统安全规则（~/bin/rootlesskit）文件删了、也从系统里拿掉了"
    must "sudo grep -qF \"$T/bin/rootlesskit\" /sys/kernel/security/apparmor/profiles" "规定位置那份自己的系统安全规则还在"
    must "[ \"\$(cat $T/etc/docker-host)\" = unix:///run/user/$U/docker.sock ]" "规定位置那份的通道换成了默认的 /run/user/$U/docker.sock（~/tools/docker/etc/docker-host）"
    must "[ ! -e ~/.config/systemd/user/sop-docker.service ] && [ \"\$(systemctl --user show -p LoadState --value sop-docker.service)\" = not-found ]" "sop-docker 这个服务名不用了（登记文件删了）"
    must "grep -qx \"ExecStart=$T/bin/dockerd-rootless.sh --config-file $T/etc/daemon.json\" ~/.config/systemd/user/docker.service && ! grep -q sop-docker ~/.config/systemd/user/docker.service" \
      "后台服务 docker 现在是规定位置那份的"
    must "systemctl --user -q is-active docker.service && [ \"\$(systemctl --user is-enabled docker.service)\" = enabled ] && [ \"\$(readlink -f ~/.config/systemd/user/default.target.wants/docker.service)\" = \"$HOME/.config/systemd/user/docker.service\" ]" \
      "后台服务 docker 在跑、登录后自己起来"
    out=$(env -u DOCKER_CONTEXT DOCKER_HOST=unix:///run/user/$U/docker.sock $T/bin/docker info --format '{{.DockerRootDir}}' 2>&1)
    must "[ \"$out\" = \"\$(realpath $T/data)\" ]" "照官方提示设了 DOCKER_HOST=unix:///run/user/$U/docker.sock 的程序，连到的也是规定位置那份（$out）"
    must "grep -q '提醒：~/.bashrc 里有照官方装法提示加的几行' $L" "提醒了 ~/.bashrc 里照官方提示加的那几行（工具包不动它们）"
    must "grep -qxF -f $B/bashrc-add ~/.bashrc" "~/.bashrc 里小白自己加的那几行没被动"
    homefiles > /tmp/io-homefiles-after.txt
    comm -13 $B/homefiles.txt /tmp/io-homefiles-after.txt > /tmp/io-home-added.txt
    comm -23 $B/homefiles.txt /tmp/io-homefiles-after.txt > /tmp/io-home-removed.txt
    echo "  主目录里比装之前多的 $(wc -l < /tmp/io-home-added.txt) 项（不算 ~/tools、~/.cache）："; sed 's/^/    /' /tmp/io-home-added.txt
    echo "  主目录里比装之前少的 $(wc -l < /tmp/io-home-removed.txt) 项："; sed 's/^/    /' /tmp/io-home-removed.txt
    must "! grep -i -e docker -e containerd -e rootlesskit /tmp/io-home-added.txt | grep -v -x -e '~/.docker' -e '~/.docker/.*' \
          -e '~/.config/systemd/user/docker.service' -e '~/.config/systemd/user/default.target.wants/docker.service' | grep -q ." \
      "多出来的里没有旧 Docker 的（~/.docker 的默认指向、规定位置那份接过来的 docker.service 除外）"
    must "[ ! -s /tmp/io-home-removed.txt ]" "主目录里原来就有的一样没少"

    step "再装一遍规定位置的 Docker（以后升级工具包会这样）：接过来的服务登记和安装脚本自己按 docker 这个名字写的一字不差"
    cp ~/.config/systemd/user/docker.service /tmp/io-unit-before; mt=$(stat -c %Y ~/.config/systemd/user/docker.service)
    ver=$(NEW version --format '{{.Server.Version}}')
    plan=$(SOP_TOOLS=$HOME/tools bash $SRC/machine/install/docker-rootless.sh --plan 2>&1)
    must "echo \"$plan\" | grep -qx unit=docker && echo \"$plan\" | grep -qx host=unix:///run/user/$U/docker.sock" "安装脚本认它是自己的（unit=docker，通道 /run/user/$U/docker.sock）"
    SOP_TOOLS=$HOME/tools SOP_DOCKER_VERSION=$ver http_proxy=$PROXY https_proxy=$PROXY bash $SRC/machine/install/docker-rootless.sh > /tmp/io-reinstall.log 2>&1; irc=$?
    tail -3 /tmp/io-reinstall.log | sed 's/^/  | /'
    must "[ $irc = 0 ] && grep -q '后台服务 docker（登录后自己起来）' /tmp/io-reinstall.log" "重装成功，后台服务还是 docker"
    must "cmp -s /tmp/io-unit-before ~/.config/systemd/user/docker.service && [ \"\$(stat -c %Y ~/.config/systemd/user/docker.service)\" = $mt ]" "服务登记文件一个字没变（修改时间也没变：安装脚本看着一样就不写）"
    must "[ \"\$(cat $T/etc/docker-host)\" = unix:///run/user/$U/docker.sock ] && [ \"\$(NEW volume ls -q | sort | tr '\n' ' ')\" = 'notes shop_pgdata ' ]" "重装以后通道没变、带走的卷都在"
  fi

  if [ $KIND = docker-ce ]; then
    step "docker-ce 另看：软件源、钥匙文件、apt 下载过的官方源索引、containerd"
    must "! grep -rqs download.docker.com /etc/apt/sources.list /etc/apt/sources.list.d" "软件源里没有指向 download.docker.com 的了"
    must "[ ! -e /etc/apt/keyrings/docker.asc ]" "钥匙文件 /etc/apt/keyrings/docker.asc 删了"
    must "! apt-cache policy docker-ce containerd.io 2>/dev/null | grep -q download.docker.com" "apt 里看不到官方源的 docker-ce、containerd.io 了"
    for p in /var/lib/containerd /etc/containerd /opt/containerd /run/containerd /etc/cni /var/lib/docker /etc/docker; do
      must "! sudo test -e $p" "$p 没了"
    done
    must "! getent group docker >/dev/null" "用户组 docker 删了"
    lists=$(ls /var/lib/apt/lists | grep -c download.docker.com)
    echo "  apt 下载过的官方源索引（/var/lib/apt/lists/download.docker.com_*）现在还有 $lists 个；执行一次 sudo apt-get update 看看："
    sudo apt-get update > /tmp/io-update.log 2>&1; urc=$?
    grep -i -e docker -e '^E:' -e '^W:' /tmp/io-update.log | sed 's/^/    /'
    must "[ $urc = 0 ] && ! grep -qi -e download.docker.com -e '^E:' /tmp/io-update.log && ! ls /var/lib/apt/lists | grep -q download.docker.com" \
      "apt-get update 正常、不再去连 download.docker.com，那几个索引随之清掉（系统每天自己更新软件列表时也一样）"
  fi

  step "新开终端，不加 sudo 敲 docker"
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-end.txt; sed 's/^/  新开终端：/' /tmp/io-end.txt
  must "grep -q \"docker → $T/bin/docker\" /tmp/io-end.txt && grep -q '默认指向 rootless' /tmp/io-end.txt && grep -q \"数据在 $T/data\" /tmp/io-end.txt" \
    "卸完：敲 docker 是规定位置那份（程序、默认指向、数据位置）"

  step "带走的数据在规定位置那份里，和原来一致"
  # 先只看有没有（docker run -v 卷名 遇到没有的卷会自己建一个空的，不能先跑）
  vols=$(NEW volume ls -q | sort | tr '\n' ' ')
  must "[ \"$vols\" = 'notes shop_pgdata ' ]" "新的里只有带走的两个卷（选了不要的匿名卷没带、试还原用的临时卷删了）：$vols"
  if [ "$vols" = 'notes shop_pgdata ' ]; then
    NEW run --rm -v shop_pgdata:/data:ro -v notes:/notes:ro busybox:1.36 sh -c 'cd /data && sha256sum blob && stat -c "%n %u:%g %a" . blob sub sub/link && readlink sub/link && sha256sum sub/link && cat /notes/a.txt && stat -c "%n %a" /notes/a.txt' > /tmp/io-data-new.txt 2>&1
    must "cmp -s $B/data.txt /tmp/io-data-new.txt" "数据卷 shop_pgdata、notes 里的内容、归属（70:70，含符号链接）、权限、链接和原来一样"
    diff $B/data.txt /tmp/io-data-new.txt | sed 's/^/    /'
    must "[ \"\$(NEW volume inspect shop_pgdata --format '{{index .Labels \"com.docker.compose.project\"}}')\" = shop ]" "数据卷带着原来的项目标签"
    out=$(NEW run --rm -v shop_pgdata:/data shop-web:dev sh -c 'ls /data/blob' 2>&1); echo "  用带走的镜像和卷起一个容器：$out"
    must "[ \"$out\" = /data/blob ]" "带走的镜像和数据卷能直接用"
  fi
  must "NEW image inspect busybox:1.36 >/dev/null && [ \"\$(NEW image inspect shop-web:dev --format '{{index .Config.Labels \"com.docker.compose.project\"}}')\" = shop ]" "镜像 busybox:1.36、自己做的 shop-web:dev（带标签）都在"
  ls ~/tools/backup/ 2>/dev/null | sed 's/^/  备份留着：/'

  step "再清点一次：电脑上没有不在规定位置的 Docker 了"
  (cd $SRC && python3 -m machine.migrate.inventory --admin) > /tmp/io-inv-after.txt 2>&1
  head -8 /tmp/io-inv-after.txt | sed 's/^/  | /'
  must "! grep -qF '$LABEL' /tmp/io-inv-after.txt" "清点里没有 $LABEL 了"
  step "再执行一次 sop machine migrate"
  cd ~ && $SOP machine migrate < /dev/null > /tmp/io-run3.log 2>&1; rc3=$?
  tail -3 /tmp/io-run3.log | sed 's/^/  | /'
  must "[ $rc3 = 0 ] && grep -q '不用迁移' /tmp/io-run3.log" "说不用迁移"
  exit $fail
fi

if [ "${1:-}" = --after-reboot ]; then
  step "重启之后（登录进来，没手动起任何东西）"
  for i in $(seq 1 30); do NEW info >/dev/null 2>&1 && break; sleep 1; done
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-reboot.txt; sed 's/^/  新开终端：/' /tmp/io-reboot.txt
  must "grep -q '默认指向 rootless' /tmp/io-reboot.txt && grep -q \"数据在 $T/data\" /tmp/io-reboot.txt" "重启后敲 docker 还是规定位置那份，自己起来了"
  must "! systemctl list-unit-files docker.service containerd.service 2>/dev/null | grep -q -e docker.service -e containerd.service" "系统里没有 docker、containerd 的服务登记"
  must "! ls -d /run/docker /run/containerd /var/run/docker.sock 2>/dev/null | grep -q ." "/run 下没有旧 Docker 的东西"
  if [ $KIND = rootless ]; then
    must "systemctl --user -q is-active docker.service && grep -q \"ExecStart=$T/bin/\" ~/.config/systemd/user/docker.service && [ \"\$(cat $T/etc/docker-host)\" = unix:///run/user/$U/docker.sock ]" \
      "登录后自己起来的后台服务 docker 是规定位置那份（通道 /run/user/$U/docker.sock）"
    must "[ \"\$(systemctl --user show -p LoadState --value sop-docker.service)\" = not-found ]" "没有 sop-docker 了"
  fi
  out=$(NEW run --rm -v shop_pgdata:/data:ro busybox:1.36 sh -c 'cd /data && sha256sum blob' 2>&1)
  must "[ \"$out\" = \"$(head -1 $B/data.txt)\" ]" "重启后带走的数据还在"
  exit $fail
fi
echo "用法：--prepare [io|ce|rl] | --run1 | --run2 | --after-reboot | --look <文件>"; exit 2
