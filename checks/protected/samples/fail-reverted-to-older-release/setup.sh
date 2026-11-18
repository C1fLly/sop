# 把受保护的文件改回以前放行过的一份较松的内容：最后一条放行不是它，不通过（6.4）
. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R docs/standards/rules.md "第 1 版"; commit $R; git -C $R checkout -qb feat/a-1
put $R docs/standards/rules.md "较松的第 2 版"; commit $R; OLD=$(blob $R HEAD docs/standards/rules.md)
put $R docs/standards/rules.md "第 3 版"; commit $R; NEW=$(blob $R HEAD docs/standards/rules.md)
put $R docs/standards/rules.md "较松的第 2 版"; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "base": "main", "head": "feat/a-1", "patterns": ["docs/standards/**"], "releases": {"docs/standards/rules.md": {"blob": "$NEW", "seq": 2}}}
J
