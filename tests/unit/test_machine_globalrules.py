"""3-11 M7：各 AI 工具的全局规则文件里那一段受管段落（设计书 4.5、4.8）。
全在 /tmp 的临时 HOME 里测，HOME 和几个改位置的环境变量都指过去，不碰这台电脑真的 ~/.claude、~/.codex、~/.config/opencode、~/.pi。"""
import os
import pathlib
import stat

from machine import globalrules as G
from machine.shellenv import ShellEnvError
from tests.helpers import TempHome, mock_env

USER_RULES = '# 我自己的规矩\n\n- 回答用中文。\n- 不要动 ~/Project 下别的项目。\n'


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.h = self.tmp / 'home'
        self.h.mkdir()
        self._e = mock_env({'HOME': str(self.h), 'CLAUDE_CONFIG_DIR': '', 'CODEX_HOME': '', 'XDG_CONFIG_HOME': '',
                            'PI_CODING_AGENT_DIR': ''})
        self._e.__enter__()
        self.assertEqual(pathlib.Path.home(), self.h)

    def tearDown(self):
        self._e.__exit__(None, None, None)
        super().tearDown()

    def install(self):
        out = []
        ok, _ = G.install(out=out.append)
        return ok, '\n'.join(out)

    def p(self, rel):
        return self.h / rel


class TestContent(Base):
    def test_block_only_machine_rules_and_migration_exception(self):
        """只含包管理、Docker 的机器级规则，写明环境迁移是例外；不含流程的规则（那些在项目的 AGENTS.md 里）。"""
        b = G.block()
        self.assertTrue(b.startswith(G.BEGIN + '\n') and b.endswith(G.END + '\n'))
        for must in ('uv', 'nvm', 'pnpm', 'pnpm dlx', '~/tools/docker', 'sudo', '数据卷', '环境迁移', 'sop machine migrate', '例外'):
            self.assertIn(must, b)
        for flow_rule in ('【业务】', 'AGENTS*.md', '推送', '开 PR', '测试'):
            self.assertNotIn(flow_rule, b)
        self.assertEqual(b.count(G.BEGIN), 1)


class TestInstall(Base):
    def test_fresh_home(self):
        """什么都没有：Claude Code、Codex、Pi 的新建；OpenCode 不新建，靠 ~/.claude/CLAUDE.md（官方的退路）。出口检查合格。"""
        ok, out = self.install()
        self.assertTrue(ok)
        for rel in ('.claude/CLAUDE.md', '.codex/AGENTS.md', '.pi/agent/AGENTS.md'):
            self.assertEqual(self.p(rel).read_text(), G.block())
        self.assertFalse(self.p('.config/opencode/AGENTS.md').exists())
        self.assertFalse(self.p('.config').exists())
        self.assertIn('不新建', out)
        for d in ('.claude', '.codex', '.pi', '.pi/agent'):
            self.assertEqual(stat.S_IMODE(self.p(d).stat().st_mode), 0o700)
        ok, rows = G.check()
        self.assertTrue(ok)
        self.assertEqual([(t, str(p)) for t, p, _ in rows],
                         [('Claude Code', str(self.p('.claude/CLAUDE.md'))), ('Codex', str(self.p('.codex/AGENTS.md'))),
                          ('OpenCode', str(self.p('.claude/CLAUDE.md'))), ('Pi', str(self.p('.pi/agent/AGENTS.md')))])

    def test_outside_untouched_and_idempotent(self):
        """用户原来的规则一个字不动，这一段加在末尾；再装一次内容不变、修改时间也不动；权限照旧。"""
        f = self.p('.claude/CLAUDE.md')
        f.parent.mkdir()
        f.write_text(USER_RULES)
        os.chmod(f, 0o600)
        self.p('.config/opencode').mkdir(parents=True)
        oc = self.p('.config/opencode/AGENTS.md')
        oc.write_text('opencode 的规矩，最后一行没换行')
        self.assertTrue(self.install()[0])
        self.assertEqual(f.read_text(), USER_RULES + '\n' + G.block())
        self.assertEqual(oc.read_text(), 'opencode 的规矩，最后一行没换行\n\n' + G.block())   # 已经有它自己的：写进去
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        files = [f, oc, self.p('.codex/AGENTS.md'), self.p('.pi/agent/AGENTS.md')]
        before = {x: x.read_bytes() for x in files}
        for x in files:
            os.utime(x, (1_000_000_000, 1_000_000_000))
        ok, out = self.install()
        self.assertTrue(ok)
        self.assertEqual(out.count('本来就是最新的，没改'), 4)
        for x in files:
            self.assertEqual(x.read_bytes(), before[x])
            self.assertEqual(x.stat().st_mtime, 1_000_000_000)
        self.assertEqual(list(self.h.rglob('*.sop-tmp')), [])

    def test_replace_in_place(self):
        """这一段被手改过（或工具包升级了）：只换这一段，前后用户写的都不动；出口检查先报不合格，装完合格。"""
        f = self.p('.codex/AGENTS.md')
        f.parent.mkdir()
        old = G.block().replace('不要删数据卷', '可以删数据卷')
        f.write_text(USER_RULES + old + '\n## 用户后来加的\n- 一条\n')
        self.install()
        self.assertEqual(f.read_text(), USER_RULES + G.block() + '\n## 用户后来加的\n- 一条\n')
        f.write_text(USER_RULES + old)
        ok, rows = G.check()
        self.assertFalse(ok)
        self.assertIn(('Codex', f, 'stale'), rows)

    def test_broken_marks_not_touched_others_still_written(self):
        """标记对不上（只剩一头、有两段、结尾在前）：这个文件一个字不改、明说；别的工具照样写。"""
        f = self.p('.claude/CLAUDE.md')
        f.parent.mkdir()
        for bad in (USER_RULES + G.BEGIN + '\n- x\n', USER_RULES + G.END + '\n', USER_RULES + G.block() + G.block(),
                    USER_RULES + G.END + '\n' + G.BEGIN + '\n'):
            with self.subTest(bad=bad[-30:]):
                f.write_text(bad)
                ok, out = self.install()
                self.assertFalse(ok)
                self.assertEqual(f.read_text(), bad)
                self.assertIn('标记对不上', out)
                self.assertEqual(self.p('.pi/agent/AGENTS.md').read_text(), G.block())
                self.assertEqual(G.state_of(f), 'broken')
        f.write_bytes(b'\xff\xfe not utf8')
        ok, out = self.install()
        self.assertFalse(ok)
        self.assertEqual(f.read_bytes(), b'\xff\xfe not utf8')
        self.assertEqual(G.state_of(f), 'unreadable')
        with self.assertRaises(ShellEnvError):
            G.install_one(f)

    def test_symlink_written_through(self):
        """规则文件是链接（点文件仓库）：写到它指的文件，链接还是链接。"""
        real = self.tmp / 'dotfiles' / 'CLAUDE.md'
        real.parent.mkdir()
        real.write_text(USER_RULES)
        self.p('.claude').mkdir()
        self.p('.claude/CLAUDE.md').symlink_to(real)
        self.install()
        self.assertTrue(self.p('.claude/CLAUDE.md').is_symlink())
        self.assertEqual(real.read_text(), USER_RULES + '\n' + G.block())

    def test_env_overrides(self):
        """CLAUDE_CONFIG_DIR、CODEX_HOME、XDG_CONFIG_HOME、PI_CODING_AGENT_DIR 设了就写到那里。
        Claude Code 的挪走了时，OpenCode 的退路 ~/.claude/CLAUDE.md 里没有这一段，所以给 OpenCode 新建它自己的。"""
        env = {'CLAUDE_CONFIG_DIR': str(self.tmp / 'cc'), 'CODEX_HOME': str(self.tmp / 'cx'),
               'XDG_CONFIG_HOME': str(self.tmp / 'xdg'), 'PI_CODING_AGENT_DIR': str(self.tmp / 'pi')}
        with mock_env(env):
            self.assertTrue(self.install()[0])
            self.assertTrue(G.check()[0])
        for p in ('cc/CLAUDE.md', 'cx/AGENTS.md', 'xdg/opencode/AGENTS.md', 'pi/AGENTS.md'):
            self.assertEqual((self.tmp / p).read_text(), G.block())
        self.assertEqual(sorted(os.listdir(self.h)), [])

    def test_codex_override(self):
        """Codex 目录里有不是空的 AGENTS.override.md：Codex 只读它，所以它里面也写；空的那种不算、不碰。"""
        d = self.p('.codex')
        d.mkdir()
        (d / 'AGENTS.override.md').write_text('   \n')
        self.install()
        self.assertEqual((d / 'AGENTS.override.md').read_text(), '   \n')
        (d / 'AGENTS.override.md').write_text('临时的规矩\n')
        ok, out = self.install()
        self.assertTrue(ok)
        self.assertEqual((d / 'AGENTS.override.md').read_text(), '临时的规矩\n\n' + G.block())
        self.assertIn('AGENTS.override.md', out)
        ok, rows = G.check()
        self.assertTrue(ok)
        self.assertIn(d / 'AGENTS.override.md', [p for _, p, _ in rows])

    def test_check_missing(self):
        ok, rows = G.check()
        self.assertFalse(ok)
        self.assertEqual({s for _, _, s in rows}, {'missing'})
        self.assertFalse(self.p('.claude').exists())          # 出口检查只读，不建任何东西

    def test_main(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(G.main(['--check']), 1)
            self.assertEqual(G.main([]), 0)
            self.assertEqual(G.main(['--check']), 0)
            self.assertEqual(G.main(['--bad']), 2)
        out = buf.getvalue()
        self.assertIn('全局规则装好了，出口检查合格', out)
        self.assertIn('不合格 Claude Code：~/.claude/CLAUDE.md（没有工具包那一段）', out)
