#!/usr/bin/env bash
# S7 的受限环境：AI 在整个项目根下活动（设计书 7.6），但下面这些是只读的：
# .git（只放开提交内容、各工作目录的登记、本功能的工单分支指针、集成分支指针）、main 目录、.shared（只放开笔记和请求两个目录）。
# 用法: TOOL=<claude|none> [STATE=..] s7env.sh <命令...>
R=/tmp/sop-spike-s7/proj
export EXTRA_BINDS="ro:$R/.git rw:$R/.git/objects rw:$R/.git/worktrees ro:$R/.git/worktrees/main rw:$R/.git/refs/heads/ticket/jizhang rw:$R/.git/refs/heads/feat rw:$R/.git/logs/refs/heads/ticket/jizhang rw:$R/.git/logs/refs/heads/feat ro:$R/main ro:$R/.shared rw:$R/.shared/notes rw:$R/.shared/broker/requests ro:$R/feat-jizhang/.git"
export CHDIR=$R/feat-jizhang EXTRA_PATH=$R/.shared/bin
exec /tmp/sop-spike-ai/sbx.sh $R "$@"
