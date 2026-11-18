. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R)
put $R '源码/记账.py' 'x=1'; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["源码/**"], "protected": []}
J
