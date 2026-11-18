. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R docs/standards/rules.md "第 1 版"; commit $R; git -C $R checkout -qb feat/a-1
git -C $R rm -q docs/standards/rules.md; commit $R
cat > args.json <<J
{"gitdir": "$R/.git", "base": "main", "head": "feat/a-1", "patterns": ["docs/standards/**"], "releases": {"docs/standards/rules.md": {"blob": "deleted", "seq": 1}}}
J
