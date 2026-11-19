#!/bin/bash
# 在虚拟机里跑（由 m2.sh 拷进去、启动）。见 m2.sh 的说明。
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
step() { echo; echo "=== $* ==="; }
old=; [ "${1:-}" = --old ] && old=1
OLDS="$HOME/.nvm $HOME/.local $HOME/.config $HOME/.cache $HOME/.npm"
snapshot() { find $OLDS -printf '%p %y %s %T@ %m\n' 2>/dev/null | sort; }
# 在「新开的终端」里跑（交互、不是登录的那种，和桌面上开一个终端一样，会读 ~/.bashrc）
term() { bash -ic "$1" 2>&1 | grep -v -e 'cannot set terminal process group' -e 'no job control in this shell'; }

echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，python3 $(python3 -c 'import sys;print(sys.version.split()[0])')"
echo "git：$(git --version 2>&1)；curl：$(curl --version 2>&1 | head -1 | cut -d' ' -f1-2)"

if [ -n "$old" ]; then
  step "先用各工具官方的默认装法装一份旧的"
  export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash >/tmp/old-nvm.log 2>&1 && echo "旧 nvm：~/.nvm（官方脚本改了 ~/.bashrc）"
  term 'nvm install 24 >/tmp/old-node.log 2>&1 && npm install -g pnpm@11 >>/tmp/old-node.log 2>&1; echo "旧 Node $(node -v)、旧 pnpm $(pnpm -v)，在 $(dirname "$(command -v node)")"'
  curl -LsSf https://astral.sh/uv/install.sh | sh >/tmp/old-uv.log 2>&1 && echo "旧 uv：$(~/.local/bin/uv --version)，在 ~/.local/bin（官方脚本改了终端启动文件，留了 ~/.config/uv 的记录）"
  ~/.local/bin/uv python install 3.12 >/tmp/old-py.log 2>&1 && echo "旧 uv 装的 Python 3.12：$(ls ~/.local/bin | grep python | tr '\n' ' ')"
  curl -fsSL https://get.pnpm.io/install.sh | env ENV="$HOME/.bashrc" SHELL=/bin/bash sh - >/tmp/old-pnpm.log 2>&1 && echo "另一份旧 pnpm：~/.local/share/pnpm（官方独立安装脚本，改了 ~/.bashrc）"
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  term 'echo "装新的之前，终端里：node → $(command -v node)；pnpm → $(command -v pnpm)；uv → $(command -v uv)；NVM_DIR=$NVM_DIR"'
  snapshot > /tmp/old-before.txt
  md5sum ~/.config/uv/uv-receipt.json ~/.local/bin/* 2>/dev/null > /tmp/old-md5-before.txt
  cp ~/.bashrc /tmp/bashrc-before; cp ~/.profile /tmp/profile-before
  echo "旧的那几处记下了：$(wc -l < /tmp/old-before.txt) 个文件和目录"
fi

sleep 1; touch /tmp/m2.mark; sleep 1

step "写网络设置（第零步会写的那一份 ~/tools/sop/config/network.json）"
(cd $SRC && env $NOPROXY python3 -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')") && echo 写好了

step "M2 安装（在新开的终端里跑，代理只从网络设置来；有旧的时终端里 NVM_DIR 等还指着旧的）"
t0=$(date +%s)
term "cd $SRC && env $NOPROXY python3 -m machine.install" > /tmp/m2-install.log
grep -q '^都装好了' /tmp/m2-install.log; rc=$?
grep -v '^\s*$' /tmp/m2-install.log | grep -e '：' -e '装好' -e '没装完' | tail -12
echo "（用了 $(( $(date +%s) - t0 )) 秒；完整输出在虚拟机的 /tmp/m2-install.log）"

step "清单里所有的检查命令（在没读终端启动文件的环境里跑）"
cat > /tmp/m2-checks.py <<'PY'
from machine import catalog
for t in catalog.load():
    r = catalog.run_check(t)
    print(f"{t.name:18} {'合格' if r.ok else ('版本不够' if r.installed else '没装')} {r.version_text if r.installed else ''}")
PY
env $NOPROXY PYTHONPATH=$SRC python3 /tmp/m2-checks.py
if [ -n "$old" ]; then step "同样的检查，在读了终端启动文件的终端里跑（旧的那几行也在里面）"; term "PYTHONPATH=$SRC python3 /tmp/m2-checks.py"; fi

step "新开一个终端：用的是哪一份、能不能用"
export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY   # 下载依赖要用；不在工具包那一段里
term '
for c in node npm pnpm uv gh; do echo "$c → $(command -v $c)"; done
node -e "console.log(\"Node 能跑：\" + process.version)"
rm -rf /tmp/m2p && mkdir /tmp/m2p && cd /tmp/m2p && echo "{\"name\":\"m2\",\"version\":\"1.0.0\"}" > package.json \
  && pnpm add is-number@7 >/tmp/m2-pnpm.log 2>&1 && node -e "console.log(\"pnpm 装的依赖能用：\" + require(\"is-number\")(5))" \
  && echo "pnpm 的包仓库：$(pnpm store path)" || { echo "pnpm 装依赖不成："; tail -5 /tmp/m2-pnpm.log; }
pnpm add -g cowsay@1 >/tmp/m2-pnpm-g.log 2>&1 && echo "pnpm 全局装的命令：$(command -v cowsay)" || { echo "pnpm 全局装不成："; tail -5 /tmp/m2-pnpm-g.log; }
uv python install 3.13 >/tmp/m2-py.log 2>&1 && uv run --no-project --python 3.13 python -c "import sys; print(\"Python 能跑：\" + sys.version.split()[0] + \"，在 \" + sys.executable)" \
  || { echo "uv 装 Python 不成："; tail -5 /tmp/m2-py.log; }
echo "python3.13 → $(command -v python3.13)"
rm -rf /tmp/m2py && cd /tmp && uv init -q --python 3.13 m2py && cd m2py && uv add -q six >/tmp/m2-uvadd.log 2>&1 \
  && uv run python -c "import six; print(\"uv 装的依赖能用：six \" + six.__version__)" || { echo "uv 装依赖不成："; tail -5 /tmp/m2-uvadd.log; }
gh --version | head -1   # 不另给变量：看终端里那一段管不管用
'
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

step "登录的终端（ssh 登录、bash -l；会先读 ~/.profile）里用的是哪一份"
bash -ilc 'for c in node pnpm uv python3.13 gh; do echo "$c → $(command -v $c)"; done' 2>&1 | grep -v -e 'terminal process group' -e 'job control'

step "~/tools 之外，这次新出现或改动过的东西（不算拷进来的代码 ~/sop-src）"
find ~ -newer /tmp/m2.mark -not -path "$HOME/tools/*" -not -path "$HOME/sop-src*" -not -path "$HOME/.ssh*" -printf '%y %p\n' | sed "s#$HOME#~#" | head -40

if [ -n "$old" ]; then
  step "旧的动没动"
  snapshot > /tmp/old-after.txt
  md5sum ~/.config/uv/uv-receipt.json ~/.local/bin/* 2>/dev/null > /tmp/old-md5-after.txt
  if diff -q /tmp/old-before.txt /tmp/old-after.txt >/dev/null && diff -q /tmp/old-md5-before.txt /tmp/old-md5-after.txt >/dev/null; then
    echo "旧的那几处（$(wc -l < /tmp/old-after.txt) 个文件和目录）一样没动：大小、修改时间、权限、内容都一样"
  else
    echo "旧的有变化："; diff /tmp/old-before.txt /tmp/old-after.txt | head -20; diff /tmp/old-md5-before.txt /tmp/old-md5-after.txt | head
  fi
  diff -q /tmp/profile-before ~/.profile >/dev/null && echo "~/.profile 没动"
  echo "~/.bashrc 和装之前比："
  diff /tmp/bashrc-before ~/.bashrc | sed 's/^/  /' | head -30
  cmp -s /tmp/bashrc-before <(head -c "$(stat -c %s /tmp/bashrc-before)" ~/.bashrc) && echo "  （原来的内容一个字没动，只在末尾加了那一段）"
fi

step "再装一次：都应该跳过，终端启动文件不改"
before=$(stat -c '%Y %s' ~/.bashrc; md5sum < ~/.bashrc)
term "cd $SRC && env $NOPROXY python3 -m machine.install" | grep -e '跳过' -e '没改' -e '没装完' -e '都装好了'
after=$(stat -c '%Y %s' ~/.bashrc; md5sum < ~/.bashrc)
[ "$before" = "$after" ] && echo "~/.bashrc 没被再改（修改时间、内容都一样）" || echo "~/.bashrc 又被改了！"

step "各部分大小"
du -sh ~/tools/* 2>/dev/null | sed "s#$HOME#~#"
exit $rc
