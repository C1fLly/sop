"""3-03：工具清单 machine/tools.toml、机器级配置和登记（~/tools/sop/config/）、`sop machine` 入口（设计书 4.3、4.4、4.5）。"""
import json
import os
import stat
import subprocess
import sys

from kernel import paths
from machine import catalog, config
from tests.helpers import REPO, TempHome, mock_env

GOOD = '''
[[tool]]
name = "git"
what = "版本管理"
version = ">=2.42"
location = "系统软件包"
check = "git --version"
install = "apt:git"
admin = true
step = "M0"

[[tool]]
name = "fake"
what = "一样假工具"
version = ">=1.10"
location = "~/tools/fake"
check = '"$SOP_TOOLS/fake/bin/fake"'
install = "script:install/fake.sh"
admin = false
step = "M2"
needs = ["git"]
'''


class TestCatalog(TempHome):
    def write(self, text):
        f = self.tmp / 'tools.toml'
        f.write_text(text)
        return f

    def test_real_catalog_loads(self):
        tools = catalog.load()
        names = [t.name for t in tools]
        for must in ('git', 'curl', 'uv', 'bubblewrap', 'nvm', 'node', 'pnpm', 'gh', 'docker', 'wt'):
            self.assertIn(must, names)
        self.assertEqual(len(names), len(set(names)))
        for t in tools:
            if t.system_package:
                self.assertTrue(t.admin, t.name)
                self.assertEqual(t.install_kind()[0], 'apt')
            else:
                # 工具包自己装的都在 ~/tools 下（4.3）
                self.assertTrue(str(t.path()).startswith(str(paths.tools_dir()) + '/'), t.name)
                self.assertEqual(t.install_kind()[1].parent.parent, REPO / 'machine')
        self.assertEqual(catalog.find('wt').step, 'M5')     # wt 的仓库是私有的，登录之后才装（4.5）
        self.assertTrue(catalog.find('docker').admin)       # 免管理员 Docker 要装一条系统规则（4.5）

    def test_good_sample(self):
        tools = catalog.load(self.write(GOOD))
        self.assertEqual([t.name for t in tools], ['git', 'fake'])
        self.assertEqual(tools[1].needs, ('git',))
        with mock_env({'SOP_TOOLS_DIR': str(self.tmp / 'tools')}):
            self.assertEqual(tools[1].path(), self.tmp / 'tools' / 'fake')
        self.assertIsNone(tools[0].path())

    def test_bad_samples(self):
        cases = {
            '少字段': ('check = "git --version"\n', ''),
            '名字重复': ('name = "fake"', 'name = "git"'),
            '版本写法': ('version = ">=1.10"', 'version = "1.10+"'),
            '步骤': ('step = "M2"', 'step = "M9"'),
            'apt 却不要密码': ('install = "apt:git"\nadmin = true', 'install = "apt:git"\nadmin = false'),
            '不在 tools 下': ('location = "~/tools/fake"', 'location = "~/.local/fake"'),
            '脚本跑出 machine': ('script:install/fake.sh', 'script:../../evil.sh'),
            '依赖在后面': ('needs = ["git"]', 'needs = ["node"]'),
            '多余字段': ('step = "M0"', 'step = "M0"\ncolor = "red"'),
            '类型不对': ('admin = false', 'admin = "no"'),
        }
        for what, (a, b) in cases.items():
            with self.subTest(what):
                self.assertIn(a, GOOD)
                with self.assertRaises(catalog.CatalogError) as e:
                    catalog.load(self.write(GOOD.replace(a, b, 1)))
                self.assertIn('machine/tools.toml', str(e.exception))
        with self.assertRaises(catalog.CatalogError):
            catalog.load(self.write('不是 toml ='))
        with self.assertRaises(catalog.CatalogError):
            catalog.load(self.write('x = 1\n'))

    def test_versions(self):
        pv = catalog.parse_version
        self.assertEqual(pv('git version 2.53.0'), (2, 53, 0))
        self.assertEqual(pv('v26.13.1'), (26, 13, 1))
        self.assertEqual(pv('Docker version 29.9.3, build abc'), (29, 9, 3))
        self.assertEqual(pv('12'), (12,))
        self.assertEqual(pv('1:4.16.0-2ubuntu1'), (4, 16, 0))   # 系统软件包的版本带「1:」
        self.assertIsNone(pv('没有数字'))
        ok = catalog.version_ok
        self.assertTrue(ok('>=1.10', (1, 10)))
        self.assertTrue(ok('>=1.10', (1, 10, 0)))
        self.assertTrue(ok('>=24', (26, 13, 1)))
        self.assertFalse(ok('>=1.10', (1, 9, 99)))   # 按数比，不按字比
        self.assertFalse(ok('>=2.42', (2, 4)))
        self.assertFalse(ok('>=1', None))
        self.assertTrue(ok('', None))

    def test_run_check(self):
        tools_dir = self.tmp / 'tools'
        exe = tools_dir / 'fake' / 'bin' / 'fake'
        exe.parent.mkdir(parents=True)
        fake = catalog.load(self.write(GOOD))[1]
        with mock_env({'SOP_TOOLS_DIR': str(tools_dir)}):
            r = catalog.run_check(fake)
            self.assertFalse(r.installed)                       # 没装
            exe.write_text('#!/bin/sh\necho "fake 1.9.3"\n'); exe.chmod(0o755)
            r = catalog.run_check(fake)
            self.assertTrue(r.installed); self.assertFalse(r.ok)  # 装了，版本不够
            self.assertEqual(r.version_text, '1.9.3')
            exe.write_text('#!/bin/sh\necho "fake 1.12.0"\n')
            self.assertTrue(catalog.run_check(fake).ok)
            exe.write_text('#!/bin/sh\nsleep 5 &\nsleep 5\n')
            r = catalog.run_check(fake, timeout=0.5)
            self.assertFalse(r.installed); self.assertIn('没结束', r.output)

    def test_git_check_on_this_machine(self):
        """检查命令真的能跑：git 本机一定有（只读，不改任何东西）。"""
        r = catalog.run_check(catalog.find('git'))
        self.assertTrue(r.installed, r.output)
        self.assertIsNotNone(r.version)


class TestConfig(TempHome):
    def test_empty_then_roundtrip(self):
        self.assertEqual(config.network(), {})
        self.assertEqual(config.tools(), {})
        config.set_network(http_proxy='http://127.0.0.1:7890', https_proxy='http://127.0.0.1:7890',
                           no_proxy='localhost,127.0.0.1', source='detected')
        n = config.network()
        self.assertEqual(n['http_proxy'], 'http://127.0.0.1:7890')
        self.assertIn('checked_at', n)
        env = config.proxy_env()
        self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:7890')
        self.assertEqual(env['no_proxy'], 'localhost,127.0.0.1')
        config.set_network(http_proxy=None)
        self.assertNotIn('http_proxy', config.network())
        self.assertNotIn('http_proxy', config.proxy_env())

    def test_network_rejects_bad(self):
        for kw in ({'proxy': 'x'}, {'http_proxy': '127.0.0.1:7890'}, {'http_proxy': 'ftp://a:1'},
                   {'apt_mirror': 'mirrors.example'}, {'source': 'guess'}, {'checked_at': 'x'}, {'no_proxy': 3}):
            with self.subTest(kw):
                with self.assertRaises(config.ConfigError):
                    config.set_network(**kw)
        self.assertEqual(config.network(), {})   # 报错的那几次一个字都没写
        config.set_network(https_proxy='socks5h://user:pw@proxy.lan:1080')

    def test_private_files(self):
        config.set_network(http_proxy='http://user:secret@127.0.0.1:7890')
        d = paths.config_dir()
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(d / 'network.json').st_mode), 0o600)
        self.assertEqual([p.name for p in d.iterdir() if p.name.endswith('.tmp')], [])

    def test_tools_registry(self):
        config.record_tool('docker', path='/home/x/tools/docker', version='29.9.3')
        config.record_tool('claude', path='/home/x/.local/bin/claude', version='2.1.327', kind='ai',
                           drilled_version='2.1.300')
        config.record_tool('docker', path='/home/x/tools/docker', version='29.9.3',
                           others=[{'path': '/usr/bin/docker', 'size_bytes': 331_000_000, 'on_system_disk': True}])
        t = config.tools()
        self.assertEqual(set(t), {'docker', 'claude'})
        self.assertEqual(t['claude']['drilled_version'], '2.1.300')
        self.assertTrue(t['docker']['in_place'])
        self.assertEqual(t['docker']['others'][0]['path'], '/usr/bin/docker')
        config.forget_tool('claude')
        self.assertEqual(set(config.tools()), {'docker'})
        with self.assertRaises(ValueError):
            config.record_tool('x', path='/a', version='1', kind='other')

    def test_system_registry(self):
        now = {'kernel': '7.0.0-15-generic', 'bubblewrap': '0.11.1', 'userns_rule': 'abc123', 'tiocsti': '0'}
        self.assertEqual({c[0] for c in config.system_changes(now)}, set(now))   # 还没登记过：都算变了
        config.record_system(now)
        self.assertEqual(config.system_changes(now), [])
        self.assertEqual(config.system_changes({**now, 'bubblewrap': '0.12.0'}), [('bubblewrap', '0.11.1', '0.12.0')])
        less = dict(now); less.pop('tiocsti')
        self.assertEqual(config.system_changes(less), [('tiocsti', '0', None)])
        with self.assertRaises(ValueError):
            config.record_system({'cpu': 'x'})

    def test_broken_file_is_reported(self):
        config.record_tool('git', path='/usr/bin/git', version='2.53.0')
        f = paths.config_dir() / 'tools.json'
        f.write_text('{"tools": {')
        with self.assertRaises(config.ConfigError) as e:
            config.tools()
        self.assertIn(str(f), str(e.exception))
        f.write_text('[1, 2]')
        with self.assertRaises(config.ConfigError):
            config.tools()

    def test_concurrent_writers_lose_nothing(self):
        """几个 sop 同时登记：读改写上了锁，谁的都不丢。"""
        code = ('import sys\nfrom machine import config\n'
                'for i in range(15):\n    config.record_tool(f"{sys.argv[1]}-{i}", path="/x", version="1")\n')
        env = {**os.environ, 'PYTHONPATH': str(REPO)}
        ps = [subprocess.Popen([sys.executable, '-c', code, f'w{n}'], env=env) for n in range(4)]
        for p in ps:
            self.assertEqual(p.wait(), 0)
        self.assertEqual(len(config.tools()), 60)
        json.loads((paths.config_dir() / 'tools.json').read_text())


class TestMachineCli(TempHome):
    def sop(self, *args):
        """在不是项目的目录里执行 sop machine（机器级命令不需要项目）。"""
        cwd = self.tmp / 'not-a-project'
        cwd.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(REPO / 'kernel' / 'main.py'), *args], cwd=cwd,
                              capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': ''})

    def test_tools_listing(self):
        p = self.sop('machine', 'tools')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('~/tools/docker', p.stdout)
        self.assertIn('要输管理员密码', p.stdout)
        self.assertIn('在「安装 wt」那一步装', p.stdout)

    def test_help_and_later(self):
        p = self.sop('machine')
        self.assertEqual(p.returncode, 0)
        self.assertIn('sop machine tools', p.stdout)
        for cmd, task in (('doctor', '3-06'), ('setup', '3-12'), ('migrate', '3-31')):
            p = self.sop('machine', cmd)
            self.assertEqual(p.returncode, 2)
            self.assertIn(task, p.stdout)
        p = self.sop('machine', 'nonsense')
        self.assertEqual(p.returncode, 2)
        self.assertIn('不认识的命令', p.stdout)
        self.assertFalse((paths.config_dir()).exists())   # 只是看看，不写任何登记
