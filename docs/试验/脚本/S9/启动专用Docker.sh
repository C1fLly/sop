#!/usr/bin/env bash
# S9 里启动专供受限侧的 Docker 用的命令（S2 当时没有把这条命令存下来，这次补上）。
# 它是用 Docker 自带的免管理员脚本另起的一个后台程序，通道、数据都另放；启动前由 dockerd-wrap.py 把根目录换成白名单。
# 代理：这个后台程序本身在宿主机的网络里，所以把代理地址用环境变量给它，就能联网拉镜像。
B=/tmp/sop-spike-s9; RD=$B/rd; mkdir -p $RD/run $RD/data $RD/exec $B/rd-newroot
PX=$(printenv https_proxy)
systemd-run --user --unit sop-s9-rd --collect --quiet \
  env -i HOME=$HOME PATH=$HOME/tools/docker/bin:/usr/bin:/usr/sbin XDG_RUNTIME_DIR=$RD/run DOCKERD=$RD/dockerd-wrap.py \
      HTTP_PROXY=$PX HTTPS_PROXY=$PX NO_PROXY=localhost,127.0.0.1 \
  $HOME/tools/docker/bin/dockerd-rootless.sh --data-root $RD/data --exec-root $RD/exec --host unix://$RD/run/docker.sock --pidfile $RD/run/docker.pid
# 停掉：systemctl --user stop sop-s9-rd
