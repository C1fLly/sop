#!/usr/bin/env bash
# S9 的受限环境：只放进一张工单的工作目录（可写），.git 用「细的放法」，并把审查人指出的 commondir、gitdir 两个小文件也锁成只读。
# 另外只读地放进 JDK、Maven、Node、Docker 的命令行程序；可写地放进专用的依赖缓存；只给专用 Docker 的通道。
# 用法: [TOOL=claude|none] [NET=1] [INTERACTIVE=1] s9env.sh <工作目录名> <命令...>
P=/tmp/sop-spike-s9/proj; WT=$1; shift; feat=$(echo "$WT" | sed -E 's/^ticket-(.*)-[0-9a-z]+$/\1/')
mkdir -p $P/.git/refs/heads/ticket/$feat $P/.git/logs/refs/heads/ticket/$feat
export EXTRA_BINDS="ro:$P/.git rw:$P/.git/objects rw:$P/.git/worktrees/$WT ro:$P/.git/worktrees/$WT/commondir ro:$P/.git/worktrees/$WT/gitdir rw:$P/.git/refs/heads/ticket/$feat rw:$P/.git/logs/refs/heads/ticket/$feat ro:$P/$WT/.git ro:/home/sanchuanzl/tools/jdk-25.0.5+8 ro:/home/sanchuanzl/tools/maven/wrapper/dists/apache-maven-3.9.16/56ba1f9f ro:/home/sanchuanzl/.nvm/versions/node/v26.13.0 ro:/home/sanchuanzl/tools/docker/bin ro:/tmp/sop-spike-s9/rd/run/docker.sock ${MORE_BINDS:-}"
export EXTRA_MAP="/tmp/sop-spike-s9/cache/m2=/home/sanchuanzl/.m2 /tmp/sop-spike-s9/cache/pnpm-store=/home/sanchuanzl/.local/share/pnpm/store"
export EXTRA_ENV="JAVA_HOME=/home/sanchuanzl/tools/jdk-25.0.5+8 DOCKER_HOST=unix:///tmp/sop-spike-s9/rd/run/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/tmp/sop-spike-s9/rd/run/docker.sock TESTCONTAINERS_RYUK_DISABLED=${RYUK_OFF:-false} CI=true ${MORE_ENV:-}"
export EXTRA_PATH="/home/sanchuanzl/tools/jdk-25.0.5+8/bin:/home/sanchuanzl/tools/maven/wrapper/dists/apache-maven-3.9.16/56ba1f9f/bin:/home/sanchuanzl/tools/docker/bin"
exec /tmp/sop-spike-ai/sbx.sh $P/$WT "$@"
