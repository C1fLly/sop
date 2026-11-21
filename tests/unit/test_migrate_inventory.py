"""3-30：环境迁移 Q1 清点（设计书 4.8）。只读：用造出来的命令输出和临时目录里造的「系统」测，不碰这台电脑上的 Docker。

命令输出在 tests/fakes/migrate/ 下，是 2026-11-21 在三台全新的虚拟机（Ubuntu 26.04.1）里取的原样输出
（造法见 tests/vm/migrate-q1-guest.sh 的 --prepare、--capture）：
  system/    Ubuntu 软件源的 docker.io 29.1.3
  ce/        照 Docker 官网装的 docker-ce 29.10.0（官方软件源 docker.sources、钥匙文件 docker.asc）
  rootless/  官方一条命令装的免管理员 Docker 29.10.0（程序在 ~/bin，服务名 docker）；docker.service 是它的服务登记文件
每台里放了同样的东西：镜像 busybox:1.36、alpine:3.20、自己提交出来的 shop-web:dev（带编排文件的项目标签）；
数据卷 shop_pgdata（编排文件的标签）、notes、一个匿名卷；容器 shop-db-1（在运行）、old-tool（停了，容器里有约 3 MB 没放进卷的改动）。
"""
import json
import os
import pathlib
import stat

from machine import locate
from machine.migrate import inventory as inv
from tests.helpers import REPO, TempHome

FX = REPO / 'tests' / 'fakes' / 'migrate'
NOW = inv.parse_time('2026-11-24T06:00:00Z')          # 虚拟机里放东西之后三天
DOCKER_KEYS = {('image', 'ls'): 'images', ('container', 'ls'): 'containers', ('volume', 'ls'): 'volumes',
               ('image', 'inspect'): 'image-inspect', ('container', 'inspect'): 'container-inspect',
               ('volume', 'inspect'): 'volume-inspect', ('system', 'df'): 'df'}
VM_HOME = '/home/xiaobai'


def readonly(argv):
    """清点只许跑这几种只看不改的命令。"""
    a = argv[1:] if argv[0] == 'sudo' else argv
    if a[0] == 'dpkg-query':
        return a[1] in ('-W', '-S')
    if a[0] == 'apt-get':
        return a[1] == '-s'
    if a[0] == 'apt-mark':
        return a[1:] == ['showauto']
    if a[0] == 'systemctl':
        return 'show' in a[1:3]
    if a[0] == 'du':
        return True
    if a[0].endswith('/docker'):
        i = a.index('--host')
        return a[i - 2] == '--config' and tuple(a[i + 2:i + 4]) in DOCKER_KEYS
    return False


class FakeRun:
    """按命令找虚拟机里取的那份输出。over 可以换掉某一份：值是文字（退出码 0）或 (退出码, 输出, 报错)。"""

    def __init__(self, kind, root, home, over=None):
        self.dir, self.root, self.home, self.over = FX / kind, str(root), str(home), over or {}

    def text(self, name):
        if name in self.over:
            v = self.over[name]
            return v if isinstance(v, tuple) else (0, v, '')
        f = self.dir / f'{name}.out'
        if not f.exists():
            return 1, '', f'（测试）没有这一份：{name}'
        return (1 if name == 'dpkg' else 0), f.read_text().replace(VM_HOME, self.home), ''

    def __call__(self, argv, timeout):
        a = argv[1:] if argv[0] == 'sudo' else argv
        if a[0] == 'dpkg-query':
            return self.text('dpkg' if a[1] == '-W' else 'dpkg-S')
        if a[0] == 'apt-get':
            return self.text('autoremove-base' if a[2] == 'autoremove' else 'purge-sim')
        if a[0] == 'apt-mark':
            return self.text('showauto')
        if a[0] == 'systemctl':
            return self.text('systemctl-user-show' if a[1] == '--user' else 'systemctl-show')
        if a[0] == 'du':
            path = a[-1]
            shown = path[len(self.root):] if path.startswith(self.root + '/') else path
            for name in ('du', 'du-home'):
                rc, out, _ = self.text(name)
                for line in out.splitlines():
                    n, p = line.split('\t')
                    if p == shown:
                        return 0, f'{n}\t{path}\n', ''
            return 1, '', f'du: cannot access {path}'
        if a[0].endswith('/docker'):
            i = a.index('--host')
            return self.text(DOCKER_KEYS[tuple(a[i + 2:i + 4])])
        return 99, '', f'（测试）没想到会跑：{argv}'


def touch(p, text='', mode=None):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mode is not None:
        os.chmod(p, mode)
    return p


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / 'sys'
        self.uhome = self.tmp / 'xiaobai'
        self.rt = self.tmp / 'run-user'
        for d in (self.root, self.uhome, self.rt):
            d.mkdir()

    def probe(self, kind, *, admin=('sudo',), over=None):
        root = str(self.root)

        def usage(p):    # 系统盘上 Docker 的数据目录普通用户读不全；别的都是 1000 字节
            return (4096, True) if p.startswith(root + '/var/lib/') else (1000, False)

        self.run = FakeRun(kind, self.root, self.uhome, over)
        return inv.Probe(root=root, home=str(self.uhome), runtime=str(self.rt), run=self.run,
                         admin=list(admin) if admin else None, usage=usage,
                         sysdisk=lambda p: not p.startswith(str(self.uhome)), user='xiaobai',
                         tools=str(self.uhome / 'tools'), path_env='', now=NOW)

    def system_root(self, sock_mode=0o444):
        r = self.root
        for d in ('var/lib/docker', 'var/lib/containerd', 'etc/docker'):
            (r / d).mkdir(parents=True)
        touch(r / 'etc/systemd/system/docker.service.d/proxy.conf', '[Service]\n')
        touch(r / 'usr/bin/docker', '#!/bin/sh\n', 0o755)
        touch(r / 'var/run/docker.sock', '', sock_mode)
        touch(r / 'etc/group', 'root:x:0:\nsudo:x:27:xiaobai\ndocker:x:109:xiaobai\n')

    def ce_root(self):
        self.system_root()
        touch(self.root / 'etc/apt/sources.list.d/docker.sources',
              'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: resolute\nComponents: stable\n'
              'Signed-By: /etc/apt/keyrings/docker.asc\n')
        touch(self.root / 'etc/apt/sources.list.d/ubuntu.sources', 'Types: deb\nURIs: http://archive.ubuntu.com/ubuntu\n')
        touch(self.root / 'etc/apt/keyrings/docker.asc', 'key')
        (self.root / 'etc/containerd').mkdir()
        touch(self.root / 'etc/default/docker', '# docker\n')

    def rootless_home(self, unit=True):
        h = self.uhome
        for b in ('containerd', 'containerd-shim-runc-v2', 'ctr', 'docker', 'docker-init', 'docker-proxy', 'dockerd',
                  'dockerd-rootless-setuptool.sh', 'dockerd-rootless.sh', 'rootlesskit', 'runc'):
            touch(h / 'bin' / b, '#!/bin/sh\n', 0o755)
        (h / '.local/share/docker').mkdir(parents=True)
        if unit:
            touch(h / '.config/systemd/user/docker.service', (FX / 'rootless/docker.service').read_text().replace(VM_HOME, str(h)))
            touch(h / '.config/systemd/user/docker.service.d/proxy.conf', '[Service]\n')
            (h / '.config/systemd/user/default.target.wants').mkdir()
            os.symlink(h / '.config/systemd/user/docker.service', h / '.config/systemd/user/default.target.wants/docker.service')
        touch(self.root / f'etc/apparmor.d/{str(h).lstrip("/").replace("/", ".")}.bin.rootlesskit', 'profile')
        touch(h / '.bashrc', 'export PATH=$HOME/bin:$PATH\nexport DOCKER_HOST=unix:///run/user/1000/docker.sock\n')

    def residue(self, d):
        return [(r['kind'], r['what']) for r in d['residue']]

    def assert_readonly(self, probe):
        bad = [a for a in probe.ran if not readonly(a)]
        self.assertEqual(bad, [], '清点跑了只读以外的命令')


class TestParse(Base):
    def test_dpkg(self):
        """dpkg-query 的输出：只留装着的和「卸了设置还在」的；没装的（un）不要；带架构后缀的去掉。"""
        p = inv.parse_dpkg((FX / 'system/dpkg.out').read_text())
        self.assertEqual(p, {'containerd': ('2.2.2-0ubuntu1.2', 'ii'), 'docker.io': ('29.1.3-0ubuntu4.1', 'ii'),
                             'runc': ('1.4.0-0ubuntu1', 'ii')})
        p = inv.parse_dpkg('docker.io\t29.1.3\trc \ncontainerd:amd64\t2.2\tii \nfoo\t\tun \n')
        self.assertEqual(p, {'docker.io': ('29.1.3', 'rc'), 'containerd': ('2.2', 'ii')})

    def test_apt_sim(self):
        """apt-get -s 的模拟：docker.io 连带 7 个自动装进来的（第一段只认出 5 个，这次多了 dnsmasq-base、dns-root-data）。"""
        got = inv.parse_apt_sim((FX / 'system/purge-sim.out').read_text())
        self.assertEqual(got, ['bridge-utils', 'containerd', 'dns-root-data', 'dnsmasq-base', 'docker.io', 'pigz',
                               'runc', 'ubuntu-fan'])
        self.assertEqual(inv.parse_apt_sim((FX / 'system/autoremove-base.out').read_text()), [])
        self.assertEqual(inv.parse_apt_sim('Remv foo:amd64 [1]\nPurg bar [2]\nInst baz\n'), ['bar', 'foo'])

    def test_systemctl_show(self):
        u = inv.parse_systemctl_show((FX / 'system/systemctl-show.out').read_text())
        self.assertEqual(sorted(u), ['containerd.service', 'docker.service', 'docker.socket'])
        self.assertEqual(u['docker.service']['ActiveState'], 'active')
        u = inv.parse_systemctl_show((FX / 'system/systemctl-user-show.out').read_text())
        self.assertEqual(u['docker.service']['LoadState'], 'not-found')

    def test_sizes_and_times(self):
        cases = {'41.21MB': 41210000, '4.096kB': 4096, '0B': 0, '1.5GB': 1500000000, '12.58MB': 12580000,
                 '2MiB': 2 * 1024 ** 2, 'N/A': None, '': None, None: None}
        for text, n in cases.items():
            self.assertEqual(inv.parse_human_size(text), n, text)
        self.assertEqual(inv.parse_time('2026-11-21T05:51:03.508766505Z'), inv.parse_time('2026-11-21T13:51:03+08:00'))
        self.assertIsNone(inv.parse_time('0001-01-01T00:00:00Z'))
        self.assertIsNone(inv.parse_time('昨天'))

    def test_df(self):
        vols, imgs = inv.parse_df((FX / 'system/df.out').read_text())
        self.assertEqual(vols['shop_pgdata'], 12580000)
        self.assertEqual(len(imgs), 3)
        self.assertEqual(inv.parse_df('坏的'), ({}, {}))

    def test_exec_start(self):
        unit = (FX / 'rootless/docker.service').read_text()
        self.assertEqual(inv.exec_start(unit), '/home/xiaobai/bin/dockerd-rootless.sh  --iptables=false')
        self.assertIsNone(inv.host_in(inv.exec_start(unit)))
        self.assertEqual(inv.host_in('/x/dockerd-rootless.sh --config-file a --host unix:///t/sop-docker/docker.sock'),
                         'unix:///t/sop-docker/docker.sock')
        self.assertEqual(inv.exec_start('[Service]\nExecStart=/a \\\n  -H unix:///s\n'), '/a    -H unix:///s')


class TestSystemDocker(Base):
    def test_docker_io(self):
        """Ubuntu 软件源的 docker.io：认得出、连 /var/lib/containerd 一起量、列出镜像数据卷容器、残留清单齐全。"""
        self.system_root()
        p = self.probe('system')
        r = inv.inventory(p, tools=[])
        self.assertEqual(len(r['docker']), 1)
        d = r['docker'][0]
        self.assertEqual((d['kind'], d['version'], d['auto'], d['admin']), ('docker.io', '29.1.3-0ubuntu4.1', True, True))
        dirs = {e['path']: e for e in d['dirs']}
        self.assertEqual(dirs['/var/lib/containerd']['size_bytes'], 25845760)     # 管理员 du 量的（虚拟机里实测）
        self.assertEqual(dirs['/var/lib/docker']['size_bytes'], 12898304)
        self.assertTrue(all(e['on_system_disk'] for e in d['dirs']))
        self.assertFalse(d['size_partial'])
        self.assertEqual(d['size_bytes'], 12898304 + 25845760 + 1000)          # /etc/docker 读得全，自己量的
        res = self.residue(d)
        for pk in ('docker.io', 'containerd', 'runc', 'bridge-utils', 'pigz', 'ubuntu-fan', 'dnsmasq-base', 'dns-root-data'):
            self.assertIn(('package', pk), res)
        for item in [('service', 'docker.service'), ('service', 'docker.socket'), ('service', 'containerd.service'),
                     ('group', 'docker'), ('path', '/var/lib/docker'), ('path', '/var/lib/containerd'), ('path', '/etc/docker'),
                     ('path', '/etc/systemd/system/docker.service.d')]:
            self.assertIn(item, res)
        self.assertTrue(all(x['admin'] for x in d['residue']))
        self.assertEqual(d['removal_from'], 'apt-get 模拟')
        # 里面的东西
        self.assertTrue(d['listed'])
        imgs = {t: i for i in d['images'] for t in i['tags']}
        self.assertEqual(sorted(imgs), ['alpine:3.20', 'busybox:1.36', 'shop-web:dev'])
        self.assertEqual(imgs['shop-web:dev']['project'], 'shop')                # 镜像自己的标签
        self.assertEqual(imgs['busybox:1.36']['project'], 'shop')                # 用它的容器的标签
        self.assertTrue(imgs['busybox:1.36']['in_use'])
        self.assertEqual(imgs['busybox:1.36']['size_bytes'], 6760000)            # docker system df 的（解开以后的）
        self.assertEqual(imgs['alpine:3.20']['used_by'], ['old-tool'])
        self.assertEqual(imgs['shop-web:dev']['used_by'], [])
        vols = {v['name']: v for v in d['volumes']}
        self.assertEqual(len(vols), 3)
        pg = vols['shop_pgdata']
        self.assertEqual((pg['project'], pg['project_from'], pg['size_bytes'], pg['in_use']), ('shop', 'label', 12580000, True))
        notes = vols['notes']
        self.assertEqual((notes['project'], notes['in_use'], notes['used_by']), ('', False, ['old-tool']))
        self.assertEqual(notes['last_used'], inv.parse_time('2026-11-21T05:51:03.572930212Z'))   # old-tool 停下的时间
        anon = [v for v in vols.values() if v['anonymous']]
        self.assertEqual(len(anon), 1)
        ctrs = {c['name']: c for c in d['containers']}
        self.assertEqual(sorted(ctrs), ['old-tool', 'shop-db-1'])
        self.assertTrue(ctrs['shop-db-1']['running'])
        self.assertEqual((ctrs['shop-db-1']['project'], ctrs['shop-db-1']['service']), ('shop', 'db'))
        self.assertEqual(ctrs['old-tool']['size_rw'], 3158016)
        self.assert_readonly(p)
        # 不在 docker 组里，镜像那些用管理员看；docker 命令总是明说通道
        docker_cmds = [a for a in p.ran if '--host' in a]
        self.assertTrue(docker_cmds and all(a[0] == 'sudo' and f'unix://{inv.SYSTEM_SOCK}' in a for a in docker_cmds))
        text = inv.describe(r, NOW)
        self.assertNotIn('8.2 KB 没放进数据卷的改动', text)                    # 在运行的容器那几 KB 零碎不提醒
        for s in ('Ubuntu 软件源装的 Docker（docker.io） 29.1.3', '/var/lib/containerd', '占系统盘', 'shop_pgdata：12.6 MB；属于项目 shop（编排文件里写的）；正在用',
                  'notes：', '3 天前', '匿名卷', '3.2 MB 没放进数据卷的改动', '软件包 containerd（随 Docker 自动装进来的）',
                  '用户组 docker（组里有 xiaobai）'):
            self.assertIn(s, text)

    def test_no_admin(self):
        """这一次不让用管理员密码：量不全的写「至少」，镜像那些写明要管理员密码，一条 sudo 都不跑。"""
        self.system_root()
        p = self.probe('system', admin=None)
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertTrue(d['size_partial'])
        self.assertFalse(d['listed'])
        self.assertIn('管理员密码', d['why'])
        self.assertFalse(any(a[0] == 'sudo' for a in p.ran))
        self.assertIn('至少', inv.describe({'docker': [d], 'tools': []}, NOW))
        self.assert_readonly(p)

    def test_in_docker_group(self):
        """在 docker 组里（通道能写）：看镜像不用管理员。"""
        self.system_root(sock_mode=0o666)
        p = self.probe('system')
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertTrue(d['listed'])
        self.assertFalse(any(a[0] == 'sudo' and '--host' in a for a in p.ran))

    def test_not_running(self):
        """旧的没在运行：不去连它（系统自带的那种一连通道就会被系统自动起来），写明要它运行才列得出。"""
        self.system_root()
        show = (FX / 'system/systemctl-show.out').read_text().replace('Id=docker.service\nLoadState=loaded\nActiveState=active',
                                                                       'Id=docker.service\nLoadState=loaded\nActiveState=inactive')
        p = self.probe('system', over={'systemctl-show': show})
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertFalse(d['listed'])
        self.assertIn('没在运行', d['why'])
        self.assertFalse(any('--host' in a for a in p.ran))

    def test_apt_sim_fails(self):
        """apt-get -s 用不了时退回第一段实测的那几个（装着的、标着自动装的），并写明是估的。"""
        self.system_root()
        p = self.probe('system', over={'purge-sim': (100, '', 'E: 出错')})
        d = inv.inventory(p, tools=[])['docker'][0]
        pk = [w for k, w in self.residue(d) if k == 'package']
        self.assertEqual(pk, ['bridge-utils', 'containerd', 'docker.io', 'pigz', 'runc', 'ubuntu-fan'])
        self.assertEqual(d['removal_from'], '按第一段实测的那几个估的')

    def test_docker_ce(self):
        """照 Docker 官网装的 docker-ce：官方软件源文件、钥匙文件、containerd.io、/etc/containerd 都进残留清单。"""
        self.ce_root()
        p = self.probe('ce')
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertEqual((d['kind'], d['version']), ('docker-ce', '5:29.10.0-1~ubuntu.26.04~resolute'))
        res = self.residue(d)
        for item in [('package', 'docker-ce'), ('package', 'containerd.io'), ('package', 'docker-ce-rootless-extras'),
                     ('package', 'pigz'), ('path', '/etc/apt/sources.list.d/docker.sources'),
                     ('path', '/etc/apt/keyrings/docker.asc'), ('path', '/etc/containerd'), ('path', '/etc/default/docker'),
                     ('path', '/var/lib/containerd'), ('service', 'containerd.service'), ('group', 'docker')]:
            self.assertIn(item, res)
        self.assertNotIn(('path', '/etc/apt/sources.list.d/ubuntu.sources'), res)
        self.assertEqual(len(d['images']), 3)
        self.assertEqual(len(d['volumes']), 3)
        self.assert_readonly(p)

    def test_sources_list_line_and_signed_by(self):
        """软件源写在 sources.list 里的一行、钥匙文件用 signed-by= 指的：都认得出。"""
        self.ce_root()
        os.remove(self.root / 'etc/apt/sources.list.d/docker.sources')
        os.remove(self.root / 'etc/apt/keyrings/docker.asc')
        touch(self.root / 'etc/apt/sources.list',
              'deb [arch=amd64 signed-by=/usr/share/keyrings/my-docker.gpg] https://download.docker.com/linux/ubuntu resolute stable\n')
        touch(self.root / 'usr/share/keyrings/my-docker.gpg', 'key')
        d = inv.inventory(self.probe('ce'), tools=[])['docker'][0]
        kinds = self.residue(d)
        self.assertIn(('path', '/usr/share/keyrings/my-docker.gpg'), kinds)
        self.assertTrue(any(k == 'apt-line' and '/etc/apt/sources.list' in w for k, w in kinds))

    def test_custom_data_root(self):
        """/etc/docker/daemon.json 里另指了数据目录：一起量、一起进残留清单。"""
        self.system_root()
        touch(self.root / 'etc/docker/daemon.json', '{"data-root": "/data/docker"}')
        (self.root / 'data/docker').mkdir(parents=True)
        d = inv.inventory(self.probe('system'), tools=[])['docker'][0]
        self.assertIn('/data/docker', [e['path'] for e in d['dirs']])
        self.assertIn(('path', '/data/docker'), self.residue(d))

    def test_leftover(self):
        """软件包卸了（还剩设置，rc）、数据目录还在：认成「以前卸过留下的」；containerd 别的软件还在用时不算它的目录。"""
        self.system_root()
        os.remove(self.root / 'usr/bin/docker')
        dpkg = 'docker.io\t29.1.3\trc \ncontainerd\t2.2.2\tii \n'
        p = self.probe('system', over={'dpkg': dpkg})
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertEqual(d['kind'], 'leftover')
        res = self.residue(d)
        self.assertIn(('package', 'docker.io'), res)
        self.assertIn(('path', '/var/lib/docker'), res)
        self.assertNotIn(('path', '/var/lib/containerd'), res)
        self.assertIn('containerd 还有别的软件在用', ' '.join(d['notes']))
        self.assertIsNone(d['daemon'])
        self.assertFalse(any('--host' in a for a in p.ran))

    def test_nothing(self):
        p = self.probe('rootless')            # 这台虚拟机没有系统自带的 Docker
        r = inv.inventory(p, tools=[])
        self.assertEqual(r['docker'], [])
        self.assertIn('没找到不在规定位置的 Docker', inv.describe(r, NOW))


class TestRootless(Base):
    def test_rootless_in_bin(self):
        """官方一条命令装的免管理员 Docker：程序在 ~/bin、数据在 ~/.local/share/docker、服务名 docker；先删数据再删程序。"""
        self.rootless_home()
        p = self.probe('rootless')
        r = inv.inventory(p, tools=[])
        self.assertEqual([d['kind'] for d in r['docker']], ['rootless'])
        d = r['docker'][0]
        self.assertEqual(d['program'], '~/bin')
        self.assertFalse(d['on_system_disk'])
        res = self.residue(d)
        self.assertEqual(res[0], ('path', '~/.local/share/docker'))               # 先删数据
        self.assertIn(('path', '~/bin/dockerd'), res)
        self.assertIn(('path', '~/.config/systemd/user/docker.service'), res)
        self.assertIn(('path', '~/.config/systemd/user/docker.service.d'), res)
        self.assertIn(('path', '~/.config/systemd/user/default.target.wants/docker.service'), res)
        profile = [x for x in d['residue'] if 'apparmor' in x['what']]
        self.assertEqual(len(profile), 1)
        self.assertTrue(profile[0]['admin'])
        self.assertTrue(d['admin'])                                                 # 只因为那条系统安全规则
        self.assertEqual(d['daemon']['host'], f'unix://{self.rt}/docker.sock')
        self.assertTrue(d['daemon']['cli'].endswith('/bin/docker'))
        self.assertTrue(d['listed'])
        self.assertEqual(len(d['containers']), 2)
        self.assertTrue(any('~/.bashrc' in n for n in d['notes']))
        self.assertFalse(any(a[0] == 'sudo' and '--host' in a for a in p.ran))
        self.assert_readonly(p)
        self.assertIn('免管理员的 Docker，但不在规定位置', inv.describe(r, NOW))

    def test_rootless_custom_data_root(self):
        """免管理员那份在 ~/.config/docker/daemon.json 里另指了数据目录：先删它（和默认的数据目录一样排在程序前面）。"""
        self.rootless_home()
        other = self.uhome / 'big/docker-data'
        other.mkdir(parents=True)
        touch(self.uhome / '.config/docker/daemon.json', json.dumps({'data-root': str(other)}))
        d = inv.inventory(self.probe('rootless'), tools=[])['docker'][0]
        res = self.residue(d)
        self.assertEqual(res[:2], [('path', '~/.local/share/docker'), ('path', '~/big/docker-data')])
        self.assertIn('~/big/docker-data', [e['path'] for e in d['dirs']])

    def test_ours_is_not_old(self):
        """规定位置那份（~/tools/docker）自己的服务 docker.service 不算旧的。"""
        h = self.uhome
        touch(h / '.config/systemd/user/docker.service',
              f'[Service]\nExecStart={h}/tools/docker/bin/dockerd-rootless.sh --config-file {h}/tools/docker/etc/daemon.json\n')
        touch(h / 'tools/docker/bin/dockerd', '', 0o755)
        touch(self.rt / 'docker.sock')
        p = self.probe('rootless')
        self.assertEqual(inv.inventory(p, tools=[])['docker'], [])
        self.assertFalse(any('--host' in a for a in p.ran))

    def test_old_unit_without_bin(self):
        """程序不在 ~/bin（docker-ce-rootless-extras 带的），只有服务登记文件指着 /usr/bin/dockerd-rootless.sh：也认得出。"""
        touch(self.uhome / '.config/systemd/user/docker.service', '[Service]\nExecStart=/usr/bin/dockerd-rootless.sh\n')
        d = inv.inventory(self.probe('rootless'), tools=[])['docker'][0]
        self.assertEqual(d['kind'], 'rootless')
        self.assertIn('docker-ce-rootless-extras', d['program'])
        self.assertFalse(d['admin'])

    def test_rootless_and_system_together(self):
        """两份都有：各列各的。"""
        self.system_root()
        self.rootless_home()
        r = inv.inventory(self.probe('system'), tools=[])
        self.assertEqual([d['kind'] for d in r['docker']], ['docker.io', 'rootless'])


class TestSnapDesktop(Base):
    def test_snap(self):
        touch(self.root / 'snap/docker/current/meta/snap.yaml', "name: docker\nversion: '28.4.0'\n")
        (self.root / 'var/snap/docker/common').mkdir(parents=True)
        touch(self.root / 'var/lib/snapd/snaps/docker_3265.snap', 'x')
        d = inv.inventory(self.probe('rootless'), tools=[])['docker'][0]
        self.assertEqual((d['kind'], d['version'], d['auto'], d['admin']), ('snap', '28.4.0', False, True))
        self.assertIn(('snap', 'docker'), self.residue(d))
        self.assertIn('第一版不自动带走', inv.describe({'docker': [d], 'tools': []}, NOW))

    def test_desktop(self):
        (self.uhome / '.docker/desktop/vms/0/data').mkdir(parents=True)
        p = self.probe('rootless', over={'dpkg': 'docker-desktop\t4.50.0-200000\tii \n'})
        d = inv.inventory(p, tools=[])['docker'][0]
        self.assertEqual((d['kind'], d['version'], d['auto']), ('desktop', '4.50.0-200000', False))
        self.assertIn(('package', 'docker-desktop'), self.residue(d))
        self.assertIn(('path', '~/.docker/desktop'), self.residue(d))


class TestOtherTools(Base):
    def test_classify(self):
        """别的工具的另一份：apt 装的、snap 的、主目录里的、系统目录里自己放的，各写明卸载要不要管理员密码。"""
        C = locate.Copy
        copies = [C('/usr/bin/node', '/usr/bin/node', 10), C('/snap/bin/gh', '/usr/bin/snap', 10),
                  C(f'{self.uhome}/.nvm', f'{self.uhome}/.nvm', 10), C('/usr/local/bin/pnpm', '/usr/local/lib/pnpm/pnpm.cjs', 10)]
        p = self.probe('rootless', over={'dpkg-S': 'nodejs: /usr/bin/node\n'})
        got = {c['path']: (c['how'], c['admin']) for c in inv.classify(p, copies)}
        self.assertEqual(got, {'/usr/bin/node': ('package', True), '/snap/bin/gh': ('snap', True),
                               '~/.nvm': ('home', False), '/usr/local/bin/pnpm': ('system-dir', True)})
        dpkg_s = [a for a in p.ran if a[:2] == ['dpkg-query', '-S']]
        self.assertEqual(dpkg_s, [['dpkg-query', '-S', '/usr/bin/node', '/usr/local/lib/pnpm/pnpm.cjs']])

    def test_other_tools_uses_find_others(self):
        from machine import catalog
        tools = [catalog.Tool(name='nvm', what='装 Node', version='', location='~/tools/nvm', check='true',
                              install='script:install/nvm.sh', admin=False, step='M2', elsewhere=('~/.nvm',)),
                 catalog.Tool(name='docker', what='d', version='', location='~/tools/docker', check='true',
                              install='script:install/docker-rootless.sh', admin=True, step='M2', elsewhere=('/usr/bin/docker',))]
        (self.uhome / '.nvm/versions/node/v26/bin').mkdir(parents=True)
        touch(self.uhome / '.nvm/versions/node/v26/bin/node', '', 0o755)
        tools.insert(1, catalog.Tool(name='node', what='Node', version='', location='~/tools/nvm', check='true',
                                     install='script:install/node.sh', admin=False, step='M2', command='node'))
        seen = []

        def find(t, **kw):
            seen.append(t.name)
            return locate.find_others(t, **kw)
        p = self.probe('rootless')
        p.path_env = str(self.uhome / '.nvm/versions/node/v26/bin')
        got = inv.other_tools(p, tools, find=find)
        self.assertEqual(seen, ['nvm', 'node'])               # Docker 另外清点，不在这里
        self.assertEqual(got[0]['copies'][0]['how'], 'home')
        text = inv.describe({'docker': [], 'tools': got}, NOW)
        self.assertIn('nvm：~/.nvm，自己装在主目录里的', text)
        self.assertIn('node：~/.nvm/versions/node/v26/bin/node，自己装在主目录里的（在 ~/.nvm 里面）', text)


class TestSave(Base):
    def test_save(self):
        """存成 ~/tools/sop/config/migrate/inventory.json，只有自己能读。"""
        self.system_root()
        r = inv.inventory(self.probe('system'), tools=[])
        f = inv.save(r)
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(f)).st_mode), 0o700)
        self.assertTrue(str(f).startswith(str(self.home)))
        self.assertEqual(json.loads(pathlib.Path(f).read_text())['docker'][0]['kind'], 'docker.io')
