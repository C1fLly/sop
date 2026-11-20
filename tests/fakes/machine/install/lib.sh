# 假的安装脚本共用的（流程沙箱 3-12 用）。不连网、不要管理员密码，只往 $SOP_TOOLS 下放一个假程序。
# 剧本目录 $FAKE_SETUP_DIR：
#   installs.log    每跑一次安装脚本记一行名字
#   hang-<名字>     有这个文件：删掉它、留下 hanging-<名字>、睡两分钟（测试趁这时强制结束整组进程，模仿中途断了；只一次）
#   fail-<名字>     有这个文件：装不上，退出码 1
set -eu
fake_install() {   # 名字 版本 放到哪 [照抄哪个文件]
  name=$1 ver=$2 dest=$3 src=${4:-}
  d=${FAKE_SETUP_DIR:?没有剧本目录}
  [ -n "${SOP_TOOLS:-}" ] || { echo "没给工具目录 SOP_TOOLS" >&2; exit 2; }
  echo "$name" >> "$d/installs.log"
  echo "假的安装脚本：装 $name $ver"
  if [ -e "$d/hang-$name" ]; then
    rm -f "$d/hang-$name"; : > "$d/hanging-$name"; sleep 120
  fi
  if [ -e "$d/fail-$name" ]; then
    echo "假的安装脚本：$name 装不上（剧本让它失败）" >&2; exit 1
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -n "$src" ]; then
    cp "$src" "$dest.new"
  else
    printf '#!/bin/sh\necho "%s %s (假的)"\n' "$name" "$ver" > "$dest.new"
  fi
  chmod +x "$dest.new"
  mv "$dest.new" "$dest"
}
HERE=$(cd "$(dirname "$0")" && pwd)
