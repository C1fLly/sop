. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R)
put $R docs/x.md 'x'; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["src/**"], "protected": []}
J
