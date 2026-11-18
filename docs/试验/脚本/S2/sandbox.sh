#!/usr/bin/env bash
# 用法: GITMODE=coarse|fine DOCKER=0|1 sandbox.sh <工作目录名> <命令...>
# 试验用的受限环境启动器（bubblewrap）。只在 /tmp/sop-spike-s2 里用。
set -euo pipefail
R=/tmp/sop-spike-s2; P=$R/proj; WT=$1; shift
H=$HOME; GITMODE=${GITMODE:-fine}; DOCKER=${DOCKER:-0}
a=( --clearenv
    --setenv PATH "/usr/bin:$H/tools/docker/bin" --setenv HOME "$H" --setenv LANG C.UTF-8
    --setenv GIT_AUTHOR_NAME sop-ai --setenv GIT_AUTHOR_EMAIL ai@example.invalid
    --setenv GIT_COMMITTER_NAME sop-ai --setenv GIT_COMMITTER_EMAIL ai@example.invalid
    --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin
    --ro-bind /etc /etc --proc /proc --dev /dev
    --tmpfs /tmp --tmpfs /run --tmpfs "$H"
    --ro-bind /run/systemd/resolve /run/systemd/resolve
    --ro-bind "$H/tools/docker/bin" "$H/tools/docker/bin"
    --ro-bind "$R/probe.sh" "$R/probe.sh"
    --bind "$P/$WT" "$P/$WT" --ro-bind "$P/$WT/.git" "$P/$WT/.git" )
if [ "$GITMODE" = coarse ]; then
  # 粗：整个 .git 可写，只把配置和钩子设成只读
  a+=( --bind "$P/.git" "$P/.git" --ro-bind "$P/.git/config" "$P/.git/config" --ro-bind "$P/.git/hooks" "$P/.git/hooks" )
else
  # 细：整个 .git 只读，只放开「提交内容」「本工作目录的登记」「本功能的工单分支指针」
  feat=$(echo "$WT" | sed -E 's/^ticket-(.*)-[0-9]+$/\1/')
  mkdir -p "$P/.git/logs/refs/heads/ticket/$feat"
  a+=( --ro-bind "$P/.git" "$P/.git"
       --bind "$P/.git/objects" "$P/.git/objects"
       --bind "$P/.git/worktrees/$WT" "$P/.git/worktrees/$WT"
       --bind "$P/.git/refs/heads/ticket/$feat" "$P/.git/refs/heads/ticket/$feat"
       --bind "$P/.git/logs/refs/heads/ticket/$feat" "$P/.git/logs/refs/heads/ticket/$feat" )
fi
if [ "$DOCKER" = 1 ]; then
  a+=( --ro-bind /run/user/1000/docker.sock /run/user/1000/docker.sock --setenv DOCKER_HOST unix:///run/user/1000/docker.sock )
fi
if [ "$DOCKER" = 2 ]; then
  # 只给「专用 Docker」的通道，不给原来那个
  a+=( --ro-bind "$R/rd/run/docker.sock" "$R/rd/run/docker.sock" --setenv DOCKER_HOST "unix://$R/rd/run/docker.sock" )
fi
exec bwrap "${a[@]}" --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --new-session --chdir "$P/$WT" "$@"
