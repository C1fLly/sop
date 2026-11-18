. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R docs/standards/rules.md "第 1 版"; commit $R; git -C $R checkout -qb feat/a-1
put $R docs/standards/rules.md "第 2 版"; put $R src/x.py 1; commit $R; BL=$(blob $R HEAD docs/standards/rules.md)
cat > args.json <<J
{"gitdir": "$R/.git", "base": "main", "head": "feat/a-1", "patterns": ["docs/standards/**"], "releases": {"docs/standards/rules.md": {"blob": "$BL", "seq": 1}}}
J
