. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R sop.json '{}'; commit $R; B=$(head $R)
put $R sop.json '{"放宽": true}'
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["**"], "protected": ["/sop.json"]}
J
