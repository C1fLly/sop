#!/usr/bin/env python3
"""隔离自检里专用 Docker 的那几项（设计书 16.2、第 19 节第二段验收，v0.9 加的）。**只在虚拟机里跑**（会起专用 Docker）。

1. 借专用 Docker，用三种挂法改 .shared/hooks/post-create、.git/config、.git/hooks：
     普通挂载 / 不连带底下几层的挂载（bind-recursive=disabled）/ 管理员容器（--privileged）把只读的那层摘掉再改。
   每次改完，从宿主这边看是不是真的改成了；改成了的，特权侧「用之前核对」必须发现并拒绝执行。每次之后把现场复原。
2. 经专用 Docker 看不到 ~/tools/sop/state/（AI 状态目录、锁、指纹）和复用 SSH 连接的通道目录（6.2 第一条）。
用法：python3 -m runner.docker.selftest_docker <镜像>（镜像要带 util-linux 的 mount，例如 debian:stable-slim）"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
from kernel import paths, precheck  # noqa: E402
from kernel.errors import Tampered  # noqa: E402
from runner import aistate  # noqa: E402
from runner.selftest import make_fixture  # noqa: E402

PROJECT = 'sopdk'
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


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else 'debian:stable-slim'
    base = pathlib.Path.home() / 'Project'
    shutil.rmtree(base / 'sopdk-fixture', ignore_errors=True)
    (base / 'sopdk-fixture').mkdir(parents=True)
    R, _ = make_fixture(base / 'sopdk-fixture')       # R = ~/Project/sopdk-fixture/Project/demo
    (R / '.git' / 'hooks').mkdir(exist_ok=True)
    precheck.record(PROJECT, R)
    a = aistate.fresh(PROJECT, 'fake', 'T3', lambda d: (d / 'settings.json').write_text('{}'))
    aistate.seal(a)
    rt = paths.runtime_dir(); (rt / 'ssh-假的通道').write_text('')
    orig = {'post-create': (R / '.shared/hooks/post-create').read_bytes(), 'config': (R / '.git/config').read_bytes(),
            'hooks': sorted(os.listdir(R / '.git' / 'hooks'))}
    sock = subprocess.run([str(REPO / 'runner/docker/start_test.sh'), PROJECT, str(R)], capture_output=True, text=True)
    if sock.returncode:
        print('专用 Docker 起不来，停下：', sock.stderr[-800:]); return 2
    sock = sock.stdout.strip()
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
        subprocess.run([str(REPO / 'runner/docker/start_test.sh'), PROJECT, str(R), '停'])


if __name__ == '__main__':
    sys.exit(main())
