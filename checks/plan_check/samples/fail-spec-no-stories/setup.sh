. "$TOOLKIT/checks/samples.sh"; W=$CASE/w; F=.scratch/jz-1; put $W $F/spec.md "# 记账
## 背景
随便写写"
cat > args.json <<J
{"worktree": "$W", "fdir": "$F", "part": "spec"}
J
