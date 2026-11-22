#!/bin/bash
# SOP 工具包的第零步（设计书 4.2、4.5 的 M0；任务 3-13）。只用 bash 和系统自带的东西。
#
# 小白手册首页的那一条命令（Ubuntu 26.04 桌面版自带 wget、不带 curl 和 git，所以用 wget 取这个脚本）：
#   wget --no-hsts -qO /tmp/sop-bootstrap.sh <工具包仓库>/bootstrap.sh && bash /tmp/sop-bootstrap.sh
#
# 做的事，按顺序：
#   1. 看系统：只支持 Ubuntu 26.04（4.1），不许用管理员账号跑（会装进 /root）。
#   2. 网络：读已有的代理设置（环境变量、桌面的网络设置、/etc/environment、apt 的设置），试连 GitHub、Ubuntu 软件源、
#      工具包仓库，把结果摆给小白确认；探测不出来、连不上才问代理地址（「不知道就直接回车」）。
#   3. 缺 git、curl 才用 apt 装（要管理员密码：先说一句，再由系统问）。
#   4. 把工具包取到 ~/tools/sop/versions/<提交编号>（Git 取最新的 main）。
#   5. 用工具包里的安装脚本把 uv 装到 ~/tools/uv。
#   6. 报告主目录在哪个分区（只报告、不问，4.3）。
#   7. 写网络设置 ~/tools/sop/config/network.json、启动器 ~/tools/sop/sop、~/.bashrc 末尾工具包那一段（让新开的终端找得到 sop 和 uv）。
#   8. 出口检查：sop 能运行。最后提示执行 sop machine setup。
# 可以重复跑：已经有的跳过，内容没变的文件不重写。
#
# 选项（自测、虚拟机验证用；小白不用）：
#   --repo <地址>    工具包仓库（也可以用环境变量 SOP_TOOLKIT_REPO）。不给就用下面的 DEFAULT_REPO：GitHub 上的工具包公开仓库（3-41）
#   --yes            探测到的网络情况直接当成对的，不问
#   --proxy <地址>   不探测，直接用这个代理（给空的就是不用代理）
#   --offline <目录> 离线包（3-14）用：不上网，git、curl 的软件包、uv、工具包都从这个目录取。
#                    小白不直接用它：离线包是一个文件，bash <离线包> 解开后自己带上这个选项（machine/offline/）
set -uo pipefail

DEFAULT_REPO='https://github.com/C1fLly/sop.git'     # 工具包的公开仓库（3-41）；不登录也能取
GITHUB_URL=${SOP_BOOTSTRAP_GITHUB:-https://github.com/}
ETC_ENV=${SOP_BOOTSTRAP_ETC_ENV:-/etc/environment}
OS_RELEASE=${SOP_BOOTSTRAP_OS_RELEASE:-/etc/os-release}
SUDO_PROMPT='[sudo] 请输入 %u 的登录密码：'
OFFLINE_URL='https://github.com/C1fLly/sop/releases/latest'   # 离线包挂在工具包仓库的 Releases 上（3-51）
NO_NET="可以问一下懂网络的人这台电脑上网用的代理地址，再重新执行这一步。完全连不上外网的，用离线包：在另一台能上网的电脑上打开 $OFFLINE_URL ，下载 sop-offline-（一串字母数字）-amd64.sh 这个文件，用 U 盘拷到这台电脑，在终端里执行 bash <这个文件>（小白手册「完全连不上网」那一节）"
PROXY_RE='^https?://[^[:space:]/:]+(:[0-9]{1,5})?/?$'   # 只认网页代理：系统自带的 wget 不支持 socks

# ---------- 等住软件包的锁（3-56）：和 machine/install/apt.sh 一字不差（单元测试核对），这里要单独运行所以抄一份 ----------
SOP_APT_SH=$(cat <<'SOP_APT_END'
# 共用的一小段（3-56）：用 apt-get 装系统软件包时，等住软件包的锁。不单独运行，由要管理员权限的那一小段脚本先载入再用：
#   machine/install.py、machine/install/docker-rootless.sh 读这个文件；bootstrap.sh 要单独运行，里面抄了一份，
#   单元测试核对两份一字不差。只用 sh 的写法（install.py、bootstrap.sh 用 sh -c 跑，docker-rootless.sh 用 bash 跑）。
#
# 刚开机时系统常常正在自己更新软件（apt-daily、unattended-upgrades），占着软件包的锁。apt 的 DPkg::Lock::Timeout
# 只管 dpkg 的锁；apt-get update 要的 /var/lib/apt/lists/lock、下载要的 /var/cache/apt/archives/lock 拿不到就立刻报错退出
# （退出码 100，虚拟机里试过，apt 3.2.1）。所以这里自己等：报错里提到这几把锁，就隔 5 秒再试，
# 一共最多等 SOP_APT_WAIT 秒（默认 600，即 10 分钟），等不到退出码 75，上面认出 75 说「系统正在自己更新软件」。
# 报错里的锁文件路径不随系统语言变，所以按路径认。apt 正常的输出扔掉，报错和警告照原样打出来。
sop_apt() {
  _sop_limit=${SOP_APT_WAIT:-600} _sop_start=$(date +%s) _sop_said=0
  while :; do
    _sop_err=$(apt-get "$@" 2>&1 >/dev/null) && { [ -z "$_sop_err" ] || printf '%s\n' "$_sop_err" >&2; return 0; }
    _sop_rc=$?
    case $_sop_err in
      *'/var/lib/apt/lists/lock'*|*'/var/cache/apt/archives/lock'*|*'/var/lib/dpkg/lock'*) ;;
      *) printf '%s\n' "$_sop_err" >&2; return $_sop_rc ;;
    esac
    _sop_used=$(( $(date +%s) - _sop_start ))
    if [ "$_sop_used" -ge "$_sop_limit" ]; then
      printf '%s\n' "$_sop_err" >&2
      echo "等了 $(( (_sop_used + 59) / 60 )) 分钟，系统自己的软件更新还没做完，还占着软件包的锁。" >&2
      return 75
    fi
    if [ "$_sop_said" = 0 ]; then
      echo "系统正在自己更新软件（刚开机时常有），占着软件包的锁。等它做完再接着装，最多等 $(( (_sop_limit + 59) / 60 )) 分钟……" >&2
      _sop_said=60
    elif [ "$_sop_used" -ge "$_sop_said" ]; then
      echo "还在等系统自己的软件更新（已经等了 $(( _sop_used / 60 )) 分钟）……" >&2
      _sop_said=$(( _sop_said + 60 ))
    fi
    sleep 5
  done
}
SOP_APT_END
)
APT_LOCKED='系统正在自己更新软件，等了好几分钟还没做完（刚开机、或很久没开机时常有）。不是你做错了什么：过一会儿再执行一次同样的命令就行'

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
die() { printf '\n没做完：%s\n' "$*" >&2; exit 1; }

# ---------- 问小白 ----------
# 从标准输入读（手册里的命令是先下载、再 bash 运行，标准输入就是终端）。读不到（没有输入）算直接回车。
ask() {
  local ans=
  printf '%s' "$1" >&2
  read -r ans || ans=
  printf '%s' "$ans"
}

# ---------- 代理 ----------
# 小白输入的代理地址：去掉两头空白，没写 http:// 的补上。写法不对返回 1。
normalize_proxy() {
  local p=$1
  p=${p#"${p%%[![:space:]]*}"}; p=${p%"${p##*[![:space:]]}"}
  [ -z "$p" ] && return 0
  [[ $p == *://* ]] || p=http://$p
  [[ $p =~ $PROXY_RE ]] || return 1
  printf '%s' "${p%/}"
}

# 读已有的代理设置。输出三行：代理、不走代理的地址、从哪读到的（没有就是三个空行）。
detect_proxy() {
  local p np
  # 1. 环境变量
  p=${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}
  if [ -n "$p" ]; then
    printf '%s\n%s\n%s\n' "$p" "${no_proxy:-${NO_PROXY:-}}" '环境变量'; return
  fi
  # 2. 桌面（GNOME）的网络设置里手动填的代理
  if command -v gsettings >/dev/null 2>&1 && [ "$(gsettings get org.gnome.system.proxy mode 2>/dev/null)" = "'manual'" ]; then
    local h port
    for kind in https http; do
      h=$(gsettings get "org.gnome.system.proxy.$kind" host 2>/dev/null | tr -d "'")
      port=$(gsettings get "org.gnome.system.proxy.$kind" port 2>/dev/null)
      if [ -n "$h" ] && [ "${port:-0}" != 0 ]; then
        p=http://$h:$port
        np=$(gsettings get org.gnome.system.proxy ignore-hosts 2>/dev/null | tr -d "[]' ")
        printf '%s\n%s\n%s\n' "$p" "$np" '桌面的网络设置'; return
      fi
    done
  fi
  # 3. /etc/environment
  if [ -r "$ETC_ENV" ]; then
    p=$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?(https_proxy|HTTPS_PROXY|http_proxy|HTTP_PROXY)=["'\'']?([^"'\'']*)["'\'']?[[:space:]]*$/\3/p' "$ETC_ENV" | head -1)
    np=$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?(no_proxy|NO_PROXY)=["'\'']?([^"'\'']*)["'\'']?[[:space:]]*$/\3/p' "$ETC_ENV" | head -1)
    if [ -n "$p" ]; then printf '%s\n%s\n%s\n' "$p" "$np" "$ETC_ENV"; return; fi
  fi
  # 4. apt 的设置
  if command -v apt-config >/dev/null 2>&1; then
    p=$(apt-config dump 2>/dev/null | sed -nE 's/^Acquire::(https?)::Proxy "([^"]+)";$/\2/p' | grep -iv '^DIRECT$' | head -1)
    if [ -n "$p" ]; then printf '%s\n%s\n%s\n' "$p" '' 'apt 的设置'; return; fi
  fi
  printf '\n\n\n'
}

# 系统用的 Ubuntu 软件源的地址（第一个）
apt_source() {
  local u
  u=$(cat /etc/apt/sources.list.d/*.sources 2>/dev/null | sed -nE 's/^URIs:[[:space:]]*([^[:space:]]+).*/\1/p' | head -1)
  [ -n "$u" ] || u=$(sed -nE 's/^deb[[:space:]]+(\[[^]]*\][[:space:]]+)?(https?:[^[:space:]]+).*/\2/p' /etc/apt/sources.list 2>/dev/null | head -1)
  printf '%s' "${u:-http://archive.ubuntu.com/ubuntu/}"
}

# reach 网址 代理 不走代理的地址：连得上返回 0。用 wget（系统自带）；不留 ~/.wget-hsts
reach() {
  local -a e=(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY -u no_proxy -u NO_PROXY)
  [ -n "$2" ] && e+=(http_proxy="$2" https_proxy="$2" HTTP_PROXY="$2" HTTPS_PROXY="$2")
  [ -n "$3" ] && e+=(no_proxy="$3" NO_PROXY="$3")
  "${e[@]}" wget --no-hsts -q --spider -T "${SOP_BOOTSTRAP_TIMEOUT:-10}" -t 2 "$1" >/dev/null 2>&1
}

# 工具包仓库的网址变成可以试连的（git 地址去掉 .git 后面的部分不影响能不能连上主机，取到主机名为止）
repo_probe_url() {
  case $1 in
    http://*|https://*) printf '%s' "$(printf '%s' "$1" | sed -E 's#^(https?://[^/]+).*#\1/#')" ;;
    *) printf '' ;;      # 本机目录（自测）不用试
  esac
}

# 试连一遍，打印结果；全连上返回 0。用全局的 PROXY、NOPROXY、TARGETS（名字|网址）
probe_all() {
  local ok=0 t name url
  for t in "${TARGETS[@]}"; do
    name=${t%%|*}; url=${t#*|}
    if reach "$url" "$PROXY" "$NOPROXY"; then say "  $name（$url）：连得上"
    else say "  $name（$url）：连不上"; ok=1; fi
  done
  return $ok
}

show_network() {
  if [ -n "$PROXY" ]; then
    say "  代理：$PROXY（$SOURCE）"
    [ -n "$NOPROXY" ] && say "  不走代理的地址：$NOPROXY"
  else
    say "  代理：不用代理（$SOURCE）"
  fi
}

# 网络这一步：探测、试连、摆给小白确认；不对或连不上才问代理。定下来的放在 PROXY、NOPROXY、SOURCE
network_step() {
  local det p np src ans tries=0 last_ok=
  if [ -n "${OPT_PROXY+x}" ]; then
    PROXY=$(normalize_proxy "$OPT_PROXY") || die "代理地址的写法不对：$OPT_PROXY（要像 http://127.0.0.1:7890）"
    NOPROXY=${no_proxy:-${NO_PROXY:-}}; SOURCE='命令行给的'; SOURCE_KIND=user
  else
    mapfile -t det < <(detect_proxy)
    p=${det[0]:-}; np=${det[1]:-}; src=${det[2]:-}
    if [ -n "$p" ]; then
      PROXY=$(normalize_proxy "$p") || { say "  读到的代理设置看不懂：$p（$src），当成没有"; PROXY=; }
      NOPROXY=$np; SOURCE="从$src读到的"
    else
      PROXY=; NOPROXY=${no_proxy:-${NO_PROXY:-}}; SOURCE='没找到代理设置'
    fi
    SOURCE_KIND=detected
  fi
  while :; do
    show_network
    if probe_all; then
      last_ok=1
      [ -n "$OPT_YES" ] && return 0
      ans=$(ask '这样对吗？对就直接回车；不对就输入 n 再回车：')
      case $ans in n|N|不对|不) ;; *) return 0 ;; esac
    else
      last_ok=
      [ -n "$OPT_YES" ] && die "连不上上面那几处。$NO_NET"
      say "有连不上的。"
    fi
    tries=$((tries + 1))
    [ $tries -gt 3 ] && die "试了几次还是连不上。$NO_NET"
    while :; do
      ans=$(ask '请输入代理地址（像 http://127.0.0.1:7890）。不知道就直接回车：')
      if p=$(normalize_proxy "$ans"); then break; fi
      say "  写法不对：$ans"
    done
    if [ -z "$p" ] && [ -z "$PROXY" ]; then
      [ -n "$last_ok" ] && { SOURCE='你确认的'; SOURCE_KIND=user; return 0; }   # 本来就不用代理、也连得上
      die "不用代理连不上。$NO_NET"
    fi
    PROXY=$p; SOURCE='你填的'; SOURCE_KIND=user
    [ -n "$PROXY" ] && [ -z "$NOPROXY" ] && NOPROXY='localhost,127.0.0.1,::1'
  done
}

# 离线包：不试连、不问代理，网络设置记成「不用代理」
offline_network() {
  PROXY=; NOPROXY=; SOURCE_KIND=detected
  say "用的是离线包：不试连网络、不问代理。网络设置先记成「不用代理」，电脑能上网以后可以改。"
}

# 之后所有下载（apt、git、uv）用定下来的代理
use_network() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
  if [ -n "$PROXY" ]; then export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY; fi
  if [ -n "$NOPROXY" ]; then export no_proxy=$NOPROXY NO_PROXY=$NOPROXY; fi
}

# ---------- 各步 ----------
check_system() {
  [ "$(id -u)" != 0 ] || die "请用自己平常登录的账号执行，不要用管理员账号（sudo 或 root）：工具包要装进你自己的主目录"
  local id= ver=
  [ -r "$OS_RELEASE" ] && { id=$(. "$OS_RELEASE"; echo "${ID:-}"); ver=$(. "$OS_RELEASE"; echo "${VERSION_ID:-}"); }
  [ "$id" = ubuntu ] && [ "$ver" = 26.04 ] || die "工具包只支持 Ubuntu 26.04（这台电脑是 ${id:-看不出来} ${ver}）"
  case $(uname -m) in x86_64|aarch64) ;; *) die "不支持这种处理器：$(uname -m)" ;; esac
  command -v python3 >/dev/null 2>&1 || die "系统里没有 python3（Ubuntu 26.04 本来自带）"
}

install_apt() {
  local need=() pkg
  for pkg in git curl; do command -v "$pkg" >/dev/null 2>&1 || need+=("$pkg"); done
  if [ ${#need[@]} -eq 0 ]; then say "git、curl 都有了，跳过"; return 0; fi
  say "接下来用系统的软件包装 ${need[*]}（git 管代码和进度，curl 下载工具），要管理员权限。"
  say "系统会问这台电脑的登录密码（就是开机登录用的那个），输入时屏幕上什么都不显示，输完按回车。"
  [ -n "${OFFLINE:-}" ] && { install_apt_offline "${need[@]}"; return; }
  local -a e=()
  [ -n "$PROXY" ] && e+=(http_proxy="$PROXY" https_proxy="$PROXY")
  [ -n "$NOPROXY" ] && e+=(no_proxy="$NOPROXY")
  [ -n "${SOP_APT_WAIT:-}" ] && e+=(SOP_APT_WAIT="$SOP_APT_WAIT")
  local rc=0
  sudo -p "$SUDO_PROMPT" env "${e[@]}" DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 sh -c \
    "$SOP_APT_SH"'
sop_apt update -qq && sop_apt install -y -qq --no-install-recommends "$@"' \
    sop-apt "${need[@]}" </dev/null || rc=$?
  case $rc in
    0) ;;
    75) die "${need[*]} 没装上：$APT_LOCKED" ;;
    100) die "${need[*]} 没装上：系统装软件的程序报错了（多半是连不上软件源，看上面的报错）" ;;
    *) die "${need[*]} 没装上（密码不对，或者这个账号不能用 sudo；退出码 $rc）" ;;
  esac
  say "${need[*]} 装好了"
}

# 离线包：只用离线包里带的软件包（debs/ 下，打包时带了 Packages 索引）。apt 的索引和缓存放在一个临时目录里，
# 不动系统的软件源设置和索引；电脑上已经有的、比离线包里新的软件包照用，不降级。临时目录用完由同一个 sudo 删掉
install_apt_offline() {
  local debs=$OFFLINE/debs
  [ -f "$debs/Packages" ] || die "离线包里没有系统软件包（$debs）：离线包不完整，重新拷一次"
  local -a e=()
  [ -n "${SOP_APT_WAIT:-}" ] && e+=(SOP_APT_WAIT="$SOP_APT_WAIT")
  local rc=0
  sudo -p "$SUDO_PROMPT" env "${e[@]}" DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 sh -c "$SOP_APT_SH"'
    debs=$1; shift
    w=$(mktemp -d /tmp/sop-offline-apt.XXXXXX) || exit 1
    chmod 755 "$w"      # 系统的下载程序（_apt 账号）要进得去，不然 apt 报一串英文警告
    mkdir -p "$w/lists/partial" "$w/cache/archives/partial" "$w/parts"
    printf "deb [trusted=yes] file:%s ./\n" "$debs" > "$w/sources.list"
    o="-o Dir::Etc::SourceList=$w/sources.list -o Dir::Etc::SourceParts=$w/parts"
    o="$o -o Dir::State::Lists=$w/lists -o Dir::Cache=$w/cache"
    # 索引和下载的锁在临时目录里，没人抢；dpkg 的锁和系统共用，系统正在自己更新时 sop_apt 等它
    sop_apt $o update -qq && sop_apt $o install -y -qq --no-install-recommends "$@"
    rc=$?
    rm -rf "$w"
    exit $rc' sop-apt "$debs" "$@" </dev/null || rc=$?
  case $rc in
    0) ;;
    75) die "$* 没装上：$APT_LOCKED" ;;
    *) die "$* 没装上（密码不对、这个账号不能用 sudo，或者离线包里的软件包和这台电脑的系统对不上；退出码 $rc）" ;;
  esac
  say "$* 装好了（用的是离线包里的软件包）"
}

# 取工具包：Git 取最新的 main，放到 versions/<提交编号>；已经有这个版本就跳过。结果放在 VERSION
fetch_toolkit() {
  local vers=$SOP/versions tmp
  mkdir -p "$vers" || die "建不了 $vers"
  tmp=$vers/.bootstrap.$$
  rm -rf "$tmp"
  local -a g=(git -c core.hooksPath=/dev/null -c init.defaultBranch=main -c advice.detachedHead=false)
  # 只取最新的一个提交；不支持的（简单的网页服务）就整个取
  "${g[@]}" init -q "$tmp" || die "建不了 $tmp"
  "${g[@]}" -C "$tmp" fetch -q --depth 1 "$REPO" refs/heads/main 2>/dev/null \
    || "${g[@]}" -C "$tmp" fetch -q "$REPO" refs/heads/main \
    || { rm -rf "$tmp"; die "取不到工具包（$REPO）。看看网络和代理"; }
  VERSION=$("${g[@]}" -C "$tmp" rev-parse FETCH_HEAD) || { rm -rf "$tmp"; die "取到的工具包看不懂"; }
  if [ -d "$vers/$VERSION" ]; then
    rm -rf "$tmp"; say "工具包 ${VERSION:0:8} 已经有了，跳过"; return 0
  fi
  "${g[@]}" -C "$tmp" checkout -q FETCH_HEAD || { rm -rf "$tmp"; die "工具包取出来时出错"; }
  [ -f "$tmp/kernel/launcher.py" ] && [ -f "$tmp/machine/bootstrap.py" ] || { rm -rf "$tmp"; die "取到的不像 SOP 工具包（$REPO）"; }
  mv "$tmp" "$vers/$VERSION" || die "放不进 $vers/$VERSION"
  say "工具包 ${VERSION:0:8} 取好了，在 $vers/$VERSION"
}

install_uv() {
  local uv=$TOOLS/uv/bin/uv v
  if v=$("$uv" --version 2>/dev/null); then say "uv 已经有了（$v），跳过"; return 0; fi
  local -a e=(env SOP_TOOLS="$TOOLS")
  if [ -n "$OFFLINE" ]; then
    local arc; arc=$(ls "$OFFLINE"/uv/uv-*.tar.gz 2>/dev/null | head -1)
    [ -n "$arc" ] || die "离线包里没有 uv：离线包不完整，重新拷一次"
    e+=(SOP_UV_ARCHIVE="$arc")
  fi
  "${e[@]}" bash "$SOP/versions/$VERSION/machine/install/uv.sh" </dev/null >"$LOG" 2>&1 \
    || { tail -5 "$LOG" >&2; die "uv 没装上（完整输出在 $LOG）"; }
  say "uv 装好了（$("$uv" --version)），在 $TOOLS/uv"
}

# 工具包里的小帮手（machine/bootstrap.py），用刚装的 uv 和系统自带的 Python 跑；uv 的缓存放 ~/tools/cache/uv
helper() {
  env UV_CACHE_DIR="$TOOLS/cache/uv" UV_PYTHON_INSTALL_DIR="$TOOLS/uv/python" ${OFFLINE:+UV_OFFLINE=1} \
    "$TOOLS/uv/bin/uv" run -q --no-project --python 3.14 python -I "$SOP/versions/$VERSION/machine/bootstrap.py" "$@" </dev/null
}

main() {
  OPT_YES=; OFFLINE=; REPO=${SOP_TOOLKIT_REPO:-$DEFAULT_REPO}
  while [ $# -gt 0 ]; do
    case $1 in
      --yes) OPT_YES=1; shift ;;
      --repo) REPO=${2:?--repo 后面要给地址}; shift 2 ;;
      --proxy) OPT_PROXY=${2-}; shift 2 ;;
      --offline) OFFLINE=${2:?--offline 后面要给离线包解开的目录}; shift 2 ;;
      *) die "不认识的选项：$1" ;;
    esac
  done
  if [ -n "$OFFLINE" ]; then
    OFFLINE=$(cd "$OFFLINE" 2>/dev/null && pwd) || die "没有离线包的目录：$OFFLINE"
    [ -f "$OFFLINE/sop.bundle" ] && [ -f "$OFFLINE/VERSION" ] || die "离线包不完整（$OFFLINE）：重新拷一次"
    REPO=$OFFLINE/sop.bundle
  fi
  [ -n "$REPO" ] || die "没有工具包仓库的地址（用 --repo 给）"
  TOOLS=$HOME/tools SOP=$HOME/tools/sop
  LOG=$(mktemp "${TMPDIR:-/tmp}/sop-bootstrap.XXXXXX.log")
  cd "$HOME" || die "进不了主目录"

  say "SOP 工具包第零步：准备网络、装 git 和 curl、取工具包、装 uv。中途断了可以重新执行，做过的会跳过。"
  [ -n "$OFFLINE" ] && say "（用的是离线包，不上网：工具包提交 $(cut -c1-8 "$OFFLINE/VERSION")）"
  step "1/7 看系统"
  check_system
  say "Ubuntu 26.04，账号 $(id -un)，主目录 $HOME"

  step "2/7 网络"
  if [ -n "$OFFLINE" ]; then
    offline_network
  else
    TARGETS=("GitHub|$GITHUB_URL" "Ubuntu 软件源|$(apt_source)")
    local rp; rp=$(repo_probe_url "$REPO")
    [ -n "$rp" ] && [ "$rp" != "$GITHUB_URL" ] && TARGETS+=("工具包仓库|$rp")
    network_step
  fi
  use_network

  step "3/7 git、curl"
  install_apt

  step "4/7 取工具包"
  fetch_toolkit
  if [ -n "$OFFLINE" ] && [ "$VERSION" != "$(cat "$OFFLINE/VERSION")" ]; then die "离线包里的工具包和它写的提交编号对不上：离线包坏了，重新拷一次"; fi

  step "5/7 装 uv"
  install_uv

  step "6/7 主目录在哪个分区（只报告，不用做什么）"
  helper layout || say "（查分区出错了，不影响接着装；之后 sop machine doctor 会再查一次）"

  step "7/7 记下网络设置、装好 sop 命令"
  local -a a=(finish "$VERSION" --source "$SOURCE_KIND")
  [ -n "$PROXY" ] && a+=(--proxy "$PROXY")
  [ -n "$NOPROXY" ] && a+=(--no-proxy "$NOPROXY")
  helper "${a[@]}" || die "写网络设置、启动器时出错"
  "$SOP/sop" machine tools </dev/null >"$LOG" 2>&1 || { tail -5 "$LOG" >&2; die "sop 运行不起来（完整输出在 $LOG）"; }
  rm -f "$LOG"
  say "sop 能运行了"

  say ""
  say "第零步做完了。下一步："
  say "  关掉这个终端窗口，重新打开一个，执行：  sop machine setup"
  say "  （想在这个窗口里接着做，就执行：  ~/tools/sop/sop machine setup）"
}

if [ -z "${BASH_SOURCE[0]:-}" ] || [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
