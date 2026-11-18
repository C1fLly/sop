#!/usr/bin/env bash
# 用法: STATE=<状态目录> [RAW=1] sbx.sh <工作目录> <参数...>
# S0 用的受限环境：只看得到这一个工作目录、一个专用状态目录、一个专用临时目录。
# RAW=1 时直接运行后面的命令（用来在受限环境里执行 git、跑测试）；否则运行 claude。
set -euo pipefail
S=/tmp/sop-spike-s0; H=$HOME; WD=$1; shift; ST=${STATE:-$S/aistate/raw}; RAWMODE=${RAW:-}
C=$H/.local/share/claude/versions/2.1.325
keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_BASE_URL|ANTHROPIC_MODEL|ANTHROPIC_DEFAULT_[A-Z_]+)$'
[ -n "$RAWMODE" ] && keep='^$'
for v in $(compgen -e); do [[ $v =~ $keep ]] || unset "$v" 2>/dev/null || true; done
export PATH=/usr/bin HOME="$H" LANG=C.UTF-8 TERM=dumb TMPDIR=$S/ostmp CLAUDE_CONFIG_DIR="$H/.claude"
export GIT_AUTHOR_NAME=sop-ai GIT_AUTHOR_EMAIL=ai@example.invalid GIT_COMMITTER_NAME=sop-ai GIT_COMMITTER_EMAIL=ai@example.invalid
mkdir -p "$ST" $S/ostmp
a=( --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin
    --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs "$H"
    --ro-bind /run/systemd/resolve /run/systemd/resolve
    --bind $S/ostmp $S/ostmp --bind "$WD" "$WD" --ro-bind "$C" "$C" --bind "$ST" "$H/.claude"
    --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --new-session --chdir "$WD" )
if [ -n "$RAWMODE" ]; then exec bwrap "${a[@]}" "$@"; else exec bwrap "${a[@]}" "$C" "$@"; fi
