. "$TOOLKIT/checks/samples.sh"; R=$CASE/r; repo $R; put $R .gitignore 'dist/'; commit $R; B=$(head $R)
put $R dist/app.js 'built'; put $R src/a.py 'x'
cat > args.json <<J
{"gitdir": "$R/.git", "worktree": "$R", "base": "$B", "allowed": ["src/**"], "protected": []}
J
