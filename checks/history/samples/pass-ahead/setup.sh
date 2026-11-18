. "$TOOLKIT/checks/samples.sh"; repo $CASE/seed; git clone -q --bare $CASE/seed $CASE/remote.git; git clone -q $CASE/remote.git $CASE/local; L=$CASE/local
put $L a.txt 1; commit $L
cat > args.json <<J
{"gitdir": "$L/.git", "branch": "main", "local": "$(head $L)"}
J
