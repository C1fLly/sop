#!/bin/bash
# 3-13：在一台全新的虚拟机里验第零步 bootstrap.sh（设计书 4.2、4.5 的 M0）。
# 用法：tests/vm/m0.sh <虚拟机名字> [给 m0-guest.sh 的选项…]
#   虚拟机要先 vm.sh new <名字> 建好。工具包的 GitHub 仓库还没建（3-41），所以在本机临时起一个小网页服务代替它：
#   把工作区现在的文件做成一个只有一个提交的 Git 仓库，连同 bootstrap.sh 放在 /tmp 的临时目录里，
#   网页服务只听本机的 127.0.0.1（不对外开放；虚拟机里经 10.0.2.2 访问到它），跑完就关掉、临时目录删掉。
#   然后在虚拟机里跑 m0-guest.sh：照小白手册那一条命令用 wget 取 bootstrap.sh 再运行。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
PORT=${SOP_M0_PORT:-8767}
n=${1:?要给虚拟机的名字}; shift
(exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && { echo "本机端口 $PORT 被占了，用 SOP_M0_PORT 换一个" >&2; exit 1; }
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-m0.XXXXXX); web=
cleanup() { [ -n "$web" ] && kill "$web" 2>/dev/null; rm -rf "$tmp"; }
trap cleanup EXIT
mkdir "$tmp/work" "$tmp/www"
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -cf -) | tar -xf - -C "$tmp/work"
id=(env GIT_AUTHOR_NAME=sop-vm GIT_AUTHOR_EMAIL=sop-vm@example.invalid GIT_COMMITTER_NAME=sop-vm GIT_COMMITTER_EMAIL=sop-vm@example.invalid)
"${id[@]}" git -C "$tmp/work" init -q -b main
"${id[@]}" git -C "$tmp/work" add -A
"${id[@]}" git -C "$tmp/work" -c commit.gpgsign=false commit -q -m "工作区 $(git -C "$REPO" rev-parse --short HEAD) 加未提交的改动"
git clone -q --bare "$tmp/work" "$tmp/www/sop.git"
git -C "$tmp/www/sop.git" update-server-info          # 简单的网页服务也能被 git 取
cp "$tmp/work/bootstrap.sh" "$tmp/www/bootstrap.sh"
echo "临时的工具包仓库：提交 $(git -C "$tmp/www/sop.git" rev-parse main)"
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$tmp/www" >"$tmp/web.log" 2>&1 &
web=$!
sleep 1
"$VM" push "$n" "$tmp/work/tests/vm/m0-guest.sh" /home/xiaobai/m0-guest.sh
rc=0
"$VM" ssh "$n" bash m0-guest.sh "http://10.0.2.2:$PORT" "$(git -C "$tmp/www/sop.git" rev-parse main)" "$@" || rc=$?
"$VM" ssh "$n" rm -f m0-guest.sh || true
exit $rc
