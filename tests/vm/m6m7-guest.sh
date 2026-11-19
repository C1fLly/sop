#!/bin/bash
# 在虚拟机里跑（由 m6m7.sh 拷进去、启动）。见 m6m7.sh 的说明。
set -uo pipefail
SRC=~/sop-src
PROXY=http://10.0.2.2:7890          # 虚拟机里 10.0.2.2 就是本机，本机的代理
NOPROXY="-u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY"
CFG=~/tools/sop/config
step() { echo; echo "=== $* ==="; }
fail=0
must() { if eval "$1"; then echo "  对：$2"; else echo "  不对：$2"; fail=1; fi; }
py() { (cd $SRC && env $NOPROXY python3 "$@"); }
echo "虚拟机：$(hostname)，$(. /etc/os-release; echo "$PRETTY_NAME")，内核 $(uname -r)"

step "准备：网络设置、bubblewrap（系统软件包）、规定位置的免管理员 Docker（M2）"
py -c "from machine import config; config.set_network(http_proxy='$PROXY', https_proxy='$PROXY', no_proxy='localhost,127.0.0.1', source='user')" && echo "  网络设置写好了"
py -m machine.install bubblewrap uidmap dbus-user-session docker > /tmp/m2.log 2>&1
if grep -q '^都装好了' /tmp/m2.log; then echo "  bubblewrap $(bwrap --version)、Docker $(~/tools/docker/bin/docker --version | cut -d, -f1) 装好了"
else echo "  M2 没装好："; cat /tmp/m2.log; exit 1; fi
must "[ ! -e $CFG/system.json ]" "M6 之前还没有系统组件登记"

step "M6：隔离自检（本机那份加专用 Docker 那份），通过后记登记"
ls -d ~/tools/sop/state/* 2>/dev/null > /tmp/state-before.txt
ls -A /run/user/$(id -u)/sop 2>/dev/null > /tmp/rt-before.txt
ls -d /tmp/sop-selftest* 2>/dev/null > /tmp/tmp-before.txt
t0=$(date +%s)
py -m machine.syscheck > /tmp/m6.log 2>&1; rc=$?
cat /tmp/m6.log | sed 's/^/  /'
echo "  （用了 $(( $(date +%s) - t0 )) 秒，退出码 $rc）"
must "[ $rc = 0 ]" "M6 通过"
must "grep -q '^隔离自检通过（[0-9]* 项，0 项不符合），已记下现在的系统组件版本' /tmp/m6.log" "两份合起来 0 项不符合，记下了登记"
must "[ -f $CFG/system.json ] && [ \"\$(stat -c %a $CFG/system.json)\" = 600 ]" "登记 system.json 在、只有自己能读"
py -c "from machine import config, components; import json; print(json.dumps(config.system()['components'], ensure_ascii=False, indent=1))" | sed 's/^/  /'
must "py -c 'from machine import config, components; import sys; sys.exit(1 if config.system_changes(components.collect()) else 0)'" "登记和现在的系统组件一样"

step "M6 跑完收拾干净了"
must "diff <(ls -d ~/tools/sop/state/* 2>/dev/null) /tmp/state-before.txt >/dev/null" "~/tools/sop/state 下没多东西（没留下 sopdk）"
must "diff <(ls -A /run/user/$(id -u)/sop 2>/dev/null) /tmp/rt-before.txt >/dev/null" "通道目录里没留下假通道文件"
must "diff <(ls -d /tmp/sop-selftest* 2>/dev/null) /tmp/tmp-before.txt >/dev/null" "/tmp 下没留下假项目"
must "[ ! -e ~/Project/sopdk-fixture ]" "没有在 ~/Project 下建东西"
must "! systemctl --user -q is-active sop-docker-sopdk && [ ! -e ~/.config/systemd/user/sop-docker-sopdk.service ]" "自检用的专用 Docker 停了、登记文件删了"
echo "  留下的：~/tools/docker-sop/sopdk $(du -sh ~/tools/docker-sop/sopdk 2>/dev/null | cut -f1)（拉下来的小镜像，下次自检不用再拉）"

step "装完第一次推进流程：登记好了，不再自检（自检命令换成一跑就失败的，自检了就会报出来）"
out=$(SOP_SELFTEST_CMD=/bin/false py -c "from machine import syscheck; print('推进' if syscheck.gate() else '停下')" 2>&1)
echo "  $out"
must "[ \"$out\" = 推进 ]" "没自检，直接推进"

step "系统升级了（登记里的 bubblewrap 改成旧的）：推进流程之前先重跑真的隔离自检（两份），过了才推进"
py -c "
from machine import config
d = config.system()['components']; d['bubblewrap'] = '0.10.0 (package 0.10.0-1)'; config.record_system(d)"
py -c "from machine import syscheck; print('推进' if syscheck.gate() else '停下')" > /tmp/gate.log 2>&1
sed 's/^/  /' /tmp/gate.log
must "grep -q '上次是「0.10.0' /tmp/gate.log && grep -q '^隔离自检通过（' /tmp/gate.log && tail -1 /tmp/gate.log | grep -qx 推进" "先说变了、再自检通过、再推进"
must "py -c 'from machine import config, components; import sys; sys.exit(1 if config.system_changes(components.collect()) else 0)'" "登记换成了现在的"

step "M7：全局规则（小白原来就有 ~/.claude/CLAUDE.md 和 Pi 的规则）"
mkdir -p ~/.claude ~/.pi/agent
printf '# 我自己的规矩\n\n- 回答用中文。\n' > ~/.claude/CLAUDE.md
printf 'pi 的规矩\n' > ~/.pi/agent/AGENTS.md
cp ~/.claude/CLAUDE.md /tmp/claude-before.md; cp ~/.pi/agent/AGENTS.md /tmp/pi-before.md
py -m machine.globalrules > /tmp/m7.log 2>&1; rc=$?
sed 's/^/  /' /tmp/m7.log
must "[ $rc = 0 ] && grep -q '出口检查合格' /tmp/m7.log" "M7 装好、出口检查合格"
must "head -c \$(stat -c %s /tmp/claude-before.md) ~/.claude/CLAUDE.md | cmp -s - /tmp/claude-before.md" "~/.claude/CLAUDE.md 原来的字一个没动"
must "head -c \$(stat -c %s /tmp/pi-before.md) ~/.pi/agent/AGENTS.md | cmp -s - /tmp/pi-before.md" "Pi 原来的规矩一个字没动"
must "[ -f ~/.codex/AGENTS.md ] && [ ! -e ~/.config/opencode ]" "Codex 的新建了；OpenCode 的没新建（它读 ~/.claude/CLAUDE.md）"
md5=$(md5sum ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.pi/agent/AGENTS.md); mt=$(stat -c %Y ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.pi/agent/AGENTS.md)
sleep 1
py -m machine.globalrules > /tmp/m7b.log 2>&1
must "[ \"\$(grep -c '本来就是最新的' /tmp/m7b.log)\" = 3 ]" "再装一次：三份都没改"
must "[ \"\$(md5sum ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.pi/agent/AGENTS.md)\" = \"$md5\" ] && [ \"\$(stat -c %Y ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.pi/agent/AGENTS.md)\" = \"$mt\" ]" "内容和修改时间都没变"
echo; echo "  ~/.claude/CLAUDE.md 现在是："; sed 's/^/    /' ~/.claude/CLAUDE.md

echo
[ $fail = 0 ] && echo "全部对" || echo "有不对的"
exit $fail
