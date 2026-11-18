. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R); put $R a.py 1; commit $R; C=$(head $R)
cat > result.json <<J
{"status": "done", "findings": [{"text": "函数太长"}]}
J
cat > args.json <<J
{"path": "$CASE/result.json", "gitdir": "$R/.git", "base": "$C", "head": "$C", "kind": "review"}
J
