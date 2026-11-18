. "$TOOLKIT/checks/samples.sh"; repo $CASE/seed; P=$CASE/proj; mkdir -p $P/.shared/hooks
git clone -q --bare $CASE/seed $P/.git; git --git-dir=$P/.git worktree add -q $P/main main
git --git-dir=$P/.git worktree add -q -b feat/a-1 $P/feat-a-1 main
cp "$TOOLKIT"/templates/wt/hooks/* $P/.shared/hooks/
mkdir -p $P/.git/hooks; cp /dev/null $P/.git/hooks/pre-commit.sample
args() { S=$(sha256sum $P/.git/config | cut -d" " -f1); [ -n "${1:-}" ] && S=$1
cat > args.json <<J
{"root": "$P", "template": "$TOOLKIT/templates/wt/hooks", "config_sha": "$S", "worktrees": ["main", "feat-a-1"]}
J
}
args; echo '[core]' > $P/.git/worktrees/feat-a-1/config.worktree
