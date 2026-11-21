#!/bin/bash
# 3-33：在一台全新的虚拟机里验收迁移 docker.io（sop machine migrate，Q1 到 Q6）；3-34 加了 --ce：照 Docker 官网装的 docker-ce；
# 3-35 加了 --rl：照 Docker 官网的免管理员装法装的（程序在 ~/bin、服务名 docker，「免管理员但位置不对」）。
# 用法：tests/vm/migrate-io.sh <虚拟机名字> [--ce | --rl] [--reboot]
#   虚拟机要先 vm.sh new <名字> 建好（全新的）。把工作区的代码打包拷进去（~/sop-src），在里面跑 migrate-io-guest.sh：
#   1. --prepare（一次登录）：记下装之前系统里的文件和软件包；装 docker.io，放镜像、数据卷、容器
#      --ce：先造得像桌面版（卸掉 git、curl），记下样子，再照官网装 docker-ce（官方软件源、钥匙文件、containerd.io……）
#      --rl：记下样子，再照官网装免管理员的（uidmap、~/bin/rootlesskit 的系统安全规则、curl -fsSL https://get.docker.com/rootless | sh、
#            照它的提示往 ~/.bashrc 加 PATH）；Q2 装规定位置那份时应该另起服务名 sop-docker，Q6 卸完接过 docker 这个名字
#   2. --run1（下一次登录，docker 组生效）：第一遍迁移，Q2 装规定位置的 Docker，Q4 停了旧容器、正在打包时 kill -9 整个 sop；
#      再执行一次别的 sop 命令，看旧容器起回来、临时小镜像删掉
#   3. --run2：第二遍走完 Q1 到 Q6：Q6 切回原来那份后暂停看不加 sudo 敲 docker；卸完残留清单逐项为空、和装之前的系统比、带走的数据一致
#   4. --reboot：再重启一次，看敲 docker 还是规定位置那份、旧 Docker 在 /run 下没留东西
#   回答问题用 migrate-drive.py（模拟终端里像小白一样看着屏幕答）。
# 虚拟机里的 sudo 代表「小白输管理员密码」（用户 2026-11-19 答应第三段可以在虚拟机里用 sudo、装和卸 Docker）。
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../.." && pwd); VM=$HERE/vm.sh
n=${1:?要给虚拟机的名字}; shift
reboot=; kind=io; for a in "$@"; do case $a in --reboot) reboot=1 ;; --ce) kind=ce ;; --rl) kind=rl ;; *) echo "不认识：$a" >&2; exit 2 ;; esac; done
"$VM" start "$n"
tmp=$(mktemp -d /tmp/sop-io-vm.XXXXXX); trap 'rm -rf "$tmp"' EXIT
(cd "$REPO" && GIT_OPTIONAL_LOCKS=0 git ls-files -co --exclude-standard -z | tar --null -T - -czf "$tmp/src.tgz")
"$VM" push "$n" "$tmp/src.tgz" /home/xiaobai/sop-src.tgz
"$VM" ssh "$n" 'rm -rf ~/sop-src && mkdir ~/sop-src && tar -xzf ~/sop-src.tgz -C ~/sop-src && rm ~/sop-src.tgz'
"$VM" ssh "$n" bash sop-src/tests/vm/migrate-io-guest.sh --prepare $kind
rc=0
"$VM" ssh "$n" bash sop-src/tests/vm/migrate-io-guest.sh --run1 || rc=1
"$VM" ssh "$n" bash sop-src/tests/vm/migrate-io-guest.sh --run2 || rc=1
if [ -n "$reboot" ]; then
  echo; echo "=== 重启虚拟机 ==="
  "$VM" stop "$n"; "$VM" start "$n"
  "$VM" ssh "$n" bash sop-src/tests/vm/migrate-io-guest.sh --after-reboot || rc=1
fi
echo; [ $rc = 0 ] && echo "全部对" || echo "有不对的，看上面「不对」那几行"
exit $rc
