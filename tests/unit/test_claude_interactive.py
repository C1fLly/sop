"""3-28：Claude Code 适配器的对话方式（start_interactive）、续接（resume）、自检里的「打开对话窗口不出首次启动的那几屏」。
全用假的 claude（tests/fakes/claude/claude），在真的受限环境（bubblewrap）和模拟终端里跑，不花钱、不连网。
真实调用在 tests/real_ai/claude_interactive.py，手动跑。"""
import glob
import json
import os
import unittest

from adapters.ai import ptyscreen
from adapters.ai.claude import adapter as C
from checks.quota_scan.check import run as quota_scan
from runner import sandbox
from tests.unit.test_claude_adapter import Base

WT = 'ticket-a-1-01'


@unittest.skipUnless(sandbox.tiocsti_disabled(), '内核没禁用往终端塞按键，对话步骤不启动')
class TestInteractive(Base):
    def ictx(self, d):
        c = self.ctx(d, WT)
        c.interactive = True
        return c

    def chat(self, fn, lines=(), wait_answer=None):
        """在模拟终端里调 fn（适配器的对话方式），等输入框出来，一句一句打字，最后 /exit。返回 (Outcome 的字典, 屏幕文字)。"""
        with ptyscreen.Pty(fn) as t:
            self.assertTrue(t.wait_for(ptyscreen.is_ready, 30), t.text[-800:])
            for line in lines:
                mark = len(t.raw)
                t.type_line(line)
                t.wait_for(lambda s, m=mark: ptyscreen.is_ready(t.text_since(m)), 15)
            if wait_answer:
                self.assertTrue(t.wait_for(wait_answer, 15), t.text[-800:])
            t.type_line('/exit')
            t.close(wait=15)
        self.assertIsNotNone(t.result, t.text[-800:])
        self.assertNotIn('error', t.result, t.result)
        return t.result['value'], t.text

    def test_start_no_first_run_screens_then_resume_remembers(self):
        self.creds('ok')
        a = self.adapter()
        W = self.R / WT
        st = self.state(a, W)
        d = self.taskpack(body='请记住暗号「青石七三」，只回答：记好了')
        out, screen = self.chat(lambda: a.start_interactive(self.ictx(d), d / 'task', st))
        self.assertEqual(ptyscreen.first_run_screens(screen), [])
        self.assertEqual(out['rc'], 0)
        self.assertEqual(out['text'], '记好了')
        self.assertAlmostEqual(out['cost'], 0.0123)
        self.assertEqual(out['cost_basis'], '会话日志里工具记的数')
        sid = out['session']
        self.assertTrue(sid)
        rec = self.seen(st)[0]
        self.assertIn('青石七三', rec['prompt'])                       # 任务包是开场内容
        self.assertIn('--dangerously-skip-permissions', rec['argv'])
        for f in C.FORBIDDEN_FLAGS + ('-p',):
            self.assertNotIn(f, rec['argv'])
        self.assertEqual(rec['token'], 'fake-token-3-27-abcdefgh')
        self.assertIn('TERM', rec['env_names'])
        self.assertNotIn('CLAUDECODE', rec['env_names'])
        book = C._cost_book(st)
        self.assertEqual(book.parent, st.parent)                        # 累计数记在状态目录旁边，受限环境里看不到
        self.assertAlmostEqual(json.loads(book.read_text())[sid], 0.0123)
        # 续接：对话窗口接着聊，记得前文；只记增量
        d2 = self.taskpack(body='这一步：回答问题')
        out2, screen2 = self.chat(lambda: a.resume(self.ictx(d2), d2 / 'task', st, sid, '我刚才让你记住的暗号是什么？'))
        self.assertEqual(out2['rc'], 0)
        self.assertEqual(out2['session'], sid)
        self.assertEqual(out2['text'], '青石七三')
        self.assertIn('青石七三', screen2)
        self.assertEqual(ptyscreen.first_run_screens(screen2), [])
        self.assertAlmostEqual(out2['cost'], 0.0123)                    # 工具记的累计是 0.0246
        last = self.seen(st)[-2]                                        # 最后一行是 cost-state
        self.assertEqual(last['resumed'], sid)
        self.assertIn('--resume', last['argv'])
        self.assertIn('这一步：回答问题', last['prompt'])               # 这一步的任务包跟着补充说明一起送进去

    def test_cost_falls_back_to_claude_json(self):
        """会话日志里没有 cost-state 时，取 .claude.json 里记着这个会话的 lastCost（W28 在 2.1.327 上看到的那种）。"""
        self.creds('ok')
        a = self.adapter()
        W = self.R / WT
        st = self.state(a, W)
        d = self.taskpack(body='你好')
        out, _ = self.chat(lambda: a.start_interactive(self.ictx(d), d / 'task', st))
        for f in st.rglob('*.jsonl'):
            f.write_text(''.join(x + '\n' for x in f.read_text().splitlines() if '"cost-state"' not in x))
        self.assertEqual(C._session_total(st, out['session'], str(W)), (0.0123, '状态目录里工具记的数'))
        cfg = json.loads((st / '.claude.json').read_text())
        cfg['projects'] = {'/别的键': cfg['projects'][str(W)]}           # 不记在工作目录名下也找得到
        (st / '.claude.json').write_text(json.dumps(cfg))
        self.assertEqual(C._session_total(st, out['session'], str(W))[0], 0.0123)
        self.assertEqual(C._session_total(st, 'other', str(W)), (None, '没读到工具的报告'))

    def test_more_lines_in_window(self):
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.taskpack(body='开场')
        out, screen = self.chat(lambda: a.start_interactive(self.ictx(d), d / 'task', st),
                                lines=['请记住暗号「白鹭九一」', '我刚才让你记住的暗号是什么？'],
                                wait_answer='白鹭九一')
        self.assertEqual(out['text'], '白鹭九一')
        self.assertAlmostEqual(out['cost'], 3 * 0.0123)

    def test_not_in_terminal_no_call(self):
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.taskpack()
        out = a.start_interactive(self.ctx(d, WT), d / 'task', st)        # 不是对话方式的放法
        self.assertEqual(out.rc, 1)
        self.assertIn('终端', out.text)
        self.assertEqual(self.seen(st), [])

    def test_quota_in_window_found_in_logs(self):
        self.creds('quota')
        a = self.adapter()
        st = self.state(a, self.R / WT)
        d = self.taskpack(body='你好')
        out, _ = self.chat(lambda: a.start_interactive(self.ictx(d), d / 'task', st))
        ok, _, rep = quota_scan(out['logs'])
        self.assertFalse(ok)
        self.assertEqual(out['cost'], 0.0)

    def test_incomplete_template_shows_screens(self):
        """模板少了设置时，首次启动的几屏真的会出，模拟终端认得出来（反着试：证明上面的「没出」不是看漏了）。"""
        self.creds('ok')
        for drop, want in (('bypassPermissionsModeAccepted', '「不逐条询问」模式的警告'),
                           ('hasCompletedOnboarding', '选界面配色'), ('projects', '是否信任这个文件夹')):
            a = Dropping(drop, exe=self.exe)
            st = self.state(a, self.R / WT)
            d = self.taskpack(body='你好')
            with ptyscreen.Pty(lambda: a.start_interactive(self.ictx(d), d / 'task', st)) as t:
                t.wait_for(lambda s: ptyscreen.first_run_screens(s), 20)
                self.assertIn(want, ptyscreen.first_run_screens(t.text), t.text)
                self.assertFalse(ptyscreen.is_ready(t.text))
                for _ in range(2):
                    t.send('\r')
                    t.pump(0.5)
                t.type_line('/exit')
                t.close(wait=5)

    def test_check_screens_and_probe(self):
        self.creds('ok')
        ok, line, det = self.adapter().check_screens(wait=20)
        self.assertIs(ok, True, line)
        self.assertEqual(det['screens'], [])
        r = self.adapter().probe(timeout=30)
        self.assertTrue(r.ok, r.message)
        self.assertTrue(r.details['screens']['ok'])
        self.assertIn('没出首次启动的那几屏', r.message)
        bad = Dropping('bypassPermissionsModeAccepted', exe=self.exe)
        ok, line, det = bad.check_screens(wait=20)
        self.assertIs(ok, False)
        self.assertIn('「不逐条询问」模式的警告', line)
        r = bad.probe(timeout=30)
        self.assertFalse(r.ok)
        self.assertIn('首次启动', r.message)
        self.assertFalse(r.quota)
        self.assertEqual(glob.glob('/tmp/sop-screens-*'), [])


class TestResumeHeadless(Base):
    def test_resume_headless_remembers_and_counts_increment(self):
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / 'ticket-a-1-01')
        d = self.taskpack(body='请记住暗号「青石七三」')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        self.assertEqual(out.rc, 0, out.text)
        self.assertAlmostEqual(out.cost, 0.0123)
        d2 = self.taskpack(body='接着这一步')
        out2 = a.resume(self.ctx(d2), d2 / 'task', st, out.session, '我刚才让你记住的暗号是什么？')
        self.assertEqual(out2.rc, 0, out2.text)
        self.assertEqual(out2.session, out.session)
        self.assertEqual(out2.text, '青石七三')
        self.assertAlmostEqual(out2.cost, 0.0123)                       # 工具报的是累计 0.0246
        self.assertIn('累计数减去', out2.cost_basis)
        rec = self.seen(st)[-1]
        self.assertIn('-p', rec['argv'])
        self.assertEqual(rec['argv'][rec['argv'].index('--resume') + 1], out.session)
        for f in C.FORBIDDEN_FLAGS:
            self.assertNotIn(f, rec['argv'])
        out3 = a.resume(self.ctx(d2), d2 / 'task', st, out.session, '再说一遍暗号是什么？')
        self.assertAlmostEqual(out3.cost, 0.0123)

    def test_resume_without_earlier_total_counts_whole(self):
        """续接前的累计数没记下（例如会话不是经适配器开的）：按工具报的累计数记，宁多不少，并注明。"""
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / 'ticket-a-1-01')
        d = self.taskpack(body='请记住暗号「青石七三」')
        out = a.run_headless(self.ctx(d), d / 'task', st)
        C._cost_book(st).unlink()
        out2 = a.resume(self.ctx(d), d / 'task', st, out.session, '我刚才让你记住的暗号是什么？')
        self.assertAlmostEqual(out2.cost, 0.0246)
        self.assertIn('按累计数记', out2.cost_basis)

    def test_resume_failure_is_not_counted(self):
        self.creds('ok')
        a = self.adapter()
        st = self.state(a, self.R / 'ticket-a-1-01')
        d = self.taskpack()
        out = a.resume(self.ctx(d), d / 'task', st, 'no-such-session', '接着做')
        self.assertNotEqual(out.rc, 0)
        self.assertEqual(out.cost, 0.0)


class TestScreenText(unittest.TestCase):
    def test_first_run_markers_survive_cursor_moves(self):
        raw = b'\x1b[2J\x1b[1;1HWARNING:\x1b[1CClaude\x1b[1CCode\x1b[1Crunning\x1b[1Cin\x1b[1CBypass\x1b[1CPermissions\x1b[1Cmode\r\n'
        self.assertEqual(ptyscreen.first_run_screens(ptyscreen.screen_text(raw)), ['「不逐条询问」模式的警告'])
        ready = b'\x1b[33m\xe2\x8f\xb5\xe2\x8f\xb5\x1b[0m\x1b[1Cbypass\x1b[3;5Hpermissions\x1b[1Con'
        self.assertTrue(ptyscreen.is_ready(ptyscreen.screen_text(ready)))
        self.assertFalse(ptyscreen.is_ready('In Bypass Permissions mode, Claude Code will not ask'))


class Dropping(C.ClaudeAdapter):
    """模板少一项设置的适配器（反着试用）。"""

    def __init__(self, drop, **kw):
        super().__init__(**kw)
        self.drop = drop

    def template(self, state_dir, workdir):
        super().template(state_dir, workdir)
        f = state_dir / '.claude.json'
        d = json.loads(f.read_text())
        d.pop(self.drop)
        f.write_text(json.dumps(d))
        os.chmod(f, 0o600)


if __name__ == '__main__':
    unittest.main()
