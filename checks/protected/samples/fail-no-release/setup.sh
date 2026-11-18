. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R docs/standards/rules.md "第 1 版"; commit $R; git -C $R checkout -qb feat/a-1
put $R docs/standards/rules.md "第 2 版"; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "base": "main", "head": "feat/a-1", "patterns": ["docs/standards/**"], "releases": {}}
J
