. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R .gitignore 'tmp/'; commit $R; B=$(head $R)
put $R tmp/CLAUDE.local.md '留话'
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["**"], "protected": []}
J
