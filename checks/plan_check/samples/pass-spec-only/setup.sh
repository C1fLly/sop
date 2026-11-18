. "$TOOLKIT/checks/samples.sh"; W=$CASE/w; F=.scratch/jz-1; mkdir -p $W
put $W $F/spec.md "# 记账
## 用户故事
- S1：作为用户我要记一笔账
- S2：作为用户我要看合计
## 技术
金额用整数分"
ticket() { put $W $F/issues/$1-t.md "# $1 标题
状态：未开始
依赖：$2
覆盖：$3
风险：无
## 要做什么
x
## 验收标准
- [ ] AC1：一
- [ ] AC2：二
## 评论"; }
cat > args.json <<J
{"worktree": "$W", "fdir": "$F", "part": "spec"}
J
