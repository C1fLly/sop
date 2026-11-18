. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; F=.scratch/jz-1
put $R $F/spec.md "# 记账
## 用户故事
- S1：作为用户我要记一笔账
## 技术
金额用整数分"
put $R $F/issues/01-jine.md "# 01 金额
状态：未开始
依赖：无
覆盖：S1
风险：无
## 要做什么
解析金额
## 验收标准
- [ ] AC1：输入 12.5 显示 12.50 元
## 评论"
put $R $F/cards/01.md "1. [AC1] 输入 12.5；预期显示 12.50 元"; put $R $F/summary.md "记账"; commit $R; K=$(head $R)
sed -i 's/金额用整数分/金额用十进制小数类型/' $R/$F/spec.md; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "confirmed": "$K", "head": "$(head $R)", "fdir": "$F", "mode": "t8"}
J
