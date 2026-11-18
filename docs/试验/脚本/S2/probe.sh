#!/usr/bin/env bash
# 在受限环境里运行。每行：期望 | 实际 | 说明
R=/tmp/sop-spike-s2; P=$R/proj; H=$HOME
ok()  { printf '符合  | %s\n' "$1"; }
bad() { printf '不符  | %s\n' "$1"; }
must_fail() { local d=$1; shift; if "$@" >/dev/null 2>&1; then bad "$d（本该做不到，却做到了）"; else ok "$d：做不到"; fi; }
must_work() { local d=$1; shift; if "$@" >/dev/null 2>&1; then ok "$d：可以"; else bad "$d（本该可以，却失败）"; fi; }
echo "## 要求一：读不到凭据"
must_fail "看到 ~/.ssh" test -e "$H/.ssh"
must_fail "看到系统钥匙串的通道 /run/user/1000/bus" test -e /run/user/1000/bus
must_fail "看到 SSH 代理的通道" test -e /run/user/1000/gcr/ssh
must_fail "gh 查到登录状态" gh auth status
must_fail "读到假凭据" cat $R/outside/secret.txt
n=$(env | grep -c -i -E 'token|api_key|secret|SSH_AUTH_SOCK|DBUS'); [ "$n" = 0 ] && ok "环境变量里没有密钥和通道（共 $(env | wc -l) 个变量）" || bad "环境变量里还有 $n 个密钥或通道"
echo "## 要求二：写不了工具包、别的项目、机器级配置"
must_fail "看到工具包目录 ~/tools/sop" test -e "$H/tools/sop"
must_fail "看到别的项目" test -e $R/otherproj
must_fail "看到同项目的另一个工作目录 main/" test -e $P/main/README.md
mkdir -p "$H/.config/sop" 2>/dev/null && echo x > "$H/.config/sop/probe-wrote-this" 2>/dev/null; echo "（往 ~/.config/sop 写了一个文件，是否落到真实位置由外面核对）"
echo "## 要求三：对共用的 .git 只能写提交和自己的分支指针"
echo "probe $(date +%s%N)" >> work.txt; git add work.txt >/dev/null 2>&1
must_work "在自己的工作目录里提交" git commit -q -m "受限侧的提交"
new=$(git rev-parse HEAD 2>/dev/null)
must_fail "改 .git 里的配置" git config core.sshCommand "echo pwned"
must_fail "往 .git/hooks 里放钩子" sh -c "echo '#!/bin/sh' > $P/.git/hooks/pre-push"
must_fail "换掉工作目录里指向 .git 的那个文件" sh -c "echo 'gitdir: /tmp/evil' > .git"
must_fail "删掉再重建那个文件" sh -c "rm -f .git && echo 'gitdir: /tmp/evil' > .git"
must_fail "移动 main 分支的指针" git update-ref refs/heads/main "$new"
must_fail "移动功能分支 feat/a 的指针" git update-ref refs/heads/feat/a "$new"
must_fail "移动同一功能另一张工单 ticket/a/2 的指针" git update-ref refs/heads/ticket/a/2 "$new"
must_fail "改别的工作目录的登记 worktrees/main/HEAD" sh -c "echo junk >> $P/.git/worktrees/main/HEAD"
must_fail "往 .git 顶层新建文件" sh -c "echo x > $P/.git/new-file"
echo "## 其他"
must_fail "在沙箱里再建一层隔离空间（在里面另起 Docker 需要它）" unshare -Ur true
if [ "${DOCKER_HOST:-}" ]; then
  echo "## 要求四：能用 Docker"
  must_work "用 Docker 跑一个容器" docker run --rm nginx:1.30.6 true
  must_fail "借 Docker 读沙箱外的假凭据" docker run --rm -v $R/outside:/x:ro nginx:1.30.6 cat /x/secret.txt
  docker run --rm -v $R/otherproj:/x nginx:1.30.6 sh -c "echo x > /x/written-via-docker-${DOCKER_TAG:-1}" >/dev/null 2>&1; echo "（经 Docker 往别的项目写了一个文件，是否落到真实位置由外面核对）"
  must_work "容器挂上自己的工作目录并写文件" docker run --rm -v "$PWD":/w nginx:1.30.6 sh -c 'echo ok > /w/from-container-in-sandbox.txt'
  must_fail "借 Docker 改 .git 的配置" docker run --rm -v $P/.git:/g nginx:1.30.6 sh -c 'echo x >> /g/config'
else
  must_fail "连到 Docker" docker version
fi
