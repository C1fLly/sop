#!/usr/bin/env bash
# 用法: start.sh <阶段>   脱离终端在后台运行某个阶段，进程号写到 log/pid
cd /tmp/sop-spike-s0; setsid nohup python3 driver.py "$1" > "log/phase-$1.txt" 2>&1 < /dev/null &
echo $! > log/pid; echo "已启动 $1，进程号 $(cat log/pid)"
