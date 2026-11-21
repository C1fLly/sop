#!/bin/bash
# 3-30：在虚拟机里跑（由 migrate-q1.sh 拷进去、启动）。见 migrate-q1.sh 的说明。
#   --prepare system|ce|rootless：造「电脑上原来就有一份」，放几个镜像、数据卷、容器（单独一次登录做，下一次登录 docker 组才生效）
#   --capture：把清点要用到的那些命令的原样输出存到 ~/q1-out/（单元测试的样例从这里来）
#   --inventory：用正式代码清点一遍（python3 -m machine.migrate.inventory），前后核对旧的那几处一样都没变
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
U=$(id -u)
OLDD="env DOCKER_HOST=unix:///run/user/$U/docker.sock $HOME/bin/docker"
step() { echo; echo "=== $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }

# 往旧的 Docker 里放东西：两个镜像（拉一次，失败不重试）、一个自己提交出来的镜像（带编排文件的项目标签）、
# 一个编排文件建的卷（带标签）、一个普通的卷、一个匿名卷；一个在跑的容器、一个停了的容器（容器里有没放进卷的改动）
fill() {   # $1 = docker 命令
  local D=$1
  $D pull -q busybox:1.36 >/dev/null || { echo "拉镜像 busybox 失败，不重试"; exit 1; }
  $D pull -q alpine:3.20 >/dev/null || { echo "拉镜像 alpine 失败，不重试"; exit 1; }
  $D volume create --label com.docker.compose.project=shop --label com.docker.compose.volume=pgdata shop_pgdata >/dev/null
  $D volume create notes >/dev/null
  $D run -d --name shop-db-1 --restart unless-stopped --label com.docker.compose.project=shop --label com.docker.compose.service=db \
    -v shop_pgdata:/data busybox:1.36 sh -c 'dd if=/dev/urandom of=/data/blob bs=1M count=12 2>/dev/null; chown -R 70:70 /data; sleep 1d' >/dev/null
  $D run --name old-tool -v notes:/notes -v /scratch alpine:3.20 sh -c 'echo 笔记 > /notes/a.txt; dd if=/dev/zero of=/big bs=1M count=3 2>/dev/null; echo x > /scratch/y' >/dev/null
  $D commit --change 'LABEL com.docker.compose.project=shop' old-tool shop-web:dev >/dev/null
  sleep 2
  echo "旧的里面：镜像 $($D image ls -q | sort -u | wc -l) 个，卷 $($D volume ls -q | wc -l) 个，容器 $($D ps -a --format '{{.Names}}({{.State}})' | tr '\n' ' ')"
}

if [ "${1:-}" = --prepare ]; then
  echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"
  case ${2:-} in
    system)
      step "用 Ubuntu 软件源装一份系统自带的 docker.io，小白加进 docker 组"
      sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >/dev/null || exit 1
      sudo mkdir -p /etc/systemd/system/docker.service.d
      printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
      sudo systemctl daemon-reload; sudo systemctl restart docker
      sudo usermod -aG docker xiaobai
      fill "sudo docker"
      echo "装好的：$(dpkg-query -W -f '${Package} ${Version}' docker.io)" ;;
    ce)
      step "照 Docker 官网的步骤装 docker-ce（官方软件源、钥匙文件），小白加进 docker 组"
      export http_proxy=$PROXY https_proxy=$PROXY
      sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl >/dev/null
      sudo install -m 0755 -d /etc/apt/keyrings
      sudo -E curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc || { echo "取不到钥匙文件"; exit 1; }
      sudo chmod a+r /etc/apt/keyrings/docker.asc
      code=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
      printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$code" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
      printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' $PROXY $PROXY | sudo tee /etc/apt/apt.conf.d/99q1proxy >/dev/null
      sudo apt-get update -qq 2>&1 | tail -3
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null || { echo "装 docker-ce 失败（官方源可能还没有 $code）"; exit 1; }
      sudo mkdir -p /etc/systemd/system/docker.service.d
      printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
      sudo systemctl daemon-reload; sudo systemctl restart docker
      sudo usermod -aG docker xiaobai
      unset http_proxy https_proxy
      fill "sudo docker"
      echo "装好的：$(dpkg-query -W -f '${Package} ${Version}, ' docker-ce docker-ce-cli containerd.io)" ;;
    rootless)
      step "照官方一条命令的装法装一份免管理员的（程序在 ~/bin，服务名 docker，数据在 ~/.local/share/docker）"
      export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY
      sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq uidmap >/dev/null
      printf 'abi <abi/4.0>,\ninclude <tunables/global>\n\n"%s/bin/rootlesskit" flags=(unconfined) {\n  userns,\n}\n' "$HOME" | sudo tee /etc/apparmor.d/home.xiaobai.bin.rootlesskit >/dev/null
      sudo apparmor_parser -r /etc/apparmor.d/home.xiaobai.bin.rootlesskit
      curl -fsSL https://get.docker.com/rootless -o /tmp/rootless.sh || { echo "取不到官方的安装脚本"; exit 1; }
      SKIP_IPTABLES=1 FORCE_ROOTLESS_INSTALL=1 sh /tmp/rootless.sh >/tmp/rootless-install.log 2>&1 || { tail /tmp/rootless-install.log; exit 1; }
      mkdir -p ~/.config/systemd/user/docker.service.d
      printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY > ~/.config/systemd/user/docker.service.d/proxy.conf
      systemctl --user daemon-reload; systemctl --user restart docker; sleep 3
      unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
      fill "$OLDD"
      echo "装好的：$($OLDD version --format '{{.Server.Version}}')，数据在 $($OLDD info --format '{{.DockerRootDir}}')" ;;
    *) echo "用法：--prepare system|ce|rootless"; exit 2 ;;
  esac
  exit 0
fi

# 存一条命令的原样输出：名字.out、名字.err、名字.rc
O=~/q1-out
cap() { local n=$1; shift; "$@" >"$O/$n.out" 2>"$O/$n.err"; echo $? >"$O/$n.rc"; }

if [ "${1:-}" = --capture ]; then
  rm -rf $O; mkdir -p $O
  PK="docker.io docker-ce docker-ce-cli containerd.io containerd runc docker-ce-rootless-extras docker-buildx-plugin docker-compose-plugin docker-model-plugin docker-desktop docker-compose-v2 docker-buildx docker-compose docker-doc"
  cap dpkg dpkg-query -W -f '${Package}\t${Version}\t${db:Status-Abbrev}\n' $PK
  cap showauto apt-mark showauto
  installed=$(dpkg-query -W -f '${Package} ${db:Status-Abbrev}\n' docker.io docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras 2>/dev/null | awk '$2=="ii"{print $1}' | tr '\n' ' ')
  echo "装着的 Docker 软件包：${installed:-无}"
  cap autoremove-base apt-get -s autoremove
  [ -n "$installed" ] && cap purge-sim apt-get -s purge --autoremove $installed
  cap systemctl-show systemctl show -p Id,LoadState,ActiveState,UnitFileState,FragmentPath,DropInPaths docker.service docker.socket containerd.service
  cap systemctl-user-show systemctl --user show -p Id,LoadState,ActiveState,UnitFileState,FragmentPath,DropInPaths,ExecStart docker.service
  cap group getent group docker
  cap sources-ls ls -la /etc/apt/sources.list.d
  cap sources-grep grep -rl download.docker.com /etc/apt/sources.list.d
  cap keyrings ls -la /etc/apt/keyrings /usr/share/keyrings
  cap apparmor ls -la /etc/apparmor.d
  cap ls-dirs ls -ld /var/lib/docker /var/lib/containerd /etc/docker /etc/containerd /etc/default/docker ~/.local/share/docker ~/bin ~/.docker
  cap du sudo du -s -x -B1 /var/lib/docker /var/lib/containerd /etc/docker
  cap du-user du -s -x -B1 /var/lib/docker /var/lib/containerd
  cap du-home du -s -x -B1 ~/.local/share/docker ~/bin
  cap user-units ls -la ~/.config/systemd/user ~/.config/systemd/user/default.target.wants
  [ -f ~/.config/systemd/user/docker.service ] && cp ~/.config/systemd/user/docker.service $O/docker.service.user
  cap bin-ls ls -la ~/bin
  cap contexts sh -c 'cat ~/.docker/contexts/meta/*/meta.json'
  if [ -S /var/run/docker.sock ]; then D="docker --host unix:///var/run/docker.sock"; [ -w /var/run/docker.sock ] || D="sudo $D"
  else D="$HOME/bin/docker --host unix:///run/user/$U/docker.sock"; fi
  echo "旧的 Docker 用：$D"
  cap nosudo docker --host unix:///var/run/docker.sock version --format '{{json .}}'
  cap version $D version --format '{{json .}}'
  cap info $D info --format '{{json .}}'
  cap df $D system df -v --format '{{json .}}'
  cap images $D image ls -q --no-trunc
  cap images-all $D image ls -a --no-trunc --format '{{json .}}'
  cap image-inspect $D image inspect $(sort -u $O/images.out)
  cap containers $D container ls -a -q --no-trunc
  cap container-inspect $D container inspect --size $(cat $O/containers.out)
  cap volumes $D volume ls -q
  cap volume-inspect $D volume inspect $(cat $O/volumes.out)
  echo "存好了：$(ls $O | wc -l) 个文件"
  exit 0
fi

if [ "${1:-}" = --inventory ]; then
  shift
  OLDS="/var/lib/docker /var/lib/containerd /etc/docker /etc/apt /usr/bin/docker $HOME/bin $HOME/.local/share/docker $HOME/.config/systemd/user $HOME/.docker"
  snap() { sudo find $OLDS -maxdepth 2 -printf '%p %y %s %T@ %m\n' 2>/dev/null | grep -v -e '/var/lib/docker/\(containers\|overlay2\|image\|network\|buildkit\|tmp\)' -e '/var/lib/containerd/' | sort; }
  state() { { systemctl is-active docker.service containerd.service 2>/dev/null; systemctl --user is-active docker.service 2>/dev/null; docker ps -a --format '{{.Names}} {{.State}}' 2>/dev/null || $OLDD ps -a --format '{{.Names}} {{.State}}' 2>/dev/null; } | tr '\n' ' '; }
  snap > /tmp/q1-before.txt; s1=$(state)
  step "用正式代码清点（python3 -m machine.migrate.inventory $*）"
  (cd $SRC && python3 -m machine.migrate.inventory "$@") > /tmp/q1-report.txt 2>&1; rc=$?
  cat /tmp/q1-report.txt
  echo "（退出码 $rc）"
  snap > /tmp/q1-after.txt; s2=$(state)
  must "[ $rc = 0 ]" "清点正常结束"
  must "cmp -s /tmp/q1-before.txt /tmp/q1-after.txt" "旧的那几处（$(wc -l < /tmp/q1-before.txt) 项）大小、修改时间、权限一样都没变"
  must "[ \"$s1\" = \"$s2\" ]" "服务和容器的状态没变（$s1）"
  exit $fail
fi
if [ "${1:-}" = --stopped ]; then
  step "系统自带的 Docker 停着（只停 docker.service，通道 docker.socket 还在听）：清点不去连它，它还是停着"
  sudo systemctl stop docker.service 2>/dev/null; sleep 1
  must "! systemctl -q is-active docker.service" "先停好了"
  (cd $SRC && python3 -m machine.migrate.inventory --admin) > /tmp/q1-stopped.txt 2>&1; rc=$?
  grep -e '没列出来' /tmp/q1-stopped.txt | sed 's/^/  /'
  must "[ $rc = 0 ] && grep -q '没在运行' /tmp/q1-stopped.txt" "清单写明它没在运行、要它运行才列得出"
  must "! systemctl -q is-active docker.service" "清点之后 docker.service 还是停着"
  docker version >/dev/null 2>&1
  must "systemctl -q is-active docker.service" "对照：随手敲一条 docker 命令，它就被系统自动起来了（所以清点不能去连）"
  exit $fail
fi
echo "用法：--prepare system|ce|rootless | --capture | --inventory [参数] | --stopped"; exit 2
