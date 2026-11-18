# 远程有本地没有的提交（或本地改写了历史）：本地不是远程的延续
. "$TOOLKIT/checks/samples.sh"; repo $CASE/seed; git clone -q --bare $CASE/seed $CASE/remote.git; git clone -q $CASE/remote.git $CASE/local; L=$CASE/local
put $CASE/seed b.txt 远程的; commit $CASE/seed; git -C $CASE/seed push -q $CASE/remote.git main
put $L a.txt 本地的; commit $L
cat > args.json <<J
{"gitdir": "$L/.git", "branch": "main", "local": "$(head $L)"}
J
