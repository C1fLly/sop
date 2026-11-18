R=/tmp/sop-p1-lock/proj; cd $R/feat-demo
t() { echo "-- $1"; }
for n in 01 02; do
  t "要工单 $n 的目录"; d=$(sopreq new-worktree $n) && echo "   $d"
  cd $d; echo "工单 $n 的改动" > src/t$n.txt; git add -A; git commit -qm "工单 $n" 2>&1 | grep -v packed-refs; echo "   提交：$(git log --oneline -1)"
  cd $R/feat-demo; git merge -q --no-edit ticket/demo/$n 2>&1 | grep -v packed-refs; echo "   本地合并后功能分支：$(git log --oneline -1)"
  t "报告工单 $n 已合入"; sopreq merged $n | sed 's/^/   /'
done
t "试着改功能目录登记里的两个小文件（应只读）"
echo "../../x" > $R/.git/worktrees/feat-demo/commondir 2>&1 | sed 's/^/   /' || true
echo "/x/.git" > $R/.git/worktrees/feat-demo/gitdir 2>&1 | sed 's/^/   /' || true
echo "gitdir: /x" > $R/feat-demo/.git 2>&1 | sed 's/^/   /' || true
t "试着写别的功能的目录、main 目录"
echo x > $R/feat-other/x 2>&1 | sed 's/^/   /' || true; echo x > $R/main/x 2>&1 | sed 's/^/   /' || true
t "工单 03：先把它目录里指向 .git 的小文件改掉（运行中才建的目录，这个文件设不成只读），再报告已合入"
d=$(sopreq new-worktree 03); cd $d; echo x > src/t03.txt; git add -A; git commit -qm "工单 03" 2>&1 | grep -v packed-refs
cd $R/feat-demo; git merge -q --no-edit ticket/demo/03 2>&1 | grep -v packed-refs
echo "gitdir: /tmp/假仓库/.git/worktrees/ticket-demo-03" > $d/.git && echo "   改掉了 $d/.git（预料之中）"
sopreq merged 03 | sed 's/^/   /'
t "改回原样再报告"; echo "gitdir: $R/.git/worktrees/ticket-demo-03" > $d/.git; sopreq merged 03 | sed 's/^/   /'
t "报告全部完成"; sopreq done | sed 's/^/   /'
