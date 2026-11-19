"""3-17：专用 Docker 的正式后台服务和分组（runner/docker/service.py，设计书 6.3 二）。
只生成文件、不碰服务管理器：登记文件写进 /tmp 的临时目录（SOP_SYSTEMD_USER_DIR），systemctl 换成记下调用的假的。
真的起服务、超内存被杀、隔离自检 13 项在虚拟机里验（tests/vm/dockersvc.sh）。"""
import os
import pathlib
import stat

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
        """内存、处理器的上限设在分组上；不用交换区（超了就被杀，不是慢慢换出去）。"""
        f = self.files(limits={'memory': '300M', 'cpu': '100%'})
        sl = f['sop-my\\x2dapp.slice']
        self.assertIn('[Slice]\nMemoryMax=300M\nMemorySwapMax=0\nCPUQuota=100%\n', sl)
        self.assertIn('my-app', sl)

    def test_service_in_slice_not_autostart(self):
        """服务放进分组；交给它自己管下面的分组（Delegate），停的时候先停主程序；不设成登录后自己起来（用时才起，用户定的）。"""
        sv = self.files()['sop-docker-my-app.service']
        self.assertIn('\nSlice=sop-my\\x2dapp.slice\n', sv)
        for line in ('Delegate=yes', 'KillMode=mixed', 'Restart=on-failure'):
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
        self.assertIn('MemoryMax=50%\n', sl)
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


class TestInstall(Base):
    def test_install_writes_once(self):
        """写两份登记文件（只有自己能读：里面可能有代理的账号密码）、拷换根脚本、建数据目录；
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
        self.assertEqual(sorted(os.listdir(self.units)), ['sop-docker-my-app.service', 'sop-my\\x2dapp.slice'])

    def test_change_limit_rewrites(self):
        """改了上限、手改过登记文件：按工具包的重写，再让服务管理器重读。"""
        ctl = FakeCtl()
        S.install('my-app', self.root, {'memory': '300M'}, ctl=ctl)
        self.assertTrue(S.install('my-app', self.root, {'memory': '1G'}, ctl=ctl))
        self.assertIn('MemoryMax=1G\n', (self.units / 'sop-my\\x2dapp.slice').read_text())
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
        self.assertEqual(sorted(os.listdir(self.units)),
                         ['sop-docker-my-app.service', 'sop-docker-my.service', 'sop-my.slice', 'sop-my\\x2dapp.slice'])
        self.assertIn('Slice=sop-my.slice\n', (self.units / 'sop-docker-my.service').read_text())
        self.assertIn(f'"SOPD_PROJ={other}"', (self.units / 'sop-docker-my.service').read_text())

    def test_remove_keeps_data(self):
        """删掉：停服务、删两份登记文件、让服务管理器重读；数据目录（镜像、数据卷）不动。"""
        ctl = FakeCtl()
        S.install('my-app', self.root, ctl=ctl)
        (self.tools / 'docker-sop' / 'my-app' / 'data' / '镜像').write_text('x')
        ctl.calls.clear()
        S.remove('my-app', ctl=ctl)
        self.assertEqual(os.listdir(self.units), [])
        self.assertEqual(ctl.calls[0], ('stop', 'sop-docker-my-app.service'))
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
