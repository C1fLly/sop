#!/bin/bash
# 第一段：给一个项目建并启动它的专用 Docker（用户级后台服务，开机自己起来）。用法：专用Docker.sh <项目名> [额外的环境变量...]
set -e; P=$1; shift; RD=$HOME/tools/docker-sop/$P; PROJ=$HOME/Project/$P; BIN=$HOME/tools/docker/bin
mkdir -p $RD/data $RD/exec $RD/run $PROJ ~/.config/systemd/user; cp ~/w-sopd/dockerd-wrap.py $RD/dockerd-wrap.py
PX=${SOPD_PROXY:-http://127.0.0.1:7890}
{ echo "[Unit]"; echo "Description=SOP 专用 Docker：$P"
  echo "[Service]"
  echo "Environment=HOME=$HOME PATH=$BIN:/usr/bin:/usr/sbin XDG_RUNTIME_DIR=$RD/run DOCKERD=$RD/dockerd-wrap.py"
  echo "Environment=SOPD_RD=$RD SOPD_PROJ=$PROJ SOPD_BIN=$BIN"
  echo "Environment=HTTP_PROXY=$PX HTTPS_PROXY=$PX NO_PROXY=localhost,127.0.0.1"
  for e in "$@"; do echo "Environment=$e"; done
  echo "ExecStart=$BIN/dockerd-rootless.sh --data-root $RD/data --exec-root $RD/exec --host unix://$RD/run/docker.sock --pidfile $RD/run/docker.pid"
  echo "Restart=on-failure"; echo "Delegate=yes"; echo "KillMode=mixed"
  echo "[Install]"; echo "WantedBy=default.target"; } > ~/.config/systemd/user/sop-docker-$P.service
systemctl --user daemon-reload; systemctl --user enable sop-docker-$P >/dev/null 2>&1; systemctl --user restart sop-docker-$P
for i in $(seq 1 30); do DOCKER_HOST=unix://$RD/run/docker.sock $BIN/docker info >/dev/null 2>&1 && { echo "专用 Docker $P 起来了（$i 秒）"; exit 0; }; sleep 1; done
echo "专用 Docker $P 30 秒没起来"; journalctl --user -u sop-docker-$P -n 20 --no-pager; exit 1
