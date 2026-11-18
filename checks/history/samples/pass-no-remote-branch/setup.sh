. "$TOOLKIT/checks/samples.sh"; repo $CASE/seed; git clone -q --bare $CASE/seed $CASE/remote.git; git clone -q $CASE/remote.git $CASE/local; L=$CASE/local
git -C $L checkout -qb feat/new-1; put $L a.txt 1; commit $L
cat > args.json <<J
{"gitdir": "$L/.git", "branch": "feat/new-1", "local": "$(head $L)"}
J
