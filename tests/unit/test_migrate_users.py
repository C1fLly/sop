"""3-60：环境迁移 Q1「旧的 nvm、uv、Node 还有谁在用」（设计书 4.8）。只读：在测试自己的临时目录里造一个主目录，
里面放旧的 nvm（~/.nvm，Node 两个版本、全局装的 pnpm 和 Codex）、旧的 uv（~/.local/bin/uv、uvx、env，
~/.local/share/uv 里有它装的 Python 和一个 uv tool）、旧的 pnpm（~/.local/share/pnpm 全局装了一个包）、
几个 Python 环境、终端启动文件和用户级服务；不碰这台电脑上的 ~/.nvm、~/.local。

造法照本机 2026-11-21 只读看到的样子：Pi 是 ~/.local/bin/pi → ~/.pi/agent/bin/pi 的 sh 启动脚本，最后交给
node_modules/.bin/pi（#!/usr/bin/env node）；Claude Code、Codex（官方单文件装法）是 ELF；uv 的安装程序在
~/.bashrc、~/.zshrc 里加了 `. "$HOME/.local/bin/env"`。
"""
import dataclasses
import os
import pathlib

from machine import catalog, shellenv
from machine.migrate import inventory as inv
from machine.migrate import users
from tests.helpers import TempHome, mock_env

ELF = b'\x7fELF\x02\x01\x01' + b'\0' * 32
NODE_V = 'v22.11.0'
PY = 'cpython-3.12.7-linux-x86_64-gnu'
PI_LAUNCHER = '''#!/bin/sh
pi_node_bin=${XDG_DATA_HOME:-$HOME/.local/share}/pi-node/current/bin
if [ -x "$pi_node_bin/node" ]; then PATH=$pi_node_bin:$PATH; fi
exec "$pi_agent_dir/install/releases/$v/node_modules/.bin/pi" "$@"
'''


def put(p, data='', mode=None):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    (p.write_bytes if isinstance(data, bytes) else p.write_text)(data)
    if mode is not None:
        os.chmod(p, mode)
    return p


def link(target, p):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, p)


def snapshot(root):
    """目录里每样东西的修改时间和大小（核对「只读」）。"""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            st = os.lstat(os.path.join(d, n))
            out[os.path.join(d, n)] = (st.st_mtime_ns, st.st_size)
    return out


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.h = self.tmp / 'xiaobai'
        self.h.mkdir()
        self.tools_dir = self.tmp / 'tools'      # 规定位置（~/tools）：不在造出来的主目录下面，和 catalog 的规定位置一致
        self.tools_dir.mkdir()
        self._tools_env = mock_env({'SOP_TOOLS_DIR': str(self.tools_dir)})
        self._tools_env.__enter__()

    def tearDown(self):
        self._tools_env.__exit__(None, None, None)
        super().tearDown()

    # ---------- 造旧的 ----------
    def old_nvm(self, versions=(NODE_V, 'v20.18.0'), default='22'):
        n = self.h / '.nvm'
        put(n / 'nvm.sh', '# nvm\n')
        put(n / 'alias/default', default + '\n')
        for v in versions:
            put(n / f'versions/node/{v}/bin/node', ELF, 0o755)
            mods = n / f'versions/node/{v}/lib/node_modules'
            put(mods / 'npm/package.json', '{"name": "npm", "bin": {"npm": "bin/npm-cli.js", "npx": "bin/npx-cli.js"}}')
            put(mods / 'corepack/package.json', '{"name": "corepack", "bin": {"corepack": "dist/corepack.js"}}')
        mods = n / f'versions/node/{NODE_V}/lib/node_modules'
        put(mods / 'pnpm/package.json', '{"name": "pnpm", "bin": {"pnpm": "bin/pnpm.cjs", "pnpx": "bin/pnpx.cjs"}}')
        put(mods / '@openai/codex/package.json', '{"name": "@openai/codex", "bin": {"codex": "bin/codex.js"}}')
        put(mods / '@openai/codex/bin/codex.js', '#!/usr/bin/env node\n', 0o755)
        put(mods / 'broken/package.json', '{坏的')
        link('../lib/node_modules/@openai/codex/bin/codex.js', n / f'versions/node/{NODE_V}/bin/codex')
        return n

    def old_uv(self):
        b = self.h / '.local/bin'
        put(b / 'uv', ELF, 0o755)
        put(b / 'uvx', ELF, 0o755)
        put(b / 'env', '#!/bin/sh\ncase ":${PATH}:" in *:"$HOME/.local/bin":*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n')
        put(b / 'env.fish', 'if not contains "$HOME/.local/bin" $PATH\nend\n')
        data = self.h / '.local/share/uv'
        py = data / f'python/{PY}/bin/python3.12'
        put(py, ELF, 0o755)
        put(data / 'python/.lock', '')
        put(data / 'tools/ruff/bin/ruff', f'#!{data}/tools/ruff/bin/python\n', 0o755)
        link(str(data / 'tools/ruff/bin/ruff'), b / 'ruff')
        return data

    def venv(self, d, home, *, uv='0.5.11', link_to=None):
        d = pathlib.Path(d)
        put(d / 'pyvenv.cfg', f'home = {home}\nimplementation = CPython\n' + (f'uv = {uv}\n' if uv else '')
            + 'version_info = 3.12.7\ninclude-system-site-packages = false\n')
        link(link_to or f'{home}/python3', d / 'bin/python')
        return d

    def ai_tools(self):
        b = self.h / '.local/bin'
        put(self.h / '.local/share/claude/versions/2.1.330', ELF, 0o755)
        link(str(self.h / '.local/share/claude/versions/2.1.330'), b / 'claude')
        put(self.h / '.pi/agent/bin/pi', PI_LAUNCHER, 0o755)
        put(self.h / '.pi/agent/install/releases/1.0/node_modules/.bin/pi', '#!/usr/bin/env node\n', 0o755)
        link('../../.pi/agent/bin/pi', b / 'pi')
        put(self.h / '.opencode/bin/opencode', ELF, 0o755)

    def path_env(self, *extra):
        return os.pathsep.join([str(self.h / '.opencode/bin'), str(self.h / f'.nvm/versions/node/{NODE_V}/bin'),
                                str(self.h / '.local/bin'), *map(str, extra)])

    # ---------- 清点 ----------
    def tools(self):
        """工具清单里的 uv、nvm、Node、pnpm（别的装法常放的位置只留主目录下的，系统目录在这台电脑上是真的）。"""
        out = []
        for t in catalog.load():
            if t.name in ('uv', 'nvm', 'node', 'pnpm', 'gh'):
                out.append(dataclasses.replace(t, elsewhere=tuple(e for e in t.elsewhere if e.startswith('~/'))))
        return out

    def probe(self, path_env=None):
        return inv.Probe(root=str(self.tmp / 'sys'), home=str(self.h), runtime=str(self.tmp / 'rt'),
                         run=lambda a, t: (1, '', '（测试）不该跑命令'), admin=None, usage=lambda p: (1000, False),
                         sysdisk=lambda p: False, user='xiaobai', tools=str(self.tools_dir),
                         path_env=self.path_env() if path_env is None else path_env, now=0)

    def run_inventory(self, path_env=None):
        p = self.probe(path_env)
        r = inv.inventory(p, tools=self.tools())
        self.assertEqual([a for a in p.ran if a[:2] != ['dpkg-query', '-W']], [], '只许查软件包，不该跑别的命令')
        return r, r['tool_users']

    def find(self, res, kind, what=None):
        got = [i for i in res['items'] if i['kind'] == kind and (what is None or what in i['what'])]
        return got


class TestWhoUsesOld(Base):
    def full_home(self):
        self.old_nvm()
        data = self.old_uv()
        put(self.h / '.local/share/pnpm/global/5/node_modules/serve/package.json', '{"name": "serve", "bin": "bin/serve.js"}')
        put(self.h / '.local/share/pnpm/store/v10/files/00/abc', 'x')
        self.ai_tools()
        pybin = data / f'python/{PY}/bin'
        self.venv(self.h / 'Project/shop/.venv', pybin)
        self.venv(self.h / 'Project/shop/backend/.venv', pybin, uv='')                  # 不是 uv 建的，Python 是旧 uv 的
        self.venv(self.h / 'code/other/.venv', '/usr/bin', link_to='/usr/bin/python3')  # 系统的 Python：不算
        self.venv(self.h / 'Project/web/node_modules/x/.venv', pybin)                  # node_modules 里不找
        self.venv(self.h / 'a/b/c/d/e/f/g/.venv', pybin)                               # 太深不找
        put(self.h / '.bashrc', '# ~/.bashrc\nalias ll="ls -l"\n# 以前装过 ~/.nvm\n'
            'export NVM_DIR="$HOME/.nvm"\n[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"  # This loads nvm\n'
            '. "$HOME/.local/bin/env"\n' + shellenv.block(self.tools_dir))
        put(self.h / '.profile', 'if [ -d "$HOME/.local/bin" ] ; then\n    PATH="$HOME/.local/bin:$PATH"\nfi\n'
            '. "$HOME/.local/bin/env"\n')
        put(self.h / '.zshrc', 'export PATH=~/.nvm/versions/node/v20.18.0/bin:$PATH\n')
        put(self.h / '.config/fish/conf.d/uv.env.fish', 'source "$HOME/.local/bin/env.fish"\n')
        put(self.h / '.config/systemd/user/notes.service',
            f'[Service]\nExecStart=%h/.nvm/versions/node/{NODE_V}/bin/node %h/srv/notes.js\n')
        put(self.h / '.config/systemd/user/docker.service', f'[Service]\nExecStart={self.tools_dir}/docker/bin/dockerd\n')
        put(self.h / '.config/autostart/clip.desktop', '[Desktop Entry]\nExec=/usr/bin/clip\n')
        put(self.h / 'bin/mdview', '#!/usr/bin/env node\n', 0o755)
        put(self.h / 'bin/hello', '#!/bin/bash\necho hi\n', 0o755)
        put(self.h / 'bin/oldpy', f'#!{pybin}/python3.12\n', 0o755)
        return data

    def test_everything(self):
        """造齐一整套旧的：每一类「还在用」都列出来，不该列的不列；只看文件，主目录里一样东西都没变。"""
        self.full_home()
        before = snapshot(self.h)
        r, res = self.run_inventory()
        self.assertEqual(snapshot(self.h), before, '清点改了主目录里的东西')
        olds = {(o['tool'], o['path']) for o in res['old']}
        self.assertEqual(olds, {('uv', '~/.local/bin/uv'), ('uv', '~/.local/share/uv'), ('nvm', '~/.nvm'),
                                ('pnpm', '~/.local/share/pnpm')})
        # AI 工具：Pi 靠 Node 运行、现在终端里找到的是旧的；Claude Code、OpenCode 是单个程序，不列
        ai = {i['what']: i for i in self.find(res, 'ai-tool')}
        self.assertEqual(sorted(ai), ['Codex', 'Pi'])
        self.assertEqual((ai['Pi']['tool'], ai['Pi']['how'], ai['Pi']['where']), ('nvm', 'launcher', '~/.local/bin/pi'))
        self.assertIn(f'~/.nvm/versions/node/{NODE_V}/bin/node', ai['Pi']['effect'])
        # Codex 装成旧 nvm 里的全局包（PATH 里先找到的是旧 nvm 的 bin）：卸了就没了
        self.assertIn('装在旧的 nvm（~/.nvm）里面', ai['Codex']['effect'])
        # 旧的里面装着的
        vers = {i['version']: i['default'] for i in self.find(res, 'node-version')}
        self.assertEqual(vers, {NODE_V: True, 'v20.18.0': False})
        glob = {i['what'] for i in self.find(res, 'global')}
        self.assertEqual(glob, {'pnpm（命令 pnpm、pnpx）', '@openai/codex（命令 codex）', 'broken', 'serve（命令 serve）'})
        self.assertEqual([i['what'] for i in self.find(res, 'python')], ['Python 3.12.7'])
        uvt = self.find(res, 'uv-tool')
        self.assertEqual([(i['what'], i['commands']) for i in uvt], [('ruff（命令 ~/.local/bin/ruff）', ['~/.local/bin/ruff'])])
        self.assertIn('uv tool install ruff', uvt[0]['fix'])
        # 命令：靠 Node 运行的 mdview、第一行写死旧 Python 的 oldpy；bash 写的 hello、uv 自己、ruff（算在 uv tool 里）不另列
        cmds = {i['what']: i for i in self.find(res, 'command')}
        self.assertEqual(sorted(cmds), ['mdview', 'oldpy'])
        self.assertEqual(cmds['oldpy']['tool'], 'uv')
        # Python 环境：两个用旧 uv 的 Python 的；系统 Python 的、node_modules 里的、太深的不列
        vs = {i['where']: i for i in self.find(res, 'venv')}
        self.assertEqual(sorted(vs), ['~/Project/shop/.venv', '~/Project/shop/backend/.venv'])
        self.assertEqual((vs['~/Project/shop/.venv']['version'], vs['~/Project/shop/.venv']['made_by_uv']), ('3.12.7', '0.5.11'))
        self.assertIn('uv sync', vs['~/Project/shop/.venv']['fix'])
        self.assertGreater(res['scanned_dirs'], 5)
        self.assertFalse(res['scan_partial'])
        # 终端启动文件：nvm 的两行、uv 的 env 那几行、zsh 里直接写的旧 Node；注释、SOP 那一段、Ubuntu 自带的那几行不列
        sh = {(i['where'], i['line_no']): i for i in self.find(res, 'shell')}
        self.assertEqual(sorted(sh), [('~/.bashrc', 4), ('~/.bashrc', 5), ('~/.bashrc', 6), ('~/.config/fish/conf.d/uv.env.fish', 1),
                                      ('~/.profile', 4), ('~/.zshrc', 1)])
        self.assertEqual(sh[('~/.bashrc', 5)]['tool'], 'nvm')
        env_line = sh[('~/.bashrc', 6)]
        self.assertEqual(env_line['tool'], 'uv')
        self.assertIn('claude', env_line['keeps'])
        self.assertIn('pi', env_line['keeps'])
        self.assertNotIn('uv', env_line['keeps'])
        self.assertIn('留着', env_line['fix'])
        self.assertEqual(sh[('~/.zshrc', 1)]['tool'], 'nvm')
        # 后台服务：指向旧 Node 的列，规定位置 Docker 的不列
        sv = self.find(res, 'service')
        self.assertEqual([i['what'] for i in sv], ['用户级后台服务 notes.service'])
        # 给人看的
        text = inv.describe(r, 0)
        for s in ('谁还在用旧的 nvm、uv、Node', 'Pi（~/.local/bin/pi）：Pi 靠 Node 运行', 'Node v22.11.0（~/.nvm/versions/node/v22.11.0）：旧的 nvm 里默认用的就是它',
                  '~/Project/shop/.venv：这个 Python 环境用的是旧的 uv 里的 Python 3.12.7', '那一行：. "$HOME/.local/bin/env"',
                  '用户级后台服务 notes.service', '看了'):
            self.assertIn(s, text)

    def test_new_node_first(self):
        """终端里先找到的是规定位置那份 Node：Pi 和靠 Node 运行的命令不再算在用旧的。"""
        self.full_home()
        new = self.tools_dir / 'nvm/versions/node/v24.11.0/bin'
        put(new / 'node', ELF, 0o755)
        path_env = os.pathsep.join([str(new), str(self.h / '.local/bin'), str(self.h / 'bin')])
        _, res = self.run_inventory(path_env)
        self.assertEqual([i['what'] for i in self.find(res, 'ai-tool')], [])
        self.assertEqual([i['what'] for i in self.find(res, 'command')], ['oldpy'])
        self.assertTrue(self.find(res, 'node-version'))          # 旧的里面装着的照样列

    def test_pi_own_node(self):
        """Pi 的安装程序自带了 Node（~/.local/share/pi-node）：Pi 用它，不算在用旧的。"""
        self.full_home()
        put(self.h / '.local/share/pi-node/current/bin/node', ELF, 0o755)
        _, res = self.run_inventory()
        self.assertNotIn('Pi', [i['what'] for i in self.find(res, 'ai-tool')])

    def test_env_line_alone(self):
        """~/.local/bin 里只有旧 uv 自己（没有别的命令）：env 那一行跟着旧的一起删。"""
        self.old_uv()
        os.remove(self.h / '.local/bin/ruff')
        put(self.h / '.bashrc', '. "$HOME/.local/bin/env"\n')
        _, res = self.run_inventory(path_env=str(self.h / '.local/bin'))
        sh = self.find(res, 'shell')
        self.assertEqual(len(sh), 1)
        self.assertEqual(sh[0]['keeps'], [])
        self.assertIn('一起删掉', sh[0]['fix'])

    def test_nvm_dir_points_to_new(self):
        """终端启动文件自己把 NVM_DIR 指到规定位置：用 $NVM_DIR 的那几行不算旧的；写着 ~/.nvm 的才算。"""
        self.old_nvm()
        put(self.h / '.bashrc', f'export NVM_DIR="{self.tools_dir}/nvm"\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
            'source ~/.nvm/bash_completion\n')
        _, res = self.run_inventory(path_env='')
        self.assertEqual([i['line_no'] for i in self.find(res, 'shell')], [3])

    def test_nothing_old(self):
        """没有旧的 nvm、uv、Node：什么都不找（主目录都不走一遍），给人看的也不多一段。"""
        self.ai_tools()
        self.venv(self.h / 'Project/x/.venv', '/usr/bin')
        r, res = self.run_inventory(path_env=str(self.h / '.local/bin'))
        self.assertEqual((res['old'], res['items'], res['scanned_dirs']), ([], [], 0))
        self.assertNotIn('谁还在用', inv.describe(r, 0))

    def test_old_but_unused(self):
        """有旧的、没人用：明说没发现。"""
        put(self.h / '.local/bin/uv', ELF, 0o755)
        r, res = self.run_inventory(path_env=str(self.h / '.local/bin'))
        self.assertEqual(res['items'], [])
        self.assertIn('没发现还有谁在用', inv.describe(r, 0))

    def test_scan_limit(self):
        """目录太多时只看前面的、写明没找全。"""
        self.old_uv()
        for i in range(30):
            (self.h / f'many/d{i}').mkdir(parents=True)
        roots = users.old_roots(self.probe(), inv.other_tools(self.probe(), self.tools()))
        _, seen, partial = users.venvs(self.probe(), roots, max_dirs=10)
        self.assertTrue(partial)
        self.assertEqual(seen, 11)


class TestRuntime(Base):
    def test_runtime(self):
        """看可执行文件的开头认怎么运行。"""
        cases = {'a': (ELF, ('native', '')), 'b': ('#!/usr/bin/env node\n', ('node-env', '')),
                 'c': ('#!/usr/bin/env -S node --no-warnings\n', ('node-env', '')),
                 'd': ('#!/home/x/.nvm/versions/node/v1/bin/node\n', ('interp', '/home/x/.nvm/versions/node/v1/bin/node')),
                 'e': ('#!/bin/sh\nexec "$d/node_modules/.bin/pi"\n', ('launcher', '/bin/sh')),
                 'f': ('#!/bin/bash\necho hi\n', ('script', '/bin/bash')), 'g': ('#!/usr/bin/env python3\n', ('script', 'python3')),
                 'h': ('plain', ('unknown', '')), 'i': ('#!/bin/sh\npi_node_bin=x\n', ('script', '/bin/sh'))}
        for name, (data, want) in cases.items():
            self.assertEqual(users.runtime(str(put(self.tmp / 'rt' / name, data))), want, name)
        self.assertEqual(users.runtime(str(self.tmp / 'nope')), ('unknown', ''))
