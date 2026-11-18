. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R .gitignore '.claude/settings.local.json'; commit $R; B=$(head $R)
put $R .claude/settings.local.json '{}'
H=$(sha256sum $R/.claude/settings.local.json | cut -d' ' -f1)
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["**"], "protected": [], "snapshot": {".claude/settings.local.json": "$H"}}
J
