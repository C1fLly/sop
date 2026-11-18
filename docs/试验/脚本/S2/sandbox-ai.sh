#!/usr/bin/env bash
# 用法: sandbox-ai.sh <claude|codex|opencode|pi> <工作目录名> <命令...>
# 在 sandbox.sh（细粒度 .git）的基础上，放进某一个 AI 工具运行所需的最少东西。
set -euo pipefail
R=/tmp/sop-spike-s2; P=$R/proj; TOOL=$1; WT=$2; shift 2; H=$HOME
NODE=$H/.nvm/versions/node/v26.13.0
STATE=${AISTATE:-}
# 环境变量：只留白名单。密钥靠继承传进去，不写在命令行上（命令行别的进程看得到）。
keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$'
[ "$TOOL" = claude ] && keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_BASE_URL|ANTHROPIC_MODEL|ANTHROPIC_DEFAULT_[A-Z_]+)$'
for v in $(compgen -e); do [[ $v =~ $keep ]] || unset "$v" 2>/dev/null || true; done
export PATH="/usr/bin:$NODE/bin" HOME="$H" LANG=C.UTF-8 TERM=dumb
export GIT_AUTHOR_NAME=sop-ai GIT_AUTHOR_EMAIL=ai@example.invalid GIT_COMMITTER_NAME=sop-ai GIT_COMMITTER_EMAIL=ai@example.invalid
feat=$(echo "$WT" | sed -E 's/^ticket-(.*)-[0-9]+$/\1/')
mkdir -p "$P/.git/logs/refs/heads/ticket/$feat"
a=( --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin
    --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs "$H"
    --ro-bind /run/systemd/resolve /run/systemd/resolve
    --bind "$P/$WT" "$P/$WT" --ro-bind "$P/$WT/.git" "$P/$WT/.git"
    --ro-bind "$P/.git" "$P/.git"
    --bind "$P/.git/objects" "$P/.git/objects"
    --bind "$P/.git/worktrees/$WT" "$P/.git/worktrees/$WT"
    --bind "$P/.git/refs/heads/ticket/$feat" "$P/.git/refs/heads/ticket/$feat"
    --bind "$P/.git/logs/refs/heads/ticket/$feat" "$P/.git/logs/refs/heads/ticket/$feat" )
rob() { for f in "$@"; do a+=( --ro-bind "$f" "$f" ); done; }
case "$TOOL" in
  claude)   rob "$H/.local/share/claude/versions/2.1.325"
            if [ -n "$STATE" ]; then mkdir -p "$STATE"; a+=( --bind "$STATE" "$H/.claude" --setenv CLAUDE_CONFIG_DIR "$H/.claude" ); fi ;;                       # 只有程序本身；登录信息在环境变量里
  codex)    a+=( --dir "$H/.codex" ); rob "$H/.codex/packages" "$H/.codex/config.toml" "$H/.codex/cc-switch-model-catalog.json" ;;
  opencode) a+=( --dir "$H/.config/opencode" ); rob "$H/.opencode/bin" "$H/.config/opencode/opencode.json" ;;
  pi)       a+=( --dir "$H/.pi/agent" ); rob "$NODE" "$H/.pi/agent/bin" "$H/.pi/agent/install" "$H/.pi/agent/npm" "$H/.pi/agent/models.json" "$H/.pi/agent/models-store.json" "$H/.pi/agent/auth.json" "$H/.pi/agent/settings.json" ;;
  none)     ;;
esac
exec bwrap "${a[@]}" --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --new-session --chdir "$P/$WT" "$@"
