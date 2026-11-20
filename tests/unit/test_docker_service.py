"""3-17：专用 Docker 的正式后台服务和分组（runner/docker/service.py，设计书 6.3 二）。
只生成文件、不碰服务管理器：登记文件写进 /tmp 的临时目录（SOP_SYSTEMD_USER_DIR），systemctl 换成记下调用的假的。
真的起服务、超内存被杀、隔离自检 13 项在虚拟机里验（tests/vm/dockersvc.sh）。"""
import ast
import json
import os
import pathlib
import stat
import subprocess

from runner.docker import service as S
from tests.helpers import REPO, TempHome, mock_env


class FakeCtl:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, check=True):
        self.calls.append(args)

        class P:
            returncode = 3        # is-active：没在跑
        return P()


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.units = self.tmp / 'units'
        self.tools = self.tmp / 'tools'
        self.h = self.tmp / 'home'
        self.h.mkdir()
        self._e = mock_env({'SOP_SYSTEMD_USER_DIR': str(self.units), 'SOP_TOOLS_DIR': str(self.tools), 'HOME': str(self.h)})
        self._e.__enter__()
        self.root = self.tmp / 'Project' / 'my-app'
        self.root.mkdir(parents=True)

    def tearDown(self):
        self._e.__exit__(None, None, None)
        super().tearDown()

    def files(self, **kw):
        return S.render('my-app', self.root, **kw)


class TestNames(Base):
    def test_service_and_slice_names(self):
        """服务 sop-docker-<项目名>.service；分组 sop-<项目名>.slice，项目名里的「-」写成 \\x2d，免得 sop-my-app 落在 sop-my 下面。"""
        self.assertEqual(S.service_name('demo'), 'sop-docker-demo.service')
        self.assertEqual(S.slice_name('demo'), 'sop-demo.slice')
        self.assertEqual(S.slice_name('my-app'), 'sop-my\\x2dapp.slice')
        self.assertNotEqual(S.slice_name('my-app').removesuffix('.slice').split('-')[:2], ['sop', 'my'])
        for bad in ('My', '../x', 'a b', ''):
            with self.assertRaises(ValueError):
                S.service_name(bad)

    def test_locations(self):
        """数据在 ~/tools/docker-sop/<项目名>/（4.3），通道在它的 run/ 下；程序用规定位置那份 Docker。"""
        self.assertEqual(S.data_dir('demo'), self.tools / 'docker-sop' / 'demo')
        self.assertEqual(S.socket('demo'), self.tools / 'docker-sop' / 'demo' / 'run' / 'docker.sock')
        self.assertEqual(S.docker_bin(), self.tools / 'docker' / 'bin')
        with mock_env({'SOP_SYSTEMD_USER_DIR': '', 'XDG_CONFIG_HOME': ''}):
            self.assertEqual(S.unit_dir(), self.h / '.config' / 'systemd' / 'user')


class TestRender(Base):
    def test_slice_carries_limits(self):
        """处理器的上限设在分组上；内存（3-55）：容器合起来的上限用 SOPD_MEM（字节数）交给换根脚本写在 ctr/ 上，
        分组上是兜底（再多留 512M 给专用 Docker 自己）；不用交换区（超了就被杀，不是慢慢换出去）。"""
        f = self.files(limits={'memory': '300M', 'cpu': '100%'})
        sl = f['sop-my\\x2dapp.slice']
        self.assertIn(f'[Slice]\nMemoryMax={(300 + 512) * 1024 ** 2}\nMemorySwapMax=0\nCPUQuota=100%\n', sl)
        self.assertIn('my-app', sl)
        self.assertIn(f'Environment="SOPD_MEM={300 * 1024 ** 2}"\n', f['sop-docker-my-app.service'])
        f = self.files(limits={'memory': 'infinity'})
        self.assertIn('\nMemoryMax=infinity\n', f['sop-my\\x2dapp.slice'])
        self.assertIn('Environment="SOPD_MEM=max"\n', f['sop-docker-my-app.service'])

    def test_memory_bytes(self):
        """上限换成字节数：和服务管理器一样按 1024 算；百分数按物理内存算；0 不行。"""
        self.assertEqual(S.memory_bytes('300M'), 300 * 1024 ** 2)
        self.assertEqual(S.memory_bytes('2G'), 2 * 1024 ** 3)
        self.assertEqual(S.memory_bytes('4096'), 4096)
        self.assertEqual(S.memory_bytes('100%'), os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE'))
        self.assertIsNone(S.memory_bytes('infinity'))
        for bad in ('0', '0M', '0%'):
            with self.assertRaises(S.ServiceError):
                self.files(limits={'memory': bad})

    def test_service_in_slice_not_autostart(self):
        """服务放进分组；交给它自己管下面的分组（Delegate），停的时候先停主程序；不设成登录后自己起来（用时才起，用户定的）。"""
        sv = self.files()['sop-docker-my-app.service']
        self.assertIn('\nSlice=sop-my\\x2dapp.slice\n', sv)
        for line in ('Delegate=yes', 'DelegateSubgroup=daemon', 'KillMode=mixed', 'Restart=on-failure'):
            self.assertIn(f'\n{line}\n', sv)
        self.assertNotIn('[Install]', sv)
        self.assertNotIn('WantedBy', sv)

    def test_service_starts_wrapped_dockerd(self):
        """经换根脚本起：DOCKERD 指向拷过去的 dockerd-wrap.py，项目根、数据目录、程序目录用环境变量给它；通道在数据目录下。"""
        sv = self.files()['sop-docker-my-app.service']
        rd = self.tools / 'docker-sop' / 'my-app'
        b = self.tools / 'docker' / 'bin'
        for want in (f'"DOCKERD={rd}/dockerd-wrap.py"', f'"SOPD_RD={rd}"', f'"SOPD_PROJ={self.root}"', f'"SOPD_BIN={b}"',
                     f'"XDG_RUNTIME_DIR={rd}/run"', f'"HOME={self.h}"', f'"PATH={b}:/usr/bin:/usr/sbin"',
                     f'ExecStart={b}/dockerd-rootless.sh --data-root {rd}/data --exec-root {rd}/exec '
                     f'--host unix://{rd}/run/docker.sock --pidfile {rd}/run/docker.pid\n'):
            self.assertIn(want, sv)
        # 不把用户的会话通道、钥匙串、SSH 代理这些给它（6.3 二：接上就拆了凭据隔离）
        for bad in ('DBUS_SESSION_BUS_ADDRESS', 'SSH_AUTH_SOCK', '/run/user', 'tools/sop'):
            self.assertNotIn(bad, sv)

    def test_proxy_only_when_given_and_percent_escaped(self):
        """拉镜像的代理用环境变量给后台程序；没有代理就不写。代理里的「%」（账号密码里转写过的字符）写成「%%」。"""
        sv = self.files()['sop-docker-my-app.service']
        self.assertNotIn('PROXY', sv)
        sv = self.files(proxy='http://u:p%40ss@127.0.0.1:7890')['sop-docker-my-app.service']
        self.assertIn('Environment="HTTP_PROXY=http://u:p%%40ss@127.0.0.1:7890"', sv)
        self.assertIn('Environment="HTTPS_PROXY=http://u:p%%40ss@127.0.0.1:7890"', sv)
        self.assertIn('Environment="NO_PROXY=localhost,127.0.0.1"', sv)

    def test_default_limits(self):
        """没给上限时：内存是这台电脑的一半、处理器一半的核（至少 1 核）。"""
        sl = self.files()['sop-my\\x2dapp.slice']
        half = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') // 2
        self.assertIn(f'MemoryMax={half + 512 * 1024 ** 2}\n', sl)
        cores = max(1, (os.cpu_count() or 2) // 2)
        self.assertIn(f'CPUQuota={cores * 100}%\n', sl)

    def test_bad_input_refused(self):
        """上限写法不对、项目根不是完整路径、路径里有空格引号、项目名长到通道路径超长：都不生成。"""
        for lim in ({'memory': '300 MB'}, {'memory': '1e9'}, {'cpu': '1.5'}, {'cpu': '0%'}, {'memory': '300M\nExecStartPre=/bin/x'}):
            with self.assertRaises(S.ServiceError):
                self.files(limits=lim)
        with self.assertRaises(S.ServiceError):
            S.render('my-app', 'Project/my-app')
        for bad in ('a b', 'a"b', 'a%b', 'a$b', 'a\nb'):
            with self.assertRaises(S.ServiceError):
                S.render('my-app', self.tmp / bad)
        with self.assertRaises(S.ServiceError):
            S.render('a' * 63, self.root)


class TestOomScore(Base):
    """3-54：分组超了内存上限时，内核先杀容器、不杀专用 Docker 自己。真的超内存在虚拟机里演（tests/vm/dockersvc.sh）。"""

    def test_service_processes_lowest(self):
        """服务里的进程（rootlesskit、dockerd、containerd）分数设成 100：普通用户能设的最低（系统给用户服务的默认是 200）。"""
        self.assertIn('\nOOMScoreAdjust=100\n', self.files()['sop-docker-my-app.service'])

    def wrap_const(self, name):
        tree = ast.parse((REPO / 'runner' / 'docker' / 'dockerd_wrap.py').read_text())
        for n in tree.body:
            if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == name:
                return ast.literal_eval(n.value)
        self.fail(f'dockerd_wrap.py 里没有 {name}')

    def run_wrapper(self, *args, check=True):
        """用一个假的 runc（只记下收到的参数）跑 runc 外壳（和它用的 spec.py）。没调到 runc 时返回 None。"""
        b = self.tmp / 'bin'
        b.mkdir(exist_ok=True)
        (b / 'args').unlink(missing_ok=True)
        (b / 'runc').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/args"\n')
        (b / 'runc').chmod(0o755)
        (b / 'spec.py').write_text(self.wrap_const('SPEC_PY'))
        w = self.tmp / 'runc-wrap'
        w.write_text(self.wrap_const('RUNC_SH').replace('@BIN@', str(b)).replace('@SOP@', str(b)))
        w.chmod(0o755)
        p = subprocess.run([str(w), *args], capture_output=True, text=True)
        if check:
            self.assertEqual(p.returncode, 0, p.stderr)
        return (b / 'args').read_text().splitlines() if (b / 'args').exists() else None

    def test_wrapper_raises_container_score(self):
        """建容器：--bundle 下 config.json 里的分数（dockerd 给的，等于它自己的）改成 1000；容器的分组指到 ctr/<容器编号>、
        超内存时整个容器一起杀（memory.oom.group，3-55）；别的不动；参数原样交给真的 runc。"""
        bundle = self.tmp / 'bundle'
        bundle.mkdir()
        spec = {'ociVersion': '1.2.1', 'process': {'args': ['sh'], 'oomScoreAdj': 100}, 'root': {'path': 'rootfs'},
                'linux': {'namespaces': [{'type': 'cgroup'}]}}
        (bundle / 'config.json').write_text(json.dumps(spec, separators=(',', ':')))
        args = ['--root', '/x', '--log', '/x/log.json', 'create', '--bundle', str(bundle), '--pid-file', '/x/pid', 'c1']
        self.assertEqual(self.run_wrapper(*args), args)
        got = json.loads((bundle / 'config.json').read_text())
        self.assertEqual(got, {**spec, 'process': {**spec['process'], 'oomScoreAdj': 1000},
                               'linux': {**spec['linux'], 'cgroupsPath': 'ctr/c1',
                                         'resources': {'unified': {'memory.oom.group': '1'}}}})
        # 容器自己要了别的分组位置（例如 --cgroup-parent），也改回 ctr/ 下
        # 原有的资源设置留着，只加 memory.oom.group
        spec['linux']['cgroupsPath'] = '/elsewhere/c2'
        spec['linux']['resources'] = {'pids': {'limit': 100}, 'unified': {'memory.oom.group': '0', 'cpu.weight': '50'}}
        (bundle / 'config.json').write_text(json.dumps(spec))
        self.run_wrapper('create', '--bundle', str(bundle), 'c2')
        lx = json.loads((bundle / 'config.json').read_text())['linux']
        self.assertEqual(lx['cgroupsPath'], 'ctr/c2')
        self.assertEqual(lx['resources'], {'pids': {'limit': 100}, 'unified': {'memory.oom.group': '1', 'cpu.weight': '50'}})

    def test_wrapper_refuses_when_it_cannot_place(self):
        """改不成（容器编号认不出、config.json 坏了或没有）就不交给 runc：不让容器落到 ctr/ 外面、不受上限管。"""
        bundle = self.tmp / 'bundle'
        bundle.mkdir()
        (bundle / 'config.json').write_text('{"process": {}}')
        for cid in ('../x', '-x', ''):
            self.assertIsNone(self.run_wrapper('create', '--bundle', str(bundle), cid, check=False))
        self.assertEqual(json.loads((bundle / 'config.json').read_text()), {'process': {}})
        (bundle / 'config.json').write_text('{坏')
        self.assertIsNone(self.run_wrapper('create', '--bundle', str(bundle), 'c1', check=False))
        self.assertIsNone(self.run_wrapper('create', '--bundle', str(self.tmp / 'nope'), 'c1', check=False))

    def test_wrapper_exec_and_other_commands(self):
        """docker exec 另起的进程（--process 文件）也改成 1000；带空格的写法也认；别的命令（state、kill、delete）什么都不改。"""
        proc = self.tmp / 'process.json'
        proc.write_text('{"args": ["ls"], "oomScoreAdj": 200}')
        self.run_wrapper('exec', '--process', str(proc), '--detach', 'c1')
        self.assertEqual(json.loads(proc.read_text())['oomScoreAdj'], 1000)
        other = self.tmp / 'other.json'
        other.write_text('{"oomScoreAdj":200}')
        self.assertEqual(self.run_wrapper('kill', str(other), 'KILL'), ['kill', str(other), 'KILL'])
        self.assertEqual(other.read_text(), '{"oomScoreAdj":200}')

    def test_wrap_makes_container_group(self):
        """换根脚本（3-55）：认准自己在服务分组的 daemon/ 里，打开服务分组下一层的开关，建 ctr/、写内存上限、不用交换区。
        真的分组在虚拟机里验（tests/vm/dockersvc.sh）。"""
        src = (REPO / 'runner' / 'docker' / 'dockerd_wrap.py').read_text()
        for want in ("os.path.basename(own) != 'daemon'", "f'{SVC}/cgroup.subtree_control'", "CTR = SVC + '/ctr'",
                     "(('memory.max', MEM), ('memory.swap.max', '0'))", "os.environ['SOPD_MEM']"):
            self.assertIn(want, src)

    def test_wrapper_registered_as_default_runtime(self):
        """换根脚本把它放进新根、只读，并设成专用 Docker 默认的运行时。"""
        src = (REPO / 'runner' / 'docker' / 'dockerd_wrap.py').read_text()
        self.assertIn("ro(f'{NR}/sop')", src)
        self.assertIn("os.chmod(f'{NR}/sop/spec.py', 0o444)", src)
        self.assertIn("'--add-runtime', 'sop-runc=/sop/runc', '--default-runtime', 'sop-runc'", src)


class TestInstall(Base):
    def test_install_writes_once(self):
        """写四份登记文件（只有自己能读：里面可能有代理的账号密码）、拷换根脚本、建数据目录；
        再装一次什么都不改（内容、修改时间都不动，也不让服务管理器重读）。"""
        ctl = FakeCtl()
        self.assertTrue(S.install('my-app', self.root, {'memory': '300M'}, ctl=ctl))
        self.assertEqual(ctl.calls, [('daemon-reload',)])
        sv, sl = self.units / 'sop-docker-my-app.service', self.units / 'sop-my\\x2dapp.slice'
        for f in (sv, sl):
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        rd = self.tools / 'docker-sop' / 'my-app'
        wrap = rd / 'dockerd-wrap.py'
        self.assertEqual(wrap.read_text(), (REPO / 'runner' / 'docker' / 'dockerd_wrap.py').read_text())
        self.assertEqual(stat.S_IMODE(wrap.stat().st_mode), 0o700)
        for d in ('data', 'exec', 'run'):
            self.assertTrue((rd / d).is_dir())
        self.assertEqual(stat.S_IMODE(rd.stat().st_mode), 0o700)
        mt = [f.stat().st_mtime_ns for f in (sv, sl, wrap)]
        self.assertFalse(S.install('my-app', self.root, {'memory': '300M'}, ctl=ctl))
        self.assertEqual(ctl.calls, [('daemon-reload',)])
        self.assertEqual([f.stat().st_mtime_ns for f in (sv, sl, wrap)], mt)
        self.assertEqual(sorted(os.listdir(self.units)), ['sop-docker-my-app.service', 'sop-idle-my-app.service',
                                                          'sop-idle-my-app.timer', 'sop-my\\x2dapp.slice'])

    def test_change_limit_rewrites(self):
        """改了上限、手改过登记文件：按工具包的重写，再让服务管理器重读。"""
        ctl = FakeCtl()
        S.install('my-app', self.root, {'memory': '300M'}, ctl=ctl)
        self.assertTrue(S.install('my-app', self.root, {'memory': '1G'}, ctl=ctl))
        self.assertIn(f'MemoryMax={(1024 + 512) * 1024 ** 2}\n', (self.units / 'sop-my\\x2dapp.slice').read_text())
        sv = self.units / 'sop-docker-my-app.service'
        sv.write_text(sv.read_text() + 'ExecStartPost=/bin/sh -c 偷\n')
        self.assertTrue(S.install('my-app', self.root, {'memory': '1G'}, ctl=ctl))
        self.assertNotIn('偷', sv.read_text())
        self.assertEqual(ctl.calls, [('daemon-reload',)] * 3)

    def test_two_projects_separate(self):
        """两个项目各一套，名字不重、数据目录不重、分组不互相包含。"""
        ctl = FakeCtl()
        other = self.tmp / 'Project' / 'my'
        other.mkdir()
        S.install('my-app', self.root, ctl=ctl)
        S.install('my', other, ctl=ctl)
        self.assertEqual(sorted(x for x in os.listdir(self.units) if not x.startswith('sop-idle-')),
                         ['sop-docker-my-app.service', 'sop-docker-my.service', 'sop-my.slice', 'sop-my\\x2dapp.slice'])
        self.assertIn('sop-docker-my.service', (self.units / 'sop-idle-my.service').read_text())
        self.assertIn('Slice=sop-my.slice\n', (self.units / 'sop-docker-my.service').read_text())
        self.assertIn(f'"SOPD_PROJ={other}"', (self.units / 'sop-docker-my.service').read_text())

    def test_names_never_collide_across_projects(self):
        """3-19：任意两个不同的项目，四份登记文件的名字没有一个相同（3-18 原来的计时器名 sop-docker-<项目名>-idle 和
        项目 <项目名>-idle 的专用 Docker 服务同名，装一个会盖掉另一个）；装两个、删一个，另一个的四份一份不少、内容不变。"""
        names = ['a', 'app', 'app-idle', 'idle', 'idle-app', 'docker', 'docker-app', 'my', 'my-app', 'my-app-idle', 'x2d', 'sop']
        seen = {}
        for n in names:
            for f in self.files() if n == 'my-app' else S.render(n, self.root):
                self.assertNotIn(f, seen, f'{n} 和 {seen.get(f)} 都有 {f}')
                seen[f] = n
        ctl = FakeCtl()
        S.install('app', self.root, ctl=ctl)
        before = {f: (self.units / f).read_text() for f in os.listdir(self.units)}
        other = self.tmp / 'Project' / 'app-idle'
        other.mkdir()
        S.install('app-idle', other, ctl=ctl)
        self.assertEqual(len(os.listdir(self.units)), 8)
        for f, t in before.items():
            self.assertEqual((self.units / f).read_text(), t, f)
        S.remove('app-idle', ctl=ctl)
        self.assertEqual({f: (self.units / f).read_text() for f in os.listdir(self.units)}, before)

    def test_remove_keeps_data(self):
        """删掉：停服务（连同闲了停的计时器）、删四份登记文件、让服务管理器重读；数据目录（镜像、数据卷）不动。"""
        ctl = FakeCtl()
        S.install('my-app', self.root, ctl=ctl)
        (self.tools / 'docker-sop' / 'my-app' / 'data' / '镜像').write_text('x')
        ctl.calls.clear()
        S.remove('my-app', ctl=ctl)
        self.assertEqual(os.listdir(self.units), [])
        self.assertEqual(ctl.calls[0], ('stop', 'sop-docker-my-app.service', 'sop-idle-my-app.timer'))
        self.assertIn(('daemon-reload',), ctl.calls)
        self.assertTrue((self.tools / 'docker-sop' / 'my-app' / 'data' / '镜像').exists())
        ctl.calls.clear()
        S.remove('my-app', ctl=ctl)                      # 再删一次：没有登记文件，不重读
        self.assertNotIn(('daemon-reload',), ctl.calls)

    def test_start_gives_up_and_says_why(self):
        """起不来（这里没有 Docker 程序）：等到时候说清楚是哪个服务没起来，不卡住。"""
        ctl = FakeCtl()
        with self.assertRaises(S.ServiceError) as c:
            S.start('my-app', self.root, ctl=ctl, wait=1)
        self.assertIn('sop-docker-my-app.service', str(c.exception))
        self.assertIn('免管理员 Docker 没装', str(c.exception))
        self.assertIn(('start', '--no-block', 'sop-docker-my-app.service'), ctl.calls)


class TestSelftestUsesService(Base):
    def test_no_more_temporary_unit(self):
        """隔离自检里专用 Docker 那份用正式的服务和分组起（3-11 留下的），第二段的临时启动办法删了。"""
        src = (REPO / 'runner' / 'docker' / 'selftest_docker.py').read_text()
        self.assertIn('service.start(PROJECT', src)
        self.assertIn('service.remove(PROJECT)', src)
        self.assertNotIn('start_test', src)
        self.assertFalse((REPO / 'runner' / 'docker' / 'start_test.sh').exists())


class TestIdle(Base):
    """3-18：用时才起、闲了停（用户定的：sop 退出后 15 分钟没再用就停）。真的起、停、再起在虚拟机里验（tests/vm/dockersvc.sh）。"""

    def test_timer_units(self):
        """专用 Docker 起来时把计时器带起来（Wants）、它停了计时器跟着停（PartOf）；每分钟跑一次闲了停的脚本；
        两份都不设成登录后自己起来。脚本在数据目录（专用 Docker 的视野里没有），「在用」锁在 state 下。"""
        f = self.files()
        sv, tm, isv = f['sop-docker-my-app.service'], f['sop-idle-my-app.timer'], f['sop-idle-my-app.service']
        self.assertIn('\nWants=sop-idle-my-app.timer\n', sv)
        self.assertIn('\nPartOf=sop-docker-my-app.service\n', tm)
        for line in ('OnActiveSec=60', 'OnUnitActiveSec=60'):
            self.assertIn(f'\n{line}\n', tm)
        rd = self.tools / 'docker-sop' / 'my-app'
        lock = self.home / 'state' / 'my-app' / 'docker.lock'
        self.assertIn(f'\nType=oneshot\nExecStart={rd}/idle-stop.sh sop-docker-my-app.service {lock} 900\n', isv)
        for t in (sv, tm, isv):
            self.assertNotIn('[Install]', t)
        self.assertIn(' 60\n', self.files(idle=60)['sop-idle-my-app.service'])
        for bad in (0, -1, '900', 8 * 24 * 3600):
            with self.assertRaises(S.ServiceError):
                self.files(idle=bad)

    def test_install_copies_idle_script(self):
        S.install('my-app', self.root, ctl=FakeCtl())
        sh = self.tools / 'docker-sop' / 'my-app' / 'idle-stop.sh'
        self.assertEqual(sh.read_text(), S.IDLE_SH)
        self.assertEqual(stat.S_IMODE(sh.stat().st_mode), 0o700)
        for n in os.listdir(self.units):
            self.assertEqual(stat.S_IMODE((self.units / n).stat().st_mode), 0o600)

    def run_idle(self, lock, idle=900):
        """用一个假的 systemctl（只记下参数）跑闲了停的脚本，返回它要停的东西（没停就是空的）。"""
        b = self.tmp / 'bin'
        b.mkdir(exist_ok=True)
        (b / 'systemctl').write_text('#!/bin/sh\nprintf "%s " "$@" >> "$(dirname "$0")/stopped"\n')
        (b / 'systemctl').chmod(0o755)
        sh = self.tmp / 'idle-stop.sh'
        sh.write_text(S.IDLE_SH)
        sh.chmod(0o755)
        (b / 'stopped').unlink(missing_ok=True)
        p = subprocess.run([str(sh), 'sop-docker-my-app.service', str(lock), str(idle)], capture_output=True, text=True,
                           env={**os.environ, 'PATH': f'{b}:/usr/bin:/bin'})
        self.assertEqual(p.returncode, 0, p.stderr)
        return (b / 'stopped').read_text() if (b / 'stopped').exists() else ''

    def test_idle_script(self):
        """没有锁文件（没经 sop 用过）不管；有 sop 拿着「在用」锁不停；最后一次用完不到时间不停；够了就停。"""
        lock = self.tmp / 'docker.lock'
        self.assertEqual(self.run_idle(lock), '')
        lock.write_text('')
        old = lock.stat().st_mtime - 901
        os.utime(lock, (old, old))
        import fcntl
        fd = os.open(lock, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_SH)
        self.assertEqual(self.run_idle(lock), '')                   # 有 sop 在用
        os.close(fd)
        self.assertEqual(self.run_idle(lock), '--user stop sop-docker-my-app.service ')
        os.utime(lock)
        self.assertEqual(self.run_idle(lock), '')                   # 刚用完
        os.utime(lock, (old, old))
        self.assertEqual(self.run_idle(lock, idle=1000), '')        # 闲多久停按参数（901 秒 < 1000 秒）

    def test_use_holds_shared_lock(self):
        """use()：拿共享的「在用」锁（几个 sop 可以同时用；闲了停的脚本拿不到独占锁就不停），起来，返回通道；
        release() 放开锁并把修改时间记成最后一次用完；起不来时锁也放开。"""
        import fcntl
        from unittest import mock
        lock = self.home / 'state' / 'my-app' / 'docker.lock'
        with mock.patch.object(S, 'start', return_value='/x/docker.sock') as st:
            a = S.use('my-app', self.root, {'memory': '1G'}, 'http://p:1')
            b = S.use('my-app', self.root)
        self.assertEqual(a.sock, '/x/docker.sock')
        self.assertEqual(st.call_args_list[0].args[:4], ('my-app', self.root, {'memory': '1G'}, 'http://p:1'))
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

        def free():
            fd = os.open(lock, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False
            finally:
                os.close(fd)
        self.assertFalse(free())
        a.release()
        self.assertFalse(free())                                   # b 还在用
        os.utime(lock, (1, 1))
        b.touch()
        self.assertGreater(lock.stat().st_mtime, 1)
        os.utime(lock, (1, 1))
        b.release()
        b.release()                                                # 放两次不出错
        self.assertTrue(free())
        self.assertGreater(lock.stat().st_mtime, 1)
        with mock.patch.object(S, 'start', side_effect=S.ServiceError('起不来')):
            with self.assertRaises(S.ServiceError):
                S.use('my-app', self.root)
        self.assertTrue(free())

    def test_limits_from_profile(self):
        """上限从技术栈档案 toolchain.toml 的 [docker] 段来：只认 memory、cpu。"""
        self.assertEqual(S.check_limits(None), {})
        self.assertEqual(S.check_limits({'memory': '2G'}), {'memory': '2G'})
        for bad in ({'memory': '2G', 'swap': '1G'}, ['2G'], 'yes'):
            with self.assertRaises(S.ServiceError):
                S.check_limits(bad)


class TestEngineUsesDocker(Base):
    """sop 在要运行项目代码的地方才起专用 Docker（档案有 [docker] 段时），一个进程只起一次，退出时放开。"""

    def engine(self, toolchain):
        from kernel.engine import Engine

        class P:
            name, root = 'my-app', self.root

            def profile(self_):
                return {'toolchain': toolchain, 'commands': {}} if toolchain is not None else None
        return Engine(P(), None, None)

    def test_only_when_profile_wants_it(self):
        from unittest import mock
        with mock.patch.object(S, 'use') as use:
            self.assertIsNone(self.engine(None).docker())
            self.assertIsNone(self.engine({'ro': []}).docker())
        use.assert_not_called()

    def test_once_per_process_and_released(self):
        from unittest import mock
        lease = mock.Mock(sock='/x/docker.sock')
        e = self.engine({'docker': {'memory': '2G'}})
        with mock.patch.object(S, 'use', return_value=lease) as use, mock.patch.object(S, 'proxy', return_value=''):
            self.assertEqual(e.docker(), '/x/docker.sock')
            self.assertEqual(e.docker(), '/x/docker.sock')
        use.assert_called_once_with('my-app', self.root, {'memory': '2G'}, '')
        lease.touch.assert_called_once()
        e.release_docker()
        e.release_docker()
        lease.release.assert_called_once()
        with self.assertRaises(S.ServiceError):
            self.engine({'docker': {'swap': '1G'}}).docker()

    def test_wired_into_steps(self):
        """装依赖、门禁、工单上的实现给通道；规划、只看不改的 AI 步骤不给；run() 收尾时放开。"""
        from kernel import steps
        self.assertEqual(steps.DOCKER_KINDS, ('ticket_impl', 'implement_spec'))
        src = (REPO / 'kernel' / 'steps.py').read_text()
        self.assertEqual(src.count('docker_sock=eng.docker(prof)'), 2)
        self.assertIn('docker_sock=eng.docker() if kind in DOCKER_KINDS else None', src)
        self.assertIn('self.release_docker()', (REPO / 'kernel' / 'engine.py').read_text())
