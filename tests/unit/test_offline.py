"""3-14：离线包（设计书 4.2 第 3 条）。打包脚本 machine/offline/pack.sh、包头 header.sh、bootstrap.sh --offline。

真的下载（软件源、uv）和真的断网、apt 只在虚拟机里做（tests/vm/offline.sh）。这里在 /tmp 的临时目录里测：
- 软件包索引的写法（用 dpkg-deb 现做一个小软件包）；
- uv.sh 从离线包里的压缩包装、不下载；
- 用打包脚本的拼接那一步拼出一个离线包（工具包是本机的 Git 打包文件，uv 是跑测试这份的小包装），
  bash <离线包> 从头跑完第零步：一次都没上网（假 wget 没被叫过）、版本对、网络设置记成不用代理、sop 能运行、
  临时目录删掉了；缺 git 时只用离线包里的软件包（假 sudo 看传了什么）；
- 离线包拷坏了（改一个字节、少一截）就停下，什么都不装。
"""
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
import unittest

from tests.helpers import REPO, sh
from tests.unit.test_bootstrap import Bootstrap

PACK = REPO / 'machine/offline/pack.sh'
HEADER = REPO / 'machine/offline/header.sh'


def pack_func(code, env):
    """载入 pack.sh（不跑 main），执行一段 bash。"""
    return subprocess.run(['bash', '-c', f'. "{PACK}"; {code}'], capture_output=True, text=True, env=env)


class TestPieces(Bootstrap):
    def test_write_index(self):
        if not shutil.which('dpkg-deb'):
            self.skipTest('没有 dpkg-deb')
        src = self.tmp / 'pkg'
        (src / 'DEBIAN').mkdir(parents=True)
        (src / 'DEBIAN/control').write_text('Package: sop-demo\nVersion: 1.0\nArchitecture: all\nMaintainer: t <t@example.invalid>\n'
                                            'Description: demo\n')
        debs = self.tmp / 'debs'
        debs.mkdir()
        sh('dpkg-deb', '--build', '--root-owner-group', src, debs / 'sop-demo_1.0_all.deb')
        r = pack_func(f'ARCH=amd64; write_index "{debs}"', self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        pk = (debs / 'Packages').read_text()
        self.assertIn('Package: sop-demo\n', pk)
        self.assertIn('Filename: ./sop-demo_1.0_all.deb\n', pk)
        self.assertRegex(pk, r'SHA256: [0-9a-f]{64}\n\n$')
        self.assertIn('Architectures: amd64 all', (debs / 'Release').read_text())
        self.assertRegex((debs / 'Release').read_text(), r'\nDate: \w{3}, \d{2} \w{3} \d{4} [\d:]{8} \+0000\n')   # 没有日期 apt 会报警告
        r = pack_func('uv_arch amd64; uv_arch arm64; uv_arch i386 || echo no', self.env())
        self.assertEqual(r.stdout.split(), ['x86_64', 'aarch64', 'no'])

    def test_uv_from_archive(self):
        """离线包里的 uv：从压缩包装，不下载（假的 curl 被叫就算错）。"""
        arc = self.tmp / 'uv-x86_64-unknown-linux-gnu.tar.gz'
        make_uv_archive(arc)
        self.fake('curl', 'echo "curl $*" >> "$FAKE_LOG"; exit 1')
        tools = self.tmp / 'tools'
        r = subprocess.run(['bash', REPO / 'machine/install/uv.sh'], capture_output=True, text=True,
                           env=self.env(SOP_TOOLS=str(tools), SOP_UV_ARCHIVE=str(arc)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((tools / 'uv/bin/uv').is_file())
        self.assertTrue(os.access(tools / 'uv/bin/uv', os.X_OK))
        self.assertIn('uv', r.stdout)
        self.assertFalse(self.log.exists())
        r = subprocess.run(['bash', REPO / 'machine/install/uv.sh'], capture_output=True, text=True,
                           env=self.env(SOP_TOOLS=str(tools), SOP_UV_ARCHIVE=str(self.tmp / 'none.tar.gz')))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('没有 uv 的压缩包', r.stderr)


def make_uv_archive(arc):
    """uv 的「官方压缩包」：里面的 uv 是个小包装，转给跑测试的这份 uv（不用拷几十 MB）。"""
    uv = shutil.which('uv')
    if not uv:
        raise unittest.SkipTest('跑测试的电脑上没有 uv')
    d = arc.parent / 'uv-src' / 'uv-x86_64-unknown-linux-gnu'
    d.mkdir(parents=True)
    (d / 'uv').write_text(f'#!/bin/sh\nexec "{uv}" "$@"\n')
    (d / 'uvx').write_text(f'#!/bin/sh\nexec "{shutil.which("uvx") or uv}" "$@"\n')
    for f in ('uv', 'uvx'):
        (d / f).chmod(0o755)
    with tarfile.open(arc, 'w:gz') as t:
        t.add(d, arcname=d.name)


class TestOfflinePackage(Bootstrap):
    """拼一个离线包（不下载：工具包是本机仓库、软件包索引是空的、uv 是小包装），bash <离线包> 跑完第零步。"""

    def setUp(self):
        super().setUp()
        work = self.tmp / 'toolkit-work'
        files = [f for f in sh('git', '-C', REPO, 'ls-files', '-co', '--exclude-standard', '-z').split('\0')
                 if f and (REPO / f).is_file() and not f.startswith('docs/')]
        for f in files:
            (work / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, work / f)
        sh('git', 'init', '-q', '-b', 'main', work)
        sh('git', '-C', work, 'add', '-A')
        sh('git', '-C', work, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'toolkit')
        self.version = sh('git', '-C', work, 'rev-parse', 'main')
        p = self.tmp / 'payload'
        (p / 'debs').mkdir(parents=True)
        (p / 'uv').mkdir()
        sh('git', '-C', work, 'bundle', 'create', p / 'sop.bundle', 'main')
        shutil.copy2(work / 'bootstrap.sh', p / 'bootstrap.sh')
        (p / 'VERSION').write_text(self.version + '\n')
        (p / 'ARCH').write_text('amd64\n')
        (p / 'debs/Packages').write_text('')
        make_uv_archive(p / 'uv/uv-x86_64-unknown-linux-gnu.tar.gz')
        self.pkg = self.tmp / f'sop-offline-{self.version[:8]}-amd64.sh'
        w = self.tmp / 'packwork'
        w.mkdir()
        r = pack_func(f'WORK="{w}"; assemble "{p}" "{HEADER}" "{self.pkg}"', self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.fake('wget', 'echo "wget $*" >> "$FAKE_LOG"; exit 1')     # 断网：一叫就记下、连不上
        self.fake('sudo', 'echo "sudo $*" >> "$FAKE_LOG"; exit 0')

    def run_pkg(self, *args, path=None, **extra):
        env = self.env(UV_PYTHON_DOWNLOADS='never', **extra)
        if path:
            env['PATH'] = path
        return subprocess.run(['bash', str(self.pkg), *args], capture_output=True, text=True, input='', env=env, timeout=300,
                              cwd=self.tmp)

    def offline_dirs(self):
        return sorted(pathlib.Path('/tmp').glob('sop-offline.*'))

    def test_header_filled(self):
        head = self.pkg.read_bytes().split(b'\n__SOP_PAYLOAD_BELOW__\n', 1)[0].decode()
        self.assertIn(self.version, head)
        self.assertNotIn('@PAYLOAD_SHA256@', head)
        self.assertNotIn('@VERSION@', head)

    def test_offline_run(self):
        before = self.offline_dirs()
        r = self.run_pkg()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertIn('用的是离线包', out)
        self.assertIn('git、curl 都有了，跳过', out)
        self.assertIn('sop machine setup', out)
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else '')   # 没叫过 wget、sudo
        sop = self.h / 'tools/sop'
        self.assertEqual((sop / 'versions/latest').read_text(), self.version)
        self.assertEqual(sh('git', '-C', sop / 'versions' / self.version, 'rev-parse', 'HEAD'), self.version)
        net = json.loads((sop / 'config/network.json').read_text())
        self.assertNotIn('http_proxy', net)
        self.assertEqual(net['source'], 'detected')
        self.assertTrue((self.h / 'tools/uv/bin/uv').is_file())
        self.assertEqual(self.offline_dirs(), before)                  # 解开的临时目录删掉了
        self.assertEqual(sorted(p.name for p in self.h.iterdir()), ['.bashrc', 'tools'])
        # 再跑一遍：都跳过
        r = self.run_pkg()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('已经有了，跳过', r.stdout)
        self.assertIn('uv 已经有了', r.stdout)

    def test_offline_apt_uses_only_package(self):
        """缺 git：只用离线包里的软件包装（假 sudo 记下传了什么），apt 的软件源设置、索引都指到临时目录，不上网。"""
        nogit = self.tmp / 'nogit'
        nogit.mkdir()
        (nogit / 'curl').symlink_to('/usr/bin/true')
        off = self.tmp / 'off'
        (off / 'debs').mkdir(parents=True)
        (off / 'debs/Packages').write_text('')
        r = self.func(f'OFFLINE="{off}"; PROXY=; NOPROXY=; PATH="{self.bin}:{nogit}"; install_apt')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('装好了（用的是离线包里的软件包）', r.stdout)
        self.assertIn('登录密码', r.stdout)
        calls = self.log.read_text()
        self.assertIn('Dir::Etc::SourceList', calls)
        self.assertIn('trusted=yes', calls)
        self.assertTrue(calls.rstrip().endswith(f'sop-apt {off}/debs git'), calls)
        self.assertNotIn('wget', calls)
        # 离线包里没有软件包：停下明说
        (off / 'debs/Packages').unlink()
        self.log.unlink()
        r = self.func(f'OFFLINE="{off}"; PROXY=; NOPROXY=; PATH="{self.bin}:{nogit}"; install_apt')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('离线包不完整', r.stderr)
        self.assertFalse(self.log.exists())

    def test_damaged(self):
        data = bytearray(self.pkg.read_bytes())
        data[-100] ^= 1
        self.pkg.write_bytes(bytes(data))
        r = self.run_pkg()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('拷坏了', r.stderr)
        self.assertFalse((self.h / 'tools').exists())
        # 少一截（没拷完）
        self.pkg.write_bytes(bytes(data[:len(data) // 2]))
        r = self.run_pkg()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('拷坏了', r.stderr)
        self.assertFalse((self.h / 'tools').exists())
