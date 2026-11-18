#!/bin/bash
# 第一段 W27：在 vm-b 里造出「免管理员的装法，只是位置不对」：照官方一条命令的装法，程序在 ~/bin，数据在 ~/.local/share/docker（只在虚拟机里）
set -e; . /etc/profile.d/sop-proxy.sh
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq uidmap dbus-user-session >/dev/null
sudo loginctl enable-linger xiaobai   # 让用户级后台服务不登录也能起来（官方说明里的建议做法）
curl -fsSL https://get.docker.com/rootless -o /tmp/rootless.sh
# 官方脚本在新系统上要先有一条系统安全规则才能起；规则按程序的真实路径写
SKIP_IPTABLES=1 FORCE_ROOTLESS_INSTALL=1 sh /tmp/rootless.sh >/tmp/rootless-install.log 2>&1 || true
if ! ~/bin/docker version >/dev/null 2>&1; then
  printf 'abi <abi/4.0>,\ninclude <tunables/global>\n\n"%s/bin/rootlesskit" flags=(unconfined) {\n  userns,\n}\n' "$HOME" | sudo tee /etc/apparmor.d/home.xiaobai.bin.rootlesskit >/dev/null
  sudo systemctl restart apparmor.service
  SKIP_IPTABLES=1 FORCE_ROOTLESS_INSTALL=1 sh /tmp/rootless.sh >>/tmp/rootless-install.log 2>&1
fi
mkdir -p ~/.config/systemd/user/docker.service.d
printf '[Service]\nEnvironment=HTTP_PROXY=http://10.0.2.2:7890 HTTPS_PROXY=http://10.0.2.2:7890 NO_PROXY=localhost,127.0.0.1\n' > ~/.config/systemd/user/docker.service.d/proxy.conf
export XDG_RUNTIME_DIR=/run/user/$(id -u) DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock PATH=$HOME/bin:$PATH
systemctl --user daemon-reload; systemctl --user restart docker; sleep 3
docker pull -q alpine:3.20 >/dev/null; docker pull -q postgres:17-alpine >/dev/null; docker pull -q busybox:1.36 >/dev/null
docker volume create oldproj_pgdata >/dev/null; docker volume create oldproj_files >/dev/null
docker run -d --name oldproj-db -v oldproj_pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=fake postgres:17-alpine >/dev/null
for i in $(seq 1 30); do docker exec oldproj-db pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done; sleep 2
docker exec oldproj-db psql -qU postgres -c "create table leave(id serial primary key, who text, days numeric); insert into leave(who,days) select '员工'||g, g*0.5 from generate_series(1,500) g;"
docker run --rm -v oldproj_files:/d alpine:3.20 sh -c 'echo root的文件 > /d/a.txt; mkdir /d/sub; echo 普通 > /d/sub/b.txt; chown 1000:1000 /d/sub/b.txt; echo 七零 > /d/c.txt; chown 70:70 /d/c.txt; chmod 600 /d/c.txt'
echo "--- 旧 Docker（免管理员，程序在 $(command -v dockerd)，数据在 $(docker info --format '{{.DockerRootDir}}')）："; docker version --format '版本 {{.Server.Version}}'
docker images --format '镜像 {{.Repository}}:{{.Tag}} {{.Size}}'; docker volume ls --format '卷 {{.Name}}'; docker ps --format '运行中 {{.Names}} {{.Image}}'
docker exec oldproj-db psql -tAU postgres -c "select count(*), sum(days) from leave"
