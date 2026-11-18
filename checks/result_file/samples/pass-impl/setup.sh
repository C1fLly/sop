. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R); put $R a.py 1; commit $R; C=$(head $R)
cat > result.json <<J
{"status": "done", "commits": ["$C"], "commands": [{"cmd": "pytest", "rc": 0}], "deviations": [], "questions": [], "findings": [], "pr_body": "做了金额解析"}
J
cat > args.json <<J
{"path": "$CASE/result.json", "gitdir": "$R/.git", "base": "$B", "head": "$C", "kind": "impl"}
J
