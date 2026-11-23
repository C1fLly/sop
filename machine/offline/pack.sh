#!/bin/bash
# 打离线包（设计书 4.2 第 3 条；任务 3-14）。给完全连不上外网的电脑用：在另一台能上网的电脑上下载、U 盘拷过去。
#
# 由做工具包的人在一台能上网的 Ubuntu 26.04 上运行（和要装的电脑同一种处理器），不用管理员密码，不改这台电脑：
#   machine/offline/pack.sh --repo <工具包仓库> [--out <文件>]
# 打出来是一个文件 sop-offline-<提交编号前 8 位>-<处理器>.sh（约 50 MB），小白在断网的电脑上执行 bash <这个文件>。
# 里面有：
#   bootstrap.sh       那个提交的第零步
#   debs/              git、curl 和它们要的全部系统软件包（按「什么都没装」算的，桌面版缺什么都补得上），带软件包索引
#   uv/                uv 的官方压缩包（下载时按官方给的校验值核对过）
#   sop.bundle         工具包仓库 main 那一个提交连同历史（Git 打包文件，第零步照常用 git 从它取）
#   VERSION、ARCH      提交编号、处理器
# 文件开头是 machine/offline/header.sh（先核对校验值、再解开、再运行第零步），后面跟着上面这些打成的 tar。
#
# 下载的东西都放在 /tmp 下的临时目录，做完删掉。apt 的索引和下载缓存也放在那里（不用系统的、不上锁、不用 sudo）。
# 选项：--repo（或 SOP_TOOLKIT_REPO）工具包仓库；--out 打到哪；SOP_UV_VERSION 指定 uv 版本（不给就是最新的）。
#
# 发版（3-51）：离线包挂在 GitHub 上工具包仓库的 Releases（https://github.com/C1fLly/sop/releases/latest，
# bootstrap.sh 连不上网时指向它），不进 Git 仓库。步骤见 docs/第三段/3-51-离线包挂到Releases.md「以后发版」：
#   tests/vm/offline.sh --repo https://github.com/C1fLly/sop.git --save <本机目录>   在虚拟机里打、验、另存一份
#   查离线包里没有本机私人信息 → gh release create offline-<提交前 8 位> --target <提交> … →
#   tests/vm/offline.sh --url <Releases 上的下载地址> --sha256 <校验值>                验下下来的那份
set -uo pipefail

PKGS=(git curl)
die() { printf '\n没打成：%s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

# uv 的压缩包名里的处理器写法
uv_arch() {
  case $1 in amd64) echo x86_64 ;; arm64) echo aarch64 ;; *) return 1 ;; esac
}

# 下载（系统自带的 wget；不留 ~/.wget-hsts）
get() {
  local i
  for i in 1 2 3; do
    wget --no-hsts -nv -T 30 -t 5 --retry-connrefused --waitretry=3 -O "$2" "$1" 2>"$WORK/wget.log" && return 0
    sleep 3
  done
  tail -3 "$WORK/wget.log" >&2
  die "下载不下来：$1（看看网络和代理）"
}

# 1. 工具包：克隆 main，打成 Git 打包文件；结果 VERSION
pack_toolkit() {
  local repo=$1 out=$2 src=$WORK/src.git
  git clone -q --bare --single-branch --branch main "$repo" "$src" 2>/dev/null || die "取不到工具包仓库的 main：$repo"
  VERSION=$(git --git-dir "$src" rev-parse main) || die "工具包仓库看不懂：$repo"
  git --git-dir "$src" cat-file -e main:kernel/launcher.py 2>/dev/null && git --git-dir "$src" cat-file -e main:machine/offline/header.sh 2>/dev/null \
    || die "$repo 的 main 不像 SOP 工具包（或者太旧，还没有离线包）"
  git --git-dir "$src" bundle create "$out/sop.bundle" main 2>/dev/null || die "工具包打不成 Git 打包文件"
  git --git-dir "$src" show main:bootstrap.sh > "$out/bootstrap.sh" || die "取不到那个提交的 bootstrap.sh"
  git --git-dir "$src" show main:machine/offline/header.sh > "$WORK/header.sh" || die "取不到那个提交的 header.sh"
  printf '%s\n' "$VERSION" > "$out/VERSION"
  say "工具包：提交 ${VERSION:0:8}（$(du -h "$out/sop.bundle" | cut -f1)）"
}

# 2. 系统软件包：用这台电脑的软件源设置，索引和缓存放临时目录；装的状态当成「什么都没装」，这样要的全都下下来。
#    apt 自己的设置片段（/etc/apt/apt.conf.d）不读：那里有取完索引后自动跑的钩子（会去更新系统的数据），
#    这里要的只是下载。代理照环境变量走
pack_debs() {
  local out=$1 w=$WORK/apt
  mkdir -p "$w/lists/partial" "$w/cache/archives/partial" "$w/parts" "$out"
  : > "$w/status"
  printf 'Dir::Etc::Parts "%s";\n' "$w/parts" > "$w/apt.conf"
  export APT_CONFIG=$w/apt.conf
  local -a o=(-o Debug::NoLocking=1 -o Dir::State="$w" -o Dir::State::Lists="$w/lists" -o Dir::State::status="$w/status"
              -o Dir::Cache="$w/cache" -o APT::Install-Recommends=false -o APT::Architecture="$ARCH")
  say "系统软件包：先取软件源的索引（几十 MB，几分钟）……"
  apt-get -q "${o[@]}" update >"$WORK/apt.log" 2>&1 || { tail -5 "$WORK/apt.log" >&2; die "取不到软件源的索引"; }
  apt-get -q "${o[@]}" --download-only -y install "${PKGS[@]}" >>"$WORK/apt.log" 2>&1 \
    || { tail -5 "$WORK/apt.log" >&2; die "${PKGS[*]} 的软件包下载不下来"; }
  mv "$w/cache/archives/"*.deb "$out/" || die "没下到软件包"
  write_index "$out"
  say "系统软件包：$(ls "$out"/*.deb | wc -l) 个（$(du -sh "$out" | cut -f1)）"
}

# 软件包索引（Packages、Release），只用 dpkg-deb（系统自带），不用另装 dpkg-dev
write_index() {
  local d=$1 f
  : > "$d/Packages"
  for f in "$d"/*.deb; do
    dpkg-deb -f "$f" >> "$d/Packages" || die "软件包坏了：$f"
    printf 'Filename: ./%s\nSize: %s\nSHA256: %s\n\n' "$(basename "$f")" "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -d' ' -f1)" >> "$d/Packages"
  done
  printf 'Origin: sop-offline\nLabel: sop-offline\nDate: %s\nArchitectures: %s all\nSHA256:\n %s %s Packages\n' \
    "$(LC_ALL=C date -Ru)" "$ARCH" "$(sha256sum "$d/Packages" | cut -d' ' -f1)" "$(stat -c %s "$d/Packages")" > "$d/Release"
}

# 3. uv：官方压缩包，按官方给的校验值核对
pack_uv() {
  local out=$1 a v name
  a=$(uv_arch "$ARCH") || die "uv 没有这种处理器的：$ARCH"
  v=${SOP_UV_VERSION:-}
  if [ -z "$v" ]; then
    v=$(wget --no-hsts -q -T 30 -t 5 -S --spider --max-redirect=5 https://github.com/astral-sh/uv/releases/latest 2>&1 \
        | sed -nE 's#^ *[Ll]ocation: .*/releases/tag/([^ /]+).*#\1#p' | tail -1 | tr -d '\r')
    [[ $v =~ ^[0-9]+(\.[0-9]+)+$ ]] || die "查不到 uv 的最新版本（看看网络和代理）"
  fi
  name=uv-$a-unknown-linux-gnu.tar.gz
  mkdir -p "$out"
  get "https://github.com/astral-sh/uv/releases/download/$v/$name" "$out/$name"
  get "https://github.com/astral-sh/uv/releases/download/$v/$name.sha256" "$WORK/uv.sha256"
  [ "$(sha256sum "$out/$name" | cut -d' ' -f1)" = "$(cut -d' ' -f1 "$WORK/uv.sha256")" ] || die "uv 的压缩包和官方的校验值对不上"
  say "uv：$v（$(du -h "$out/$name" | cut -f1)）"
}

# 4. 拼成一个文件：header.sh（填上提交编号、处理器、校验值）+ tar
assemble() {    # 内容目录 header 输出文件
  local dir=$1 header=$2 out=$3 tarf=$WORK/payload.tar sha
  tar -cf "$tarf" -C "$dir" . || die "打不成 tar"
  sha=$(sha256sum "$tarf" | cut -d' ' -f1)
  mkdir -p "$(dirname "$out")" || die "建不了 $(dirname "$out")"
  sed -e "s/@VERSION@/$(cat "$dir/VERSION")/" -e "s/@ARCH@/$(cat "$dir/ARCH")/" -e "s/@PAYLOAD_SHA256@/$sha/" "$header" > "$out.part" \
    && cat "$tarf" >> "$out.part" && chmod 644 "$out.part" && mv "$out.part" "$out" || { rm -f "$out.part"; die "写不了 $out"; }
}

main() {
  local repo=${SOP_TOOLKIT_REPO:-} out=
  while [ $# -gt 0 ]; do
    case $1 in
      --repo) repo=${2:?--repo 后面要给地址}; shift 2 ;;
      --out) out=${2:?--out 后面要给文件}; shift 2 ;;
      *) die "不认识的选项：$1" ;;
    esac
  done
  [ -n "$repo" ] || die "要给工具包仓库（--repo）"
  local id= ver=
  [ -r /etc/os-release ] && { id=$(. /etc/os-release; echo "${ID:-}"); ver=$(. /etc/os-release; echo "${VERSION_ID:-}"); }
  [ "$id" = ubuntu ] && [ "$ver" = 26.04 ] || die "要在 Ubuntu 26.04 上打（软件包按这台电脑的软件源取）；这台是 ${id:-看不出来} $ver"
  ARCH=$(dpkg --print-architecture) || die "看不出处理器"
  for c in git wget apt-get dpkg-deb sha256sum tar; do command -v $c >/dev/null || die "缺 $c"; done
  WORK=$(mktemp -d /tmp/sop-pack.XXXXXX) || die "在 /tmp 下建不了临时目录"
  trap 'rm -rf "$WORK"' EXIT
  local p=$WORK/payload
  mkdir -p "$p"
  printf '%s\n' "$ARCH" > "$p/ARCH"
  pack_toolkit "$repo" "$p"
  pack_debs "$p/debs"
  pack_uv "$p/uv"
  out=${out:-$PWD/sop-offline-${VERSION:0:8}-$ARCH.sh}
  assemble "$p" "$WORK/header.sh" "$out"
  say ""
  say "离线包打好了：$out（$(du -h "$out" | cut -f1)）"
  say "拷到断网的电脑上，在终端里执行：bash $(basename "$out")"
}

if [ -z "${BASH_SOURCE[0]:-}" ] || [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
