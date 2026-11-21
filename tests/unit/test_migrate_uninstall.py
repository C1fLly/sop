"""3-32：环境迁移 Q6（卸载旧的 Docker、切默认指向；设计书 4.8）。从不碰这台电脑上的 Docker 和系统：

- 旧的 Docker 是什么样、残留清单有哪几项，用 3-30 在三台虚拟机里取的命令输出现算（tests/fakes/migrate/，和 Q1 的测试一样）；
- 卸的时候跑的命令全是假的（tests/fakes/system/：sudo、apt-get、dpkg-query、systemctl、groupdel、apparmor_parser；
  tests/fakes/docker/docker 加了默认指向那几个命令），状态都在每个测试自己的临时目录里，「系统」是临时目录造的；
- 每条命令跑之前先核对它是假的（或者是在测试的临时目录、FAKESYS_ROOT 下面动手的 rm、sed），不是就让测试失败，一条都不放过去。
"""
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
from unittest import mock

from machine.migrate import carry as C, flow, inventory as inv, record, uninstall as U
from machine.migrate.dockercli import Daemon
from tests.helpers import REPO
from tests.unit.test_migrate_inventory import NOW, Base as InvBase, touch

FAKES = REPO / 'tests' / 'fakes'
FSYS = FAKES / 'system'
DOCKER = str(FAKES / 'docker' / 'docker')
SYS_HOST = 'unix:///var/run/docker.sock'
SOP_UNIT_TAIL = '''ExecReload=/bin/kill -s HUP $MAINPID
TimeoutSec=0
RestartSec=2
Restart=always
Delegate=yes
Type=notify
NotifyAccess=all
KillMode=mixed

[Install]
WantedBy=default.target
'''


def key(host):
    return re.sub(r'[^A-Za-z0-9.-]', '_', host)


class Q6Base(InvBase):
    def setUp(self):
        super().setUp()
        self.fd = self.tmp / 'fakedocker'
        self.fd.mkdir()
        self.state_f, self.log_f = self.tmp / 'fakesys.json', self.tmp / 'fakesys.log'
        self.tools = self.uhome / 'tools'
        (self.tools / 'docker' / 'bin').mkdir(parents=True)
        (self.tools / 'docker' / 'etc').mkdir()
        os.symlink(DOCKER, self.tools / 'docker' / 'bin' / 'docker')
        self.new_host = f'unix://{self.rt}/docker.sock'
        self.patches = [mock.patch.dict(os.environ, {
            'PATH': f'{FSYS}{os.pathsep}{os.environ["PATH"]}', 'FAKESYS_ROOT': str(self.root), 'FAKESYS_STATE': str(self.state_f),
            'FAKESYS_LOG': str(self.log_f), 'FAKESYS_HOME': str(self.uhome), 'FAKESYS_RUNTIME': str(self.rt),
            'FAKEDOCKER_ROOT': str(self.fd), 'SOP_TOOLS_DIR': str(self.tools), 'TMPDIR': str(self.tmp)}),
            mock.patch.object(tempfile, 'tempdir', str(self.tmp))]
        for x in self.patches:
            x.start()
        # 保险：PATH 里先找到的必须是假的
        for c in ('sudo', 'systemctl', 'apt-get', 'dpkg-query', 'groupdel', 'apparmor_parser'):
            self.assertTrue(os.path.realpath(shutil.which(c)).startswith(str(FSYS) + '/'), c)
        self.said = []

    def tearDown(self):
        for x in reversed(self.patches):
            x.stop()
        super().tearDown()

    # ---- 只放假命令过去 ----
    def safe_run(self, argv, timeout):
        exe = argv[0] if '/' in argv[0] else shutil.which(argv[0])
        real = os.path.realpath(exe or '/nonexistent')
        if not (real.startswith(str(FAKES) + '/') or real.startswith(str(self.tmp) + '/')):
            self.fail(f'Q6 要跑一条不是假的命令：{argv}')
        return U._subprocess(argv, timeout)

    def real_probe(self):
        return inv.Probe(root=str(self.root), home=str(self.uhome), runtime=str(self.rt), run=self.safe_run, admin=None,
                         usage=lambda p: (1000, False), sysdisk=lambda p: True, user='xiaobai', tools=str(self.tools),
                         path_env='', now=NOW)

    def machine(self, **kw):
        kw.setdefault('check', lambda: True)
        return U.Machine(self.real_probe(), run=self.safe_run, sleep=lambda s: None, **kw)

    # ---- 假系统、假 Docker 的状态 ----
    def sys_state(self):
        return json.loads(self.state_f.read_text()) if self.state_f.exists() else {}

    def put_sys(self, st):
        self.state_f.write_text(json.dumps(st))

    def syslog(self):
        return [json.loads(x) for x in self.log_f.read_text().splitlines()] if self.log_f.exists() else []

    def changes(self):
        """跑过的会改东西的系统命令（dpkg-query、systemctl show、apt-get -s 只读，不算）。"""
        return [x for x in self.syslog() if x['cmd'] not in ('dpkg-query', 'sudo')
                and not (x['cmd'] == 'systemctl' and 'show' in x['args'][:2])
                and not (x['cmd'] == 'apt-get' and x['args'][:1] == ['-s'])]

    def dlog(self):
        f = self.fd / 'log'
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def docker_state(self, host):
        f = self.fd / key(host) / 'state.json'
        return json.loads(f.read_text()) if f.exists() else {}

    def put_docker(self, host, st):
        d = self.fd / key(host)
        (d / 'vols').mkdir(parents=True, exist_ok=True)
        (d / 'state.json').write_text(json.dumps(st))

    def contexts(self, current='', extra=None):
        c = self.uhome / '.docker'
        c.mkdir(exist_ok=True)
        (c / 'config.json').write_text(json.dumps({'currentContext': current} if current else {}))
        (c / 'sop-fake-contexts.json').write_text(json.dumps(extra or {}))

    def current_context(self):
        return json.loads((self.uhome / '.docker' / 'config.json').read_text()).get('currentContext') or 'default'

    def seed_system(self, d, pkg_main='docker.io'):
        """按残留清单造假系统：软件包装着、系统服务在跑。"""
        files = {pkg_main: ['/usr/bin/docker']}
        pk = {r['what']: {'version': '1', 'status': 'ii', 'files': files.get(r['what'], [])}
              for r in d['residue'] if r['kind'] == 'package'}
        units = {}
        for r in d['residue']:
            if r['kind'] == 'service':
                owner = 'containerd.io' if pkg_main == 'docker-ce' else 'containerd'
                units[r['what']] = {'LoadState': 'loaded', 'ActiveState': 'active',
                                    'package': owner if r['what'].startswith('containerd') else pkg_main,
                                    'host': SYS_HOST if r['what'] == 'docker.service' else ''}
        self.put_sys({'packages': pk, 'units': units})
        (self.tools / 'docker' / 'etc' / 'docker-host').write_text(self.new_host + '\n')
        self.put_docker(self.new_host, {'images': {}, 'containers': {}, 'volumes': {'shop_pgdata': {'labels': {}}}})
        self.contexts('', {'rootless': self.new_host})

    def system_inv(self, kind='system'):
        self.ce_root() if kind == 'ce' else self.system_root()
        d = inv.inventory(self.probe(kind), tools=[])['docker'][0]
        self.seed_system(d, 'docker-ce' if kind == 'ce' else 'docker.io')
        return d

    def choice(self, d, volumes=None, images=None):
        return {'kind': d['kind'], 'label': d['label'], 'choice': flow.DROP, 'volumes': volumes or {}, 'images': images or {},
                'skipped': []}

    def q6(self, d, answers=('y',), *, ready=True, c=None, started=None, m=None):
        if ready:
            C.save_state({'items': {}, 'ready_for_q6': {d['kind']: True}, 'backup_dir': str(self.tools / 'backup' / 'm')})
        s = flow.Session(self.said.append, flow.Ask(list(answers), say=self.said.append), self.real_probe())
        if started:
            s.started = list(started)
        self.session = s
        rc = U.q6({'docker': [d]}, {'docker': [c or self.choice(d)], 'tools': []}, s, m=m or self.machine())
        return rc, '\n'.join(self.said)


class SystemDocker(Q6Base):
    def test_declined_touches_nothing(self):
        """再确认一次，直接回车 = 不卸：一条会改东西的命令都没跑，旧的、默认指向都不动。"""
        d = self.system_inv()
        rc, out = self.q6(d, answers=('',))
        self.assertEqual(rc, 0, out)
        self.assertIn('好，不卸', out)
        self.assertEqual(self.syslog(), [])
        self.assertTrue((self.root / 'var/lib/docker').exists())
        self.assertEqual(self.current_context(), 'default')
        self.assertEqual(list(self.tmp.glob('sop-migrate-cfg-*')), [])      # 规定位置那份的临时设置目录收拾了
        # 逐条打印了要删什么
        for s in ('Q6 卸载旧的：Ubuntu 软件源装的 Docker（docker.io）', '软件包 containerd（随 Docker 自动装进来的）',
                  '软件包 dnsmasq-base', '/var/lib/containerd', '用户组 docker', '旧 Docker 里的容器', 'old-tool', 'shop-db-1',
                  '要管理员权限的几步，系统会问这台电脑的登录密码'):
            self.assertIn(s, out)

    def test_not_ready_refuses(self):
        """带了数据的那份，carry.json 里没有 ready_for_q6：不卸，连问都不问。"""
        d = self.system_inv()
        rc, out = self.q6(d, ready=False)
        self.assertEqual(rc, 1, out)
        self.assertIn('还没核对通过（Q5），不卸', out)
        self.assertNotIn('Q6 卸载旧的', out)
        self.assertEqual(self.syslog(), [])
        C.save_state({'items': {}, 'ready_for_q6': {d['kind']: False}})
        rc, out = self.q6(d, ready=False)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.syslog(), [])

    def test_stopped_containers_not_back_refuses(self):
        """迁移停掉的旧容器还没起回来：先不卸。"""
        d = self.system_inv()
        record.add_stopped(Daemon(DOCKER, SYS_HOST), ['shop-db-1'])
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('还没起回来', out)
        self.assertEqual(self.syslog(), [])

    def test_docker_io_all_gone(self):
        """docker.io：停服务、卸软件包（一个一个点名，连同随装的 7 个）、删目录、删用户组；残留逐项为空才说卸完了；
        默认指向切到新的；规定位置那份的数据卷还在。"""
        d = self.system_inv()
        n = len(d['residue'])
        rc, out = self.q6(d, started=[(d['label'], ['systemctl', 'stop', 'docker.service'])])
        self.assertEqual(rc, 0, out)
        self.assertIn(f'卸完了：Q1 记下的残留清单 {n} 项逐项又看了一遍，都没有了', out)
        self.assertIn('规定位置的 Docker 仍然正常', out)
        for p in ('var/lib/docker', 'var/lib/containerd', 'etc/docker', 'etc/systemd/system/docker.service.d', 'usr/bin/docker'):
            self.assertFalse((self.root / p).exists(), p)
        self.assertEqual((self.root / 'etc/group').read_text(), 'root:x:0:\nsudo:x:27:xiaobai\n')
        self.assertEqual(self.sys_state()['packages'], {})
        self.assertEqual(self.sys_state()['units'], {})
        ch = self.changes()
        self.assertTrue(all(x['sudo'] for x in ch), ch)
        order = [x['cmd'] + ' ' + x['args'][0] for x in ch]
        self.assertEqual(order, ['systemctl stop', 'apt-get purge', 'groupdel docker', 'systemctl daemon-reload'], order)
        purge = next(x['args'] for x in ch if x['cmd'] == 'apt-get')
        self.assertEqual(sorted(purge[3:]), ['bridge-utils', 'containerd', 'dns-root-data', 'dnsmasq-base', 'docker.io', 'pigz',
                                            'runc', 'ubuntu-fan'])
        sudo = [json.loads(x) for x in self.log_f.read_text().splitlines() if json.loads(x)['cmd'] == 'sudo']
        self.assertTrue(any(x['args'][x['args'].index('rm'):][:3] == ['rm', '-rf', '--'] for x in sudo if 'rm' in x['args']))
        self.assertTrue(all(x['args'][:2] == ['-p', U.ADMIN[2]] for x in sudo))          # 用中文的密码提示
        self.assertEqual(self.current_context(), 'rootless')
        self.assertIn('默认指向切到规定位置的这份了（「rootless」', out)
        self.assertIn('shop_pgdata', self.docker_state(self.new_host)['volumes'])
        self.assertEqual(self.session.started, [])          # 卸掉的那份不用「停回去」了
        res = json.loads((record.migrate_dir() / 'uninstall.json').read_text())['docker.io']
        self.assertEqual((res['left'], res['old_gone'], res['new_ok'], res['pointer']), ([], True, True, 'rootless'))

    def test_runtime_leftovers_removed_and_shared_dir_kept(self):
        """3-33：/run/docker、通道、/opt/containerd、/run/containerd 删掉；/etc/cni/net.d 空的删掉；/etc/cni 里有别的软件的
        东西（另一个目录）就留着，而且不算残留（还是说卸完了）。"""
        self.system_root()
        for x in ('run/docker/netns', 'run/containerd/s', 'opt/containerd/bin', 'etc/cni/net.d', 'etc/cni/other-tool'):
            (self.root / x).mkdir(parents=True)
        touch(self.root / 'etc/cni/other-tool/conf', 'x')
        d = inv.inventory(self.probe('system'), tools=[])['docker'][0]
        self.seed_system(d)
        rc, out = self.q6(d)
        self.assertEqual(rc, 0, out)
        self.assertIn('都没有了', out)
        for x in ('run/docker', 'var/run/docker.sock', 'opt/containerd', 'run/containerd', 'etc/cni/net.d'):
            self.assertFalse(os.path.lexists(self.root / x), x)
        self.assertEqual((self.root / 'etc/cni/other-tool/conf').read_text(), 'x')
        self.assertIn('（不是空的就留着）', out)
        sudo = [json.loads(x)['args'] for x in self.log_f.read_text().splitlines() if json.loads(x)['cmd'] == 'sudo']
        rmdir = [a[a.index('rmdir'):] for a in sudo if 'rmdir' in a]
        self.assertEqual(rmdir, [['rmdir', '--ignore-fail-on-non-empty', '--', str(self.root / 'etc/cni/net.d'),
                                  str(self.root / 'etc/cni')]])
        rm = next(a[a.index('rm'):] for a in sudo if 'rm' in a)
        self.assertNotIn(str(self.root / 'etc/cni'), rm)                    # /etc/cni 不走 rm -rf

    def test_empty_shared_dir_left_is_reported(self):
        """/etc/cni 是空的却没删掉（rmdir 没成）：算还在，不说卸完了。"""
        self.system_root()
        (self.root / 'etc/cni').mkdir(parents=True)
        d = inv.inventory(self.probe('system'), tools=[])['docker'][0]
        self.seed_system(d)
        m = self.machine()
        real_run = m._run

        def run(argv, timeout):          # rmdir 这一条假装没成（什么都不做）
            if 'rmdir' in argv:
                return 0, '', ''
            return real_run(argv, timeout)
        m._run = run
        rc, out = self.q6(d, m=m)
        self.assertEqual(rc, 1, out)
        self.assertIn('/etc/cni', out.split('没卸干净')[1])
        self.assertIn('sudo rmdir /etc/cni', out)

    def test_purge_fails_keeps_data_and_pointer(self):
        """卸软件包没成：不往下删数据目录；残留如实列出、不说卸完了；旧的程序还在，默认指向不动。"""
        d = self.system_inv()
        os.environ['FAKESYS_FAIL'] = r'^apt-get purge'
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertNotIn('卸完了', out)
        self.assertIn('没卸干净', out)
        self.assertIn('软件包 docker.io', out)
        self.assertIn('sudo apt purge docker.io', out)
        self.assertTrue((self.root / 'var/lib/docker').exists())
        self.assertFalse(any(x['cmd'] in ('groupdel',) for x in self.changes()))
        self.assertFalse(any('rm' in x['args'] for x in self.syslog() if x['cmd'] == 'sudo'))
        self.assertIn('旧的程序还在，docker 命令的默认指向不动', out)
        self.assertEqual(self.current_context(), 'default')

    def test_purge_would_take_more_refuses(self):
        """真卸之前 apt-get -s 算出来还会连带卸掉清单上没列的包（清点之后装了依赖 Docker 的软件）：一样都不动，说清楚。"""
        d = self.system_inv()
        st = self.sys_state()
        st['packages']['docker.io']['rdeps'] = ['my-docker-tool']
        self.put_sys(st)
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('还会连带卸掉上面没列的 my-docker-tool', out)
        self.assertNotIn('卸完了', out)
        self.assertEqual(self.changes(), [])
        self.assertTrue((self.root / 'var/lib/docker').exists())
        self.assertEqual(self.current_context(), 'default')

    def test_new_docker_missing_refuses(self):
        """规定位置的 Docker 没装好（找不到 docker-host）：不卸，连问都不问。"""
        d = self.system_inv()
        (self.tools / 'docker' / 'etc' / 'docker-host').unlink()
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('规定位置的 Docker 没装好', out)
        self.assertNotIn('Q6 卸载旧的', out)
        self.assertEqual(self.syslog(), [])

    def test_masked_service_is_left(self):
        """卸完系统服务的登记还在（例如被屏蔽成指向 /dev/null 的）：也算没清掉，如实列出。"""
        d = self.system_inv()
        st = self.sys_state()
        st['units']['docker.socket'] = {'LoadState': 'masked', 'ActiveState': 'inactive', 'package': '', 'host': ''}
        self.put_sys(st)
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('系统服务 docker.socket', out.split('没卸干净')[1])
        self.assertIn('sudo systemctl disable --now docker.socket', out)

    def test_pointer_left_on_kept_docker(self):
        """另一份留着的 Docker（snap 版）也用系统那条通道：卸掉 docker.io 后，默认指向还指着它，不切走。"""
        d = self.system_inv()
        snap = {'kind': 'snap', 'label': inv.LABELS['snap'], 'auto': False, 'admin': True, 'daemon': None, 'dirs': [],
                'residue': [{'kind': 'snap', 'what': 'docker', 'admin': True}]}
        C.save_state({'items': {}, 'ready_for_q6': {d['kind']: True}})
        s = flow.Session(self.said.append, flow.Ask(['y'], say=self.said.append), self.real_probe())
        keep = {'kind': 'snap', 'label': snap['label'], 'choice': flow.KEEP, 'volumes': {}, 'images': {}, 'skipped': []}
        rc = U.q6({'docker': [d, snap]}, {'docker': [self.choice(d), keep], 'tools': []}, s, m=self.machine())
        out = '\n'.join(self.said)
        self.assertEqual(rc, 0, out)
        self.assertIn('卸完了', out)
        self.assertEqual(self.current_context(), 'default')
        self.assertIn('还有你留着的另一份 Docker 在用，不动它', out)

    def test_home_guard(self):
        """测试漏设 HOME（主目录是自测公用的假主目录）：自测的保险挡住，一条命令都不跑。"""
        from kernel import paths
        d = self.system_inv()
        with mock.patch.dict(os.environ, {'HOME': os.environ[paths.TEST_MARK]}):
            with self.assertRaises(paths.HomeGuard):
                self.q6(d)
        self.assertEqual(self.syslog(), [])
        self.assertTrue((self.root / 'var/lib/docker').exists())

    def test_pointer_switched_back_first(self):
        """默认指向事先指着新的：卸之前先切回原来那份；卸到一半停下（软件包没卸掉），它仍指着原来那份。"""
        d = self.system_inv()
        self.contexts('rootless', {'rootless': self.new_host})
        os.environ['FAKESYS_FAIL'] = r'^apt-get purge'
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('先切回原来那份「default」', out)
        self.assertEqual(self.current_context(), 'default')

    def test_group_left_is_reported(self):
        """用户组没删掉：如实列出、给出命令；旧的程序没了，默认指向照样切到新的。"""
        d = self.system_inv()
        os.environ['FAKESYS_FAIL'] = r'^groupdel'
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertNotIn('卸完了', out)
        self.assertIn('下面 1 项还在', out)
        self.assertIn('用户组 docker', out)
        self.assertIn('sudo groupdel docker', out)
        self.assertEqual(self.current_context(), 'rootless')

    def test_cannot_check_packages_is_not_clean(self):
        """卸完查不了软件包（dpkg-query 不回答）：算不空，写「查不了」；看不出旧的程序没了，默认指向不动。"""
        d = self.system_inv()
        os.environ['FAKESYS_FAIL'] = r'^dpkg-query'
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertNotIn('卸完了', out)
        self.assertIn('查不了', out)
        self.assertEqual(self.current_context(), 'default')

    def test_new_docker_broken_is_said(self):
        """规定位置那份检查没过：照实说，不算成功。"""
        d = self.system_inv()
        rc, out = self.q6(d, m=self.machine(check=lambda: False))
        self.assertEqual(rc, 1, out)
        self.assertIn('规定位置的 Docker 现在不正常', out)

    def test_unsafe_paths_are_not_deleted(self):
        """设置文件另指的数据目录落在 ~/tools 里、或者太靠近根：不删，列为残留并写明为什么。"""
        d = self.system_inv()
        (self.tools / 'docker' / 'data').mkdir()
        d['residue'] += [{'kind': 'path', 'what': '~/tools/docker/data', 'admin': True},
                         {'kind': 'path', 'what': '/var', 'admin': True}]
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertTrue((self.tools / 'docker' / 'data').exists())
        self.assertTrue((self.root / 'var').exists())
        self.assertIn('没删：在工具包的目录 ~/tools 里', out)
        self.assertIn('没删：太靠近根目录', out)
        rm = [x['args'] for x in self.syslog() if x['cmd'] == 'sudo' and 'rm' in x['args']]
        self.assertTrue(rm and not any(str(self.tools) in a or a == str(self.root / 'var') for x in rm for a in x))

    def test_unsafe(self):
        m = self.machine()
        for what in ('/', '/var', '/home', '~', '~/tools', '~/tools/docker/data', '/var/lib/../..', 'var/lib/docker', '~/../x'):
            self.assertIsNotNone(U.unsafe(m, what), what)
        for what in ('/var/lib/docker', '/etc/docker', '/data/docker', '~/.local/share/docker', '~/bin/dockerd'):
            self.assertIsNone(U.unsafe(m, what), what)

    def test_docker_ce_sources_and_keys(self):
        """docker-ce：官方软件源文件、钥匙文件、/etc/containerd、/etc/default/docker 都删掉，别的软件源不动。"""
        d = self.system_inv('ce')
        rc, out = self.q6(d)
        self.assertEqual(rc, 0, out)
        for p in ('etc/apt/sources.list.d/docker.sources', 'etc/apt/keyrings/docker.asc', 'etc/containerd', 'etc/default/docker',
                  'var/lib/containerd'):
            self.assertFalse((self.root / p).exists(), p)
        self.assertTrue((self.root / 'etc/apt/sources.list.d/ubuntu.sources').exists())
        purge = next(x['args'] for x in self.changes() if x['cmd'] == 'apt-get')
        self.assertIn('containerd.io', purge)
        self.assertIn('卸完了', out)

    def test_sources_list_line(self):
        """软件源写在 sources.list 里的：只删指向 download.docker.com 的那一行，别的行一字不动。"""
        self.ce_root()
        os.remove(self.root / 'etc/apt/sources.list.d/docker.sources')
        other = 'deb http://archive.ubuntu.com/ubuntu resolute main\n# 注释里提到 download.docker.com 不算\n'
        touch(self.root / 'etc/apt/sources.list',
              'deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu resolute stable\n' + other)
        d = inv.inventory(self.probe('ce'), tools=[])['docker'][0]
        self.assertIn('apt-line', [r['kind'] for r in d['residue']])
        self.seed_system(d, 'docker-ce')
        rc, out = self.q6(d)
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / 'etc/apt/sources.list').read_text(), other)

    def test_leftover(self):
        """以前卸过、东西还留着：没有能连的 Docker，不用 ready_for_q6；清掉设置、目录；默认指向原来指着已经不在的系统通道，切到新的。"""
        for p in ('var/lib/docker', 'etc/docker'):
            (self.root / p).mkdir(parents=True)
        d = {'kind': 'leftover', 'label': inv.LABELS['leftover'], 'auto': True, 'admin': True, 'daemon': None,
             'dirs': [{'path': '/var/lib/docker', 'size_bytes': 4096, 'on_system_disk': True}],
             'residue': [{'kind': 'package', 'what': 'docker.io', 'admin': True, 'note': '卸了，设置文件还在（要连设置一起清掉）'},
                         {'kind': 'path', 'what': '/var/lib/docker', 'admin': True},
                         {'kind': 'path', 'what': '/etc/docker', 'admin': True}]}
        self.put_sys({'packages': {'docker.io': {'status': 'rc'}}})
        (self.tools / 'docker' / 'etc' / 'docker-host').write_text(self.new_host + '\n')
        self.contexts('', {'rootless': self.new_host})
        rc, out = self.q6(d, ready=False)
        self.assertEqual(rc, 0, out)
        self.assertIn('工具包列不出来、也带不走', out)
        self.assertFalse((self.root / 'var/lib/docker').exists())
        self.assertEqual(self.sys_state()['packages'], {})
        self.assertEqual(self.current_context(), 'rootless')

    def test_snap_only_prints_official_steps(self):
        d = {'kind': 'snap', 'label': inv.LABELS['snap'], 'auto': False, 'admin': True, 'daemon': None, 'dirs': [],
             'residue': [{'kind': 'snap', 'what': 'docker', 'admin': True}]}
        rc, out = self.q6(d)
        self.assertEqual(rc, 0, out)
        self.assertIn('sudo snap remove --purge docker', out)
        self.assertEqual(self.syslog(), [])


class RootlessDocker(Q6Base):
    """免管理员但位置不对的（官方一条命令装在 ~/bin、服务名 docker）；规定位置那份用 sop-docker 这个名字和它并存。"""

    def setUp(self):
        super().setUp()
        self.rootless_home()
        h = self.uhome
        # 数据目录里有自己删不掉的东西（容器内部账号的文件）：要借 rootlesskit 删
        locked = h / '.local/share/docker/volumes/x/_data'
        locked.mkdir(parents=True)
        (locked / 'pg').write_text('data')
        os.chmod(locked, 0o555)
        touch(h / 'bin/rootlesskit', f'#!/bin/sh\necho "$@" >> {self.tmp}/rootlesskit.log\nchmod -R u+w "$3" && exec "$@"\n', 0o755)
        touch(h / 'bin/my-script', '#!/bin/sh\n', 0o755)                 # 小白自己的，不是 Docker 的
        self.sop_host = f'unix://{self.rt}/sop-docker/docker.sock'
        tools_exec = f'{self.tools}/docker/bin/dockerd-rootless.sh'
        units = h / '.config/systemd/user'
        touch(units / 'sop-docker.service', '[Unit]\nDescription=Docker (Rootless, SOP: ~/tools/docker)\n\n[Service]\n'
              f'Environment=PATH={self.tools}/docker/bin:/usr/bin:/bin\n' + '\n'.join(U.SOP_UNIT_LINES) + '\n'
              f'ExecStart={tools_exec} --config-file {self.tools}/docker/etc/daemon.json\n' + SOP_UNIT_TAIL)
        (self.tools / 'docker' / 'etc' / 'docker-host').write_text(self.sop_host + '\n')
        self.put_sys({'user_units': {
            'docker.service': {'LoadState': 'loaded', 'ActiveState': 'active', 'host': self.new_host,
                               'exec': f'{h}/bin/dockerd-rootless.sh'},
            'sop-docker.service': {'LoadState': 'loaded', 'ActiveState': 'active', 'host': self.sop_host, 'exec': tools_exec}},
            'stores': {tools_exec: str(self.fd / key(self.sop_host))}})
        self.put_docker(self.new_host, {'images': {}, 'containers': {}, 'volumes': {'oldvol': {'labels': {}}}})       # 旧的
        self.put_docker(self.sop_host, {'images': {}, 'containers': {}, 'volumes': {'shop_pgdata': {'labels': {}}}})  # 规定位置的
        self.contexts('rootless', {'rootless': self.new_host})        # 旧的官方脚本建的默认指向
        self.d = inv.inventory(self.probe('rootless'), tools=[])['docker'][0]

    def test_all_gone_and_name_taken_over(self):
        d = self.d
        self.assertEqual(d['kind'], 'rootless')
        rc, out = self.q6(d)
        self.assertEqual(rc, 0, out)
        h = self.uhome
        self.assertFalse((h / '.local/share/docker').exists())
        self.assertIn('rm -rf', (self.tmp / 'rootlesskit.log').read_text())     # 自己删不掉，借 rootlesskit 删的
        self.assertEqual(sorted(os.listdir(h / 'bin')), ['my-script'])
        apparmor = self.root / f'etc/apparmor.d/{str(h).lstrip("/").replace("/", ".")}.bin.rootlesskit'
        self.assertFalse(apparmor.exists())
        self.assertTrue(any(x['cmd'] == 'apparmor_parser' and x['sudo'] for x in self.syslog()))
        # 接过 docker 这个服务名和通道
        units = h / '.config/systemd/user'
        self.assertFalse((units / 'sop-docker.service').exists())
        self.assertFalse((units / 'docker.service.d').exists())
        text = (units / 'docker.service').read_text()
        self.assertIn(f'ExecStart={self.tools}/docker/bin/dockerd-rootless.sh', text)
        self.assertNotIn('sop-docker', text)
        self.assertEqual((self.tools / 'docker' / 'etc' / 'docker-host').read_text(), self.new_host + '\n')
        st = self.sys_state()['user_units']
        self.assertEqual(sorted(st), ['docker.service'])
        self.assertEqual(st['docker.service']['ActiveState'], 'active')
        self.assertEqual(set(self.docker_state(self.new_host)['volumes']), {'shop_pgdata'})   # 通道上现在是规定位置那份
        self.assertEqual(self.current_context(), 'rootless')
        self.assertIn('接过来了：服务名 docker', out)
        self.assertIn('卸完了', out)
        # 先停旧的、先删数据、再删程序（借旧的 rootlesskit 删数据，所以它要比程序先）
        user = [' '.join(x['args']) for x in self.syslog() if x['cmd'] == 'systemctl' and 'show' not in x['args'][:2]]
        self.assertEqual(user[0], '--user disable --now docker.service')

    def test_helper_record_forgotten(self):
        """上次迁移临时放进旧 Docker 的小镜像没删掉（记录里只剩这一条）：卸掉旧的后记录删掉。
        不然 sop 下次启动会按记录去同一条通道（现在是规定位置那份）删同名的镜像。"""
        record.set_helper(Daemon(DOCKER, self.new_host), C.HELPER)
        rc, out = self.q6(self.d)
        self.assertEqual(rc, 0, out)
        self.assertFalse(record.record_path().exists())
        self.assertTrue(record.recover(self.said.append))
        self.assertFalse(any(x['host'] == self.new_host and x['args'][:2] == ['image', 'rm'] for x in self.dlog()))

    def test_take_over_fails_rolls_back(self):
        """docker.service 起不来：退回原来的 sop-docker，通道文件不改，如实说。"""
        os.environ['FAKESYS_FAIL'] = r'^systemctl --user enable --now docker\.service'
        rc, out = self.q6(self.d)
        self.assertEqual(rc, 1, out)
        self.assertIn('退回原来的 sop-docker', out)
        units = self.uhome / '.config/systemd/user'
        self.assertTrue((units / 'sop-docker.service').exists())
        self.assertFalse((units / 'docker.service').exists())
        self.assertEqual((self.tools / 'docker' / 'etc' / 'docker-host').read_text(), self.sop_host + '\n')
        self.assertEqual(self.sys_state()['user_units']['sop-docker.service']['ActiveState'], 'active')
        self.assertEqual(self.current_context(), 'sop-rootless')     # 旧的已经没了：默认指向切到新的（它还在 sop-docker 的通道上）

    def test_running_without_service_refuses(self):
        d = self.d
        d['residue'] = [r for r in d['residue'] if 'systemd/user' not in r['what']]
        d['daemon']['running'] = True
        rc, out = self.q6(d)
        self.assertEqual(rc, 1, out)
        self.assertIn('不是用后台服务起的', out)
        self.assertEqual(self.changes(), [])


class WholeFlow(Q6Base):
    def test_choose_remove_carry_nothing_then_uninstall(self):
        """sop machine migrate 从头走：选卸、数据卷镜像都不要、再确认一次 → 卸完、默认指向切到新的。"""
        d = self.system_inv()
        answers = ['2'] + ['2'] * len(d['volumes']) + ['2'] * len(d['images']) + ['y']
        rc = flow.migrate(ask=flow.Ask(answers, say=self.said.append), say=self.said.append, inv={'docker': [d], 'tools': []},
                          probe=self.real_probe(), q2_fn=lambda i, say: True, sleep=lambda s: None, machine=self.machine())
        out = '\n'.join(self.said)
        self.assertEqual(rc, 0, out)
        self.assertIn('没有要带走的数据，Q4、Q5 不用做。', out)
        self.assertIn('卸完了', out)
        self.assertEqual(self.current_context(), 'rootless')

    def test_default_keeps_everything(self):
        d = self.system_inv()
        rc = flow.migrate(ask=flow.Ask([], say=self.said.append), say=self.said.append, inv={'docker': [d], 'tools': []},
                          probe=self.real_probe(), q2_fn=lambda i, say: True, sleep=lambda s: None, machine=self.machine())
        self.assertEqual(rc, 0)
        self.assertNotIn('Q6 卸载旧的', '\n'.join(self.said))
        self.assertEqual(self.syslog(), [])
