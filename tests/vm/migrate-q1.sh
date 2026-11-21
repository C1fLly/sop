#!/bin/bash
# 3-30：在虚拟机里验迁移 Q1 清点（machine/migrate/inventory.py）。
# 用法：tests/vm/migrate-q1.sh <虚拟机名字> --prepare system|ce|rootless
#       tests/vm/migrate-q1.sh <虚拟机名字> --capture <本机目录>      把清点用到的命令的原样输出取回本机（做单元测试的样例）
#       tests/vm/migrate-q1.sh <虚拟机名字> --inventory [参数...]     用正式代码清点一遍，核对旧的一样都没动
#   虚拟机要先 vm.sh new <名字> 建好。每次把工作区的代码打包拷进去（~/sop-src）。
#   system：Ubuntu 软件源的 docker.io；ce：照 Docker 官网装的 docker-ce；rootless：官方一条命令装的免管理员（~/bin）。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装和卸 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-q1-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
case ${1:-} in
  --capture)
    out=${2:?要给本机目录}
    "$VM" ssh "$n" bash sop-src/tests/vm/migrate-q1-guest.sh --capture
    "$VM" ssh "$n" 'tar -czf ~/q1-out.tgz -C ~ q1-out'
    mkdir -p "$out"; "$VM" pull "$n" /home/xiaobai/q1-out.tgz "$tmp/q1-out.tgz"; tar -xzf "$tmp/q1-out.tgz" -C "$out" ;;
  *) "$VM" ssh "$n" bash sop-src/tests/vm/migrate-q1-guest.sh "$@" ;;
esac
