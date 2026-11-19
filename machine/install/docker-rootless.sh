#!/bin/bash
# 装免管理员的 Docker 到 ~/tools/docker，数据在 ~/tools/docker/data（设计书 4.3、4.5、4.8；任务 3-09）。
# 程序用 Docker 官方的静态压缩包（docker、docker-rootless-extras 两个）。SOP_DOCKER_VERSION 可以指定版本（如 29.10.0），
# 不给就装官方下载站上最新的。设置在 ~/tools/docker/etc/daemon.json（数据位置、网络设置里的代理）。
#
# 要管理员密码的只有一步，而且只在缺东西时才有：先用一句大白话说要做什么，再由系统问密码（sudo）。这一步做的是
#   - 装系统软件包 uidmap、dbus-user-session、iptables 里缺的那几样（4.3「在系统盘上的」）
#   - 载入 Docker 要的网络模块（nf_tables，老系统是 ip_tables）：官方安装脚本装之前要看到它已经载入。只载入这一次、不写开机配置：
#     之后 Docker 自己用到时系统会自动载入（3-09 在虚拟机里删掉开机配置重启验过）
#   - 给 ~/tools/docker/bin/rootlesskit 加那一条系统安全规则（/etc/apparmor.d/ 下按真实路径起名，和官方说明、体检 components.py 一样）
#
# 官方安装脚本 dockerd-rootless-setuptool.sh 的三处（4.8）：
#   1. 系统自带的 Docker 在运行、而且小白能直接用它（/var/run/docker.sock 能写）时，它会中止：这时才加 --force
#   2. 它装完把 docker 命令的默认指向（context）切到新的：电脑上另有一份 Docker 时，由这个脚本切回原来那份
#   3. 它的后台服务名写死成 docker：电脑上另有一份免管理员的 Docker 已经占了这个名字时不用它，
#      自己写一个 sop-docker.service（通道 /run/user/<编号>/sop-docker/docker.sock），旧的一样不动；
#      卸掉旧的之后由环境迁移接过默认的名字（4.8）
# 后台服务的登记文件由这个脚本先写好（多了 --config-file 指到 ~/tools/docker/etc/daemon.json），官方脚本看到已有就不改它，
# 只做检查、起服务、设成登录后自己起来、建默认指向。
#
# 装好之后通道写在 ~/tools/docker/etc/docker-host（一行，例如 unix:///run/user/1000/docker.sock），工具包自己用这份 Docker 时按它找。
# 中途失败：这一次新放的程序、服务登记文件拿掉，默认指向改回去；系统规则、系统软件包留着（重装还要用）。
#
# --plan：只看、不改，打印要怎么装（给单元测试用；不下载、不要密码）。
. "$(dirname "$0")/lib.sh"
plan=; [ "${1:-}" = --plan ] && plan=1

[ "$(id -u)" != 0 ] || die "不能用管理员身份装：免管理员的 Docker 要用小白自己的账号装（不要加 sudo）"
T=$SOP_TOOLS/docker
BIN=$T/bin
UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
DOCKER_CFG=${DOCKER_CONFIG:-$HOME/.docker}
# 下面几个系统位置可以换（只给单元测试用）
SYS_SOCK=${SOP_SYS_DOCKER_SOCK:-/var/run/docker.sock}
AA=${SOP_APPARMOR_DIR:-/etc/apparmor.d}
AA_ON=${SOP_APPARMOR_ENABLED:-/sys/module/apparmor/parameters/enabled}
PROC_MODULES=${SOP_PROC_MODULES:-/proc/modules}
BUILTIN=${SOP_MODULES_BUILTIN:-/lib/modules/$(uname -r)/modules.builtin}
RUNTIME=${XDG_RUNTIME_DIR:-}

case $T in *[\"\\\$\`\ ]*) die "工具目录的路径里有空格或引号这类字符，系统规则写不了：$T" ;; esac

# ---------- 看清现在的情况 ----------

# 1. 系统自带的 Docker：通道在就算有；小白能写这个通道时官方脚本才中止，才加 --force
system=; [ -S "$SYS_SOCK" ] && system=1
force=; [ -w "$SYS_SOCK" ] && force=--force

# 3. 后台服务名：docker 这个名字已经被另一份免管理员的 Docker 占了（登记文件不是指着规定位置的程序），
#    或者另一份没用后台服务、自己在默认通道上跑着，就用 sop-docker
unit=docker
if [ -f "$UNITS/docker.service" ]; then
  grep -qF "$BIN/dockerd-rootless.sh" "$UNITS/docker.service" || unit=sop-docker
elif [ -n "$RUNTIME" ] && [ -S "$RUNTIME/docker.sock" ]; then
  unit=sop-docker
fi
if [ $unit = docker ]; then host=unix://$RUNTIME/docker.sock; else host=unix://$RUNTIME/sop-docker/docker.sock; fi

# 2. 装之前 docker 命令的默认指向（~/.docker/config.json 的 currentContext，没写就是 default）
ctx_before=$(python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("currentContext") or "default")
except FileNotFoundError:
    print("default")
except Exception:
    print("?")' "$DOCKER_CFG/config.json")
[ "$ctx_before" != "?" ] || die "读不懂 $DOCKER_CFG/config.json（docker 命令的设置），没有往下装"
# 要切回去的：用官方脚本装（它会切到 rootless）、而且电脑上另有一份（系统自带的在，或原来就指着别的）
restore=
if [ $unit = docker ] && [ "$ctx_before" != rootless ] && { [ -n "$system" ] || [ "$ctx_before" != default ]; }; then
  restore=$ctx_before
fi

# 要管理员权限的几样，缺哪样做哪样
pkgs=()
for p in uidmap dbus-user-session iptables; do
  dpkg-query -W -f '${Status}' "$p" 2>/dev/null | grep -q 'ok installed' || pkgs+=("$p")
done
module=nf_tables
ipt=$(PATH=$PATH:/sbin:/usr/sbin command -v iptables 2>/dev/null) && case $($ipt --version 2>/dev/null) in *legacy*) module=ip_tables ;; esac
load_module=
grep -qw "^$module" "$PROC_MODULES" 2>/dev/null || grep -qw "$module" "$BUILTIN" 2>/dev/null || load_module=1
rk=$(realpath -m "$BIN/rootlesskit")
rule_name=${rk#/}; rule_name=${rule_name//\//.}
rule="# SOP 工具包写的（任务 3-09）：允许规定位置的免管理员 Docker 建隔离空间。重装时会被换回来
abi <abi/4.0>,
include <tunables/global>

\"$rk\" flags=(unconfined) {
  userns,

  # Site-specific additions and overrides. See local/README for details.
  include if exists <local/$rule_name>
}"
write_rule=
if [ -d "$AA" ] && [ "$(cat "$AA_ON" 2>/dev/null)" = Y ]; then
  [ "$(cat "$AA/$rule_name" 2>/dev/null)" = "$rule" ] || write_rule=1
fi

if [ -n "$plan" ]; then
  echo "unit=$unit"; echo "host=$host"; echo "force=${force:-no}"; echo "restore=$restore"
  echo "packages=${pkgs[*]}"; yn() { if [ -n "$1" ]; then echo yes; else echo no; fi; }
  echo "module=$module load=$(yn "$load_module")"
  echo "rule=$rule_name write=$(yn "$write_rule")"
  exit 0
fi

# 先看装得了装不了，再问密码
systemctl --user show-environment >/dev/null 2>&1 && [ -n "$RUNTIME" ] && [ -w "$RUNTIME" ] \
  || die "要在登录进来的终端里运行（桌面上开的终端、ssh 登录都行）：找不到这个账号的用户级后台服务"

case $(uname -m) in
  x86_64) arch=x86_64 ;;
  aarch64|arm64) arch=aarch64 ;;
  *) die "不支持这种处理器：$(uname -m)" ;;
esac

# ---------- 要管理员密码的那一步（缺东西才有） ----------

if [ ${#pkgs[@]} -gt 0 ] || [ -n "$load_module$write_rule" ]; then
  root=$WORK/root.sh what=()
  { echo 'set -e'
    if [ ${#pkgs[@]} -gt 0 ]; then
      echo 'export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1'   # 不要 needrestart 那几行英文
      echo 'apt-get -o DPkg::Lock::Timeout=300 update -qq'     # 刚开机时系统可能正在自己更新、占着锁：等它最多 5 分钟
      echo "apt-get -o DPkg::Lock::Timeout=300 install -y -qq --no-install-recommends ${pkgs[*]} >/dev/null"
    fi
    [ -n "$load_module" ] && echo "modprobe $module"
    if [ -n "$write_rule" ]; then
      printf 'cat > %q <<'"'"'SOP_RULE_END'"'"'\n%s\nSOP_RULE_END\n' "$AA/$rule_name" "$rule"
      echo "apparmor_parser -r $(printf %q "$AA/$rule_name")"
    fi
  } > "$root"
  [ ${#pkgs[@]} -gt 0 ] && what+=("装系统软件包 ${pkgs[*]}")
  [ -n "$load_module" ] && what+=("让系统载入 Docker 要的网络模块 $module")
  [ -n "$write_rule" ] && what+=("给 $rk 加一条系统安全规则，允许它建隔离空间")
  echo
  said=${what[0]}; for w in "${what[@]:1}"; do said+="；$w"; done
  echo "接下来这一步要管理员权限：$said。"
  echo "系统会问这台电脑的登录密码（就是开机登录用的那个），输入时屏幕上什么都不显示，输完按回车。"
  command -v sudo >/dev/null || die "这台电脑上没有 sudo，这一步做不了"
  penv=()
  for k in http_proxy https_proxy no_proxy; do [ -n "${!k:-}" ] && penv+=("$k=${!k}"); done
  sudo -p "[sudo] 请输入 %u 的登录密码：" env "${penv[@]}" bash "$root" \
    || die "要管理员权限的那一步没做成（密码不对、这个账号不能用 sudo、不是在终端里运行的，或者连不上软件源；看上面的报错）"
  echo "要管理员权限的那一步做完了。"
fi

# ---------- 装程序（不用管理员密码） ----------

site=https://download.docker.com/linux/static/stable/$arch
if [ -n "${SOP_DOCKER_VERSION:-}" ]; then
  v=${SOP_DOCKER_VERSION#v}
else
  fetch "$site/" "$WORK/index.html"
  v=$(grep -o 'docker-rootless-extras-[0-9]*\.[0-9]*\.[0-9]*\.tgz' "$WORK/index.html" | sed 's/^docker-rootless-extras-//; s/\.tgz$//' | sort -uV | tail -1)
  [ -n "$v" ] || die "在 Docker 的下载站上找不到版本号（$site/）"
  grep -q "\"docker-$v.tgz\"" "$WORK/index.html" || die "Docker 的下载站上有 docker-rootless-extras-$v，却没有 docker-$v"
fi
for f in "docker-$v" "docker-rootless-extras-$v"; do
  fetch "$site/$f.tgz" "$WORK/$f.tgz"
  tar -xzf "$WORK/$f.tgz" -C "$WORK" || die "$f.tgz 解不开"
done
mkdir -p "$WORK/bin"
cp -a "$WORK"/docker/* "$WORK"/docker-rootless-extras/* "$WORK/bin/"
for f in docker dockerd containerd runc rootlesskit dockerd-rootless.sh dockerd-rootless-setuptool.sh; do
  [ -x "$WORK/bin/$f" ] || die "压缩包里没有 $f"
done

# 中途失败：这一次新放的东西拿掉（原来就有的不动），默认指向改回去
fresh=; [ -e "$BIN" ] || fresh=1
unit_file=$UNITS/$unit.service
new_unit=; [ -e "$unit_file" ] || new_unit=1
ok=
on_exit() {
  if [ -z "$ok" ]; then
    echo "没装好，收拾这一次新放的东西…" >&2
    if [ -n "$new_unit" ] && [ -e "$unit_file" ]; then
      systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
      rm -f "$unit_file"; systemctl --user daemon-reload || true
    fi
    if [ -n "$restore" ] && [ -x "$BIN/docker" ]; then env -u DOCKER_HOST -u DOCKER_CONTEXT "$BIN/docker" context use "$restore" >/dev/null 2>&1 || true; fi
    [ -n "$fresh" ] && rm -rf "$BIN"
  fi
  rm -rf "$WORK"
}
trap on_exit EXIT

# 规定位置的那一份正在跑（重装、升级）：先停下，换程序
if [ -e "$unit_file" ] && systemctl --user -q is-active "$unit"; then
  echo "规定位置的 Docker 正在运行，先停下再换程序（容器会跟着停，之后照常起来的按它们自己的重启设置）"
  systemctl --user stop "$unit"
fi
mkdir -p "$T/etc" "$T/data"
rm -rf "$T/.bin.new" "$T/.bin.old"
cp -a "$WORK/bin" "$T/.bin.new"
[ -e "$BIN" ] && mv "$BIN" "$T/.bin.old"
mv "$T/.bin.new" "$BIN"
rm -rf "$T/.bin.old"

# 设置：数据位置、代理（网络设置里的，4.4）
python3 - "$T/etc/daemon.json" "$T/data" <<'PY'
import json, os, sys
conf = {"data-root": sys.argv[2]}
px = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy")}
if px["http_proxy"] or px["https_proxy"]:
    conf["proxies"] = {n: v for n, v in (("http-proxy", px["http_proxy"]), ("https-proxy", px["https_proxy"]),
                                          ("no-proxy", px["no_proxy"])) if v}
text = json.dumps(conf, indent=2, ensure_ascii=False) + "\n"
try:
    same = open(sys.argv[1]).read() == text
except FileNotFoundError:
    same = False
if not same:
    with open(sys.argv[1] + ".tmp", "w") as f:
        f.write(text)
    os.replace(sys.argv[1] + ".tmp", sys.argv[1])
PY

# 后台服务的登记文件（内容照官方脚本的样子，多了 --config-file；sop-docker 另用自己的运行目录）
unit_text="[Unit]
Description=Docker Application Container Engine (Rootless, SOP: ~/tools/docker)
Documentation=https://docs.docker.com/go/rootless/
Requires=dbus.socket

[Service]
Environment=PATH=$BIN:/sbin:/usr/sbin:/usr/local/bin:/usr/bin:/bin"
if [ $unit = sop-docker ]; then
  unit_text+="
Environment=XDG_RUNTIME_DIR=%t/sop-docker
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus
RuntimeDirectory=sop-docker
RuntimeDirectoryMode=0700"
fi
unit_text+="
ExecStart=$BIN/dockerd-rootless.sh --config-file $T/etc/daemon.json
ExecReload=/bin/kill -s HUP \$MAINPID
TimeoutSec=0
RestartSec=2
Restart=always
StartLimitBurst=3
StartLimitInterval=60s
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
Delegate=yes
Type=notify
NotifyAccess=all
KillMode=mixed

[Install]
WantedBy=default.target"
mkdir -p "$UNITS"
if [ "$(cat "$unit_file" 2>/dev/null)" != "$unit_text" ]; then
  printf '%s\n' "$unit_text" > "$unit_file.sop-tmp" && mv "$unit_file.sop-tmp" "$unit_file"
fi
systemctl --user daemon-reload

if [ $unit = docker ]; then
  # 用官方安装脚本：检查、起服务、登录后自己起来、建默认指向 rootless 并切过去
  [ -n "$force" ] && echo "系统自带的 Docker 正在运行，官方安装脚本要加 --force 才肯装（两份并存，旧的不动）"
  env -u DOCKER_HOST -u DOCKER_CONTEXT PATH="$BIN:/sbin:/usr/sbin:$PATH" "$BIN/dockerd-rootless-setuptool.sh" install $force \
    > "$WORK/setuptool.log" 2>&1 || { tail -15 "$WORK/setuptool.log" >&2; die "Docker 的官方安装脚本出错了（上面是它最后的几行）"; }
  if [ -n "$restore" ]; then
    env -u DOCKER_HOST -u DOCKER_CONTEXT "$BIN/docker" context use "$restore" >/dev/null 2>&1 \
      || die "没能把 docker 命令的默认指向切回原来的 $restore"
    echo "官方安装脚本把 docker 命令的默认指向切到了新的这份；电脑上另有一份 Docker，已切回原来的「$restore」（敲 docker 看到的还是原来那份）"
  fi
else
  # 官方脚本的服务名写死成 docker，已经被另一份占了：用自己的名字起，不用官方脚本
  echo "电脑上另有一份免管理员的 Docker 占着 docker 这个服务名，规定位置的这份用 sop-docker 这个名字，两份并存，旧的不动"
  systemctl --user enable "$unit" >/dev/null 2>&1 || die "没能把 $unit 设成登录后自己起来"
  systemctl --user start "$unit" || die "$unit 起不来，看 journalctl --user -u $unit"
fi

# 核对：起来了、是免管理员的、数据在规定位置
for i in $(seq 1 30); do
  info=$(env -u DOCKER_CONTEXT DOCKER_HOST="$host" "$BIN/docker" info --format '{{.DockerRootDir}}|{{.SecurityOptions}}' 2>/dev/null) && break
  sleep 1
done
[ -n "$info" ] || die "Docker 起来之后连不上（通道 $host），看 journalctl --user -u $unit"
[ "${info%%|*}" = "$(realpath -m "$T/data")" ] || die "Docker 的数据不在规定位置：${info%%|*}（应该是 $T/data）"
case $info in *rootless*) ;; *) die "连上的这份 Docker 不是免管理员的：$host" ;; esac
printf '%s\n' "$host" > "$T/etc/docker-host"
ok=1
echo "免管理员的 Docker $v 装好了：程序在 $BIN，数据在 $T/data，通道 $host，后台服务 $unit（登录后自己起来）"
"$BIN/docker" --version
