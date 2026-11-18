#!/bin/bash
# 第一段 W27：环境迁移（设计书 4.8）的试验原型，在虚拟机里一步一步执行。不是正式的工具包代码。
# 用法：迁移.sh <a|b> <q1|q2|q4|q5|q6|坏一次|看旧的>
#   a：原来是用系统自带方式装的、需要管理员的 Docker
#   b：原来是免管理员的装法，只是位置不对（程序在 ~/bin，数据在 ~/.local/share/docker）
# Q3（小白选择）由试验代替：所有镜像和数据卷都选「带走」。虚拟机里的 sudo 代表「小白输管理员密码」。
set -eo pipefail; . /etc/profile.d/sop-proxy.sh
S=$1; STEP=$2; VER=29.9.3; T=$HOME/tools/docker; BK=$HOME/tools/backup/migrate-test
U=$(id -u); export XDG_RUNTIME_DIR=/run/user/$U
if [ $S = a ]; then OLD="sudo docker"; else OLD="env DOCKER_HOST=unix:///run/user/$U/docker.sock $HOME/bin/docker"; fi
NEWSOCK=$([ $S = a ] && echo /run/user/$U/docker.sock || echo $T/run/docker.sock)
NEW="env DOCKER_HOST=unix://$NEWSOCK $T/bin/docker"
manifest() {  # 在容器里列出卷里每个文件的路径、属主、权限、大小、校验值（按容器里的账号编号看）
  $1 run --rm -v "$2":/v:ro alpine:3.20 sh -c 'cd /v && find . -print0 | sort -z | xargs -0 stat -c "%n %u:%g %a %s" && find . -type f -print0 | sort -z | xargs -0 sha256sum' ; }
case $STEP in
q1)  # 清点：不在规定位置的 Docker 在哪、哪种装法、占多大、占不占系统盘、卸载要不要密码；镜像、卷、运行中的容器
  echo "== Q1 清点"
  if [ $S = a ]; then echo "装法：系统自带方式（$(dpkg -S "$(command -v dockerd)" | cut -d: -f1) 软件包），需要管理员；卸载要管理员密码"; D=/var/lib/docker; sz=$(sudo du -sh $D | cut -f1); dev=$(df --output=source $D | tail -1)
  else echo "装法：免管理员，程序在 ~/bin，后台服务名 docker"; D=$HOME/.local/share/docker; sz=$($HOME/bin/rootlesskit du -sh $D 2>/dev/null | cut -f1 || du -sh $D 2>/dev/null | cut -f1); dev=$(df --output=source $D | tail -1); fi
  sysdev=$(df --output=source / | tail -1); echo "数据目录 $D，占 $sz，在 $dev 上（$([ "$dev" = "$sysdev" ] && echo 是系统盘 || echo 不是系统盘)）"
  $OLD images --format '镜像 {{.Repository}}:{{.Tag}}  {{.Size}}'
  for v in $($OLD volume ls -q); do users=$($OLD ps -a --filter volume=$v --format '{{.Names}}({{.State}})' | tr '\n' ' '); proj=$($OLD volume inspect $v --format '{{index .Labels "com.docker.compose.project"}}'); echo "卷 $v  属于项目：${proj:-看名字是 ${v%%_*}}  用它的容器：${users:-无}"; done
  $OLD ps --format '运行中的容器 {{.Names}}（{{.Image}}）：容器里没放进数据卷的改动卸载后会丢' ;;
q2)  # 在规定位置装一份免管理员的 Docker
  echo "== Q2 在 ~/tools/docker 装一份免管理员的 Docker $VER"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq uidmap dbus-user-session >/dev/null
  mkdir -p $T/bin $T/etc $T/data $T/run; cd /tmp
  for f in docker-$VER.tgz docker-rootless-extras-$VER.tgz; do curl -fsSL -o $f https://download.docker.com/linux/static/stable/x86_64/$f; tar -xzf $f; done
  cp -f docker/* docker-rootless-extras/* $T/bin/
  printf '{\n  "data-root": "%s",\n  "proxies": {"http-proxy": "http://10.0.2.2:7890", "https-proxy": "http://10.0.2.2:7890", "no-proxy": "localhost,127.0.0.1"}\n}\n' $T/data > $T/etc/daemon.json
  # 那一条系统安全规则（按真实路径写，要管理员密码）
  printf 'abi <abi/4.0>,\ninclude <tunables/global>\n\n"%s/bin/rootlesskit" flags=(unconfined) {\n  userns,\n}\n' $T | sudo tee /etc/apparmor.d/home.xiaobai.tools.docker.bin.rootlesskit >/dev/null; sudo systemctl restart apparmor.service
  if [ $S = a ]; then
    # 情况一：官方安装脚本加 --force；装完把 docker 命令的默认指向切回原来那份
    PATH=$T/bin:$PATH $T/bin/dockerd-rootless-setuptool.sh install --force > /tmp/setuptool.log 2>&1 || { tail -5 /tmp/setuptool.log; exit 1; }
    sed -i "s#^ExecStart=.*#ExecStart=$T/bin/dockerd-rootless.sh --config-file $T/etc/daemon.json#" ~/.config/systemd/user/docker.service
    systemctl --user daemon-reload; systemctl --user restart docker
    echo "装完官方脚本切到的默认指向：$($T/bin/docker context show)"; $T/bin/docker context use default >/dev/null; echo "已切回：$($T/bin/docker context show)（敲 docker 看到的仍是原来那份）"
  else
    # 情况二：官方脚本把服务名写死成 docker，和旧的撞了；照专用 Docker 的办法用另一个服务名、另一条通道自己起
    mkdir -p ~/.config/systemd/user
    printf '[Unit]\nDescription=SOP 规定位置的 Docker（迁移期间用另一个名字）\n[Service]\nEnvironment=PATH=%s/bin:/sbin:/usr/sbin:/usr/bin:/bin\nEnvironment=XDG_RUNTIME_DIR=%s/run\nExecStart=%s/bin/dockerd-rootless.sh --config-file %s/etc/daemon.json --host unix://%s/run/docker.sock\nRestart=always\nDelegate=yes\nType=simple\nKillMode=mixed\n[Install]\nWantedBy=default.target\n' $T $T $T $T $T > ~/.config/systemd/user/sop-docker.service
    systemctl --user daemon-reload; systemctl --user enable --now sop-docker >/dev/null 2>&1; sleep 4
  fi
  for i in $(seq 1 20); do $NEW info >/dev/null 2>&1 && break; sleep 1; done
  echo "新的：$($NEW version --format '{{.Server.Version}}')，数据在 $($NEW info --format '{{.DockerRootDir}}')，通道 $NEWSOCK"
  echo "旧的照常：$($OLD ps --format '{{.Names}} {{.Status}}')" ;;
q4)  # 备份并带走：镜像导出再导入；卷用临时容器打包、还原到新 Docker 的临时卷里核对，再还原成同名的卷
  echo "== Q4 备份并带走（备份放在 $BK）"; mkdir -p $BK; need=$($OLD system df --format '{{.Size}}' | head -3 | tr '\n' ' '); echo "旧 Docker 里镜像、容器、卷的大小：$need；备份位置剩 $(df -h --output=avail $BK | tail -1)"
  imgs=$($OLD images --format '{{.Repository}}:{{.Tag}}' | sort); $OLD save -o $BK/images.tar $imgs; [ $S = a ] && sudo chown $U $BK/images.tar
  $NEW load -q -i $BK/images.tar | sed 's/^/新的导入：/'
  running=$($OLD ps --filter volume=oldproj_pgdata --format '{{.Names}}')
  # 第一次试的时候这里没有保险：中途出错退出，停掉的旧容器就一直停着，违反「中途失败旧的照常可用」。现在无论怎么退出都先把它起回来
  trap '[ -n "$running" ] && $OLD start $running >/dev/null 2>&1 && echo "（退出前已把旧容器 $running 重新起来）"' EXIT
  [ -n "$running" ] && { echo "备份数据库的卷之前先停掉用它的容器 $running（之后再起来）"; $OLD stop -t 20 $running >/dev/null; }
  [ "${FAIL_AT_RESTORE:-}" = 1 ] && { echo "（演练：在停掉旧容器之后，让还原这一步失败）"; $NEW run --rm alpine:3.20 sh -c 'exit 7'; }
  for v in $($OLD volume ls -q); do
    $OLD run --rm -v $v:/from:ro -v $BK:/to alpine:3.20 tar -C /from --numeric-owner -cpf /to/vol-$v.tar .
    manifest "$OLD" $v > $BK/vol-$v.before
    $NEW volume create $v-trial >/dev/null; $NEW run --rm -v $v-trial:/to -v $BK:/from:ro alpine:3.20 tar -C /to --numeric-owner -xpf /from/vol-$v.tar
    manifest "$NEW" $v-trial > $BK/vol-$v.try
    if cmp -s $BK/vol-$v.before $BK/vol-$v.try; then echo "卷 $v：试还原后文件清单、属主、权限、校验值都一致（$(grep -c . $BK/vol-$v.before) 行）"; $NEW volume rm $v-trial >/dev/null
    else echo "卷 $v：试还原后对不上，停下"; diff $BK/vol-$v.before $BK/vol-$v.try | head; exit 1; fi
    $NEW volume create $v >/dev/null; $NEW run --rm -v $v:/to -v $BK:/from:ro alpine:3.20 tar -C /to --numeric-owner -xpf /from/vol-$v.tar
  done
  trap - EXIT; [ -n "$running" ] && { $OLD start $running >/dev/null; echo "旧的容器已重新起来：$($OLD ps --format '{{.Names}} {{.Status}}')"; } ;;
q5)  # 核对：镜像都在；卷的清单一致；新 Docker 上用带过来的卷起数据库查数
  echo "== Q5 核对"
  for i in $($OLD images --format '{{.Repository}}:{{.Tag}}'); do $NEW image inspect $i >/dev/null && echo "镜像 $i 在" || echo "镜像 $i 不在"; done
  for v in $($OLD volume ls -q); do manifest "$NEW" $v > $BK/vol-$v.after; cmp -s $BK/vol-$v.before $BK/vol-$v.after && echo "卷 $v 一致" || echo "卷 $v 不一致"; done
  $NEW run -d --name newcheck-db -v oldproj_pgdata:/var/lib/postgresql/data postgres:17-alpine >/dev/null
  for i in $(seq 1 30); do $NEW exec newcheck-db pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done; sleep 1
  echo "新 Docker 上的数据库：$($NEW exec newcheck-db psql -tAU postgres -c 'select count(*), sum(days) from leave')（应为 500|62625.0）"; $NEW rm -f newcheck-db >/dev/null
  echo "卷里文件在宿主机上的属主（新 Docker 是免管理员的，容器里的账号映射到用户自己的一段编号）："; ls -ln $T/data/volumes/oldproj_files/_data/ 2>/dev/null | tail -3 || $T/bin/rootlesskit ls -ln $T/data/volumes/oldproj_files/_data/ | tail -3 ;;
坏一次)  # 中途让它失败一次：在 Q4 停掉旧容器之后让还原失败；旧的应照常可用
  echo "== 人为让 Q4 中途失败一次"
  FAIL_AT_RESTORE=1 bash "$0" $S q4 2>&1 | tail -3 | sed 's/^/  /' || true
  sleep 3; echo "失败之后旧的：$($OLD ps --format '{{.Names}} {{.Status}}')；数据：$($OLD exec oldproj-db psql -tAU postgres -c 'select count(*) from leave' 2>&1)"
  for v in $($NEW volume ls -q); do $NEW volume rm $v >/dev/null; done; echo "新 Docker 里做了一半的卷已清掉" ;;
q6)  # 卸载旧的（小白再确认一次之后）
  echo "== Q6 卸载旧的"
  if [ $S = a ]; then
    sudo docker rm -f $(sudo docker ps -aq) >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq docker.io >/dev/null; sudo rm -rf /var/lib/docker /etc/docker /etc/systemd/system/docker.service.d
    echo "旧的已卸：dockerd $(command -v dockerd >/dev/null && echo 还在 || echo 没了)；/var/lib/docker $([ -e /var/lib/docker ] && echo 还在 || echo 没了)"
    $T/bin/docker context use rootless >/dev/null; echo "docker 命令的默认指向切到新的：$($T/bin/docker context show)"
  else
    $OLD rm -f $($OLD ps -aq) >/dev/null
    systemctl --user disable --now docker >/dev/null 2>&1
    # 数据目录里有属于容器内部账号的文件，用户自己删不掉，要借旧的 rootlesskit 删，所以先删数据、再删程序
    rm -rf $HOME/.local/share/docker 2>/dev/null || $HOME/bin/rootlesskit rm -rf $HOME/.local/share/docker
    PATH=$HOME/bin:$PATH $HOME/bin/dockerd-rootless-setuptool.sh uninstall >/dev/null 2>&1 || true
    rm -f ~/.config/systemd/user/docker.service; rm -rf ~/.config/systemd/user/docker.service.d
    for f in containerd containerd-shim-runc-v2 ctr docker docker-init docker-proxy dockerd dockerd-rootless-setuptool.sh dockerd-rootless.sh rootlesskit runc vpnkit; do rm -f $HOME/bin/$f; done
    sudo rm -f /etc/apparmor.d/home.xiaobai.bin.rootlesskit
    echo "旧的已卸：~/bin 里 Docker 的程序 $(ls $HOME/bin 2>/dev/null | grep -c docker) 个；~/.local/share/docker $([ -e $HOME/.local/share/docker ] && echo 还在 || echo 没了)"
    # 新的接过默认的服务名和通道
    systemctl --user disable --now sop-docker >/dev/null 2>&1
    sed -e 's#^Environment=XDG_RUNTIME_DIR=.*##' -e "s# --host unix://$T/run/docker.sock##" -e 's#（迁移期间用另一个名字）##' ~/.config/systemd/user/sop-docker.service > ~/.config/systemd/user/docker.service
    rm -f ~/.config/systemd/user/sop-docker.service; systemctl --user daemon-reload; systemctl --user enable --now docker >/dev/null 2>&1; sleep 4
    NEW="env DOCKER_HOST=unix:///run/user/$U/docker.sock $T/bin/docker"
  fi
  for i in $(seq 1 20); do $NEW info >/dev/null 2>&1 && break; sleep 1; done
  echo "规定位置的那一份仍正常：$($NEW version --format '{{.Server.Version}}')，镜像 $($NEW images -q | wc -l) 个，卷 $($NEW volume ls -q | tr '\n' ' ')"
  $NEW run --rm -v oldproj_files:/d:ro alpine:3.20 cat /d/c.txt ;;
看旧的) $OLD ps -a --format '{{.Names}} {{.Status}}' ;;
esac
