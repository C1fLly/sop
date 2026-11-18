# 自动调用的 AI 有问题要问：正常结束、什么都没做、交回一个问题（9.3）。格式是对的
. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; B=$(head $R); put $R a.py 1; commit $R; C=$(head $R)
cat > result.json <<J
{"status": "question", "commits": [], "questions": [{"text": "金额要不要支持负数？", "category": "业务"}]}
J
cat > args.json <<J
{"path": "$CASE/result.json", "gitdir": "$R/.git", "base": "$C", "head": "$C", "kind": "impl"}
J
