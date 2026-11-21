#!/bin/bash
# 工具包仓库在 GitHub 上跑检查之前，把跑检查的那台临时电脑准备好（3-40；设计书 16.4）。
# 只给 .github/workflows/check.yml 用，只在 GitHub 的临时电脑上跑：要用 sudo 装软件包、改内核开关、往 ~/.ssh 放钥匙。
# 本机绝对不要跑它；不在 GitHub Actions 里（没有 GITHUB_ACTIONS=true 和 RUNNER_TEMP）就直接停下。
#
# 用法：tests/ci/prepare.sh [--light]
#   不带参数：装齐单元测试、流程沙箱、总检查要的东西：bubblewrap、uv、wt，核对内核开关。
#   --light ：只装 uv（总检查、文档检查只要 Python、git 和 uv）。
#
# 为什么要这几样（和本机一样，测试才不会悄悄跳过）：
#   - Python 3.14：pyproject.toml 要求 >=3.14 且不许 uv 另外下载；Ubuntu 26.04 的临时电脑自带 3.14（这里核对）。
#   - uv：用工具包自己的安装脚本 machine/install/uv.sh 装到 ~/tools/uv（和小白电脑上 M2 一样的装法），版本钉死。
#   - bubblewrap：单元测试真起受限环境。Ubuntu 26.04 默认限制普通用户建隔离空间，靠 AppArmor 里 bwrap 那条规则放行；
#     这里只核对能用，不能用就停下说明，不去关系统的限制（关了就和小白的电脑不一样了）。
#   - 往终端塞按键（legacy_tiocsti）：内核没禁用时，对话那几项单元测试会跳过；这里把它设成禁用（和 Ubuntu 26.04 默认一样，
#     是收紧不是放宽）。
#   - wt：流程沙箱经 kernel/wtx.py 真调 wt；几项单元测试没有 wt 会跳过；test_machine_wt.py 要 ~/tools/wt 是一份 Git 克隆。
#     wt 的仓库 C1fLly/wt 是私有的，要一把只能读这个仓库的钥匙（仓库机密设置里的 WT_DEPLOY_KEY，由 3-41 和用户定），
#     用工具包自己的 machine/install/wt.sh 经 SSH 克隆到 ~/tools/wt、切到钉死的版本，装完马上删掉钥匙。
#     没给钥匙就停下（不让流程沙箱因为没有 wt 而失败得莫名其妙，也不让几项测试悄悄跳过）。
#
# 钉死的版本（换版本时改这里，改完在 GitHub 上跑一遍）：
#   uv 0.13.7：和写这个文件时本机跑自测的 uv 同一个版本（3-40）。
#   wt 1.3.1 ：和本机 ~/tools/wt 同一个版本（提交 9502f8c）。
set -euo pipefail

UV_VERSION=0.13.7
WT_VERSION=1.3.1

die() { echo "准备跑检查的电脑没成：$*" >&2; exit 1; }

[ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${RUNNER_TEMP:-}" ] && [ -n "${GITHUB_PATH:-}" ] \
  || die "这个脚本只在 GitHub Actions 的临时电脑上跑（要用 sudo、改内核开关、往 ~/.ssh 放钥匙），本机不要跑"

repo=$(cd "$(dirname "$0")/../.." && pwd)
light=0
case ${1:-} in
  '') ;;
  --light) light=1 ;;
  *) die "用法：tests/ci/prepare.sh [--light]" ;;
esac

# Python
py=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])') || die "没有 python3"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' \
  || die "python3 是 $py，工具包要 3.14 以上（pyproject.toml）。临时电脑的系统换了？看看 runs-on"
echo "python3 $py"

# uv：工具包自己的安装脚本，装到 ~/tools/uv/bin
SOP_TOOLS=$HOME/tools SOP_UV_VERSION=$UV_VERSION bash "$repo/machine/install/uv.sh"
got=$("$HOME/tools/uv/bin/uv" --version)
[ "${got#uv }" != "$got" ] && [ "$(echo "$got" | awk '{print $2}')" = "$UV_VERSION" ] || die "uv 版本不对：$got（要 $UV_VERSION）"
echo "$HOME/tools/uv/bin" >> "$GITHUB_PATH"

[ "$light" = 1 ] && exit 0

# bubblewrap
sudo apt-get -o DPkg::Lock::Timeout=600 -qq update
sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -qq install -y bubblewrap
bwrap --version
bwrap --unshare-all --die-with-parent --ro-bind / / --proc /proc --dev /dev true \
  || die "bubblewrap 起不来受限环境。多半是系统限制普通用户建隔离空间、又没有放行 bwrap 的那条 AppArmor 规则：
$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null | sed 's/^/  kernel.apparmor_restrict_unprivileged_userns = /')
  这里不去关系统的限制（关了就和小白的电脑不一样）；看看临时电脑的系统是不是换了"

# 往终端塞按键：禁用（和 Ubuntu 26.04 默认一样）
t=$(cat /proc/sys/dev/tty/legacy_tiocsti 2>/dev/null || echo 没有这个开关)
if [ "$t" != 0 ]; then
  echo "内核的「往终端塞按键」开关是 $t，设成禁用（0）"
  sudo sysctl -q -w dev.tty.legacy_tiocsti=0 || die "设不了 dev.tty.legacy_tiocsti=0"
  [ "$(cat /proc/sys/dev/tty/legacy_tiocsti)" = 0 ] || die "dev.tty.legacy_tiocsti 设了还不是 0"
fi
echo "往终端塞按键：已禁用"

# wt：只读钥匙临时放进 ~/.ssh，装完就删
[ -n "${WT_DEPLOY_KEY:-}" ] || die "没给读 wt 仓库的钥匙（仓库机密设置里的 WT_DEPLOY_KEY）。
  流程沙箱要真调 wt，wt 的仓库 C1fLly/wt 是私有的。要在 C1fLly/wt 上加一把只读的部署钥匙，私钥放进本仓库的机密设置（3-41）"
mkdir -p -m 700 "$HOME/.ssh"
key=$HOME/.ssh/id_ed25519
[ ! -e "$key" ] || die "$key 已经有了，不盖掉它"
trap 'rm -f "$key"' EXIT
( umask 077; printf '%s\n' "$WT_DEPLOY_KEY" > "$key" )
# GitHub 的主机钥匙从它的接口（HTTPS）取，不用 ssh-keyscan 盲信第一次连上的
curl -fsSL --retry 5 --retry-all-errors https://api.github.com/meta \
  | python3 -c 'import json, sys; [print("github.com", k) for k in json.load(sys.stdin)["ssh_keys"]]' >> "$HOME/.ssh/known_hosts" \
  || die "取不到 GitHub 的主机钥匙"
SOP_TOOLS=$HOME/tools SOP_WT_VERSION=$WT_VERSION SOP_WT_REPO=${SOP_CI_WT_REPO:-git@github.com:C1fLly/wt.git} \
  bash "$repo/machine/install/wt.sh"
rm -f "$key"
trap - EXIT
[ "$("$HOME/tools/wt/wt" --version)" = "wt $WT_VERSION" ] || die "wt 版本不对"
echo "$HOME/tools/wt" >> "$GITHUB_PATH"
echo "准备好了"
