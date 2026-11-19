# 安装脚本共用的几样（3-08）。由 machine/install.py 运行各脚本，环境里给好：
#   SOP_TOOLS  工具目录（平常是 ~/tools），各工具装在它下面的规定位置（设计书 4.3）
#   代理（http_proxy 等，按 ~/tools/sop/config/network.json）、各工具的缓存位置（machine/shellenv.py）
# 规矩：只往 $SOP_TOOLS 下装，不改终端启动文件（那一段由 shellenv.py 写）；别处另有一份旧的，不碰它。
# 每个脚本可以重复跑：已经装过就换成新下的那一份。下载的东西先放临时目录，下载不全不会装一半。
set -eo pipefail

die() { echo "安装失败：$*" >&2; exit 1; }

[ -n "${SOP_TOOLS:-}" ] || die "没给工具目录（SOP_TOOLS）"
case $SOP_TOOLS in /*) ;; *) die "工具目录要是绝对路径：$SOP_TOOLS" ;; esac
mkdir -p "$SOP_TOOLS"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/sop-install.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# fetch 网址 存到哪。连接被断开这类一时的错也重试（3-08 在虚拟机里经代理碰到过一次）
fetch() {
  curl -fsSL -S --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -o "$2" "$1" \
    || die "下载不下来：$1（看看网络和代理设置：~/tools/sop/config/network.json）"
}

# latest_tag 所有者/仓库：GitHub 上最新发布的标签。跟着网页的跳转取，不用 GitHub 的接口（不怕次数限制）
latest_tag() {
  local url tag
  url=$(curl -fsSIL --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -o /dev/null -w '%{url_effective}' "https://github.com/$1/releases/latest") \
    || die "查不到 $1 的最新版本（看看网络和代理设置）"
  tag=${url##*/}
  [[ $tag =~ ^v?[0-9]+(\.[0-9]+)+$ ]] || die "$1 的最新版本号看不懂：$tag"
  echo "$tag"
}

# 载入规定位置的 nvm（不管环境里原来的 NVM_DIR 指向哪）。
# nvm 自己的函数里很多地方故意返回非零，载入之后关掉「出错就退出」，各步自己判断成没成
use_nvm() {
  export NVM_DIR="$SOP_TOOLS/nvm"
  [ -s "$NVM_DIR/nvm.sh" ] || die "规定位置还没有 nvm（$NVM_DIR），要先装 nvm"
  set +e
  . "$NVM_DIR/nvm.sh" --no-use || die "规定位置的 nvm 载入出错"
}
