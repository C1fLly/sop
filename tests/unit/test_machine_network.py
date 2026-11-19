"""3-50：体检的网络连通（4.4）。假服务都只听 127.0.0.1，测完关掉；不连外面的网络。
连得上（网页、加密网页、SSH）、连不上（拒绝连接、不是 SSH、域名解析不了、证书不对）、超时、走代理（含要账号密码、
不走代理的名单、SSH 直连不通而经代理能通），地址从哪来、密钥不读不发，报告的文字。"""
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import unittest
from unittest import mock

from kernel import paths
from machine import config, doctor, network
from tests.helpers import TempHome
from tests.unit.test_machine_doctor import fake_data


class Server:
    """一个只听 127.0.0.1 的假服务：每来一个连接，在新线程里调用 handle(连接, 服务)。记下收到的东西。"""

    def __init__(self, handle):
        self.handle, self.seen, self.conns = handle, [], []
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(c)
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        try:
            self.handle(c, self)
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self.stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)     # 叫醒还在等连接的线程
        except OSError:
            pass
        self.sock.close()
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass
        self.thread.join(2)


def read_head(c):
    buf = b''
    c.settimeout(3)
    while b'\r\n\r\n' not in buf:
        chunk = c.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.decode('latin-1')


def web(code=404):
    def h(c, srv):
        srv.seen.append(read_head(c))
        c.sendall(f'HTTP/1.1 {code} X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
    return h


def ssh_banner(c, srv):
    c.sendall(b'SSH-2.0-FakeSSH\r\n')
    srv.seen.append(c.recv(100))      # 对方不该发任何东西：等到它断开，收到的是 b''


def silent(c, srv):
    srv.stop.wait(10)


def hang_up(c, srv):
    read_head(c)          # 收下请求，一个字不回就断开


def proxy(route=None, code=200):
    """假的网页代理：CONNECT 转到 route（给了的话）或者请求里的主机端口；不加密的网页按整个地址转。记下请求的头。"""
    def h(c, srv):
        head = read_head(c)
        srv.seen.append(head)
        first = head.split('\r\n')[0].split()
        if first[0] == 'CONNECT':
            if code != 200:
                c.sendall(f'HTTP/1.1 {code} No\r\nContent-Length: 0\r\n\r\n'.encode())
                return
            host, port = first[1].rsplit(':', 1)
            up = socket.create_connection(route or ('127.0.0.1', int(port)), timeout=3)
            c.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            pump(c, up)
        else:
            import urllib.parse
            u = urllib.parse.urlsplit(first[1])
            up = socket.create_connection(route or ('127.0.0.1', u.port), timeout=3)
            up.sendall(head.replace(first[1], u.path or '/', 1).encode('latin-1'))
            pump(c, up)
    return h


def pump(a, b):
    def one(x, y):
        try:
            while True:
                d = x.recv(4096)
                if not d:
                    break
                y.sendall(d)
        except OSError:
            pass
        finally:
            try:
                y.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    t = threading.Thread(target=one, args=(b, a), daemon=True)
    t.start()
    one(a, b)
    t.join(3)
    b.close()


def closed_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Net(TempHome):
    def setUp(self):
        super().setUp()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        super().tearDown()

    def serve(self, handle):
        s = Server(handle)
        self.servers.append(s)
        return s

    def t(self, url, key='x', group='source'):
        return network.Target(key, '试的那一样', url, group)


NONE = network.Proxies()


class TestDirect(Net):
    def test_web_ok_any_status_no_credentials(self):
        s = self.serve(web(401))
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/v1/x?key=secret'), NONE, timeout=3)
        self.assertEqual((r.state, r.via, r.detail), ('ok', '直连', '对方回了 401'))   # 401 也算连得上
        req = s.seen[0]
        self.assertTrue(req.startswith('HEAD /v1/x HTTP/1.1'))
        self.assertNotIn('secret', req)
        self.assertNotIn('Authorization', req)

    def test_refused(self):
        r = network.probe(self.t(f'http://127.0.0.1:{closed_port()}/'), NONE, timeout=3)
        self.assertEqual(r.state, 'fail')
        self.assertIn('拒绝连接', r.reason)

    def test_no_answer_times_out(self):
        s = self.serve(silent)
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/'), NONE, timeout=0.5)
        self.assertEqual(r.state, 'fail')
        self.assertIn('0.5 秒没回应', r.reason)
        self.assertLess(r.seconds, 3)

    def test_hang_up_and_not_web(self):
        s = self.serve(hang_up)
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/'), NONE, timeout=3)
        self.assertIn('什么都没回就断开了', r.reason)
        s = self.serve(ssh_banner)
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/'), NONE, timeout=3)
        self.assertIn('回的不是网页', r.reason)

    def test_name_not_resolved(self):
        with mock.patch('socket.create_connection', side_effect=socket.gaierror(-2, 'Name or service not known')):
            r = network.probe(self.t('https://registry.example.invalid/'), NONE, timeout=3)
        self.assertEqual(r.state, 'fail')
        self.assertIn('域名 registry.example.invalid 解析不了', r.reason)

    def test_connect_timeout(self):
        with mock.patch('socket.create_connection', side_effect=TimeoutError()):
            r = network.probe(self.t('https://pypi.org/simple/'), NONE, timeout=2)
        self.assertIn('2 秒没连上：可能要走代理才连得上', r.reason)

    def test_ssh(self):
        s = self.serve(ssh_banner)
        r = network.probe(self.t(f'ssh://127.0.0.1:{s.port}', 'github_ssh', 'github'), NONE, timeout=3)
        self.assertEqual((r.state, r.detail), ('ok', 'SSH-2.0-FakeSSH'))
        s.thread.join(0.2)
        for _ in range(30):
            if s.seen:
                break
            threading.Event().wait(0.05)
        self.assertEqual(s.seen, [b''])                     # 只读了对方那一行，自己什么都没发
        w = self.serve(lambda c, srv: c.sendall(b'220 mail.example ESMTP\r\n'))   # 先开口的别种服务
        r = network.probe(self.t(f'ssh://127.0.0.1:{w.port}'), NONE, timeout=3)
        self.assertIn('不是 SSH 服务', r.reason)
        w = self.serve(lambda c, srv: None)                          # 一连上就断开
        r = network.probe(self.t(f'ssh://127.0.0.1:{w.port}'), NONE, timeout=3)
        self.assertIn('不是 SSH 服务（什么都没回）', r.reason)
        q = self.serve(silent)
        r = network.probe(self.t(f'ssh://127.0.0.1:{q.port}'), NONE, timeout=0.5)
        self.assertIn('秒没回应', r.reason)

    def test_skip_without_address(self):
        r = network.probe(network.Target('ai:codex', 'Codex 的服务', '', 'ai', '服务地址还没登记'), NONE)
        self.assertEqual((r.state, r.reason), ('skip', '服务地址还没登记'))


@unittest.skipUnless(shutil.which('openssl'), '没有 openssl，造不出假证书')
class TestTls(Net):
    def setUp(self):
        super().setUp()
        self.cert, self.key = self.tmp / 'c.pem', self.tmp / 'k.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=127.0.0.1',
                        '-addext', 'subjectAltName=IP:127.0.0.1', '-keyout', str(self.key), '-out', str(self.cert)],
                       check=True, capture_output=True)
        import ssl
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(self.cert, self.key)

    def tls_web(self, code=404):
        inner = web(code)

        def h(c, srv):
            with self.ctx.wrap_socket(c, server_side=True) as t:
                inner(t, srv)
        return h

    def test_tls_ok_and_bad_cert(self):
        s = self.serve(self.tls_web(200))
        url = f'https://127.0.0.1:{s.port}/'
        r = network.probe(self.t(url), NONE, timeout=3, cafile=str(self.cert))
        self.assertEqual((r.state, r.detail), ('ok', '对方回了 200'))
        r = network.probe(self.t(url), NONE, timeout=3)      # 不认这张自签的证书：像被网络拦截了
        self.assertEqual(r.state, 'fail')
        self.assertIn('证书核对不过', r.reason)

    def test_tls_through_proxy(self):
        s = self.serve(self.tls_web(403))
        p = self.serve(proxy())
        px = network.Proxies(f'http://127.0.0.1:{p.port}', f'http://127.0.0.1:{p.port}', '', 'network')
        r = network.probe(self.t(f'https://127.0.0.1:{s.port}/simple/'), px, timeout=3, cafile=str(self.cert))
        self.assertEqual((r.state, r.via, r.detail), ('ok', f'经代理 http://127.0.0.1:{p.port}', '对方回了 403'))
        self.assertTrue(p.seen[0].startswith(f'CONNECT 127.0.0.1:{s.port} HTTP/1.1'))
        self.assertTrue(s.seen[0].startswith('HEAD /simple/ HTTP/1.1'))


class TestProxy(Net):
    def px(self, port, no_proxy='', user=''):
        a = f'http://{user}127.0.0.1:{port}'
        return network.Proxies(a, a, no_proxy, 'network')

    def test_plain_http_through_proxy(self):
        s = self.serve(web(200))
        p = self.serve(proxy())
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/ubuntu/'), self.px(p.port), timeout=3)
        self.assertEqual((r.state, r.via), ('ok', f'经代理 http://127.0.0.1:{p.port}'))
        self.assertTrue(p.seen[0].startswith(f'HEAD http://127.0.0.1:{s.port}/ubuntu/ HTTP/1.1'))

    def test_proxy_down_and_needs_password(self):
        r = network.probe(self.t('https://github.com/'), self.px(closed_port()), timeout=3)
        self.assertEqual(r.state, 'fail')
        self.assertIn('代理 127.0.0.1', r.reason)
        self.assertIn('代理软件可能没开', r.reason)
        p = self.serve(proxy(code=407))
        r = network.probe(self.t('https://github.com/'), self.px(p.port, user='me:pw@'), timeout=3)
        self.assertIn('要账号密码', r.reason)
        self.assertNotIn('pw', r.reason + r.via)            # 代理的账号密码不打印
        self.assertIn('Proxy-Authorization: Basic', p.seen[0])
        p = self.serve(proxy(code=403))
        r = network.probe(self.t('https://github.com/'), self.px(p.port), timeout=3)
        self.assertIn('不肯转到 github.com:443（回了 403）', r.reason)

    def test_proxy_silent_times_out(self):
        p = self.serve(silent)
        r = network.probe(self.t('https://github.com/'), self.px(p.port), timeout=0.5)
        self.assertIn('0.5 秒没回应', r.reason)

    def test_no_proxy_goes_direct(self):
        s = self.serve(web(200))
        r = network.probe(self.t(f'http://127.0.0.1:{s.port}/'), self.px(closed_port(), no_proxy='localhost,127.*'), timeout=3)
        self.assertEqual((r.state, r.via), ('ok', '直连'))

    def test_socks_not_tried(self):
        px = network.Proxies('socks5://127.0.0.1:1080', 'socks5://127.0.0.1:1080', '', 'env')
        r = network.probe(self.t('https://github.com/'), px, timeout=1)
        self.assertEqual(r.state, 'skip')
        self.assertIn('socks', r.reason)

    def test_ssh_direct_fails_but_proxy_works(self):
        banner = self.serve(ssh_banner)
        p = self.serve(proxy(route=('127.0.0.1', banner.port)))
        r = network.probe(self.t(f'ssh://127.0.0.1:{closed_port()}', 'github_ssh', 'github'), self.px(p.port), timeout=3)
        self.assertEqual(r.state, 'fail')
        self.assertIn('经代理', r.reason)
        self.assertIn('SSH 默认不走代理', r.reason)

    def test_bypass_rules(self):
        np = '*zhihu.com,.example.com,localhost,127.*,10.*,api.local:8080'
        for host, want in (('www.zhihu.com', True), ('example.com', True), ('a.b.example.com', True),
                           ('notexample.com', False), ('127.0.0.1', True), ('github.com', False), ('api.local', True),
                           ('LOCALHOST', True)):
            self.assertEqual(network.bypass(host, np), want, host)
        self.assertTrue(network.bypass('github.com', '*'))
        self.assertFalse(network.bypass('github.com', ''))

    def test_check_keeps_order_and_runs_together(self):
        slow = [self.serve(silent) for _ in range(3)]
        ts = [self.t(f'http://127.0.0.1:{s.port}/', key=str(i)) for i, s in enumerate(slow)]
        rs = network.check(ts, NONE, timeout=0.5)
        self.assertEqual([r.target.key for r in rs], ['0', '1', '2'])
        self.assertTrue(all(r.state == 'fail' for r in rs))


class TestTargets(TempHome):
    def test_proxies_from_network_or_env(self):
        net = {'http_proxy': 'http://127.0.0.1:7890', 'https_proxy': 'http://127.0.0.1:7890', 'no_proxy': 'localhost'}
        p = network.proxies_from(net, environ={'https_proxy': 'http://other:1'})
        self.assertEqual((p.https, p.no_proxy, p.source), ('http://127.0.0.1:7890', 'localhost', 'network'))
        p = network.proxies_from({'source': 'user'}, environ={'https_proxy': 'http://other:1'})
        self.assertEqual((p.https, p.source), ('', 'none'))            # 网络设置写的不用代理：不看终端
        p = network.proxies_from({}, environ={'HTTPS_PROXY': 'http://e:2', 'no_proxy': 'x'})
        self.assertEqual((p.https, p.no_proxy, p.source), ('http://e:2', 'x', 'env'))
        self.assertEqual(network.proxies_from({}, environ={}).source, 'none')

    def test_apt_sources(self):
        d = self.tmp / 'apt'
        (d / 'sources.list.d').mkdir(parents=True)
        (d / 'sources.list').write_text('# deb http://old.example/ubuntu x main\n'
                                        'deb [arch=amd64 signed-by=/k] http://u:p@mirror.example/ubuntu/ resolute main\n')
        (d / 'sources.list.d' / 'ubuntu.sources').write_text(
            'Types: deb\nURIs: http://cn.archive.ubuntu.com/ubuntu/\nSuites: resolute\n\n'
            'Types: deb\nURIs: http://security.ubuntu.com/ubuntu/ http://cn.archive.ubuntu.com/ubuntu/\nSuites: x\n')
        got = network.apt_sources((str(d / 'sources.list'), str(d / 'sources.list.d/*.sources')))
        self.assertEqual(got, ['http://mirror.example/ubuntu/', 'http://cn.archive.ubuntu.com/ubuntu/',
                               'http://security.ubuntu.com/ubuntu/'])

    def test_ai_address_from_env_file_only_url(self):
        ai = paths.config_dir() / 'ai'
        ai.mkdir(parents=True)
        (ai / 'codex.env').write_text('OPENAI_API_KEY=fake-secret-key\nOPENAI_BASE_URL="https://relay.example/v1?k=1"\n')
        url, src = network.ai_address('codex', environ={})
        self.assertEqual((url, src), ('https://relay.example/', 'codex.env'))
        self.assertEqual(network.ai_address('pi', environ={}), ('', ''))
        self.assertEqual(network.ai_address('claude', environ={'ANTHROPIC_BASE_URL': 'https://user:pw@api.relay.example:8443/x',
                                                               'ANTHROPIC_AUTH_TOKEN': 'fake-secret'}),
                         ('https://api.relay.example:8443/', '环境变量'))
        self.assertEqual(network.ai_address('claude', environ={}), (network.CLAUDE_DEFAULT, '官方地址'))

    def test_targets(self):
        net = {'npm_registry': 'https://npm.mirror.example/', 'apt_mirror': 'http://mirror.example/ubuntu/'}
        ts = network.targets(net, ['claude', 'pi'], environ={}, apt_files=())
        keys = [t.key for t in ts]
        self.assertEqual(keys[:4], ['github', 'github_ssh', 'ai:claude', 'ai:pi'])
        by = {t.key: t for t in ts}
        self.assertEqual(by['github_ssh'].url, 'ssh://github.com:22')
        self.assertEqual(by['ai:claude'].url, network.CLAUDE_DEFAULT)
        self.assertEqual(by['ai:pi'].url, '')
        self.assertIn('还没登记', by['ai:pi'].why_skip)
        self.assertEqual(by['apt:mirror.example'].url, 'http://mirror.example/ubuntu/')
        self.assertEqual(by['npm'].url, 'https://npm.mirror.example/')
        self.assertEqual(by['pypi'].url, network.PYPI_DEFAULT)
        self.assertTrue({'dl:uv', 'dl:nvm', 'dl:node', 'dl:docker'} <= set(keys))


def result(key, label, url, group, state, **kw):
    return network.Result(network.Target(key, label, url, group, kw.pop('why', '')), state, **kw)


def net_data(source='network', configured=True):
    p = network.Proxies('http://127.0.0.1:7890', 'http://127.0.0.1:7890', 'localhost', source) if source != 'none' \
        else network.Proxies()
    return {'proxies': p, 'configured': configured, 'results': [
        result('github', 'GitHub 网页', 'https://github.com/', 'github', 'ok', via='经代理 http://127.0.0.1:7890',
               detail='对方回了 200'),
        result('github_ssh', 'GitHub 的 SSH（推送用）', 'ssh://github.com:22', 'github', 'fail', via='直连',
               reason='github.com:22 8 秒没连上：可能要走代理才连得上，或者被网络挡住了'),
        result('ai:pi', 'Pi 的服务', '', 'ai', 'skip', why='服务地址还没登记', reason='服务地址还没登记'),
        result('npm', 'Node 依赖包的源（npm）', 'https://registry.npmjs.org/', 'source', 'ok', via='直连', detail='对方回了 404'),
    ]}


class TestReport(TempHome):
    def test_describe(self):
        text = network.describe(net_data())
        for must in ('代理：http://127.0.0.1:7890（网络设置里的）；有一串不走代理的地址',
                     '试连了 3 样，连得上 2 样，连不上 1 样。只连不登录，没带任何密钥。',
                     'GitHub 网页（https://github.com/）：连得上，经代理 http://127.0.0.1:7890，对方回了 200。',
                     'GitHub 的 SSH（推送用）（github.com:22）：连不上（直连）。github.com:22 8 秒没连上',
                     '推送、开 PR 都做不了',
                     'Pi 的服务：没试。服务地址还没登记。',
                     '软件源：', 'network.json'):
            self.assertIn(must, text)
        self.assertIn('还没有网络设置，按终端里的', network.describe(net_data('env', False)))
        self.assertIn('不用代理（还没有网络设置', network.describe(net_data('none', False)))
        self.assertIn('不用代理（网络设置里没写代理）', network.describe(net_data('none', True)))

    def test_in_doctor_report(self):
        text, bad, notes = doctor.report(fake_data(network=net_data()), home='/home/u')
        self.assertIn('七、网络连通', text)
        self.assertIn('要注意：有 1 样连不上：GitHub 的 SSH（推送用），原因见第七项', text)
        self.assertEqual(bad, ['uv', 'node'])               # 连不上不算基础工具没装好
        text, _, notes = doctor.report(fake_data(network=None), home='/home/u')
        self.assertIn('这次没试连网络（--no-network）', text)
        self.assertEqual(notes, [])

    def test_collect_reads_network_setting_and_writes_nothing(self):
        config.set_network(http_proxy='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9', no_proxy='localhost',
                           source='user')
        before = sorted(os.listdir(paths.config_dir()))
        with mock.patch.object(network, 'check', side_effect=lambda ts, p, timeout: [network.Result(t, 'skip') for t in ts]):
            d = network.collect(['claude'], environ={})
        self.assertEqual((d['proxies'].https, d['proxies'].source, d['configured']), ('http://127.0.0.1:9', 'network', True))
        self.assertIn('ai:claude', [r.target.key for r in d['results']])
        self.assertEqual(sorted(os.listdir(paths.config_dir())), before)
        self.assertFalse((paths.config_dir() / 'ai').exists())


if __name__ == '__main__':
    unittest.main()
