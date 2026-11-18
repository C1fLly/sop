. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R)
put $R src/a.py 'x=1'; commit $R; put $R src/b.py 'y=2'   # 一个提交了、一个没提交
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["src/**"], "protected": ["/sop.json"]}
J
