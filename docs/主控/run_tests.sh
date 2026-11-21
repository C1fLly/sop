#!/bin/bash
# 主控窗口用：自己跑全部自测，打出三个数；再拿本机底照比一遍。
# 用法：docs/主控/run_tests.sh <任务编号>      先要有底照：docs/主控/snap.sh > /tmp/sop-orch/snap-base.txt
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p /tmp/sop-orch; log=/tmp/sop-orch/tests-$1.log
cd ~/tools/sop/dev && uv run python tests/run_all.py > "$log" 2>&1; rc=$?
u=$(grep -oE 'Ran [0-9]+ tests' "$log" | sed -n 1p)
s=$(grep -oE 'Ran [0-9]+ tests' "$log" | sed -n 2p)
c=$(grep -oE '总检查：[0-9]+ 个样例，[0-9]+ 个不合格' "$log")
echo "task=$1 exit=$rc unit=[$u] sandbox=[$s] checks=[$c] last=$(tail -1 "$log")"
"$here/snap.sh" > /tmp/sop-orch/snap-now.txt
diff /tmp/sop-orch/snap-base.txt /tmp/sop-orch/snap-now.txt >/dev/null && echo "本机关键文件：和底照一样" || { echo "本机关键文件：和底照不一样！"; diff /tmp/sop-orch/snap-base.txt /tmp/sop-orch/snap-now.txt; }
