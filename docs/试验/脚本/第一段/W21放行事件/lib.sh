# 第一段 W21 试验用的小函数
W=/tmp/sop-p1-w21; REL=$W/tools/release.py
blob() { git rev-parse "$1:$2"; }
# 等一个 PR 上指定名字的检查都结束，打印结果。用法：wait_pr <仓库> <PR号> <名字...>
wait_pr() {
  local R=$1 N=$2; shift 2; local t0=$(date +%s) out ok n
  sleep 8
  while true; do
    out=$(gh pr checks $N -R $R --json name,state,bucket,startedAt,completedAt --jq '.[] | "\(.name)\t\(.state)\t\(.bucket)"' 2>/dev/null | sort)
    ok=1; for n in "$@"; do echo "$out" | grep -qP "^$n\t(SUCCESS|FAILURE|SKIPPED|CANCELLED|NEUTRAL)" || ok=0; done
    if [ $ok = 1 ]; then echo "$out" | sed 's/^/    /'; return 0; fi
    if [ $(( $(date +%s) - t0 )) -gt 300 ]; then echo "    等了 300 秒还没结束："; echo "$out" | sed 's/^/    /'; return 1; fi
    sleep 5
  done
}
guard_log() { # 打印某个 PR 最近一次守门检查的输出里关键几行
  local R=$1 N=$2 id
  id=$(gh pr checks $N -R $R --json name,link --jq '.[] | select(.name=="guard") | .link' | sed -E 's#.*/runs/([0-9]+)/job.*#\1#')
  gh run view $id -R $R --log 2>/dev/null | sed -E 's/^[^\t]*\t[^\t]*\t[0-9TZ:.-]+ //' | grep -E '^(PR #|日志分支|  放行|  [^ ].*：|改动|守门检查|PR 改了)' | sed 's/^/    | /'
}
# 改进版：只认在 since（秒）之后开始的检查。用法：wait_pr2 <仓库> <PR号> <since> <名字...>
wait_pr2() {
  local R=$1 N=$2 S=$3; shift 3; local t0=$(date +%s) out ok n
  while true; do
    out=$(gh pr checks $N -R $R --json name,state,startedAt --jq ".[] | select((.startedAt // \"1970-01-01T00:00:00Z\") | fromdateiso8601 >= $S) | \"\(.name)\t\(.state)\"" 2>/dev/null | sort)
    ok=1; for n in "$@"; do echo "$out" | grep -qP "^$n\t(SUCCESS|FAILURE|SKIPPED|CANCELLED|NEUTRAL)" || ok=0; done
    if [ $ok = 1 ]; then echo "$out" | sed 's/^/    /'; return 0; fi
    if [ $(( $(date +%s) - t0 )) -gt 300 ]; then echo "    等了 300 秒还没结束："; echo "$out" | sed 's/^/    /'; return 1; fi
    sleep 5
  done
}
