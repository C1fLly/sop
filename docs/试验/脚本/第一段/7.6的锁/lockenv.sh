#!/usr/bin/env bash
# 第一段：7.6 路径的受限环境 + v0.6 补的锁（功能目录登记里的 commondir、gitdir 只读；别的功能的目录只读）
R=/tmp/sop-p1-lock/proj
export EXTRA_BINDS="ro:$R/.git rw:$R/.git/objects rw:$R/.git/worktrees ro:$R/.git/worktrees/main ro:$R/.git/worktrees/feat-other ro:$R/.git/worktrees/feat-demo/commondir ro:$R/.git/worktrees/feat-demo/gitdir rw:$R/.git/refs/heads/ticket/demo rw:$R/.git/refs/heads/feat rw:$R/.git/logs/refs/heads/ticket/demo rw:$R/.git/logs/refs/heads/feat ro:$R/main ro:$R/feat-other ro:$R/.shared rw:$R/.shared/notes rw:$R/.shared/broker/requests ro:$R/feat-demo/.git"
export CHDIR=$R/feat-demo EXTRA_PATH=$R/.shared/bin TOOL=none
exec /tmp/sop-spike-ai/sbx.sh $R "$@"
