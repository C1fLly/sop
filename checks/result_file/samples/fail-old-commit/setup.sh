# 声称的提交存在，但不是这一步新加的
. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R); put $R a.py 1; commit $R; C=$(head $R)
cat > result.json <<J
{"status": "done", "commits": ["$B"], "pr_body": "x"}
J
cat > args.json <<J
{"path": "$CASE/result.json", "gitdir": "$R/.git", "base": "$B", "head": "$C", "kind": "impl"}
J
