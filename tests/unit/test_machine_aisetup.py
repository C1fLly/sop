"""3-10：M4 登录 AI 工具（machine/aisetup.py）。
SOP_HOME 是 /tmp 下临时的（登记文件写在那里，不碰真的 ~/tools/sop/config）；claude 是假的（tests/fakes/claude/claude），
自检在真的受限环境（bubblewrap）里跑，不花钱、不连网。每个测试开头确认用的是假的 claude。"""
import os
import pathlib
import shutil
import stat

from adapters.ai.claude import adapter as C
from machine import aisetup, network
from tests.helpers import REPO, TMP_ROOT, TempHome

FAKE = REPO / 'tests' / 'fakes' / 'claude' / 'claude'
TOKEN = 'fake-token-3-10-abcdefgh'


class Counting(C.ClaudeAdapter):
    calls = 0

    def probe(self, *a, **kw):
        type(self).calls += 1
        return super().probe(*a, **kw)


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.exe = self.tmp / 'bin' / 'claude'
        self.exe.parent.mkdir()
        shutil.copy(FAKE, self.exe)
        Counting.calls = 0
        self.a = Counting(exe=self.exe, environ={})
        self.assertEqual(self.a.location()[1], str(self.exe))        # 用的是假的
        self.assertTrue(str(aisetup.env_file('claude')).startswith(str(TMP_ROOT)))
        self.said = []

    def answers(self, *items):
        it = iter(items)
        self.asked = []

        def ask(q):
            self.asked.append(q)
            return next(it)
        return ask

    def secret(self, value):
        def s(q):
            self.asked.append(q)
            return value
        return s

    def run_setup(self, *answers, secret=TOKEN, environ=None):
        return aisetup.setup_tool('claude', ask=self.answers(*answers), secret=self.secret(secret), say=self.said.append,
                                  environ=environ or {}, adapter=self.a)

    def write(self, mode='ok', perm=0o600):
        f = aisetup.write_env('claude', {'ANTHROPIC_BASE_URL': f'https://{mode}.fake.invalid', 'ANTHROPIC_AUTH_TOKEN': TOKEN})
        os.chmod(f, perm)
        return f

    def all_text(self, res=None):
        out = '\n'.join(self.said + getattr(self, 'asked', []))
        if res is not None:
            out += '\n'.join(aisetup.report(res))
        return out


class TestCheck(Base):
    def test_not_registered_no_call(self):
        r = aisetup.check({'claude': self.a})
        self.assertFalse(r.ok)
        self.assertIn('还没登记', r.tools[0].message)
        self.assertEqual(Counting.calls, 0)

    def test_registered_ok(self):
        self.write()
        r = aisetup.check({'claude': self.a})
        self.assertTrue(r.ok, r.tools[0].message)
        self.assertEqual(Counting.calls, 1)
        self.assertGreater(r.cost, 0)
        self.assertIn('还没做过真实 AI 演练', r.tools[0].remind)
        rep = '\n'.join(aisetup.report(r))
        self.assertIn('美元', rep)
        self.assertIn('第 5 期', rep)
        self.assertNotIn(TOKEN, rep)

    def test_others_can_read(self):
        self.write(perm=0o644)
        r = aisetup.check({'claude': self.a})
        self.assertFalse(r.ok)
        self.assertIn('chmod 600', r.tools[0].message)
        self.assertEqual(Counting.calls, 0)

    def test_missing_url_or_key(self):
        aisetup.write_env('claude', {'ANTHROPIC_AUTH_TOKEN': TOKEN})
        self.assertIn('没有服务地址', aisetup.check({'claude': self.a}).tools[0].message)
        aisetup.write_env('claude', {'ANTHROPIC_BASE_URL': 'https://ok.fake.invalid'})
        self.assertIn('没有密钥', aisetup.check({'claude': self.a}).tools[0].message)
        self.assertEqual(Counting.calls, 0)

    def test_quota_stops(self):
        self.write('quota')
        r = aisetup.check({'claude': self.a})
        self.assertFalse(r.ok)
        self.assertTrue(r.quota)
        self.assertIn('充值', r.tools[0].message)
        self.assertIn('没有重试', '\n'.join(aisetup.report(r)))
        self.assertEqual(Counting.calls, 1)

    def test_call_fails(self):
        self.write('iserror')
        r = aisetup.check({'claude': self.a})
        self.assertFalse(r.ok)
        self.assertFalse(r.quota)


class TestSetup(Base):
    def test_typed_url_and_key(self):
        r = self.run_setup('1', 'https://ok.fake.invalid/v1', '')
        self.assertTrue(r.ok, (r.message, self.said))
        f = aisetup.env_file('claude')
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(f.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(f.parent.parent.stat().st_mode), 0o700)
        self.assertEqual(aisetup.read_env('claude'), {'ANTHROPIC_BASE_URL': 'https://ok.fake.invalid/v1',
                                                      'ANTHROPIC_AUTH_TOKEN': TOKEN})
        # 适配器读得到这一份（问题 5），体检按 …BASE_URL 那一行试连（3-50）
        env, src = C.ClaudeAdapter(exe=self.exe, environ={}).credentials()
        self.assertEqual(env, {'ANTHROPIC_BASE_URL': 'https://ok.fake.invalid/v1', 'ANTHROPIC_AUTH_TOKEN': TOKEN})
        self.assertEqual(src, str(f))
        self.assertEqual(network.ai_address('claude', environ={})[0], 'https://ok.fake.invalid/')
        self.assertNotIn(TOKEN, self.all_text())
        self.assertEqual(Counting.calls, 1)
        self.assertEqual([p.name for p in f.parent.iterdir()], ['claude.env'])     # 没留临时文件

    def test_api_key_variant(self):
        r = self.run_setup('', 'https://ok.fake.invalid', '2')
        self.assertTrue(r.ok, r.message)
        self.assertEqual(sorted(aisetup.read_env('claude')), ['ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL'])

    def test_copy_from_terminal(self):
        environ = {'ANTHROPIC_BASE_URL': 'https://user:pw@ok.fake.invalid/x?k=1', 'ANTHROPIC_AUTH_TOKEN': TOKEN,
                   'ANTHROPIC_MODEL': 'some model', 'CLAUDE_CODE_SESSION_ID': 'abc', 'CLAUDECODE': '1', 'PATH': '/bin'}
        r = self.run_setup('1', 'y', environ=environ)
        self.assertTrue(r.ok, r.message)
        self.assertEqual(aisetup.read_env('claude'), {k: environ[k] for k in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN',
                                                                            'ANTHROPIC_MODEL')})
        q = '\n'.join(self.asked)
        self.assertIn('https://ok.fake.invalid/x', q)           # 地址给人看时去掉账号密码、参数
        self.assertNotIn('pw@', q)
        self.assertNotIn(TOKEN, self.all_text())

    def test_decline_terminal_copy(self):
        environ = {'ANTHROPIC_BASE_URL': 'https://iserror.fake.invalid', 'ANTHROPIC_AUTH_TOKEN': 'fake-other'}
        r = self.run_setup('1', 'n', 'https://ok.fake.invalid', '', environ=environ)
        self.assertTrue(r.ok, r.message)
        self.assertEqual(aisetup.read_env('claude')['ANTHROPIC_AUTH_TOKEN'], TOKEN)

    def test_official_account(self):
        r = self.run_setup('2')
        self.assertFalse(r.ok)
        self.assertIn('没有验证过', r.message)
        self.assertIn('W37', '\n'.join(self.said))
        self.assertFalse(aisetup.env_file('claude').exists())
        self.assertEqual(Counting.calls, 0)

    def test_bad_input_not_written(self):
        for answers, key in ((('1', 'api.example.com'), TOKEN), (('1', 'https://ok.fake.invalid'), 'fake bad key'),
                             (('1', 'https://ok.fake.invalid'), '')):
            r = self.run_setup(*answers, secret=key)
            self.assertFalse(r.ok)
            self.assertIn('这次没有登记', r.message)
            self.assertFalse(aisetup.env_file('claude').exists())
        self.assertEqual(Counting.calls, 0)

    def test_already_ok_skips(self):
        self.write()
        before = aisetup.env_file('claude').read_bytes()
        r = self.run_setup()          # 一个问题都不该问
        self.assertTrue(r.ok)
        self.assertTrue(any('跳过' in s for s in self.said))
        self.assertEqual(aisetup.env_file('claude').read_bytes(), before)
        self.assertEqual(Counting.calls, 1)

    def test_quota_no_retry_no_reentry(self):
        self.write('quota')
        r = self.run_setup()
        self.assertTrue(r.quota)
        self.assertEqual(Counting.calls, 1)

    def test_broken_then_reenter_or_not(self):
        self.write('iserror')
        r = self.run_setup('n')
        self.assertFalse(r.ok)
        self.assertEqual(aisetup.read_env('claude')['ANTHROPIC_BASE_URL'], 'https://iserror.fake.invalid')
        r = self.run_setup('', '1', 'https://ok.fake.invalid', '')
        self.assertTrue(r.ok, r.message)
        self.assertEqual(Counting.calls, 3)

    def test_write_env_rejects(self):
        for bad in ({'ANTHROPIC_BASE_URL': 'https://a\nX=1'}, {'ANTHROPIC_AUTH_TOKEN': "a'b"}, {'bad name': 'x'},
                    {'ANTHROPIC_AUTH_TOKEN': ''}):
            with self.assertRaises(aisetup.SopError):
                aisetup.write_env('claude', bad)
        self.assertFalse(aisetup.env_file('claude').exists())

    def test_whole_setup(self):
        res = aisetup.setup(ask=self.answers('1', 'https://ok.fake.invalid', ''), secret=self.secret(TOKEN),
                            say=self.said.append, environ={}, adapters={'claude': self.a})
        self.assertTrue(res.ok)
        self.assertEqual([t.name for t in res.tools], ['claude'])
        self.assertNotIn(TOKEN, '\n'.join(aisetup.report(res)))


class TestNoRealCall(Base):
    def test_default_tools_list(self):
        self.assertEqual(list(aisetup.TOOLS), ['claude'])
        for k in ('label', 'url_var', 'key_vars', 'env_prefix', 'adapter'):
            self.assertIn(k, aisetup.TOOLS['claude'])
        self.assertTrue(aisetup.TOOLS['claude']['url_var'].endswith('BASE_URL'))
        self.assertTrue(pathlib.Path(aisetup.__file__).exists())
