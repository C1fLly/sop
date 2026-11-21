#!/bin/bash
# 3-33：在虚拟机里跑（由 migrate-io.sh 拷进去、启动）。见 migrate-io.sh 的说明。
#   --prepare：先记下装 docker.io 之前系统里有哪些文件、哪些软件包；再装 docker.io、放镜像数据卷容器（单独一次登录做，下一次登录 docker 组才生效）
#   --run1   ：第一遍 sop machine migrate：Q2 装规定位置的 Docker，Q3 选卸 docker.io、带走数据，Q4 停了旧容器、正在打包时强制结束整个 sop；
#              看旧容器停着；再执行一次别的 sop 命令，看起回来、临时小镜像删掉
#   --run2   ：先把默认指向手动切到新的（模拟小白切过）；第二遍走完 Q1 到 Q6，Q6 切回原来那份之后暂停整个 sop，看不加 sudo 敲 docker
#              是原来那份；卸完核对残留清单逐项为空、和装 docker.io 之前的系统比、敲 docker 是规定位置那份、带走的数据一致
#   --look <文件>：新开一个终端，不加 sudo 敲 docker，看到的写进文件（run2 暂停时由驱动调）
set -uo pipefail
SRC=~/sop-src
T=~/tools/docker
B=~/io-base                          # 装 docker.io 之前的样子、旧数据的校验值
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
SOP="python3 -I $SRC/kernel/main.py"   # 启动器执行的就是这一句（kernel/launcher.py、kernel/main.py）
DRIVE="python3 -I $SRC/tests/vm/migrate-drive.py"
OLD="env -u DOCKER_HOST -u DOCKER_CONTEXT /usr/bin/docker --host unix:///var/run/docker.sock"
NEW() { env -u DOCKER_CONTEXT DOCKER_HOST="$(cat $T/etc/docker-host)" $T/bin/docker "$@"; }
term() { bash -ic "$1" 2>&1 | grep -v -e 'cannot set terminal process group' -e 'no job control in this shell'; }
step() { echo; echo "=== $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }

sysfiles() {   # 系统里的文件（只要路径）；apt 的索引、dpkg 自己的库、缓存不算
  sudo find /etc /usr /var/lib /opt /srv -xdev \( -path /var/lib/apt/lists -o -path /var/lib/dpkg -o -path /var/lib/systemd \
    -o -path /var/lib/ubuntu-advantage -o -path /var/lib/update-notifier -o -path /var/lib/cloud -o -name __pycache__ \) -prune -o -print 2>/dev/null | sort
}
pkgs() { dpkg-query -W -f '${Package} ${db:Status-Abbrev}\n' | awk '$2 ~ /^ii/ {print $1}' | sort; }

if [ "${1:-}" = --look ]; then
  term 'echo "docker → $(command -v docker)；默认指向 $(docker context show 2>&1)；连到的 Docker 数据在 $(docker info --format "{{.DockerRootDir}}" 2>&1 | tail -1)"; docker ps --format "容器 {{.Names}}" 2>&1 | head -5' > "$2"
  exit 0
fi

if [ "${1:-}" = --prepare ]; then
  echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"
  rm -rf $B; mkdir -p $B
  step "记下装 docker.io 之前的样子（系统文件路径、装着的软件包、主目录里的东西）"
  sysfiles > $B/files.txt; pkgs > $B/pkgs.txt
  find ~ -mindepth 1 -maxdepth 3 -not -path "$HOME/sop-src*" -not -path "$HOME/io-base*" | sort > $B/home.txt
  echo "  系统文件 $(wc -l < $B/files.txt) 个，软件包 $(wc -l < $B/pkgs.txt) 个"
  step "用 Ubuntu 软件源装一份系统自带的 docker.io，小白加进 docker 组"
  sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >/dev/null || exit 1
  sudo mkdir -p /etc/systemd/system/docker.service.d       # 虚拟机只能经本机代理拉镜像；小白照网上教程也常这样加
  printf '[Service]\nEnvironment=HTTP_PROXY=%s HTTPS_PROXY=%s NO_PROXY=localhost,127.0.0.1\n' $PROXY $PROXY | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
  sudo systemctl daemon-reload; sudo systemctl restart docker
  sudo usermod -aG docker xiaobai
  D="sudo $OLD"
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
  echo "  装好的：$(dpkg-query -W -f '${Package} ${Version}' docker.io)"
  exit 0
fi

net() { (cd $SRC && env -u http_proxy -u https_proxy python3 -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')"); }
state_of() { $OLD inspect -f '{{.State.Status}}' "$1" 2>/dev/null || echo 没有; }
rules() {    # $1 = 文件；$2 = 1 表示还要回答「确定现在卸掉它吗」、在切回原来那份之后暂停；否则在打包时强制结束
  python3 - "$1" "$2" <<'EOF'
import json, sys, os
f, q6 = sys.argv[1], sys.argv[2] == '1'
ans = [{'q': r'docker\.io）[^\n]*合计', 'a': '2'}, {'q': r'匿名卷[^\n]*：', 'a': '2'}, {'q': '现在停一下吗', 'a': 'y'}]
ev = [{'on': '打包数据卷', 'do': 'kill'}]
if q6:
    ans.append({'q': '确定现在卸掉它吗', 'a': 'y'})
    ev = [{'on': '先切回原来那份', 'do': 'pause', 'run': f'bash {os.path.expanduser("~/sop-src/tests/vm/migrate-io-guest.sh")} --look /tmp/io-mid.txt'}]
json.dump({'answers': ans, 'events': ev, 'timeout': 2400}, open(f, 'w'), ensure_ascii=False)
EOF
}

if [ "${1:-}" = --run1 ]; then
  step "这一次登录：小白在 docker 组里（$(id -nG | tr ' ' '\n' | grep -x docker || echo 不在)），不加 sudo 能连系统自带的那份"
  must "$OLD version >/dev/null 2>&1" "不加 sudo 连得上系统自带的那份"
  must "[ ! -e $T ]" "规定位置的 Docker 还没装（让 Q2 去装）"
  net && echo "  写好网络设置（第零步会写的那一份）"
  rules /tmp/io-rules1.json 0
  step "第一遍 sop machine migrate（在模拟终端里，像小白一样回答；Q4 打包时强制结束）"
  cd ~ && $DRIVE /tmp/io-rules1.json /tmp/io-run1.log -- $SOP machine migrate >/dev/null; rc=$?
  grep -v -e '^\s*$' /tmp/io-run1.log | tail -25 | sed 's/^/  | /'
  must "[ $rc = 137 ]" "在 Q4 打包时被强制结束了（kill -9 整组）"
  must "grep -q 'docker：装好了' /tmp/io-run1.log && [ -x $T/bin/docker ] && NEW version >/dev/null 2>&1" "Q2 装好了规定位置的 Docker，能连上"
  must "grep -q '已切回原来的「default」' /tmp/io-run1.log" "Q2 装完把默认指向切回了原来那份"
  must "grep -q '旧 Docker 里临时放一个打包用的小镜像' /tmp/io-run1.log" "旧的里没有打包用的小镜像，从新的那份导过去了（记进了记录）"
  sleep 5      # 打包用的临时容器在客户端被杀后自己退出、自己删掉
  st=$(state_of shop-db-1)
  must "[ \"$st\" = exited ]" "旧容器 shop-db-1 被停着（$st）"
  must "[ -f ~/tools/sop/config/migrate/stopped.json ] && grep -q shop-db-1 ~/tools/sop/config/migrate/stopped.json" "停容器之前写下了记录 stopped.json"
  echo "  记录：$(tr -d '\n ' < ~/tools/sop/config/migrate/stopped.json 2>/dev/null)"
  echo "  旧的里现在的容器：$($OLD ps -a --format '{{.Names}}({{.State}})' | tr '\n' ' ')"
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-after-q2.txt; sed 's/^/  新开终端：/' /tmp/io-after-q2.txt
  must "grep -q '数据在 /var/lib/docker' /tmp/io-after-q2.txt && grep -q '默认指向 default' /tmp/io-after-q2.txt" "Q2 之后新开终端不加 sudo 敲 docker，看到的是原来那份"
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
  env -u DOCKER_HOST $T/bin/docker context use rootless >/dev/null
  bash $SRC/tests/vm/migrate-io-guest.sh --look /tmp/io-before.txt; sed 's/^/  新开终端：/' /tmp/io-before.txt
  must "grep -q '默认指向 rootless' /tmp/io-before.txt && grep -q \"数据在 $T/data\" /tmp/io-before.txt" "切过去了：敲 docker 现在是规定位置那份"
  rules /tmp/io-rules2.json 1
  step "第二遍 sop machine migrate（走完 Q1 到 Q6；Q6 切回原来那份之后暂停一下看）"
  cd ~ && $DRIVE /tmp/io-rules2.json /tmp/io-run2.log -- $SOP machine migrate >/dev/null; rc=$?
  sed -n '/^Q3 /,$p' /tmp/io-run2.log | grep -v -e '^\s*$' | sed 's/^/  | /'
  must "[ $rc = 0 ]" "sop machine migrate 正常结束（退出码 0）"
  must "! grep -q '驱动：这些问题没出现' /tmp/io-run2.log" "该问的都问了（选卸、匿名卷不要了、停容器、确认卸载）"
  sed 's/^/  暂停时新开终端：/' /tmp/io-mid.txt
  must "grep -q '数据在 /var/lib/docker' /tmp/io-mid.txt && grep -q '默认指向 default' /tmp/io-mid.txt && grep -q '容器 shop-db-1' /tmp/io-mid.txt" \
    "Q6 切回之后、卸之前：不加 sudo 敲 docker 看到的是原来那份和它的容器"
  must "grep -q '都没有了' /tmp/io-run2.log && ! grep -q '没卸干净' /tmp/io-run2.log" "残留清单逐项又看了一遍都没有了（sop 自己说的）"
  must "grep -q '规定位置的 Docker 仍然正常' /tmp/io-run2.log" "规定位置那份仍然正常（sop 自己说的）"

  step "自己逐项再核对残留清单（按 Q1 存的 inventory.json）"
  python3 - > /tmp/io-residue.txt <<'EOF'
import json, os
inv = json.load(open(os.path.expanduser('~/tools/sop/config/migrate/inventory.json')))
d = next(d for d in inv['docker'] if d['kind'] == 'docker.io')
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
      path) p=${what/#\~/$HOME}; ! sudo test -e "$p" || { echo "  还在：$what"; left=1; } ;;
      apt-line) ! grep -qs '^[^#]*download\.docker\.com' "$file" || { echo "  还在：$file 里的软件源"; left=1; } ;;
      *) echo "  不认识：$kind $what"; left=1 ;;
    esac
  done < /tmp/io-residue.txt
  echo "  残留清单 $n 项：$(cut -d' ' -f1-2 /tmp/io-residue.txt | tr '\n' '，')"
  must "[ $n -gt 5 ] && [ $left = 0 ]" "残留清单 $n 项逐项为空"

  step "和装 docker.io 之前的系统比（独立于残留清单）"
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
  must "! grep -q 'docker.io' /tmp/io-inv-after.txt" "清点里没有 docker.io 了"
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
  out=$(NEW run --rm -v shop_pgdata:/data:ro busybox:1.36 sh -c 'cd /data && sha256sum blob' 2>&1)
  must "[ \"$out\" = \"$(head -1 $B/data.txt)\" ]" "重启后带走的数据还在"
  exit $fail
fi
echo "用法：--prepare | --run1 | --run2 | --after-reboot | --look <文件>"; exit 2
