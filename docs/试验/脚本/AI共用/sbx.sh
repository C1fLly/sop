#!/usr/bin/env bash
# 用法: TOOL=<claude|codex|opencode|pi|none> [STATE=<状态目录>] [EXTRA_RW="目录1 目录2"] [EXTRA_RO="..."]
#       [EXTRA_BINDS="ro:路径 rw:路径 ..."] [EXTRA_MAP="源=目标 ..."] [EXTRA_ENV="名=值 ..."] [CHDIR=起始目录] [EXTRA_PATH=目录]
#       [NET=1 保留代理变量] [INTERACTIVE=1 对话方式，不脱离终端] sbx.sh <工作目录> <命令...>
# S5、S7、S1 后续共用的受限环境（照 S2 的 sandbox-ai.sh 和 S0 的 sbx.sh 改的）：
# 只看得到 <工作目录>（可写）、EXTRA_RW/EXTRA_RO 里列的目录、某一个 AI 工具运行必需的最少东西。
# 主目录、/tmp、/run 都是空的；环境变量只留白名单。TOOL=claude 时后面的命令就是 claude 的参数。
set -euo pipefail
OUTER_TERM=${TERM:-xterm-256color}; H=$HOME; WD=$1; shift; T=${TOOL:-none}; ST=${STATE:-}; XRW=${EXTRA_RW:-}; XRO=${EXTRA_RO:-}; XB=${EXTRA_BINDS:-}; CD=${CHDIR:-}; XPATH=${EXTRA_PATH:-}; XMAP=${EXTRA_MAP:-}; XENV=${EXTRA_ENV:-}; NETKEEP=${NET:-}; TTY=${INTERACTIVE:-}
NODE=$H/.nvm/versions/node/v26.13.0
C=${CLAUDE_BIN:-$(readlink -f "$H/.local/bin/claude")}
keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$'
[ "$T" = claude ] && keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|ANTHROPIC_AUTH_TOKEN|ANTHROPIC_BASE_URL|ANTHROPIC_MODEL|ANTHROPIC_DEFAULT_[A-Z_]+)$'
[ "$T" = none ] && keep='^$'
[ "$T" = none ] && [ -n "$NETKEEP" ] && keep='^(http_proxy|https_proxy|all_proxy|no_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$'
for v in $(compgen -e); do [[ $v =~ $keep ]] || unset "$v" 2>/dev/null || true; done
export PATH="/usr/bin:$NODE/bin${XPATH:+:$XPATH}" HOME="$H" LANG=C.UTF-8 TERM=dumb
export GIT_AUTHOR_NAME=sop-ai GIT_AUTHOR_EMAIL=ai@example.invalid GIT_COMMITTER_NAME=sop-ai GIT_COMMITTER_EMAIL=ai@example.invalid
a=( --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin
    --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs "$H"
    --ro-bind /run/systemd/resolve /run/systemd/resolve
    --bind "$WD" "$WD" )
for d in $XRW; do a+=( --bind "$d" "$d" ); done
for d in $XRO; do a+=( --ro-bind "$d" "$d" ); done
# EXTRA_BINDS：形如 "ro:/路径 rw:/路径 ..."，按写的顺序挂载，后面的盖住前面的
# EXTRA_MAP：形如 "源路径=受限环境里的路径 ..."，可写
for m in $XMAP; do a+=( --bind "${m%%=*}" "${m#*=}" ); done
# EXTRA_ENV：形如 "名字=值 ..."（值里不能有空格）
for e in $XENV; do a+=( --setenv "${e%%=*}" "${e#*=}" ); done
for b in $XB; do m=${b%%:*}; p=${b#*:}; if [ "$m" = rw ]; then a+=( --bind "$p" "$p" ); else a+=( --ro-bind "$p" "$p" ); fi; done
rob() { for f in "$@"; do a+=( --ro-bind "$f" "$f" ); done; }
case "$T" in
  claude)   rob "$C"; if [ -n "$ST" ]; then mkdir -p "$ST"; a+=( --bind "$ST" "$H/.claude" --setenv CLAUDE_CONFIG_DIR "$H/.claude" ); fi ;;
  codex)    a+=( --dir "$H/.codex" ); rob "$H/.codex/packages" "$H/.codex/config.toml" "$H/.codex/cc-switch-model-catalog.json"; a+=( --dir "$H/.local/bin" --symlink "$(readlink -f "$H/.local/bin/codex")" "$H/.local/bin/codex" ) ;;
  opencode) a+=( --dir "$H/.config/opencode" ); rob "$H/.opencode/bin" "$H/.config/opencode/opencode.json" ;;
  pi)       a+=( --dir "$H/.pi/agent" ); rob "$NODE" "$H/.pi/agent/bin" "$H/.pi/agent/install" "$H/.pi/agent/npm" "$H/.pi/agent/models.json" "$H/.pi/agent/models-store.json" "$H/.pi/agent/auth.json" "$H/.pi/agent/settings.json" ;;
  none)     ;;
esac
a+=( --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --chdir "${CD:-$WD}" )
if [ -n "$TTY" ]; then a+=( --setenv TERM "${OUTER_TERM:-xterm-256color}" ); else a+=( --new-session ); fi
case "$T" in
  claude)   exec bwrap "${a[@]}" "$C" "$@" ;;
  codex)    exec bwrap "${a[@]}" "$H/.local/bin/codex" "$@" ;;
  opencode) exec bwrap "${a[@]}" "$H/.opencode/bin/opencode" "$@" ;;
  pi)       exec bwrap "${a[@]}" "$H/.pi/agent/bin/pi" "$@" ;;
  none)     exec bwrap "${a[@]}" "$@" ;;
esac
