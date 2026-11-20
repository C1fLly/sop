"""3-08：M2 安装 uv、nvm、Node、pnpm、gh，缓存目录，终端启动文件里那一段（设计书 4.3、4.5；W36）。
3-09：免管理员 Docker 的安装脚本怎么判断（--plan，只看不改）、用系统软件包装的几样（要管理员密码）。

真的下载、安装只在虚拟机里做（tests/vm/m2.sh）；这里在 /tmp 的临时目录里测：
那一段怎么加、怎么换、段落外的字一个不动；安装脚本和检查命令的环境只认规定位置；
清单里 nvm、Node、pnpm 的检查命令在环境里留着旧 nvm 时也不认错；安装的先查、再装、再查。
"""
import contextlib
import io
import os
import pathlib
import socket
import stat
import subprocess

from machine import catalog, components, install, shellenv
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
                     '$HOME/tools/docker/bin',
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
        for name in install.MINE + ('docker',):
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
        for name in ('uidmap', 'dbus-user-session'):
            self.assertEqual(catalog.find(name).install_kind(), ('apt', name))
        self.assertEqual(set(install.DOCKER) - {t.name for t in catalog.load()}, set())
        self.assertIn('mktemp -d', lib)
        p = subprocess.run(['bash', str(REPO / 'machine' / 'install' / 'gh.sh')], capture_output=True, text=True,
                           env={'PATH': os.environ['PATH'], 'HOME': str(self.tmp)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('没给工具目录', p.stderr)
        p = subprocess.run(['bash', str(REPO / 'machine' / 'install' / 'node.sh')], capture_output=True, text=True,
                           env={'PATH': os.environ['PATH'], 'HOME': str(self.tmp), 'SOP_TOOLS': str(self.tools)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('还没有 nvm', p.stderr)


DOCKER_SH = REPO / 'machine' / 'install' / 'docker-rootless.sh'


class TestDockerPlan(TempHome):
    """免管理员 Docker 的安装脚本 --plan：只看不改，打印怎么装。系统那几个位置都换成临时目录里的（4.8 的三处）。"""

    def setUp(self):
        super().setUp()
        self.h = self.tmp / 'home'
        self.run_dir = self.tmp / 'run-user'
        self.aa = self.tmp / 'apparmor.d'
        for d in (self.h, self.run_dir, self.aa):
            d.mkdir()
        self.units = self.h / '.config' / 'systemd' / 'user'
        self.mods = self.tmp / 'modules'
        self.mods.write_text('nf_tables 401408 0 - Live\nip_tables 32768 0 - Live\n')
        self.builtin = self.tmp / 'modules.builtin'
        self.builtin.write_text('')
        self.aa_on = self.tmp / 'aa-enabled'
        self.aa_on.write_text('Y\n')
        self.tools = self.h / 'tools'
        self.sock = self.tmp / 'docker.sock'          # 「系统自带的 Docker」的通道，用到才建
        self._socks = []

    def tearDown(self):
        for s in self._socks:
            s.close()
        super().tearDown()

    def make_sock(self, path, mode=0o660):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        os.chmod(path, mode)
        self._socks.append(s)

    def plan(self, ok=True):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.h), 'SOP_TOOLS': str(self.tools),
               'XDG_RUNTIME_DIR': str(self.run_dir), 'SOP_SYS_DOCKER_SOCK': str(self.sock),
               'SOP_APPARMOR_DIR': str(self.aa), 'SOP_APPARMOR_ENABLED': str(self.aa_on),
               'SOP_PROC_MODULES': str(self.mods), 'SOP_MODULES_BUILTIN': str(self.builtin)}
        p = subprocess.run(['bash', str(DOCKER_SH), '--plan'], capture_output=True, text=True, env=env)
        if not ok:
            self.assertNotEqual(p.returncode, 0)
            return p.stderr
        self.assertEqual(p.returncode, 0, p.stderr)
        return dict(line.split('=', 1) for line in p.stdout.splitlines())

    def context(self, name):
        (self.h / '.docker').mkdir(exist_ok=True)
        (self.h / '.docker' / 'config.json').write_text('{"auths": {}, "currentContext": "%s"}' % name)

    def unit(self, execstart):
        self.units.mkdir(parents=True, exist_ok=True)
        (self.units / 'docker.service').write_text(f'[Service]\nExecStart={execstart} --config-file x\n')

    def test_fresh_machine(self):
        p = self.plan()
        self.assertEqual((p['unit'], p['host'], p['force'], p['restore']),
                         ('docker', f'unix://{self.run_dir}/docker.sock', 'no', ''))
        self.assertTrue(p['module'].endswith('load=no'))
        # 系统规则的名字和体检（components.py）认的是同一个
        name = components.docker_rule_name(os.path.realpath(self.tools / 'docker' / 'bin' / 'rootlesskit'))
        self.assertEqual(p['rule'], f'{name} write=yes')
        self.assertEqual(list(self.aa.iterdir()), [])                       # 只看不改
        self.assertFalse((self.h / '.docker').exists())
        self.assertFalse(self.units.exists())

    def test_system_docker(self):
        """系统自带的在运行：小白能写它的通道才加 --force；装完默认指向切回原来那份。"""
        self.make_sock(self.sock)
        p = self.plan()
        self.assertEqual((p['unit'], p['force'], p['restore']), ('docker', '--force', 'default'))
        os.chmod(self.sock, 0o440)                                          # 小白不在 docker 组：官方脚本不中止，不加
        p = self.plan()
        self.assertEqual((p['force'], p['restore']), ('no', 'default'))
        self.context('desktop-linux')                                       # 原来指着别的：切回那个
        self.assertEqual(self.plan()['restore'], 'desktop-linux')
        self.context('rootless')                                            # 已经是 rootless（重装）：不动
        self.assertEqual(self.plan()['restore'], '')

    def test_context_without_system_docker(self):
        self.context('default')                                             # 电脑上只有这一份：留着官方脚本切到的 rootless
        self.assertEqual(self.plan()['restore'], '')
        self.context('remote-box')                                          # 原来指着别的：切回
        self.assertEqual(self.plan()['restore'], 'remote-box')
        (self.h / '.docker' / 'config.json').write_text('{坏的')
        self.assertIn('读不懂', self.plan(ok=False))

    def test_service_name_taken(self):
        """docker 这个服务名被另一份免管理员的 Docker 占了：用 sop-docker，另用一条通道，不用官方脚本（不切默认指向）。"""
        self.unit(f'{self.h}/bin/dockerd-rootless.sh')
        p = self.plan()
        self.assertEqual((p['unit'], p['host'], p['restore']), ('sop-docker', f'unix://{self.run_dir}/sop-docker/docker.sock', ''))
        self.make_sock(self.sock)                                           # 再加上系统自带的：也不切（官方脚本没跑）
        self.assertEqual(self.plan()['restore'], '')
        self.unit(f'{self.tools}/docker/bin/dockerd-rootless.sh')           # 是规定位置那份自己的（重装）：照用 docker
        self.assertEqual(self.plan()['unit'], 'docker')

    def test_manual_rootless_running(self):
        """另一份没用后台服务、自己在默认通道上跑着：也不占它的名字和通道。"""
        self.make_sock(self.run_dir / 'docker.sock')
        self.assertEqual(self.plan()['unit'], 'sop-docker')

    def test_admin_parts(self):
        self.mods.write_text('')                                            # 网络模块没载入：要载入
        self.assertTrue(self.plan()['module'].endswith('load=yes'))
        self.builtin.write_text('kernel/net/netfilter/nf_tables.ko\nkernel/net/ipv4/netfilter/ip_tables.ko\n')
        self.assertTrue(self.plan()['module'].endswith('load=no'))          # 编进内核的不用载入
        self.aa_on.write_text('N\n')                                       # 系统没开安全模块：不写规则
        self.assertTrue(self.plan()['rule'].endswith('write=no'))

    def test_refuse_odd_paths(self):
        self.tools = self.tmp / 'my tools'
        self.assertIn('空格或引号', self.plan(ok=False))


class TestInstallApt(TempHome):
    """用系统软件包装的几样：先说一句要做什么，再由系统问密码；几样合成一次 apt；代理按网络设置给进去。"""

    def fake_run(self, rc=0):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, rc)
        return calls, run

    def test_one_apt_with_explanation(self):
        calls, run = self.fake_run()
        tools = [catalog.find('uidmap'), catalog.find('dbus-user-session')]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok, msg = install.install_apt(tools, net={'http_proxy': 'http://p:1', 'https_proxy': 'http://p:1'}, run=run)
        self.assertTrue(ok)
        self.assertIn('装好了', msg)
        said = out.getvalue()
        self.assertIn('uidmap、dbus-user-session', said)
        self.assertIn('管理员权限', said)
        self.assertIn('登录密码', said)
        self.assertEqual(len(calls), 1)                                     # 合成一次
        cmd = calls[0]
        self.assertEqual(cmd[:3], ['sudo', '-p', install.SUDO_PROMPT])
        self.assertIn('http_proxy=http://p:1', cmd)
        self.assertNotIn('HTTP_PROXY=http://p:1', cmd)
        self.assertIn('DEBIAN_FRONTEND=noninteractive', cmd)
        self.assertEqual(cmd[-3:], ['sop-apt', 'uidmap', 'dbus-user-session'])
        self.assertIn('sop_apt update -qq && sop_apt install', cmd[-4])   # 等住软件包的锁（3-56）
        self.assertIn(install.APT_SH.read_text(), cmd[-4])

    def test_nothing_to_do_and_failure(self):
        calls, run = self.fake_run()
        self.assertEqual(install.install_apt([], run=run), (True, ''))
        self.assertEqual(calls, [])
        calls, run = self.fake_run(rc=1)
        with contextlib.redirect_stdout(io.StringIO()):
            ok, msg = install.install_apt([catalog.find('uidmap')], net={}, run=run)
        self.assertFalse(ok)
        self.assertIn('没装上', msg)
        self.assertIn('密码不对', msg)
        for rc, said, not_said in ((75, '系统正在自己更新软件', '密码不对'), (100, '连不上软件源', '密码不对')):
            calls, run = self.fake_run(rc=rc)
            with contextlib.redirect_stdout(io.StringIO()):
                ok, msg = install.install_apt([catalog.find('uidmap')], net={}, run=run)
            self.assertFalse(ok)
            self.assertIn(said, msg)
            self.assertNotIn(not_said, msg)


# 假的 apt-get：前 $FAKE_LOCKED 次报「锁被占」（$FAKE_LOCK_MSG 指定哪句），之后成功；$FAKE_APT_RC 有值时一律按它报别的错
FAKE_APT = '''#!/bin/bash
n=$(( $(cat "$T/apt-calls" 2>/dev/null || echo 0) + 1 )); echo $n > "$T/apt-calls"
echo "apt-get $* SOP_APT_WAIT=${SOP_APT_WAIT:-}" >> "$T/apt.log"
echo "normal output that should be hidden"
if [ -n "${FAKE_APT_RC:-}" ]; then echo "E: Unable to locate package nope" >&2; exit "$FAKE_APT_RC"; fi
if [ "$n" -le "${FAKE_LOCKED:-0}" ]; then
  printf '%s\n' "${FAKE_LOCK_MSG:-E: Could not get lock /var/lib/apt/lists/lock. It is held by process 1234 (apt-get)}" >&2
  echo "E: Unable to lock directory /var/lib/apt/lists/" >&2
  exit 100
fi
[ -z "${FAKE_WARN:-}" ] || echo "W: $FAKE_WARN" >&2
exit 0
'''
# 假的时钟：sleep 不真睡，只把时钟往后拨；date +%s 读这个时钟
FAKE_SLEEP = '#!/bin/bash\necho $(( $(cat "$T/clock" 2>/dev/null || echo 0) + $1 )) > "$T/clock"\n'
FAKE_DATE = '#!/bin/bash\necho $(( 1700000000 + $(cat "$T/clock" 2>/dev/null || echo 0) ))\n'


class TestAptWait(TempHome):
    """3-56：系统正在自己更新软件、占着软件包的锁时，等它（apt.sh 的 sop_apt）。
    真的 apt 只在虚拟机里（tests/vm/aptlock.sh）；这里用假的 apt-get、假的时钟。"""

    def setUp(self):
        super().setUp()
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        for name, body in (('apt-get', FAKE_APT), ('sleep', FAKE_SLEEP), ('date', FAKE_DATE),
                           ('sudo', '#!/bin/bash\nshift 2\nexec "$@"\n')):     # 假 sudo：去掉 -p 提示，直接跑
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def env(self, **extra):
        return {'PATH': f'{self.bin}:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'T': str(self.tmp), **extra}

    def sop_apt(self, *args, **extra):
        return subprocess.run(['sh', '-c', f'. "{install.APT_SH}"; sop_apt "$@"', 'x', *args],
                              capture_output=True, text=True, env=self.env(**extra))

    def calls(self):
        return int((self.tmp / 'apt-calls').read_text())

    def test_waits_until_lock_free(self):
        r = self.sop_apt('update', '-qq', FAKE_LOCKED='3', FAKE_WARN='a warning')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), 4)                       # 三次锁被占，第四次成了
        self.assertEqual(r.stderr.count('系统正在自己更新软件'), 1)   # 只说一次
        self.assertIn('最多等 10 分钟', r.stderr)
        self.assertNotIn('Could not get lock', r.stderr)        # 等到了就不打 apt 那几行英文
        self.assertIn('W: a warning', r.stderr)                 # 警告照打
        self.assertEqual(r.stdout, '')                          # 正常的输出扔掉
        self.assertIn('apt-get update -qq', (self.tmp / 'apt.log').read_text())

    def test_every_lock_and_language(self):
        for msg in ('E: Could not get lock /var/cache/apt/archives/lock. It is held by process 9 (unattended-upgr)',
                    'E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 9 (unattended-upgr)',
                    'E: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), is another process using it?',
                    'E: 无法获得锁 /var/lib/apt/lists/lock。锁正由进程 9（apt-get）持有'):
            (self.tmp / 'apt-calls').unlink(missing_ok=True)
            r = self.sop_apt('install', '-y', 'git', FAKE_LOCKED='1', FAKE_LOCK_MSG=msg)
            self.assertEqual((r.returncode, self.calls()), (0, 2), msg)

    def test_gives_up_with_75(self):
        r = self.sop_apt('update', FAKE_LOCKED='999', SOP_APT_WAIT='130')
        self.assertEqual(r.returncode, 75)
        self.assertEqual(self.calls(), 27)                      # 0、5、……、130 秒各试一次
        self.assertIn('最多等 3 分钟', r.stderr)
        self.assertEqual(r.stderr.count('还在等'), 2)           # 每分钟说一句
        self.assertIn('Could not get lock', r.stderr)           # 等不到才把 apt 的原话打出来
        self.assertIn('还没做完', r.stderr)

    def test_other_errors_not_waited(self):
        r = self.sop_apt('install', 'nope', FAKE_APT_RC='100')
        self.assertEqual(r.returncode, 100)
        self.assertEqual(self.calls(), 1)
        self.assertIn('Unable to locate package', r.stderr)
        self.assertNotIn('系统正在自己更新', r.stderr)

    def test_install_apt_end_to_end(self):
        """install_apt 真的拼出来的那条命令（假 sudo、真 env 和 sh）：等到了装上；等不到说系统正在自己更新、不说密码不对。"""
        def run(cmd, **kw):
            return subprocess.run(cmd, env=self.env(**env), capture_output=True, text=True)
        tools = [catalog.find('uidmap')]
        env = {'FAKE_LOCKED': '2'}
        with contextlib.redirect_stdout(io.StringIO()):
            ok, msg = install.install_apt(tools, net={}, run=run)
        self.assertTrue(ok, msg)
        log = (self.tmp / 'apt.log').read_text().splitlines()
        self.assertEqual([x.split()[1] for x in log], ['update', 'update', 'update', 'install'])
        self.assertIn('--no-install-recommends uidmap', log[-1])
        (self.tmp / 'apt-calls').unlink()
        env = {'FAKE_LOCKED': '999'}
        with mock_env({'SOP_APT_WAIT': '20'}), contextlib.redirect_stdout(io.StringIO()):
            ok, msg = install.install_apt(tools, net={}, run=run)
        self.assertFalse(ok)
        self.assertIn('系统正在自己更新软件', msg)
        self.assertNotIn('密码不对', msg)
        self.assertIn('SOP_APT_WAIT=20', (self.tmp / 'apt.log').read_text())   # 期限给得进 sudo

    def test_docker_script_uses_it(self):
        """Docker 的安装脚本给 sudo 的那一小段载入 apt.sh、用 sop_apt；认出 75。"""
        t = (REPO / 'machine/install/docker-rootless.sh').read_text()
        self.assertIn('cat "$(dirname "$0")/apt.sh"', t)
        self.assertIn("echo 'sop_apt update -qq'", t)
        self.assertIn('75) die', t)
        self.assertNotIn('-o DPkg::Lock::Timeout', t)
