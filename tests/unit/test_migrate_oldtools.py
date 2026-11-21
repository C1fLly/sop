"""3-61：环境迁移 Q6「卸旧的 nvm、uv、pnpm」（设计书 4.8）。全在测试自己的临时目录里造：主目录（旧的 ~/.nvm、~/.local/bin/uv、
~/.local/share/uv、~/.local/share/pnpm，终端启动文件照 Ubuntu 的样子和三个官方安装程序加的几行）、规定位置 ~/tools（假的 nvm、
Node、pnpm、uv）。不碰这台电脑上的 ~/.nvm、~/.local、~/.bashrc。

「新开一个终端看看」真的起 bash -i、bash -l -i（HOME 是造出来的主目录、环境是干净的），外面套一层整个系统只读、
只有测试临时目录能写、不联网的 bubblewrap，所以系统的 /etc/profile 读到了也写不了任何东西。
"""
import json
import os
import shutil

from machine import shellenv
from machine.migrate import flow, inventory as inv, oldtools as O, record
from tests import safehome
from tests.helpers import mock_env
from tests.unit.test_migrate_users import ELF, NODE_V, PY, Base, link, put, snapshot

NEW_V = 'v24.11.0'
UBUNTU_BASHRC_HEAD = '# ~/.bashrc\ncase $- in\n    *i*) ;;\n      *) return;;\nesac\nalias ll=\'ls -alF\'\n'
NVM_LINES = ('export NVM_DIR="$HOME/.nvm"\n'
             '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"  # This loads nvm\n'
             '[ -s "$NVM_DIR/bash_completion" ] && \\. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion\n')
ENV_LINE = '. "$HOME/.local/bin/env"\n'
PNPM_LINES = ('\n# pnpm\nexport PNPM_HOME="{h}/.local/share/pnpm"\ncase ":$PATH:" in\n  *":$PNPM_HOME:"*) ;;\n'
              '  *) export PATH="$PNPM_HOME:$PATH" ;;\nesac\n# pnpm end\n')
SKEL_PROFILE = '''# ~/.profile: executed by the command interpreter for login shells.
if [ -n "$BASH_VERSION" ]; then
    if [ -f "$HOME/.bashrc" ]; then
	. "$HOME/.bashrc"
    fi
fi
if [ -d "$HOME/bin" ] ; then
    PATH="$HOME/bin:$PATH"
fi
if [ -d "$HOME/.local/bin" ] ; then
    PATH="$HOME/.local/bin:$PATH"
fi
'''
UV_ENV = '#!/bin/sh\ncase ":${PATH}:" in\n    *:"$HOME/.local/bin":*) ;;\n    *) export PATH="$HOME/.local/bin:$PATH" ;;\nesac\n'


class OldToolsBase(Base):
    def setUp(self):
        super().setUp()
        self.said = []
        bw = shutil.which('bwrap')
        self.assertTrue(bw, '这项测试要用 bubblewrap 把「新开的终端」关在只读的系统里')
        self.wrap = [bw, '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc', '--bind', str(self.tmp), str(self.tmp),
                     '--unshare-net', '--die-with-parent', '--']

    # ---------- 规定位置（假的） ----------
    def new_tools(self):
        t = self.tools_dir
        put(t / 'nvm/nvm.sh', f'export PATH="$NVM_DIR/versions/node/{NEW_V}/bin:$PATH"\n')
        for c in ('node', 'pnpm'):
            put(t / f'nvm/versions/node/{NEW_V}/bin/{c}', '#!/bin/sh\necho new\n', 0o755)
        put(t / 'uv/bin/uv', '#!/bin/sh\necho new\n', 0o755)

    # ---------- 旧的 ----------
    def old_home(self, *, sop_block=True):
        h = self.h
        put(h / '.nvm/nvm.sh', f'export PATH="$NVM_DIR/versions/node/{NODE_V}/bin:$PATH"\n')
        put(h / '.nvm/alias/default', '22\n')
        put(h / f'.nvm/versions/node/{NODE_V}/bin/node', ELF, 0o755)
        mods = h / f'.nvm/versions/node/{NODE_V}/lib/node_modules'
        put(mods / 'npm/package.json', '{"name": "npm", "bin": {"npm": "bin/npm-cli.js"}}')
        put(mods / 'pnpm/package.json', '{"name": "pnpm", "bin": {"pnpm": "bin/pnpm.cjs"}}')
        self.old_uv()                                        # ~/.local/bin/uv、uvx、env、env.fish，~/.local/share/uv（Python、uv tool ruff）
        put(h / '.local/bin/env', UV_ENV)
        put(h / '.config/uv/uv-receipt.json', json.dumps({'install_prefix': f'{h}/.local/bin', 'binaries': ['uv', 'uvx']}))
        put(h / '.local/share/pnpm/pnpm', ELF, 0o755)
        put(h / '.local/share/pnpm/global/5/node_modules/serve/package.json', '{"name": "serve", "bin": "bin/serve.js"}')
        self.ai_tools()                                      # claude、pi 在 ~/.local/bin
        put(h / 'bin/mdview', '#!/usr/bin/env node\n', 0o755)
        self.venv(h / 'Project/shop/.venv', h / f'.local/share/uv/python/{PY}/bin')
        self.bashrc = (UBUNTU_BASHRC_HEAD + NVM_LINES + ENV_LINE + PNPM_LINES.format(h=h)
                       + (shellenv.block(self.tools_dir) if sop_block else ''))
        put(h / '.bashrc', self.bashrc)
        put(h / '.profile', SKEL_PROFILE + ENV_LINE)
        put(h / '.zshrc', f'export PATH=~/.nvm/versions/node/{NODE_V}/bin:$PATH\nsetopt autocd\n')
        put(h / '.config/fish/conf.d/uv.env.fish', 'source "$HOME/.local/bin/env.fish"\n')
        # 旧的里面装着的、规定位置那份已经重装过的
        put(self.tools_dir / 'uv/tools/ruff/bin/ruff', '#!/bin/sh\n', 0o755)
        put(self.tools_dir / 'pnpm/global/5/node_modules/serve/package.json', '{"name": "serve"}')

    # ---------- 跑 ----------
    def host(self, **kw):
        kw.setdefault('check', lambda n: True)
        return O.Host(self.probe(), wrap=self.wrap, tools=self.tools(), **kw)

    def choices(self, *paths):
        ALL = (('nvm', '~/.nvm'), ('uv', '~/.local/bin/uv'), ('uv', '~/.local/share/uv'), ('pnpm', '~/.local/share/pnpm'))
        return {'tools': [{'name': n, 'path': p, 'choice': O.DROP if (not paths or p in paths) else 'keep'} for n, p in ALL]}

    def q6(self, ch, answers=('y',), host=None):
        s = flow.Session(self.said.append, flow.Ask(list(answers), say=self.said.append), self.probe())
        rc = O.q6_tools(ch, s, host=host or self.host())
        return rc, '\n'.join(self.said)

    def first(self, login, cmd, host=None):
        found, why = (host or self.host()).new_shell(login)
        self.assertIsNotNone(found, why)
        return (found.get(cmd) or [None])[0]


class TestUninstall(OldToolsBase):
    def test_all_three(self):
        """选了卸旧的 nvm、uv（程序和 ~/.local/share/uv）、pnpm：只删那几行（先备份）、新终端核对过才删目录，
        env 那一行和 env 文件留着（~/.local/bin 里还有 claude、pi）；卸完再清点，这几样都不在了；
        登录的终端里原来先找到的是旧 uv（3-08），卸完是规定位置那份。"""
        self.new_tools()
        self.old_home()
        h, t = self.h, self.tools_dir
        # 卸之前：登录的终端里 uv 先找到的是旧的（3-08 留下的问题），桌面上开的终端是规定位置的
        self.assertEqual(self.first(True, 'uv'), f'{h}/.local/bin/uv')
        self.assertEqual(self.first(False, 'uv'), f'{t}/uv/bin/uv')
        keep_before = {k: v for k, v in snapshot(h).items() if not k.startswith((f'{h}/.nvm', f'{h}/.local/share/uv', f'{h}/.local/share/pnpm'))
                       and k not in {f'{h}/.bashrc', f'{h}/.zshrc', f'{h}/.local/bin/uv', f'{h}/.local/bin/uvx', f'{h}/.local/bin/ruff',
                                     f'{h}/.config/uv/uv-receipt.json', f'{h}/.config/uv',
                                     f'{h}/.local/bin', f'{h}/.local/share'}}     # 后两个是删了东西的目录本身（修改时间跟着变）
        rc, out = self.q6(self.choices())
        self.assertEqual(rc, 0, out)
        for s in ('~/.nvm', '~/.local/bin/uvx', '~/.local/share/pnpm', '确定现在卸掉它们吗',
                  '~/Project/shop/.venv', '留着：', 'mdview', '卸完了'):
            self.assertIn(s, out)
        for gone in ('.nvm', '.local/bin/uv', '.local/bin/uvx', '.local/share/uv', '.local/share/pnpm', '.local/bin/ruff',
                     '.config/uv/uv-receipt.json'):
            self.assertFalse(os.path.lexists(h / gone), gone)
        for kept in ('.local/bin/env', '.local/bin/env.fish', '.local/bin/claude', '.local/bin/pi', 'bin/mdview'):
            self.assertTrue(os.path.lexists(h / kept), kept)
        # 终端启动文件：只删了那几行，别的一个字不动；备份是原来的样子
        want = self.bashrc.replace(NVM_LINES, '').replace(PNPM_LINES.format(h=h), '\n')
        self.assertEqual((h / '.bashrc').read_text(), want)
        self.assertEqual((h / '.zshrc').read_text(), 'setopt autocd\n')
        self.assertEqual((h / '.profile').read_text(), SKEL_PROFILE + ENV_LINE)
        backups = list(t.glob('backup/migrate-*/startup-files-*/.bashrc'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.bashrc)
        self.assertEqual(oct(backups[0].stat().st_mode & 0o777), '0o600')
        # 别的东西一样没动（修改时间、大小）
        after = snapshot(h)
        self.assertEqual({k: v for k, v in after.items() if k in keep_before and v != keep_before[k]}, {})
        # 新终端：第一个就是规定位置那份（登录的那种也是）
        for login in (False, True):
            self.assertEqual(self.first(login, 'uv'), f'{t}/uv/bin/uv')
            self.assertEqual(self.first(login, 'node'), f'{t}/nvm/versions/node/{NEW_V}/bin/node')
            self.assertEqual(self.first(login, 'pnpm'), f'{t}/nvm/versions/node/{NEW_V}/bin/pnpm')
        # 再清点：旧的这几样都不在了
        r = inv.inventory(self.probe(path_env=f'{h}/.local/bin'), tools=self.tools())
        self.assertEqual(r['tools'], [])
        rec = json.loads((record.migrate_dir() / 'uninstall.json').read_text())
        self.assertTrue(rec['tools']['ok'])
        self.assertTrue(rec['tools']['new_shell_ok'])

    def test_declined_touches_nothing(self):
        """直接回车（默认「否」）：一样都不动，备份目录都不建。"""
        self.new_tools()
        self.old_home()
        before = snapshot(self.h)
        rc, out = self.q6(self.choices(), answers=())
        self.assertEqual(rc, 0)
        self.assertIn('好，不卸', out)
        self.assertEqual(snapshot(self.h), before)
        self.assertFalse((self.tools_dir / 'backup').exists())

    def test_blockers(self):
        """装在旧 nvm 里的 Codex 别处没有、用户级服务指着旧 Node：nvm 不卸；pnpm 全局包、uv tool 没重装：那两样不卸；
        旧 uv 程序照卸（env 那一行留着）。挡住的那几样，终端启动文件里它们的行一行不动。"""
        self.new_tools()
        self.old_home()
        h = self.h
        mods = h / f'.nvm/versions/node/{NODE_V}/lib/node_modules'
        put(mods / '@openai/codex/package.json', '{"name": "@openai/codex", "bin": {"codex": "bin/codex.js"}}')
        put(mods / '@openai/codex/bin/codex.js', '#!/usr/bin/env node\n', 0o755)
        link('../lib/node_modules/@openai/codex/bin/codex.js', h / f'.nvm/versions/node/{NODE_V}/bin/codex')
        put(h / '.config/systemd/user/notes.service', f'[Service]\nExecStart=%h/.nvm/versions/node/{NODE_V}/bin/node x.js\n')
        shutil.rmtree(self.tools_dir / 'uv/tools')
        shutil.rmtree(self.tools_dir / 'pnpm/global')
        rc, out = self.q6(self.choices())
        self.assertEqual(rc, 1, out)
        self.assertIn('nvm ~/.nvm：这次不卸', out)
        self.assertIn('Codex', out)
        self.assertIn('notes.service', out)
        self.assertIn('pnpm ~/.local/share/pnpm：这次不卸', out)
        self.assertIn('pnpm add -g serve', out)
        self.assertIn('uv ~/.local/share/uv：这次不卸', out)
        self.assertIn('uv tool install ruff', out)
        for kept in ('.nvm', '.local/share/pnpm', '.local/share/uv', '.local/bin/ruff', '.local/bin/env'):
            self.assertTrue(os.path.lexists(h / kept), kept)
        for gone in ('.local/bin/uv', '.local/bin/uvx'):
            self.assertFalse(os.path.lexists(h / gone), gone)
        self.assertEqual((h / '.bashrc').read_text(), self.bashrc)      # 只有 nvm、pnpm 的行，都没动；env 那一行留着

    def test_codex_reinstalled_elsewhere(self):
        """Codex 在别处另有一份（官方装法放在 ~/.local/bin）：不挡。"""
        self.new_tools()
        self.old_home()
        mods = self.h / f'.nvm/versions/node/{NODE_V}/lib/node_modules'
        put(mods / '@openai/codex/package.json', '{"name": "@openai/codex", "bin": {"codex": "bin/codex.js"}}')
        put(self.tools_dir / f'nvm/versions/node/{NEW_V}/lib/node_modules/@openai/codex/package.json', '{}')
        put(self.h / '.local/bin/codex', ELF, 0o755)
        rc, out = self.q6(self.choices('~/.nvm'))
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.h / '.nvm').exists())

    def test_new_shell_wrong_restores(self):
        """~/.bashrc 里没有工具包那一段：删掉旧的那几行后新终端里找不到规定位置的 Node，启动文件原样放回去、目录一样不删。"""
        self.new_tools()
        self.old_home(sop_block=False)
        before = snapshot(self.h)
        rc, out = self.q6(self.choices('~/.nvm'))
        self.assertEqual(rc, 1, out)
        self.assertIn('终端启动文件已经放回原样', out)
        self.assertEqual((self.h / '.bashrc').read_text(), self.bashrc)
        self.assertEqual((self.h / '.zshrc').read_text(), f'export PATH=~/.nvm/versions/node/{NODE_V}/bin:$PATH\nsetopt autocd\n')
        self.assertEqual({k for k in snapshot(self.h)}, set(before))     # 一个文件都没少
        rec = json.loads((record.migrate_dir() / 'uninstall.json').read_text())
        self.assertFalse(rec['tools']['ok'])

    def test_pnpm_lines_not_official(self):
        """PNPM_HOME 不是 pnpm 官方装法那一段的写法（别的行还用着它）：只删那一行会把当前目录放进 PATH，pnpm 这次不卸；别的照卸。"""
        self.new_tools()
        self.old_home()
        h = self.h
        self.bashrc = self.bashrc.replace(PNPM_LINES.format(h=h), f'export PNPM_HOME="{h}/.local/share/pnpm"\nexport PATH="$PNPM_HOME:$PATH"\n')
        put(h / '.bashrc', self.bashrc)
        rc, out = self.q6(self.choices('~/.nvm', '~/.local/share/pnpm'))
        self.assertEqual(rc, 1, out)
        self.assertIn('还用着 PNPM_HOME', out)
        self.assertTrue((h / '.local/share/pnpm').exists())
        self.assertFalse((h / '.nvm').exists())
        self.assertIn('export PATH="$PNPM_HOME:$PATH"', (h / '.bashrc').read_text())
        self.assertNotIn('NVM_DIR', (h / '.bashrc').read_text().split(shellenv.BEGIN)[0])

    def test_syntax_would_break(self):
        """删掉那几行以后语法就坏了（if 那一行和里面那一行都指着旧 nvm，只剩 fi）：nvm 不卸，文件不动。"""
        self.new_tools()
        self.old_home()
        h = self.h
        self.bashrc = self.bashrc.replace(NVM_LINES, 'if [ -d ~/.nvm ]; then\n  export NVM_DIR="$HOME/.nvm"\nfi\n')
        put(h / '.bashrc', self.bashrc)
        rc, out = self.q6(self.choices('~/.nvm'))
        self.assertEqual(rc, 1, out)
        self.assertIn('语法不对了', out)
        self.assertTrue((h / '.nvm').exists())
        self.assertEqual((h / '.bashrc').read_text(), self.bashrc)

    def test_env_line_goes_when_alone(self):
        """~/.local/bin 里只有旧 uv 自己：env 那一行和 env、env.fish 一起删。"""
        self.new_tools()
        h = self.h
        put(h / '.local/bin/uv', ELF, 0o755)
        put(h / '.local/bin/uvx', ELF, 0o755)
        put(h / '.local/bin/env', UV_ENV)
        put(h / '.local/bin/env.fish', 'set x\n')
        put(h / '.bashrc', UBUNTU_BASHRC_HEAD + ENV_LINE + shellenv.block(self.tools_dir))
        put(h / '.profile', SKEL_PROFILE)
        rc, out = self.q6({'tools': [{'name': 'uv', 'path': '~/.local/bin/uv', 'choice': O.DROP}]},
                          host=O.Host(self.probe(path_env=f'{h}/.local/bin'), wrap=self.wrap, tools=self.tools(),
                                      check=lambda n: True))
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(h / '.local/bin'), [])
        self.assertNotIn('.local/bin/env', (h / '.bashrc').read_text())

    def test_new_not_installed_refuses(self):
        """规定位置的 Node 没装好：nvm 不卸（4.8：新的先装好，才谈旧的）。"""
        self.new_tools()
        self.old_home()
        rc, out = self.q6(self.choices('~/.nvm'), host=self.host(check=lambda n: n != 'node'))
        self.assertEqual(rc, 1)
        self.assertIn('规定位置的 node 没装好', out)
        self.assertTrue((self.h / '.nvm').exists())

    def test_home_guard(self):
        """自测的保险（3-59）：测试漏设 HOME（主目录是公用的假主目录）时一样都不删。"""
        self.new_tools()
        self.old_home()
        before = snapshot(self.h)
        with mock_env({'HOME': os.environ[safehome.MARK]}):
            with self.assertRaises(Exception) as e:
                self.q6(self.choices())
        self.assertIn('自测的保险', str(e.exception))
        self.assertEqual(snapshot(self.h), before)

    def test_unsafe_paths(self):
        """删之前核对路径：主目录、公用目录、~/tools 里的、主目录外面的都不删。"""
        p = self.probe()
        h = str(self.h)
        self.assertIsNone(O.unsafe(p, f'{h}/.nvm'))
        for bad in (h, f'{h}/.local', f'{h}/.local/bin', f'{h}/.config', '/usr/local/bin/node', str(self.tools_dir / 'nvm'),
                    os.path.dirname(h)):
            self.assertTrue(O.unsafe(p, bad), bad)


class TestFlow(OldToolsBase):
    def test_migrate_whole(self):
        """sop machine migrate 从头走（没有 Docker）：在旧 nvm 里面的 node 不单独问；gh 另一份只打印怎么卸；
        选卸旧 uv 程序、再确认 → 卸完。"""
        self.new_tools()
        self.old_home()
        put(self.h / '.local/bin/gh', ELF, 0o755)
        p = self.probe()
        i = inv.inventory(p, tools=self.tools())
        order = [(t['name'], c['path']) for t in i['tools'] for c in t['copies'] if not c.get('inside')]
        self.assertIn(('node', f'~/.nvm/versions/node/{NODE_V}/bin/node'),
                      [(t['name'], c['path']) for t in i['tools'] for c in t['copies'] if c.get('inside')])
        answers = ['2' if x in (('uv', '~/.local/bin/uv'), ('gh', '~/.local/bin/gh')) else '1' for x in order] + ['y']
        rc = flow.migrate(ask=flow.Ask(answers, say=self.said.append), say=self.said.append, inv=i, probe=p,
                          q2_fn=lambda inv_, say: True, sleep=lambda s: None, host=self.host())
        out = '\n'.join(self.said)
        self.assertEqual(rc, 0, out)
        self.assertIn('在 ~/.nvm 里面，跟着它一起留或卸', out)
        self.assertIn('rm "$HOME/.local/bin/gh"', out)
        self.assertIn('卸完了', out)
        self.assertFalse((self.h / '.local/bin/uv').exists())
        self.assertTrue((self.h / '.nvm').exists())
        self.assertTrue((self.h / '.local/bin/gh').exists())
        ch = json.loads((record.migrate_dir() / 'choices.json').read_text())
        self.assertEqual({t['choice'] for t in ch['tools'] if t['name'] == 'node'}, {'inside'})
