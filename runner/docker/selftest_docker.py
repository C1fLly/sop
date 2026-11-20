#!/usr/bin/env python3
"""隔离自检里专用 Docker 的那几项（设计书 16.2、第 19 节第二段验收，v0.9 加的）。会起一个临时的专用 Docker，
要用规定位置的免管理员 Docker（~/tools/docker，M2 装的）。M6 和「系统升级后先重跑隔离自检」都跑它（machine/syscheck.py，3-11）。

1. 借专用 Docker，用三种挂法改 .shared/hooks/post-create、.git/config、.git/hooks：
     普通挂载 / 不连带底下几层的挂载（bind-recursive=disabled）/ 管理员容器（--privileged）把只读的那层摘掉再改。
   每次改完，从宿主这边看是不是真的改成了；改成了的，特权侧「用之前核对」必须发现并拒绝执行。每次之后把现场复原。
2. 经专用 Docker 看不到 ~/tools/sop/state/（AI 状态目录、锁、指纹）和复用 SSH 连接的通道目录（6.2 第一条）。

专用 Docker 用正式的后台服务和分组起（runner/docker/service.py，3-17）：sop-docker-sopdk.service 放在分组 sop-sopdk.slice 里，
和真项目的一模一样，所以测的就是真项目会用的那一套。
跑完收拾干净（3-11 起，因为装机时要在小白的电脑上跑）：假项目在 /tmp 下现建、用完删；~/tools/sop/state/ 下这次用的
那个项目目录、通道目录里放的假通道文件都删掉；服务停掉、登记文件（服务、分组、3-18 加的闲了停的计时器和它的服务）删掉（里面写着 /tmp 下这次的假项目）。留下的只有这个
专用 Docker 的数据 ~/tools/docker-sop/sopdk（拉下来的那个小镜像，下次自检不用再拉）。
拉镜像走网络设置（config/network.json）里的代理；环境变量 SOPD_PROXY 已经给了就用它（service.proxy）。
用法：python3 runner/docker/selftest_docker.py [镜像]（镜像要带 util-linux 的 mount，默认 debian:stable-slim）"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
from kernel import paths, precheck  # noqa: E402
from kernel.errors import Tampered  # noqa: E402
from runner import aistate  # noqa: E402
from runner.docker import service  # noqa: E402
from runner.selftest import make_fixture  # noqa: E402

PROJECT = 'sopdk'          # 这次自检用的项目名：state/sopdk、docker-sop/sopdk、服务 sop-docker-sopdk、分组 sop-sopdk.slice
DOCKER = str(pathlib.Path.home() / 'tools' / 'docker' / 'bin' / 'docker')


def docker(sock, *args, check=False):
    p = subprocess.run([DOCKER, *args], capture_output=True, text=True, env={**os.environ, 'DOCKER_HOST': f'unix://{sock}'})
    if check and p.returncode:
        raise RuntimeError(f'docker {args}: {p.stderr}')
    return p


def snapshot(R):
    out = {}
    for rel in ('.shared/hooks/post-create', '.git/config'):
        out[rel] = hashlib.sha256((R / rel).read_bytes()).hexdigest()
    out['.git/hooks'] = sorted(os.listdir(R / '.git' / 'hooks')) if (R / '.git' / 'hooks').exists() else []
    return out


def restore(R, orig):
    (R / '.shared' / 'hooks' / 'post-create').write_bytes(orig['post-create'])
    (R / '.git' / 'config').write_bytes(orig['config'])
    for n in os.listdir(R / '.git' / 'hooks'):
        if n not in orig['hooks']:
            p = R / '.git' / 'hooks' / n
            p.chmod(0o644); p.unlink()


def cleanup(tmp, rt_file):
    """收拾这次自检在电脑上留下的：/tmp 下的假项目、state 下这个项目的目录（里面有封存成只读的状态目录）、假通道文件。"""
    for d in (tmp, paths.sop_home() / 'state' / PROJECT):
        if os.path.exists(d):
            subprocess.run(['chmod', '-R', 'u+w', str(d)], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)
    try:
        os.unlink(rt_file)
    except FileNotFoundError:
        pass


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else 'debian:stable-slim'
    if os.path.exists(paths.sop_home() / 'state' / PROJECT / 'ai-state'):
        print(f'{paths.sop_home() / "state" / PROJECT} 已经有东西（真有一个叫 {PROJECT} 的项目？），不动它，停下'); return 2
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='sop-selftest-docker-', dir='/tmp'))
    rt_file = paths.runtime_dir() / 'ssh-假的通道'
    try:
        return run(image, tmp, rt_file)
    finally:
        cleanup(tmp, rt_file)


def run(image, tmp, rt_file):
    R, _ = make_fixture(tmp)                          # R = /tmp/sop-selftest-docker-…/Project/demo
    (R / '.git' / 'hooks').mkdir(exist_ok=True)
    precheck.record(PROJECT, R)
    a = aistate.fresh(PROJECT, 'fake', 'T3', lambda d: (d / 'settings.json').write_text('{}'))
    aistate.seal(a)
    rt = rt_file.parent
    rt_file.write_text('')
    orig = {'post-create': (R / '.shared/hooks/post-create').read_bytes(), 'config': (R / '.git/config').read_bytes(),
            'hooks': sorted(os.listdir(R / '.git' / 'hooks'))}
    try:
        sock = str(service.start(PROJECT, R, proxy=service.proxy()))
    except (service.ServiceError, OSError) as e:
        service.remove(PROJECT)
        print('专用 Docker 起不来，停下：', str(e)[-800:]); return 2      # 没有汇总行：syscheck 当成「中途出错」
    try:
        if docker(sock, 'image', 'inspect', image).returncode:
            docker(sock, 'pull', '-q', image, check=True)
        r = str(R)
        mounts = {
            '普通挂载': ['-v', f'{r}:/p'],
            '不连带底下几层（bind-recursive=disabled）': ['--mount', f'type=bind,src={r},dst=/p,bind-recursive=disabled'],
            '管理员容器摘掉只读层': ['--privileged', '-v', f'{r}:/p'],
        }
        unlayer = 'umount -l /p/.shared/cache 2>/dev/null; umount -l /p/.shared 2>/dev/null; umount -l /p/.git 2>/dev/null; '
        attacks = {
            '.shared/hooks/post-create': "echo 'cat ~/.ssh/id_* > /tmp/偷' >> /p/.shared/hooks/post-create",
            '.git/config': "printf '[core]\\n\\tsshCommand = sh -c 偷\\n' >> /p/.git/config",
            '.git/hooks': "printf '#!/bin/sh\\necho 偷\\n' > /p/.git/hooks/pre-push && chmod +x /p/.git/hooks/pre-push",
        }
        rows = []
        for mname, margs in mounts.items():
            for target, cmd in attacks.items():
                pre = unlayer if 'privileged' in ' '.join(margs) else ''
                p = docker(sock, 'run', '--rm', *margs, image, 'sh', '-c', pre + cmd)
                before = {'.shared/hooks/post-create': hashlib.sha256(orig['post-create']).hexdigest(),
                          '.git/config': hashlib.sha256(orig['config']).hexdigest(), '.git/hooks': orig['hooks']}
                changed = snapshot(R)[target] != before[target]
                try:
                    precheck.verify(PROJECT, R, ['main', 'feat-a-1', 'ticket-a-1-01'])
                    caught = False
                except Tampered:
                    caught = True
                if changed:
                    rows.append((f'{mname} 改 {target}：改成了 → 特权侧核对发现并拒绝执行', True, caught))
                else:
                    rows.append((f'{mname} 改 {target}：改不了（{(p.stderr or p.stdout).strip()[-80:]}）；核对照常放行', False, caught))
                restore(R, orig)
        # 看不到状态目录和通道目录：普通容器和管理员容器都把整个根挂进去找
        home = str(pathlib.Path.home())
        for mname, extra in (('普通容器', []), ('管理员容器', ['--privileged'])):
            p = docker(sock, 'run', '--rm', *extra, '-v', '/:/host', image, 'sh', '-c',
                       f'ls -d /host/usr /host{paths.sop_home()}/state /host{home}/tools/sop /host{rt} /host/run/user 2>&1; true')
            lines = [l for l in p.stdout.splitlines() if l.strip()]
            rows.append((f'{mname}把根目录挂进去：对照，看得到 /host/usr（根目录确实挂进去了）', True, '/host/usr' in lines))
            seen = [l for l in lines if 'No such file' not in l and l != '/host/usr']
            rows.append((f'{mname}把根目录挂进去：看不到 ~/tools/sop、state、通道目录、/run/user（看得到的：{seen or "无"}）', [], seen))
        bad = [x for x in rows if x[1] != x[2]]
        for d, want, got in rows:
            print(f'{"符合  " if want == got else "不符合"} {d}')
        print(f'专用 Docker 的隔离自检：{len(rows)} 项，{len(bad)} 项不符合')
        return 1 if bad else 0
    finally:
        service.remove(PROJECT)


if __name__ == '__main__':
    sys.exit(main())
