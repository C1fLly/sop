#!/bin/bash
# 第一段 W27：在 vm-a 里造出「用系统自带方式装的、需要管理员的 Docker」，并放进一些数据（只在虚拟机里）
set -e; . /etc/profile.d/sop-proxy.sh
sudo apt-get update -qq >/dev/null; sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io >/dev/null
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Service]\nEnvironment=HTTP_PROXY=http://10.0.2.2:7890 HTTPS_PROXY=http://10.0.2.2:7890 NO_PROXY=localhost,127.0.0.1\n' | sudo tee /etc/systemd/system/docker.service.d/proxy.conf >/dev/null
sudo systemctl daemon-reload; sudo systemctl restart docker
sudo docker pull -q alpine:3.20 >/dev/null; sudo docker pull -q postgres:17-alpine >/dev/null; sudo docker pull -q busybox:1.36 >/dev/null
# 一个有数据库数据的卷（文件属于容器里的 postgres 账号），和一个有几种属主的普通卷
sudo docker volume create oldproj_pgdata >/dev/null; sudo docker volume create oldproj_files >/dev/null
sudo docker run -d --name oldproj-db -v oldproj_pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=fake postgres:17-alpine >/dev/null
for i in $(seq 1 30); do sudo docker exec oldproj-db pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done; sleep 2
sudo docker exec oldproj-db psql -qU postgres -c "create table leave(id serial primary key, who text, days numeric); insert into leave(who,days) select '员工'||g, g*0.5 from generate_series(1,500) g;"
sudo docker run --rm -v oldproj_files:/d alpine:3.20 sh -c 'echo root的文件 > /d/a.txt; mkdir /d/sub; echo 普通 > /d/sub/b.txt; chown 1000:1000 /d/sub/b.txt; echo 七零 > /d/c.txt; chown 70:70 /d/c.txt; chmod 600 /d/c.txt'
echo "--- 旧 Docker（系统自带方式装的）："; sudo docker version --format '版本 {{.Server.Version}}'; dpkg -S "$(command -v dockerd)"
sudo docker images --format '镜像 {{.Repository}}:{{.Tag}} {{.Size}}'; sudo docker volume ls --format '卷 {{.Name}}'; sudo docker ps --format '运行中 {{.Names}} {{.Image}}'
sudo docker exec oldproj-db psql -tAU postgres -c "select count(*), sum(days) from leave"
