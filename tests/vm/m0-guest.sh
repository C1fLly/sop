#!/bin/bash
# 在虚拟机里跑（由 m0.sh 拷进去、启动）。用法：m0-guest.sh <临时网页服务的地址> <工具包的提交编号> [--desktop]
#   默认：底盘原样（有 git、curl，能直接上网，环境里没有代理），小白看到探测结果直接回车。
#   --desktop：先造得像桌面版的小白电脑：卸掉 git、curl（桌面版不带），不让直接上网（虚拟机里设防火墙，只能连本机 10.0.2.2，
#              也就是只能走本机的代理），环境里没有代理设置 —— 第零步要问代理，小白填 10.0.2.2:7890。
#   两种都在最后再跑一遍第零步（这次环境里有代理设置，--yes），看都跳过、文件不重写。
set -uo pipefail
URL=${1:?}; WANT=${2:?}; shift 2
desktop=; [ "${1:-}" = --desktop ] && desktop=1
PROXY=http://10.0.2.2:7890
fails=0
step() { echo; echo "=== $* ==="; }
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fails=$((fails + 1)); fi; }
clean_env=(env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY)

echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，python3 $(python3 -c 'import sys;print(sys.version.split()[0])')"
if [ -n "$desktop" ]; then
  step "造成像桌面版的小白电脑：卸掉 git、curl；只能经本机的代理上网"
  sudo env DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq git curl 2>&1 | grep -E '^(Removing|Purging)' | sed 's/^/  /'
  must '! command -v git >/dev/null && ! command -v curl >/dev/null' "git、curl 都没了"
  for t in iptables ip6tables; do
    sudo $t -A OUTPUT -o lo -j ACCEPT
    [ $t = iptables ] && sudo $t -A OUTPUT -d 10.0.2.0/24 -j ACCEPT
    sudo $t -A OUTPUT -j REJECT
  done
  must "! ${clean_env[*]} wget --no-hsts -q --spider -T 5 -t 1 https://github.com/" "不走代理连不上 GitHub"
  must "${clean_env[*]} https_proxy=$PROXY wget --no-hsts -q --spider -T 10 -t 1 https://github.com/" "走本机的代理连得上 GitHub"
fi
must 'command -v wget >/dev/null' "系统自带 wget（$(wget --version | head -1 | cut -d' ' -f1-3)）"
must '[ ! -e ~/tools ]' "~/tools 还没有"

sleep 1; touch /tmp/m0.mark; sleep 1

step "第零步：照小白手册首页那一条命令（wget 取 bootstrap.sh 再运行）"
if [ -n "$desktop" ]; then
  answers='10.0.2.2:7890\n\n'          # 问代理时填本机代理；摆出结果时直接回车
  extra=(no_proxy=10.0.2.2)            # 临时网页服务在 10.0.2.2，不能走代理（本机的代理连不到虚拟机眼里的 10.0.2.2）
else
  answers='\n'                         # 摆出探测结果时直接回车
  extra=()
fi
t0=$(date +%s)
printf "$answers" | "${clean_env[@]}" "${extra[@]}" bash -c \
  "wget --no-hsts -qO /tmp/sop-bootstrap.sh $URL/bootstrap.sh && bash /tmp/sop-bootstrap.sh --repo $URL/sop.git" > /tmp/m0-1.log 2>&1
rc=$?
cat /tmp/m0-1.log | sed 's/^/  | /'
echo "（退出码 $rc，用了 $(( $(date +%s) - t0 )) 秒）"
must "[ $rc = 0 ]" "第零步做完了"

step "做完之后看"
S=~/tools/sop
must '[ "$(cat $S/versions/latest 2>/dev/null)" = "$WANT" ]' "versions/latest 是 ${WANT:0:8}"
must '[ "$(git -C $S/versions/$WANT rev-parse HEAD 2>/dev/null)" = "$WANT" ]' "~/tools/sop/versions/<提交编号> 就是这个提交"
must '[ -z "$(git -C $S/versions/$WANT status --porcelain --untracked-files=no)" ]' "版本目录没被改过"
must '[ -x ~/tools/uv/bin/uv ]' "uv 在 ~/tools/uv/bin（$(~/tools/uv/bin/uv --version 2>/dev/null)）"
must 'command -v git >/dev/null && command -v curl >/dev/null' "git、curl 有了（$(git --version 2>/dev/null)）"
echo "  网络设置："; sed 's/^/    /' $S/config/network.json
if [ -n "$desktop" ]; then
  must "grep -q '\"http_proxy\": \"$PROXY\"' $S/config/network.json && grep -q '\"source\": \"user\"' $S/config/network.json" "网络设置记的是小白填的代理"
  must "grep -q '代理：http://10.0.2.2:7890（你填的）' /tmp/m0-1.log" "问了代理、用的是填的那个"
else
  must "! grep -q proxy $S/config/network.json && grep -q '\"source\": \"detected\"' $S/config/network.json" "网络设置记的是「不用代理、探测到的」"
fi
must "grep -q '主目录不在系统盘上\|只有一个能用的 Linux 分区\|另有分区没用上\|看不出来' /tmp/m0-1.log" "报告了主目录在哪个分区"
must "grep -q 'sop machine setup' /tmp/m0-1.log" "最后提示 sop machine setup"
must 'grep -qF ">>> SOP 工具包管理的段落" ~/.bashrc' "~/.bashrc 末尾有工具包那一段"

step "新开一个终端（读 ~/.bashrc）：敲 sop 能用"
bash -ic 'echo "sop → $(command -v sop)；uv → $(command -v uv)"; sop machine tools | head -3' 2>&1 | grep -v -e 'terminal process group' -e 'job control' | sed 's/^/  /'
must "bash -ic 'sop machine tools' >/dev/null 2>&1" "新开的终端里 sop machine tools 能运行"
echo "  体检（只看不记）的前几行："
bash -ic 'sop machine doctor --readonly' 2>&1 | grep -v -e 'terminal process group' -e 'job control' | head -15 | sed 's/^/    /'

step "~/tools 之外，这次新出现或改动过的东西"
find ~ -newer /tmp/m0.mark -not -path "$HOME/tools/*" -not -path "$HOME/.ssh*" -not -name m0-guest.sh -printf '%y %p\n' | sed "s#$HOME#~#"
echo "  ~/tools 下：$(ls ~/tools | tr '\n' ' ')；大小 $(du -sh ~/tools | cut -f1)"

step "再跑一遍第零步（这次环境里有代理设置，--yes）：都跳过、文件不重写"
before=$(stat -c '%n %Y' ~/.bashrc $S/sop $S/launcher.py $S/versions/latest $S/config/network.json)
sleep 1
"${clean_env[@]}" http_proxy=$PROXY https_proxy=$PROXY no_proxy=10.0.2.2 bash /tmp/sop-bootstrap.sh --repo $URL/sop.git --yes > /tmp/m0-2.log 2>&1 </dev/null
rc=$?
grep -e '代理' -e '跳过' -e '没改' -e '连' -e '没做完' -e 'sop 能运行' /tmp/m0-2.log | sed 's/^/  | /'
after=$(stat -c '%n %Y' ~/.bashrc $S/sop $S/launcher.py $S/versions/latest $S/config/network.json)
must "[ $rc = 0 ]" "第二遍也做完了"
must "grep -q '从环境变量读到的' /tmp/m0-2.log" "代理是从环境变量读到的"
must "grep -q 'git、curl 都有了，跳过' /tmp/m0-2.log && grep -q '已经有了，跳过' /tmp/m0-2.log && grep -q 'uv 已经有了' /tmp/m0-2.log" "git/curl、工具包、uv 都跳过"
must "! grep -q '登录密码' /tmp/m0-2.log" "没要管理员密码"
diff <(echo "$before") <(echo "$after") | grep '^>' | sed 's/^> /  改了：/'
must "[ \"\$(echo \"$before\" | grep -v network.json)\" = \"\$(echo \"$after\" | grep -v network.json)\" ]" "启动器、版本、~/.bashrc 没重写（网络设置每次确认会记下时间，会写）"
[ $fails = 0 ] && echo && echo "全部对" || { echo; echo "有 $fails 处不对"; }
exit $fails
