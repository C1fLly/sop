#!/bin/bash
# 在 vm-a 里执行：换上改法版的换根脚本，重启 demo1 的专用 Docker，试正常用法和各种越界
P=~/Project/demo1; RD=~/tools/docker-sop/demo1; export DOCKER_HOST=unix://$RD/run/docker.sock; D=~/tools/docker/bin/docker
cp -n $RD/dockerd-wrap.py $RD/dockerd-wrap.py.第一段原版; cp /tmp/wrap-new.py $RD/dockerd-wrap.py; chmod +x $RD/dockerd-wrap.py
echo "[core]" > $P/.git/config
systemctl --user restart sop-docker-demo1
for i in $(seq 40); do $D info >/dev/null 2>&1 && break; sleep 1; done; $D info >/dev/null 2>&1 || { echo "专用 Docker 没起来，停下"; journalctl --user -u sop-docker-demo1 -n 30 --no-pager -o cat | grep -v "^+ " | tail -12; exit 1; }; echo "专用 Docker 就绪（$i 秒）"
ok() { echo "  [$1] $2"; }
echo "== 正常用法（应当都成功）"
$D run --rm -v $P:/p alpine:3.20 sh -c 'echo 测试 > /p/main/out.txt' && ok 成功 "容器往工作目录 main 写文件" || ok 失败 "容器往工作目录 main 写文件"
mkdir -p $P/ticket-x; echo "gitdir: x" > $P/ticket-x/.git
$D run --rm -v $P:/p alpine:3.20 sh -c 'echo 新目录 > /p/ticket-x/out.txt' && ok 成功 "专用 Docker 起来以后才建的工单目录，容器照样能写" || ok 失败 "后建的工单目录"
$D run --rm -v $P/ticket-x:/w alpine:3.20 sh -c 'echo 只挂这一个目录 > /w/out2.txt' && ok 成功 "只把后建的工单目录挂进容器" || ok 失败 "只挂后建的工单目录"
$D run --rm -v $P/.shared/cache:/c alpine:3.20 sh -c 'echo 缓存 > /c/x' && ok 成功 "容器写依赖缓存" || ok 失败 "容器写依赖缓存"
$D run --rm -v $P/.shared:/s alpine:3.20 cat /s/.env >/dev/null && ok 成功 "容器读 .env" || ok 失败 "容器读 .env"
printf 'FROM alpine:3.20\nRUN echo hi > /x\n' | $D build -q -t sop-fix-test - >/dev/null && ok 成功 "构建镜像" || ok 失败 "构建镜像"
cid=$($D run -d -e POSTGRES_PASSWORD=x postgres:17-alpine); for i in $(seq 30); do $D exec $cid pg_isready -q 2>/dev/null && break; sleep 1; done
$D exec $cid psql -U postgres -tAc 'select 40+2' 2>/dev/null | grep -q 42 && ok 成功 "数据库容器起来并能查（${i} 秒）" || ok 失败 "数据库容器"; $D rm -f $cid >/dev/null
$D run --rm --memory 64m alpine:3.20 true 2>&1 | tail -1 | sed 's/^/  （按容器限内存，和第一段一样预期不生效：）/'
echo "== 越界（应当都失败）"
try() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok 挡不住 "$name"; else ok 挡住了 "$name"; fi; }
try "普通容器改钩子"            $D run --rm -v $P:/p alpine:3.20 sh -c 'echo 坏 >> /p/.shared/hooks/post-create'
try "普通容器改 .env"           $D run --rm -v $P:/p alpine:3.20 sh -c 'echo X > /p/.shared/.env'
try "普通容器改封存的状态目录"  $D run --rm -v $P:/p alpine:3.20 sh -c 'chmod u+w /p/.shared/ai-state/claude/F9-1/settings.json && echo h >> /p/.shared/ai-state/claude/F9-1/settings.json'
try "普通容器在 .shared 里新建文件" $D run --rm -v $P:/p alpine:3.20 sh -c 'touch /p/.shared/runs/fake.log'
try "（预期挡不住）管理员容器把 .shared 重挂成可写再改钩子" $D run --rm --privileged -v $P:/p alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; mount -o remount,bind,rw /p/.shared && echo 坏 >> /p/.shared/hooks/post-create'
try "（预期挡不住）管理员容器单独挂 .shared 再重挂成可写" $D run --rm --privileged -v $P/.shared:/s alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; mount -o remount,bind,rw /s && echo 坏 >> /s/hooks/post-create'
try "（预期挡不住）管理员容器摘掉盖在 .shared 上的只读层再改" $D run --rm --privileged -v $P:/p alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; umount -l /p/.shared; echo 坏 >> /p/.shared/hooks/post-create'
try "（预期挡不住）管理员容器把 .git 重挂成可写再改配置" $D run --rm --privileged -v $P/.git:/g alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; mount -o remount,bind,rw /g && echo y >> /g/config'
try "（预期挡不住）管理员容器摘掉盖在 .git 上的只读层" $D run --rm --privileged -v $P:/p alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; umount -l /p/.git; echo y >> /p/.git/config'
try "不递归地挂项目根（底下的只读层不跟过去）再改钩子" $D run --rm --mount type=bind,src=$P,dst=/p,bind-recursive=disabled alpine:3.20 sh -c 'echo 坏 >> /p/.shared/hooks/post-create'
try "（预期挡不住）管理员容器在容器里另挂一份项目根再改" $D run --rm --privileged -v $P:/p alpine:3.20 sh -c 'apk add -q util-linux-misc >/dev/null 2>&1; mkdir /q && mount --bind /p /q && echo 坏 >> /q/.shared/hooks/post-create'
echo "== 外面看（应当都是原样）"
echo "  钩子：$(tail -1 $P/.shared/hooks/post-create)｜.env：$(cat $P/.shared/.env)｜状态目录：$(cat $P/.shared/ai-state/claude/F9-1/settings.json)｜.git/config：$(cat $P/.git/config | tr '\n' ' ')｜runs：$(ls $P/.shared/runs | tr '\n' ' ')"
