"""3-06：体检的工具位置（4.3「合格」、另有一份不在规定位置）、AI 工具的位置和版本（10.1）、`sop machine doctor` 的报告。
都在 /tmp 下的临时目录里造，不碰这台电脑上的工具；最后两项在临时 HOME 里真跑一次命令。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

from kernel import paths
from machine import catalog, config, disks, doctor, locate, space
from tests.helpers import REPO, TempHome, mock_env

TOML = '''
[[tool]]
name = "git"
what = "版本管理"
version = ">=2.0"
location = "系统软件包"
check = "true"
install = "apt:git"
admin = true
step = "M0"
command = "git"

[[tool]]
name = "nvm"
what = "装 Node"
version = ""
location = "~/tools/nvm"
check = "true"
install = "script:install/nvm.sh"
admin = false
step = "M2"
elsewhere = ["~/.nvm"]

[[tool]]
name = "node"
what = "Node"
version = ">=24"
location = "~/tools/nvm"
check = "true"
install = "script:install/node.sh"
admin = false
step = "M2"
command = "node"
elsewhere = ["/nonexistent-sop-test/node"]

[[tool]]
name = "uv"
what = "Python"
version = ">=0.13"
location = "~/tools/uv"
check = "true"
install = "script:install/uv.sh"
admin = false
step = "M0"
command = "uv"
elsewhere = ["~/.local/bin/uv", "~/.local/share/uv"]

[[tool]]
name = "wt"
what = "工作目录"
version = ">=1.3"
location = "~/tools/wt"
check = "true"
install = "script:install/wt.sh"
admin = false
step = "M5"
command = "wt"
elsewhere = ["~/.local/bin/wt"]
'''


def exe(p, text='#!/bin/sh\necho ok\n'):
    p = pathlib.Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    p.chmod(0o755)
    return p


class Machine(TempHome):
    """一台造出来的电脑：假主目录 u/、规定位置 u/tools/。"""

    def setUp(self):
        super().setUp()
        self.u = self.tmp / 'u'
        self.tools_dir = self.u / 'tools'
        self.tools_dir.mkdir(parents=True)
        self._env2 = mock_env({'SOP_TOOLS_DIR': str(self.tools_dir)})
        self._env2.__enter__()
        f = self.tmp / 'tools.toml'
        f.write_text(TOML)
        self.catalog = catalog.load(f)

    def tearDown(self):
        self._env2.__exit__(None, None, None)
        super().tearDown()


class TestCatalogFields(TempHome):
    def test_bad_fields(self):
        base = TOML.split('[[tool]]')[4]   # uv 那一项
        for bad, why in (('command = "u v"', 'command'), ('command = 3', 'command'),
                         ('elsewhere = ["relative/uv"]', 'elsewhere'), ('elsewhere = "~/.local/bin/uv"', 'elsewhere')):
            with self.subTest(bad):
                text = base.replace('command = "uv"\nelsewhere = ["~/.local/bin/uv", "~/.local/share/uv"]', bad)
                f = self.tmp / 'bad.toml'
                f.write_text('[[tool]]' + text)
                with self.assertRaises(catalog.CatalogError) as e:
                    catalog.load(f)
                self.assertIn(why, str(e.exception))
        git = TOML.split('[[tool]]')[1].replace('command = "git"', 'elsewhere = ["/usr/local/bin/git"]')
        f = self.tmp / 'apt.toml'
        f.write_text('[[tool]]' + git)
        with self.assertRaises(catalog.CatalogError):
            catalog.load(f)

    def test_real_catalog(self):
        tools = {t.name: t for t in catalog.load()}
        self.assertIn('/docker/bin/docker', tools['docker'].check)   # 免管理员 Docker 的程序在 bin/ 下（3-03 写错了）
        for name in ('uv', 'nvm', 'node', 'pnpm', 'gh', 'docker', 'wt'):
            self.assertTrue(tools[name].elsewhere, name)
        self.assertEqual(tools['bubblewrap'].command, 'bwrap')
        self.assertIn('/var/lib/docker', tools['docker'].elsewhere)
        self.assertIn('~/.nvm', tools['nvm'].elsewhere)


class TestOthers(Machine):
    def layout(self):
        """规定位置：wt 有、uv 有；另外：~/.local/bin/uv（文件）、~/.local/share/uv（目录）、~/.nvm（里面有 node）、
        ~/.local/bin/wt 指向规定位置那份、PATH 里有一个指向 ~/.local/bin/uv 的链接（同一份不重复列）。"""
        exe(self.tools_dir / 'wt' / 'wt')
        exe(self.tools_dir / 'uv' / 'bin' / 'uv')
        exe(self.u / '.local/bin/uv', '#!/bin/sh\n' + '#' * 9000 + '\n')
        (self.u / '.local/share/uv/python').mkdir(parents=True)
        (self.u / '.local/share/uv/python/big').write_bytes(b'x' * 200_000)
        os.link(self.u / '.local/share/uv/python/big', self.u / '.local/share/uv/python/big-again')   # 硬链接只算一次
        node = exe(self.u / '.nvm/versions/node/v26.1.0/bin/node')
        (self.u / '.nvm/nvm.sh').write_text('x' * 50_000)
        os.symlink(self.tools_dir / 'wt' / 'wt', self.u / '.local/bin/wt')
        alt = self.tmp / 'alt-bin'
        alt.mkdir()
        os.symlink(self.u / '.local/bin/uv', alt / 'uv')
        os.symlink('/nonexistent-sop-test/x', alt / 'node')   # 坏链接：不算
        path_env = os.pathsep.join([str(alt), str(node.parent), str(self.u / '.local/bin'), '/usr/bin', '/bin'])
        return path_env

    def test_others_found_sized_and_not_doubled(self):
        path_env = self.layout()
        sysdisk = lambda p: str(p).startswith('/usr')   # 造的：只有 /usr 下的算系统盘
        runs = []
        fake_check = lambda t: runs.append(t.name) or catalog.CheckResult(t.name != 'nvm', (26, 1, 0), t.name != 'nvm', '')
        st = {s.tool.name: s for s in locate.check_tools(self.catalog, path_env=path_env, home=str(self.u),
                                                         run_check=fake_check, sysdisk=sysdisk)}
        self.assertEqual(runs, ['git', 'nvm', 'node', 'uv', 'wt'])
        self.assertEqual(st['git'].path, '/usr/bin/git')   # 系统软件包：命令实际在哪
        self.assertEqual(st['git'].others, [])
        self.assertEqual(st['nvm'].state, 'missing')
        self.assertEqual(st['wt'].others, [])              # ~/.local/bin/wt 指向规定位置那一份，不算另一份
        nvm = st['nvm'].others
        self.assertEqual([o.path for o in nvm], [str(self.u / '.nvm')])
        self.assertGreaterEqual(nvm[0].size, 50_000)
        self.assertFalse(nvm[0].on_system_disk)
        node = st['node'].others
        self.assertEqual(len(node), 1)
        self.assertEqual(node[0].inside, str(self.u / '.nvm'))   # 在 ~/.nvm 里面，大小不重复算
        self.assertIsNone(node[0].size)
        uv = st['uv'].others
        self.assertEqual([o.real for o in uv], [str(self.u / '.local/bin/uv'), str(self.u / '.local/share/uv')])
        self.assertEqual(uv[0].path, str(self.tmp / 'alt-bin' / 'uv'))   # PATH 里先找到的那个链接，解开后是同一份
        self.assertGreaterEqual(uv[1].size, 200_000)
        self.assertLess(uv[1].size, 400_000)                    # 硬链接只算一次
        rec = st['uv'].as_record()
        self.assertTrue(rec['in_place'])
        self.assertEqual(rec['others'][1]['path'], str(self.u / '.local/share/uv'))
        json.dumps(rec)

    def test_disk_usage_partial_and_symlink(self):
        d = self.tmp / 'd'
        (d / 'locked').mkdir(parents=True)
        (d / 'locked' / 'f').write_bytes(b'x' * 10_000)
        (d / 'a').write_bytes(b'y' * 30_000)
        os.symlink('/usr', d / 'link-to-usr')   # 链接不跟着走
        full, partial = locate.disk_usage(str(d))
        self.assertFalse(partial)
        self.assertLess(full, 1_000_000)
        os.chmod(d / 'locked', 0)
        try:
            if os.geteuid() != 0:
                part, partial = locate.disk_usage(str(d))
                self.assertTrue(partial)
                self.assertLess(part, full)
        finally:
            os.chmod(d / 'locked', 0o755)
        self.assertEqual(locate.disk_usage(str(self.tmp / 'nope')), (None, True))

    def test_system_disk_cached_per_device(self):
        calls = []
        sd = locate.SystemDisk(same=lambda p: calls.append(p) or True)
        self.assertTrue(sd(str(self.tmp)))
        self.assertTrue(sd(str(self.u)))
        self.assertEqual(len(calls), 1)
        self.assertIsNone(sd('/nonexistent-sop-test'))


class TestAiTools(Machine):
    def test_found_versioned_and_kept_away_from_home(self):
        bindir = self.tmp / 'bin'
        script = ('#!/bin/sh\necho "%s"\necho "home=$HOME tok=${ANTHROPIC_AUTH_TOKEN:-none} key=${OPENAI_API_KEY:-none}"\n'
                  'touch "$HOME/in-home" && echo wrote-home\ntouch "%s/written" 2>/dev/null && echo wrote-outside\nexit 0\n')
        exe(bindir / 'claude', script % ('2.1.328 (Claude Code)', self.u))
        real_codex = exe(self.u / '.codex/packages/0.169.0/codex', '#!/bin/sh\necho "codex-cli 0.169.0"\n')
        (self.u / '.local/bin').mkdir(parents=True)
        os.symlink(real_codex, self.u / '.local/bin/codex')       # 不在 PATH 里，按默认位置找到
        exe(self.u / '.opencode/bin/opencode', '#!/bin/sh\nexit 3\n')
        with mock_env({'ANTHROPIC_AUTH_TOKEN': 'fake-secret', 'OPENAI_API_KEY': 'fake-secret'}):
            ai = {a.name: a for a in locate.find_ai_tools(path_env=f'{bindir}:/usr/bin:/bin', home=str(self.u))}
        self.assertEqual(ai['claude'].version, '2.1.328')
        self.assertEqual(ai['codex'].version, '0.169.0')
        self.assertEqual(ai['codex'].real, str(real_codex))
        self.assertTrue(ai['opencode'].found)
        self.assertIsNone(ai['opencode'].version)               # 跑不成：照实写看不出版本
        self.assertFalse(ai['pi'].found)
        seen = ai['claude'].output
        self.assertIn('tok=none key=none', seen)                # 密钥不带进去
        self.assertIn('wrote-home', seen)                       # 临时 HOME 能写
        tmp_home = seen.split('home=')[1].split()[0]
        self.assertTrue(pathlib.Path(tmp_home).name.startswith('sop-doctor-'))
        self.assertFalse(os.path.exists(tmp_home))              # 临时 HOME 用完删了
        if shutil.which('bwrap'):
            self.assertNotIn('wrote-outside', seen)             # 套了只读的一层：别处一个字都写不进
            self.assertFalse((self.u / 'written').exists())
        rec = ai['codex'].as_record()
        self.assertEqual((rec['kind'], rec['version'], rec['installed']), ('ai', '0.169.0', True))

    def test_without_working_bwrap(self):
        """bubblewrap 起不来（或者还没装）：不套，照样在临时 HOME 里查出版本。"""
        e = exe(self.tmp / 'tool', '#!/bin/sh\necho "tool 3.4.5"\n')
        broken = exe(self.tmp / 'bwrap', '#!/bin/sh\necho "bwrap: setting up uid map: Permission denied" >&2\nexit 1\n')
        self.assertEqual(locate.tool_version(str(e), bwrap=str(broken))[0], '3.4.5')
        self.assertEqual(locate.tool_version(str(e), bwrap='')[0], '3.4.5')

    def test_hanging_tool_times_out(self):
        e = exe(self.tmp / 'slow', '#!/bin/sh\nsleep 30 &\nsleep 30\n')
        v, out = locate.tool_version(str(e), timeout=0.5)
        self.assertIsNone(v)
        self.assertIn('没结束', out)


def fake_data(**over):
    t = {x.name: x for x in catalog.load()}
    ok = lambda v: catalog.CheckResult(True, v, True, '')
    tools = [
        locate.ToolStatus(t['git'], ok((2, 53, 0)), '/usr/bin/git', []),
        locate.ToolStatus(t['uv'], catalog.CheckResult(False, None, False, ''), '/home/u/tools/uv',
                          [locate.Copy('/home/u/.local/bin/uv', '/home/u/.local/bin/uv', 37_500_000, False, False)]),
        locate.ToolStatus(t['nvm'], ok((0, 40, 3)), '/home/u/tools/nvm',
                          [locate.Copy('/home/u/.nvm', '/home/u/.nvm', 1_200_000_000, False, False)]),
        locate.ToolStatus(t['node'], catalog.CheckResult(True, (22, 1, 0), False, ''), '/home/u/tools/nvm',
                          [locate.Copy('/home/u/.nvm/versions/node/v26/bin/node', '/home/u/.nvm/versions/node/v26/bin/node',
                                       None, False, False, inside='/home/u/.nvm')]),
        locate.ToolStatus(t['docker'], ok((29, 1, 0)), '/home/u/tools/docker',
                          [locate.Copy('/var/lib/docker', '/var/lib/docker', 4096, True, True)]),
    ]
    ai = [locate.AiTool('claude', 'Claude Code', '/home/u/.local/bin/claude', '/home/u/.local/share/claude/versions/2.1.328', '2.1.328'),
          locate.AiTool('codex', 'Codex')]
    parts = {'kernel': '7.0.0-43-generic #43', 'bubblewrap': '0.11.1', 'userns_rule': 'missing',
             'userns_policy': 'restrict=1 bwrap-userns-restrict=abc', 'tiocsti': '0'}
    d = {'time': '2026-11-19 15:00',
         'layout': disks.Layout('separate', ['/dev/sda2'], ['/dev/sda3']),
         'space': [space.Space('system', '/', space.SYSTEM_MIN, 50 * space.GB, 100 * space.GB),
                   space.Space('home', '/home/u', space.HOME_MIN, 300 * space.GB, 500 * space.GB)],
         'tools': tools, 'ai': ai, 'components': parts, 'changes': [],
         'registered_ai': {'claude': {'kind': 'ai', 'drilled_version': '2.1.300'}}}
    d.update(over)
    return d


class TestReport(TempHome):
    def test_plain_report(self):
        text, bad, notes = doctor.report(fake_data(), home='/home/u')
        self.assertEqual(bad, ['uv', 'node'])
        self.assertEqual(notes, [])
        for must in ('有 2 样基础工具还没装好：uv、node',
                     'git：合格，2.53.0（系统软件包，/usr/bin/git）',
                     'uv：还没装（规定位置 ~/tools/uv），在「第零步」那一步装',
                     '另有一份不在规定位置：~/.local/bin/uv（37.5 MB，不占系统盘）',
                     'nvm：合格，0.40.3（~/tools/nvm）',
                     'node：版本不够。~/tools/nvm 上是 22.1.0，要 24 或更新',
                     '~/.nvm/versions/node/v26/bin/node（在 ~/.nvm 里面，大小算在那边）',
                     '/var/lib/docker（至少 4.1 KB，有的地方要管理员权限才看得到，占系统盘）',
                     'sop machine migrate',
                     'Claude Code：2.1.328，在 ~/.local/bin/claude，实际在 ~/.local/share/claude/versions/2.1.328',
                     '上次做真实 AI 演练的是 2.1.300，现在是 2.1.328',
                     'Codex：没找到',
                     '合格：主目录不在系统盘上',
                     '系统盘（/）还剩 50.0 GB',
                     '往终端塞按键：已禁用',
                     '工具的位置和版本已记进'):
            self.assertIn(must, text)
        self.assertIn('4 样另有一份不在规定位置（uv、nvm、node、docker），不算不合格', text)
        text, _, _ = doctor.report(fake_data(), home='/home/u', readonly=True)
        self.assertIn('这次只看不记', text)
        self.assertNotIn('已记进', text)

    def test_notes(self):
        d = fake_data(layout=disks.Layout('unknown', why='x'),
                      space=[space.Space('both', '/home/u', space.HOME_MIN, 15 * space.GB, 100 * space.GB)],
                      ai=[locate.AiTool('claude', 'Claude Code')],
                      components={**fake_data()['components'], 'tiocsti': '1'})
        d['tools'] = [s for s in d['tools'] if s.state == 'ok']
        text, bad, notes = doctor.report(d, home='/home/u')
        self.assertEqual(bad, [])
        self.assertIn('基础工具全部合格', text)
        self.assertEqual(len(notes), 4)
        for n in notes:
            self.assertIn(f'要注意：{n}', text)


class TestRecord(Machine):
    def test_record_keeps_drill_version_and_leaves_system_alone(self):
        config.record_tool('claude', path='/old', version='2.1.300', kind='ai', drilled_version='2.1.300')
        config.record_tool('jdk', path='/x', version='25')        # 清单外的不动
        doctor.record(fake_data())
        t = config.tools()
        self.assertEqual(t['claude']['version'], '2.1.328')
        self.assertEqual(t['claude']['drilled_version'], '2.1.300')
        self.assertEqual(t['claude']['real'], '/home/u/.local/share/claude/versions/2.1.328')
        self.assertFalse(t['codex']['installed'])
        self.assertEqual(t['uv']['state'], 'missing')
        self.assertFalse(t['uv']['in_place'])
        self.assertEqual(t['uv']['others'][0]['size_bytes'], 37_500_000)
        self.assertEqual(t['node']['others'][0]['inside'], '/home/u/.nvm')
        self.assertIn('jdk', t)
        self.assertFalse((paths.config_dir() / 'system.json').exists())   # 系统组件只在隔离自检通过后记


class TestCommand(Machine):
    """在临时 HOME、只有系统目录的 PATH 里真跑 sop machine doctor：基础工具多半没装，AI 工具一个都找不到。"""

    def sop(self, *args):
        cwd = self.tmp / 'not-a-project'
        cwd.mkdir(exist_ok=True)
        env = {**os.environ, 'PYTHONPATH': '', 'HOME': str(self.u), 'PATH': '/usr/bin:/bin'}
        return subprocess.run([sys.executable, str(REPO / 'kernel' / 'main.py'), 'machine', *args], cwd=cwd,
                              capture_output=True, text=True, env=env, timeout=300)

    def test_readonly_writes_nothing(self):
        p = self.sop('doctor', '--readonly')
        self.assertIn(p.returncode, (0, 1), p.stdout + p.stderr)
        self.assertEqual(p.returncode, 1)   # 临时的工具目录是空的：uv、nvm 这些都没装
        for must in ('体检报告', '一、结论', '二、主目录在哪个分区', '三、剩余空间', '四、基础工具', '五、AI 工具',
                     '六、系统组件', 'uv：还没装（规定位置 ~/tools/uv）', 'Claude Code：没找到', '这次只看不记'):
            self.assertIn(must, p.stdout)
        self.assertFalse(paths.config_dir().exists())
        self.assertEqual(os.listdir(self.u), ['tools'])

    def test_records_tools_only(self):
        p = self.sop('doctor')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        t = json.loads((paths.config_dir() / 'tools.json').read_text())['tools']
        self.assertEqual(t['uv']['state'], 'missing')
        self.assertEqual(t['claude']['kind'], 'ai')
        self.assertFalse((paths.config_dir() / 'system.json').exists())
        self.assertIn('已记进', p.stdout)
        p = self.sop('doctor', '--nonsense')
        self.assertEqual(p.returncode, 2)
