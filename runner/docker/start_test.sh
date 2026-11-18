#!/bin/bash
# 测试用：给一个项目临时起一个专用 Docker（用户级的临时服务，停掉就没了）。正式的后台服务、用时才起、资源分组在第三段做。
# 用法：start_test.sh <项目名> <项目根> [停]
set -euo pipefail
P=$1; PROJ=$2; RD=$HOME/tools/docker-sop/$P; BIN=$HOME/tools/docker/bin; U=sop-docker-test-$P
if [ "${3:-}" = 停 ]; then systemctl --user stop $U 2>/dev/null || true; exit 0; fi
mkdir -p $RD/data $RD/exec $RD/run
cp "$(dirname "$0")/dockerd_wrap.py" $RD/dockerd-wrap.py; chmod +x $RD/dockerd-wrap.py
PX=${SOPD_PROXY:-}
systemctl --user stop $U 2>/dev/null || true; systemctl --user reset-failed $U 2>/dev/null || true
systemd-run --user --unit=$U --property=Delegate=yes --property=KillMode=mixed \
  --setenv=HOME=$HOME --setenv=PATH=$BIN:/usr/bin:/usr/sbin --setenv=XDG_RUNTIME_DIR=$RD/run --setenv=DOCKERD=$RD/dockerd-wrap.py \
  --setenv=SOPD_RD=$RD --setenv=SOPD_PROJ=$PROJ --setenv=SOPD_BIN=$BIN \
  ${PX:+--setenv=HTTP_PROXY=$PX --setenv=HTTPS_PROXY=$PX --setenv=NO_PROXY=localhost,127.0.0.1} \
  $BIN/dockerd-rootless.sh --data-root $RD/data --exec-root $RD/exec --host unix://$RD/run/docker.sock --pidfile $RD/run/docker.pid >/dev/null
for i in $(seq 1 60); do DOCKER_HOST=unix://$RD/run/docker.sock $BIN/docker info >/dev/null 2>&1 && { echo "$RD/run/docker.sock"; exit 0; }; sleep 1; done
echo "专用 Docker 60 秒没起来" >&2; journalctl --user -u $U -n 30 --no-pager >&2; exit 1
