"""3-08：M2 安装 uv、nvm、Node、pnpm、gh，缓存目录，终端启动文件里那一段（设计书 4.3、4.5；W36）。

真的下载、安装只在虚拟机里做（tests/vm/m2.sh）；这里在 /tmp 的临时目录里测：
那一段怎么加、怎么换、段落外的字一个不动；安装脚本和检查命令的环境只认规定位置；
清单里 nvm、Node、pnpm 的检查命令在环境里留着旧 nvm 时也不认错；安装的先查、再装、再查。
"""
import os
import pathlib
import stat
import subprocess

from machine import catalog, install, shellenv
from tests.helpers import REPO, TempHome, mock_env

OLD_RC = '# ~/.bashrc: 用户自己的\ncase $- in *i*) ;; *) return;; esac\nexport NVM_DIR="$HOME/.nvm"\nalias ll=\'ls -alF\'\n'


class TestBlock(TempHome):
    def setUp(self):
        super().setUp()
        self.tools = self.tmp / 'tools'
        self.rc = self.tmp / 'bashrc'

    def test_block_content(self):
        b = shellenv.block(pathlib.Path.home() / 'tools')
        self.assertTrue(b.startswith(shellenv.BEGIN + '\n') and b.endswith(shellenv.END + '\n'))
        for must in ('export NVM_DIR="$HOME/tools/nvm"', 'pnpm_config_store_dir="$HOME/tools/cache/pnpm/store"',
                     'pnpm_config_cache_dir=', 'pnpm_config_state_dir=', 'UV_CACHE_DIR="$HOME/tools/cache/uv"',
                     'UV_PYTHON_INSTALL_DIR="$HOME/tools/uv/python"', 'UV_PYTHON_BIN_DIR="$HOME/tools/uv/bin"',
                     'npm_config_cache="$HOME/tools/cache/npm"', '. "$NVM_DIR/nvm.sh"', '$HOME/tools/gh/bin', '$HOME/tools/pnpm/bin',
                     'export GH_TELEMETRY="0"'):
            self.assertIn(must, b)
        self.assertNotIn('export npm_config_store', b)   # pnpm 12 不认 npm_config_ 开头的（W36）
        # 每个缓存都在 ~/tools/cache/<工具名> 下
        for k, v in shellenv.variables(self.tools):
            if 'cache' in k.lower() or k.startswith('pnpm_config_'):
                rel = pathlib.Path(v).relative_to(self.tools / 'cache')
                self.assertIn(rel.parts[0], ('npm', 'pnpm', 'uv'))
        # 工具目录不是 ~/tools（自测）时写真实路径；带特殊字符的不写
        self.assertIn(f'export NVM_DIR="{self.tools}/nvm"', shellenv.block(self.tools))
        with self.assertRaises(shellenv.ShellEnvError):
            shellenv.block(self.tmp / 'a"b')
        # 网络设置里的软件源设了才写
        self.assertNotIn('registry', shellenv.block(self.tools, {}))
        b = shellenv.block(self.tools, {'npm_registry': 'https://registry.npmmirror.com/', 'pypi_index': 'https://pypi.tuna.tsinghua.edu.cn/simple'})
        self.assertIn('pnpm_config_registry="https://registry.npmmirror.com/"', b)
        self.assertIn('UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"', b)

    def test_block_works_in_bash(self):
        """那一段真的放进 bash 里跑：变量都对，PATH 最前面是规定位置，NVM_DIR 换成新的。"""
        self.rc.write_text(OLD_RC.replace('case $- in *i*) ;; *) return;; esac\n', ''))
        shellenv.install_block(self.rc, self.tools)
        out = subprocess.run(['bash', '-c', f'. "{self.rc}"; echo "$NVM_DIR|$UV_CACHE_DIR|$pnpm_config_store_dir|${{PATH%%:*}}"'],
                             capture_output=True, text=True, env={'HOME': str(self.tmp), 'PATH': '/usr/bin:/bin'}).stdout.strip()
        self.assertEqual(out, f'{self.tools}/nvm|{self.tools}/cache/uv|{self.tools}/cache/pnpm/store|{self.tools}/uv/bin')

    def test_append_replace_idempotent(self):
        self.rc.write_text(OLD_RC)
        os.chmod(self.rc, 0o640)
        self.assertTrue(shellenv.install_block(self.rc, self.tools))
        text = self.rc.read_text()
        self.assertTrue(text.startswith(OLD_RC))                         # 原来的字一个不动，加在末尾
        self.assertEqual(text, OLD_RC + '\n' + shellenv.block(self.tools))
        self.assertEqual(stat.S_IMODE(self.rc.stat().st_mode), 0o640)   # 权限照旧
        # 再装一次：内容一样就不写，修改时间也不动
        os.utime(self.rc, (1_000_000_000, 1_000_000_000))
        self.assertFalse(shellenv.install_block(self.rc, self.tools))
        self.assertEqual(self.rc.stat().st_mtime, 1_000_000_000)
        # 用户在那一段后面又加了东西；网络设置变了，重装：只换那一段，前后都不动
        self.rc.write_text(self.rc.read_text() + 'export EDITOR=vim\n')
        self.assertTrue(shellenv.install_block(self.rc, self.tools, {'npm_registry': 'https://r.example/'}))
        self.assertEqual(self.rc.read_text(), OLD_RC + '\n' + shellenv.block(self.tools, {'npm_registry': 'https://r.example/'}) + 'export EDITOR=vim\n')
        self.assertEqual(self.rc.read_text().count(shellenv.BEGIN), 1)
        self.assertEqual(list(self.tmp.glob('.bashrc*sop-tmp')) + list(self.tmp.glob('.*sop-tmp')), [])

    def test_no_trailing_newline_missing_file_symlink(self):
        self.rc.write_text('alias x=y')                                   # 最后一行没换行
        shellenv.install_block(self.rc, self.tools)
        self.assertTrue(self.rc.read_text().startswith('alias x=y\n\n' + shellenv.BEGIN))
        missing = self.tmp / 'none' / '.bashrc'
        missing.parent.mkdir()
        shellenv.install_block(missing, self.tools)
        self.assertEqual(missing.read_text(), shellenv.block(self.tools))
        self.assertEqual(stat.S_IMODE(missing.stat().st_mode), 0o644)
        # 是链接（管点文件的工具常这么做）：写到它指的文件，链接还是链接
        real = self.tmp / 'dotfiles-bashrc'
        real.write_text(OLD_RC)
        link = self.tmp / 'link-bashrc'
        link.symlink_to(real)
        shellenv.install_block(link, self.tools)
        self.assertTrue(link.is_symlink())
        self.assertIn(shellenv.BEGIN, real.read_text())

    def test_broken_marks_not_touched(self):
        for bad in (OLD_RC + shellenv.BEGIN + '\nexport A=1\n',                       # 只有开头
                    OLD_RC + shellenv.END + '\n',                                       # 只有结尾
                    OLD_RC + shellenv.block(self.tools) + shellenv.block(self.tools),   # 两段
                    OLD_RC + shellenv.END + '\n' + shellenv.BEGIN + '\n'):              # 结尾在前
            with self.subTest(bad=bad[-40:]):
                self.rc.write_text(bad)
                with self.assertRaises(shellenv.ShellEnvError):
                    shellenv.install_block(self.rc, self.tools)
                self.assertEqual(self.rc.read_text(), bad)
        self.rc.write_bytes(b'\xff\xfe not utf8')
        with self.assertRaises(shellenv.ShellEnvError):
            shellenv.install_block(self.rc, self.tools)


FAKE_NVM = r'''
# 假的 nvm.sh：nvm --version；nvm use --silent default 把 NVM_BIN 指到默认版本（没有默认版本就失败）
nvm() {
  case "$1" in
    --version) echo "$FAKE_NVM_VERSION" ;;
    use) [ -f "$NVM_DIR/alias/default" ] || return 3
         NVM_BIN="$NVM_DIR/versions/node/$(cat "$NVM_DIR/alias/default")/bin"; PATH="$NVM_BIN:$PATH"; export NVM_BIN PATH ;;
  esac
}
'''


def fake_nvm(root, version='0.40.3', node=None, pnpm=None):
    """在 root/nvm 下造一份假 nvm：node、pnpm 是打印版本号的小脚本。"""
    d = root / 'nvm'
    d.mkdir(parents=True)
    (d / 'nvm.sh').write_text(f'FAKE_NVM_VERSION={version}\n' + FAKE_NVM)
    if node:
        b = d / 'versions' / 'node' / f'v{node}' / 'bin'
        b.mkdir(parents=True)
        (d / 'alias').mkdir()
        (d / 'alias' / 'default').write_text(f'v{node}')
        for name, v in (('node', f'v{node}'), ('pnpm', pnpm)):
            if v:
                (b / name).write_text(f'#!/bin/sh\necho {v}\n')
                (b / name).chmod(0o755)
    return d


class TestChecks(TempHome):
    """清单里 nvm、Node、pnpm 的检查命令只认规定位置那一份。"""

    def setUp(self):
        super().setUp()
        self.tools = self.tmp / 'tools'
        self.old = self.tmp / 'old-home'
        self._t = mock_env({'SOP_TOOLS_DIR': str(self.tools)})
        self._t.__enter__()
        # 「旧的」：一份 ~/.nvm，有 Node 26 和 pnpm 12；终端里 NVM_DIR、NVM_BIN、PATH 都指着它
        old = fake_nvm(self.old, '0.40.3', node='26.1.0', pnpm='12.0.0')
        oldbin = old / 'versions' / 'node' / 'v26.1.0' / 'bin'
        self._o = mock_env({'NVM_DIR': str(old), 'NVM_BIN': str(oldbin), 'PATH': f'{oldbin}:{os.environ["PATH"]}',
                            'UV_CACHE_DIR': str(self.old / 'uvcache')})
        self._o.__enter__()

    def tearDown(self):
        self._o.__exit__(None, None, None)
        self._t.__exit__(None, None, None)
        super().tearDown()

    def results(self):
        return {n: catalog.run_check(catalog.find(n)) for n in ('nvm', 'node', 'pnpm')}

    def test_old_copy_is_not_counted(self):
        r = self.results()                                     # 规定位置什么都没有：一样都不算装了
        self.assertEqual([x.installed for x in r.values()], [False, False, False], r)
        fake_nvm(self.tools, '0.40.3')                         # 只装了 nvm，还没有 Node
        r = self.results()
        self.assertTrue(r['nvm'].ok)
        self.assertFalse(r['node'].installed, r['node'])       # 不会把旧的 Node 26 当成规定位置的
        self.assertFalse(r['pnpm'].installed, r['pnpm'])

    def test_versions_from_fixed_location(self):
        fake_nvm(self.tools, '0.39.0', node='22.3.0', pnpm='9.1.0')
        r = self.results()
        self.assertEqual([x.version for x in r.values()], [(0, 39, 0), (22, 3, 0), (9, 1, 0)])
        self.assertEqual([x.ok for x in r.values()], [False, False, False])   # 都不够清单的下限
        subprocess.run(['rm', '-rf', str(self.tools / 'nvm')])
        fake_nvm(self.tools, '0.40.3', node='26.13.1', pnpm='12.21.0')
        self.assertTrue(all(x.ok for x in self.results().values()))

    def test_env_for_scripts(self):
        env = install.script_env(net={'http_proxy': 'http://10.0.2.2:7890', 'https_proxy': 'http://10.0.2.2:7890',
                                      'no_proxy': 'localhost', 'npm_registry': 'https://r.example/'})
        self.assertEqual(env['SOP_TOOLS'], str(self.tools))
        self.assertEqual(env['NVM_DIR'], str(self.tools / 'nvm'))           # 旧的 NVM_DIR 换掉
        self.assertNotIn('NVM_BIN', env)                                     # 指着旧的去掉
        self.assertEqual(env['UV_CACHE_DIR'], str(self.tools / 'cache' / 'uv'))
        self.assertEqual(env['HTTPS_PROXY'], 'http://10.0.2.2:7890')
        self.assertEqual(env['npm_config_registry'], 'https://r.example/')
        self.assertTrue(env['PATH'].startswith(f'{self.tools}/uv/bin:'))
        self.assertEqual(env['HOME'], os.environ['HOME'])                    # 别的照旧


class TestInstall(TempHome):
    """先查、再装、再查；用临时清单和假安装脚本（真的安装脚本只在虚拟机里跑）。"""

    def setUp(self):
        super().setUp()
        self.tools = self.tmp / 'tools'
        self._t = mock_env({'SOP_TOOLS_DIR': str(self.tools)})
        self._t.__enter__()
        self.scripts = self.tmp / 'machine'
        (self.scripts / 'install').mkdir(parents=True)

    def tearDown(self):
        self._t.__exit__(None, None, None)
        super().tearDown()

    def tool(self, body, version='>=1.2'):
        (self.scripts / 'install' / 'fake.sh').write_text(body)
        t = catalog.Tool(name='fake', what='假的', version=version, location='~/tools/fake',
                         check='"$SOP_TOOLS/fake/bin/fake"', install='script:install/fake.sh', admin=False, step='M2')
        return t

    def run_tool(self, t):
        orig = catalog.HERE
        catalog.HERE = self.scripts
        try:
            return install.install_tool(t, env=install.script_env(net={}), out=subprocess.DEVNULL)
        finally:
            catalog.HERE = orig

    MAKE = 'mkdir -p "$SOP_TOOLS/fake/bin"; printf "#!/bin/sh\\necho fake {v}\\n" > "$SOP_TOOLS/fake/bin/fake"; chmod +x "$SOP_TOOLS/fake/bin/fake"; echo ran >> "$SOP_TOOLS/ran"\n'

    def test_install_then_skip(self):
        t = self.tool(self.MAKE.format(v='1.3.0'))
        r, msg = self.run_tool(t)
        self.assertTrue(r.ok, msg)
        self.assertIn('装好了', msg)
        r, msg = self.run_tool(t)                     # 已经合格：不再跑安装脚本
        self.assertIn('跳过', msg)
        self.assertEqual((self.tools / 'ran').read_text(), 'ran\n')

    def test_failures(self):
        r, msg = self.run_tool(self.tool('exit 7\n'))
        self.assertFalse(r.ok); self.assertIn('退出码 7', msg)
        r, msg = self.run_tool(self.tool('true\n'))
        self.assertFalse(r.ok); self.assertIn('找不到', msg)
        r, msg = self.run_tool(self.tool(self.MAKE.format(v='1.1.0')))
        self.assertFalse(r.ok); self.assertIn('不够', msg)

    def test_prepare(self):
        rc = self.tmp / 'bashrc'
        rc.write_text(OLD_RC)
        msgs = install.prepare(self.tools, {}, rc)
        for d in ('uv', 'npm', 'pnpm'):
            self.assertTrue((self.tools / 'cache' / d).is_dir())
        self.assertIn('写好了', msgs[1])
        self.assertIn('没改', install.prepare(self.tools, {}, rc)[1])

    def test_real_scripts(self):
        """真的安装脚本：清单里写的都在、bash 语法对；只往 $SOP_TOOLS 下装，不写终端启动文件；没给工具目录就不动。"""
        for name in install.MINE:
            kind, script = catalog.find(name).install_kind()
            self.assertEqual(kind, 'script')
            self.assertTrue(script.is_file(), script)
            self.assertEqual(subprocess.run(['bash', '-n', str(script)]).returncode, 0, script)
            text = script.read_text()
            self.assertNotIn('.bashrc', text)
            self.assertNotIn('.profile', text)
        lib = (REPO / 'machine' / 'install' / 'lib.sh').read_text()
        self.assertIn('PROFILE=/dev/null', (REPO / 'machine' / 'install' / 'nvm.sh').read_text())
        self.assertIn('UV_UNMANAGED_INSTALL', (REPO / 'machine' / 'install' / 'uv.sh').read_text())
        self.assertIn('sha256sum -c', (REPO / 'machine' / 'install' / 'gh.sh').read_text())
        self.assertIn('mktemp -d', lib)
        p = subprocess.run(['bash', str(REPO / 'machine' / 'install' / 'gh.sh')], capture_output=True, text=True,
                           env={'PATH': os.environ['PATH'], 'HOME': str(self.tmp)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('没给工具目录', p.stderr)
        p = subprocess.run(['bash', str(REPO / 'machine' / 'install' / 'node.sh')], capture_output=True, text=True,
                           env={'PATH': os.environ['PATH'], 'HOME': str(self.tmp), 'SOP_TOOLS': str(self.tools)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('还没有 nvm', p.stderr)
