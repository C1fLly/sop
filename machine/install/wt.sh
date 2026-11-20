#!/bin/bash
# M5：装 wt 到 ~/tools/wt（设计书 4.3、4.5；3-22）。
# wt 的仓库是私有的（GitHub 上不登录看是 404），所以排在登录 GitHub（M3）之后，用 Git 经 SSH 克隆：
# M3 的出口检查就是 SSH 连得上 GitHub。和 wt 自己说明书的装法一样，是一份 Git 克隆，切到主线上最新的正式版本标签
# （不用主线上还没发布的改动）；以后升级、回退都是在这份克隆里换标签。
#   SOP_WT_REPO     从哪里克隆（默认 git@github.com:C1fLly/wt.git；自测、离线时给本机的仓库）
#   SOP_WT_VERSION  装哪个版本（如 1.3.1 或 v1.3.1），不给就装主线上最新的版本标签
# 不做 wt 说明书里的另外两步：wt install（往 ~/.local/bin 放链接、改终端启动文件）、wt doctor --fix（改全局 Git 配置）。
# 工具包调 wt 用的是规定位置的完整路径（kernel/wtx.py），用不着这两样。
# 规定位置已经有东西（哪怕是坏的、旧的）就不动它、停下明说：那可能是用户自己的克隆，里面有他的改动。
. "$(dirname "$0")/lib.sh"

repo=${SOP_WT_REPO:-git@github.com:C1fLly/wt.git}
dest=$SOP_TOOLS/wt
if [ -e "$dest" ] || [ -L "$dest" ]; then
  die "规定位置 $dest 已经有东西了（版本不对，或者不能运行）。工具包不动它：那里面可能有你自己的改动。
要换成工具包装的那一份：先把它改个名字挪开（例如 mv $dest $dest.old），再执行一次。"
fi

# 只用自己给的 Git 设置：外面带进来的 GIT_ 变量（GIT_DIR 等）去掉；SSH 不停下来问（没见过的主机、密钥的口令都不问，
# 直接失败），钩子关掉（主目录的 Git 设置里可能指了钩子目录），新仓库不从主目录设置的模板目录复制钩子。
for v in $(compgen -e); do case $v in GIT_*) unset "$v" ;; esac; done
export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=20' GIT_TERMINAL_PROMPT=0 LC_ALL=C
g() { git -c core.hooksPath=/dev/null -c advice.detachedHead=false "$@"; }

# 克隆到规定位置旁边，弄好了再换名顶上去：中途断了，规定位置还是空的
new=$SOP_TOOLS/.wt.new.$$
trap 'rm -rf "$WORK" "$new"' EXIT
rm -rf "$new"
g clone --quiet --no-local --no-checkout --template= "$repo" "$new" 2>"$WORK/err" || {
  sed 's/^/  /' "$WORK/err" >&2
  case $repo in
    git@*|ssh://*) die "从 $repo 取不下 wt。wt 的仓库是私有的，要先登录 GitHub（M3），这台电脑的 SSH 密钥能连上 GitHub 才取得到" ;;
    *) die "从 $repo 取不下 wt" ;;
  esac
}

if [ -n "${SOP_WT_VERSION:-}" ]; then
  tag=v${SOP_WT_VERSION#v}
else
  tag=$(g -C "$new" describe --tags --abbrev=0 --match 'v[0-9]*' origin/HEAD 2>/dev/null) \
    || die "$repo 的主线上没有版本标签"
fi
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "wt 的版本号看不懂：$tag"
g -C "$new" rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null || die "$repo 里没有 $tag 这个版本"
g -C "$new" checkout --quiet --detach "refs/tags/$tag" || die "切到 $tag 没成"
[ -f "$new/wt" ] && [ -x "$new/wt" ] || die "$tag 里没有能执行的 wt"
got=$(bash "$new/wt" --version 2>&1) || die "$tag 的 wt 运行不了：$got"
[ "$got" = "wt ${tag#v}" ] || die "$tag 的 wt 自己说的版本对不上：$got"

mv -T "$new" "$dest"
echo "wt ${tag#v} 装好了，在 $dest（$(g -C "$dest" rev-parse --short HEAD)，从 $repo 取的）"
