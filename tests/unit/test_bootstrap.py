"""3-13：第零步 bootstrap.sh（设计书 4.2、4.5 的 M0）和它用的 machine/bootstrap.py。

真的 apt、真的下载只在虚拟机里做（tests/vm/bootstrap.sh）。这里在 /tmp 的临时主目录里测：
- 代理地址的写法、从哪几处读已有的代理设置（假的 gsettings、apt-config、/etc/environment）；
- 缺 git、curl 才用 apt 装，先说一句再 sudo（假的 sudo）；
- 从头跑一遍（假的 wget 当网络，工具包从本机的 Git 仓库取，uv 用跑测试的这份）：取工具包、写网络设置、启动器、
  终端启动文件那一段，sop 能运行；再跑一遍都跳过、文件不重写；连不上时问代理、填对了接着做；不是 Ubuntu 26.04 不做。
"""
import json
import os
import pathlib
import shutil
import subprocess

from machine import shellenv
from tests.helpers import GIT_ID, REPO, TempHome, sh

SCRIPT = REPO / 'bootstrap.sh'
OS_2604 = 'ID=ubuntu\nVERSION_ID="26.04"\nPRETTY_NAME="Ubuntu 26.04.1 LTS"\n'
# 假的 wget：只认 --spider 试连。$FAKE_NEED_PROXY 有值时，只有代理是它才连得上
FAKE_WGET = '''#!/bin/bash
echo "wget $* proxy=${https_proxy:-}" >> "$FAKE_LOG"
[ -z "${FAKE_NEED_PROXY:-}" ] || [ "${https_proxy:-}" = "$FAKE_NEED_PROXY" ]
'''


class Bootstrap(TempHome):
    def setUp(self):
        super().setUp()
        self.h = self.tmp / 'home'
        self.h.mkdir()
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        self.log = self.tmp / 'fake.log'
        self.fake('wget', FAKE_WGET)
        self.fake('gsettings', 'exit 1')        # 默认：不是桌面、没有桌面的代理设置
        self.fake('apt-config', 'exit 0')       # 默认：apt 没设代理
        self.etc_env = self.tmp / 'environment'
        self.etc_env.write_text('PATH="/usr/bin:/bin"\n')
        self.osr = self.tmp / 'os-release'
        self.osr.write_text(OS_2604)

    def fake(self, name, body):
        f = self.bin / name
        f.write_text(body if body.startswith('#!') else f'#!/bin/bash\n{body}\n')
        f.chmod(0o755)

    def env(self, **extra):
        e = {'HOME': str(self.h), 'PATH': f'{self.bin}:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': str(self.tmp),
             'FAKE_LOG': str(self.log), 'SOP_BOOTSTRAP_ETC_ENV': str(self.etc_env), 'SOP_BOOTSTRAP_OS_RELEASE': str(self.osr),
             'GIT_CONFIG_NOSYSTEM': '1', **GIT_ID}
        e.update(extra)
        return e

    def func(self, code, **extra):
        """载入 bootstrap.sh（不跑 main），执行一段 bash。"""
        return subprocess.run(['bash', '-c', f'. "{SCRIPT}"; {code}'], capture_output=True, text=True, env=self.env(**extra))


class TestPieces(Bootstrap):
    def test_normalize_proxy(self):
        for given, want in (('http://127.0.0.1:7890', 'http://127.0.0.1:7890'), ('  127.0.0.1:7890 ', 'http://127.0.0.1:7890'),
                            ('https://proxy.example.com:8443/', 'https://proxy.example.com:8443'), ('', '')):
            with self.subTest(given=given):
                r = self.func(f'normalize_proxy "{given}"')
                self.assertEqual((r.returncode, r.stdout), (0, want))
        for bad in ('http://a b:1', 'socks5://127.0.0.1:1080', 'http://x:123456', 'ftp://x:1'):
            with self.subTest(bad=bad):
                self.assertEqual(self.func(f'normalize_proxy "{bad}"').returncode, 1)

    def test_detect_proxy_sources(self):
        def detect(**extra):
            return self.func('detect_proxy', **extra).stdout.split('\n')[:3]
        self.assertEqual(detect(), ['', '', ''])
        # 环境变量（https 优先）
        self.assertEqual(detect(http_proxy='http://h:1', https_proxy='http://s:2', no_proxy='localhost'), ['http://s:2', 'localhost', '环境变量'])
        # /etc/environment（带引号、带 export 都认）
        self.etc_env.write_text('PATH="/usr/bin"\nexport http_proxy="http://10.0.0.1:3128/"\nno_proxy=localhost,127.0.0.1\n')
        self.assertEqual(detect(), ['http://10.0.0.1:3128/', 'localhost,127.0.0.1', str(self.etc_env)])
        self.etc_env.write_text('')
        # apt 的设置
        self.fake('apt-config', 'echo \'Acquire::http::Proxy "http://apt.example:3142";\'')
        self.assertEqual(detect(), ['http://apt.example:3142', '', 'apt 的设置'])
        # 桌面的网络设置（手动填的代理）排在 /etc/environment、apt 前面
        self.fake('gsettings', '''case "$2 $3" in
  "org.gnome.system.proxy mode") echo "'manual'" ;;
  "org.gnome.system.proxy.https host") echo "'192.168.1.5'" ;;
  "org.gnome.system.proxy.https port") echo 8080 ;;
  "org.gnome.system.proxy ignore-hosts") echo "['localhost', '127.0.0.0/8']" ;;
  *) echo "''" ;;
esac''')
        self.assertEqual(detect(), ['http://192.168.1.5:8080', 'localhost,127.0.0.0/8', '桌面的网络设置'])

    def test_apt_only_when_missing(self):
        """缺 git、curl 才装：先说一句要密码，再一次 sudo apt；都有就不碰 sudo。"""
        self.fake('sudo', 'echo "sudo $*" >> "$FAKE_LOG"')
        nogit = self.tmp / 'nogit'
        nogit.mkdir()
        (nogit / 'curl').symlink_to('/usr/bin/true')
        r = self.func(f'PROXY=http://p:1 NOPROXY=localhost; PATH="{self.bin}:{nogit}"; install_apt')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('装 git', r.stdout)
        self.assertIn('登录密码', r.stdout)
        calls = self.log.read_text()
        self.assertIn('http_proxy=http://p:1', calls)
        self.assertIn('install -y', calls)
        self.assertTrue(calls.rstrip().endswith('sop-apt git'), calls)
        self.log.unlink()
        r = self.func('PROXY=; NOPROXY=; install_apt')       # 这台电脑上 git、curl 都有
        self.assertIn('都有了，跳过', r.stdout)
        self.assertFalse(self.log.exists())
        # 装不上（密码不对）就停下明说
        self.fake('sudo', 'exit 1')
        r = self.func(f'PROXY=; NOPROXY=; PATH="{self.bin}:{nogit}"; install_apt')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('没装上', r.stderr)

    def test_apt_waits_for_lock(self):
        """3-56：等住软件包的锁那一段和 machine/install/apt.sh 一字不差；系统一直占着锁时说清楚，不说「密码不对」。"""
        r = self.func('printf %s "$SOP_APT_SH"')
        self.assertEqual(r.stdout, (REPO / 'machine/install/apt.sh').read_text().rstrip('\n'))
        self.assertNotIn('-o DPkg::Lock::Timeout', SCRIPT.read_text())
        self.fake('sudo', 'shift 2; exec "$@"')
        self.fake('apt-get', 'echo "apt-get $*" >> "$FAKE_LOG"; echo "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 9 (apt-get)" >&2; exit 100')
        self.fake('sleep', 'exit 0')
        nogit = self.tmp / 'nogit'
        nogit.mkdir()
        (nogit / 'curl').symlink_to('/usr/bin/true')
        for name in ('sh', 'env', 'date', 'cat', 'mktemp', 'chmod', 'mkdir', 'rm', 'printf'):
            if pathlib.Path('/usr/bin', name).exists():
                (nogit / name).symlink_to(pathlib.Path('/usr/bin', name))
        r = self.func(f'PROXY=; NOPROXY=; PATH="{self.bin}:{nogit}"; install_apt', SOP_APT_WAIT='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('系统正在自己更新软件', r.stderr)
        self.assertNotIn('密码不对', r.stderr)
        self.assertEqual(self.log.read_text().count('apt-get update'), 1)

    def test_not_supported_system(self):
        self.osr.write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        r = subprocess.run(['bash', str(SCRIPT), '--repo', '/nonexistent', '--yes'], capture_output=True, text=True, env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('只支持 Ubuntu 26.04', r.stderr)
        self.assertEqual(list(self.h.iterdir()), [])                 # 什么都没建
        r = subprocess.run(['bash', str(SCRIPT), '--yes'], capture_output=True, text=True, env=self.env())
        self.assertIn('工具包仓库的地址', r.stderr)                   # 仓库建好之前要给 --repo


class TestFullRun(Bootstrap):
    """从头跑一遍。工具包仓库是本机的一个 Git 仓库（工作区现在的文件），uv 用跑测试的这一份（链接到 ~/tools/uv/bin/uv）。"""

    def setUp(self):
        super().setUp()
        self.repo = self.tmp / 'toolkit.git'
        work = self.tmp / 'toolkit-work'
        files = [f for f in sh('git', '-C', REPO, 'ls-files', '-co', '--exclude-standard', '-z').split('\0')
                 if f and (REPO / f).is_file() and not f.startswith('docs/')]
        for f in files:
            (work / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, work / f)
        sh('git', 'init', '-q', '-b', 'main', work)
        sh('git', '-C', work, 'add', '-A')
        sh('git', '-C', work, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'toolkit')
        sh('git', 'clone', '-q', '--bare', work, self.repo)
        self.version = sh('git', '--git-dir', self.repo, 'rev-parse', 'main')
        uv = shutil.which('uv')
        if not uv:
            self.skipTest('跑测试的电脑上没有 uv')
        (self.h / 'tools/uv/bin').mkdir(parents=True)
        (self.h / 'tools/uv/bin/uv').symlink_to(uv)

    def run_bs(self, *args, input='', **extra):
        return subprocess.run(['bash', str(SCRIPT), '--repo', str(self.repo), *args], capture_output=True, text=True,
                              input=input, env=self.env(UV_PYTHON_DOWNLOADS='never', **extra), timeout=300)

    def test_fresh_then_again(self):
        r = self.run_bs(input='\n', http_proxy='http://127.0.0.1:7890', https_proxy='http://127.0.0.1:7890', no_proxy='localhost')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertIn('代理：http://127.0.0.1:7890（从环境变量读到的）', out)
        self.assertIn('GitHub（https://github.com/）：连得上', out)
        self.assertIn('git、curl 都有了，跳过', out)
        self.assertIn('主目录在哪个分区', out)
        self.assertIn('sop machine setup', out)
        sop = self.h / 'tools/sop'
        self.assertTrue((sop / 'versions' / self.version / 'kernel/launcher.py').is_file())
        self.assertEqual((sop / 'versions/latest').read_text(), self.version)
        self.assertEqual(sh('git', '-C', sop / 'versions' / self.version, 'rev-parse', 'HEAD'), self.version)
        net = json.loads((sop / 'config/network.json').read_text())
        self.assertEqual((net['http_proxy'], net['https_proxy'], net['no_proxy'], net['source']),
                         ('http://127.0.0.1:7890', 'http://127.0.0.1:7890', 'localhost', 'detected'))
        rc = (self.h / '.bashrc').read_text()
        self.assertIn(shellenv.BEGIN, rc)
        self.assertIn('$HOME/tools/sop:', rc)
        # 新开的终端里敲 sop 就能用（PATH 里只有系统的目录，靠那一段找到 sop、uv）
        t = subprocess.run(['bash', '-c', f'. "{self.h}/.bashrc"; command -v sop; sop machine tools'], capture_output=True, text=True,
                           env={'HOME': str(self.h), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'UV_PYTHON_DOWNLOADS': 'never'})
        self.assertEqual(t.returncode, 0, t.stdout + t.stderr)
        self.assertTrue(t.stdout.startswith(f'{self.h}/tools/sop/sop\n'), t.stdout)
        self.assertIn('工具包要装的基础工具', t.stdout)
        # 主目录里只多了 tools 和 .bashrc（wget 不留 .wget-hsts；uv 的缓存在 ~/tools/cache/uv）
        self.assertEqual(sorted(p.name for p in self.h.iterdir()), ['.bashrc', 'tools'])
        self.assertTrue((self.h / 'tools/cache/uv').is_dir())
        self.assertEqual(sorted(p.name for p in (self.h / 'tools').iterdir()), ['cache', 'sop', 'uv'])

        # 再跑一遍：都跳过，文件不重写
        files = [sop / 'sop', sop / 'launcher.py', sop / 'versions/latest', sop / 'config/network.json', self.h / '.bashrc']
        for f in files:
            os.utime(f, (1_000_000_000, 1_000_000_000))
        r = self.run_bs('--yes', http_proxy='http://127.0.0.1:7890', https_proxy='http://127.0.0.1:7890', no_proxy='localhost')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'工具包 {self.version[:8]} 已经有了，跳过', r.stdout)
        self.assertIn('uv 已经有了', r.stdout)
        self.assertIn('本来就是最新的，没改', r.stdout)
        for f in files[:3] + files[4:]:
            self.assertEqual(f.stat().st_mtime, 1_000_000_000, f)
        self.assertEqual([p.name for p in (sop / 'versions').iterdir() if p.name.startswith('.')], [])   # 没留临时目录

    def test_ask_for_proxy(self):
        """探测不到代理、直连连不上：问代理；第一次写错重问，填对了接着做，记成「小白填的」。"""
        r = self.run_bs(input='not a proxy\n10.0.2.2:7890\n\n', FAKE_NEED_PROXY='http://10.0.2.2:7890')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('代理：不用代理（没找到代理设置）', r.stdout)
        self.assertIn('有连不上的', r.stdout)
        self.assertIn('写法不对：not a proxy', r.stdout)
        self.assertIn('代理：http://10.0.2.2:7890（你填的）', r.stdout)
        self.assertIn('不知道就直接回车', r.stderr)
        net = json.loads((self.h / 'tools/sop/config/network.json').read_text())
        self.assertEqual((net['http_proxy'], net['source']), ('http://10.0.2.2:7890', 'user'))
        self.assertIn('no_proxy', net)

    def test_no_network_stops(self):
        """连不上、小白也不知道代理（直接回车）：停下，指向离线包，什么都没装。"""
        r = self.run_bs(input='\n', FAKE_NEED_PROXY='http://nowhere:1')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('离线包', r.stderr)
        self.assertFalse((self.h / 'tools/sop').exists())
        r = self.run_bs('--yes', FAKE_NEED_PROXY='http://nowhere:1')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('连不上', r.stderr)
