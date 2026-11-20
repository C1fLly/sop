"""3-27：Claude Code 适配器的能力声明、自检（probe）、自动调用（run_headless）。
全用假的 claude（tests/fakes/claude/claude），在真的受限环境（bubblewrap）里跑，不花钱、不连网。
真实调用在 tests/real_ai/claude_adapter.py，手动跑。"""
import glob
import json
import os
import pathlib
import shutil
import stat
import time

from adapters.ai import base
from adapters.ai.claude import adapter as C
from checks.quota_scan.check import run as quota_scan
from checks.result_file.check import run as check_result
from machine import config
from runner import placement
from runner.selftest import make_fixture
from tests.helpers import REPO, TempHome, mock_env

FAKE = REPO / 'tests' / 'fakes' / 'claude' / 'claude'
TOKEN = 'fake-token-3-27-abcdefgh'


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.R, _ = make_fixture(self.tmp)
        self.exe = self.tmp / 'bin' / 'claude'
        self.exe.parent.mkdir()
        shutil.copy(FAKE, self.exe)

    def creds(self, mode='ok', extra=''):
        d = config.paths.config_dir() / 'ai'
        d.mkdir(parents=True, exist_ok=True)
        f = d / 'claude.env'
        f.write_text(f'# M4 写的\nexport ANTHROPIC_BASE_URL="fake://{mode}"\nANTHROPIC_AUTH_TOKEN=\'{TOKEN}\'\n'
                     f'PATH=/坏\nCLAUDE_CONFIG_DIR=/坏\n{extra}')
        os.chmod(f, 0o600)
        return f

    def adapter(self, **kw):
        return C.ClaudeAdapter(exe=self.exe, **kw)

    def state(self, a, workdir):
        st = self.tmp / f'state-{len(list(self.tmp.glob("state-*")))}'
        st.mkdir(mode=0o700)
        a.template(st, workdir)
        return st

    def taskpack(self, body='读 README.md。结束时写一份 JSON 结果文件到 /sop/out/result.json。', budget=None):
        d = self.tmp / f'task-{len(list(self.tmp.glob("task-*")))}'
        (d / 'task').mkdir(parents=True)
        (d / 'out').mkdir()
        (d / 'task' / 'task.md').write_text(f'# 任务包：T9\n\n{body}\n', encoding='utf-8')
        tj = {'scope': 'a-1/01', 'step': 'T9', 'attempt': 1, 'result_path': '/sop/out/result.json', 'kind': 'review'}
        if budget is not None:
            tj['budget_usd'] = budget
        (d / 'task' / 'task.json').write_text(json.dumps(tj))
        return d

    def ctx(self, d, wt='ticket-a-1-01'):
        return placement.Ctx(root=self.R, kind='readonly', worktree=wt, feature='a-1', task_dir=d / 'task', out_dir=d / 'out',
                             chdir=self.R / wt)

    def seen(self, st):
        logs = sorted(pathlib.Path(st).rglob('*.jsonl'))
        return [json.loads(x) for f in logs for x in f.read_text().splitlines()]


class TestDeclaration(Base):
    def test_declaration_covers_10_1(self):
        need = ('interactive', 'headless', 'resume', 'skill_syntax', 'skill_headless', 'subagents', 'restrictions',
                'budget_flag', 'rules_file', 'skills_dir', 'session_logs', 'skills_runnable')
        for k in need:
            self.assertIn(k, C.DECLARATION)
        a = self.adapter()
        for k, v in a.caps.items():
            self.assertEqual(v, C.DECLARATION[k])
        self.assertEqual(C.DECLARATION['skills_dir'], '.claude/skills')

    def test_template_five_settings(self):
        a = self.adapter()
        st = self.state(a, self.R / 'main')
        f = st / '.claude.json'
        d = json.loads(f.read_text())
        self.assertEqual(d, {'hasCompletedOnboarding': True, 'lastOnboardingVersion': '9.9.9', 'autoUpdates': False,
                             'bypassPermissionsModeAccepted': True,
                             'projects': {str(self.R / 'main'): {'hasTrustDialogAccepted': True}}})
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_command_no_forbidden_flags(self):
        a = self.adapter(version='9.9.9')
        argv = a.command('你好', budget=0.5)
        self.assertEqual(argv[:3], [os.path.realpath(self.exe), '-p', '你好'])
        for f in ('--output-format', 'json', '--dangerously-skip-permissions', '--max-budget-usd', '0.5'):
            self.assertIn(f, argv)
        for f in C.FORBIDDEN_FLAGS:
            self.assertNotIn(f, argv)
        self.assertNotIn('--max-budget-usd', a.command('你好'))
        self.assertEqual(a.command('x', session='abc')[-2:], ['--resume', 'abc'])

    def test_caps_check(self):
        self.assertEqual(self.adapter().check_caps(), [])
        old = self.tmp / 'bin' / 'claude-old'
        shutil.copy(FAKE, old)
        self.assertEqual([f for f, _ in C.ClaudeAdapter(exe=old).check_caps()], ['--max-budget-usd'])


class TestCredentials(Base):
    def test_from_config_file(self):
        self.creds(extra='CLAUDE_CODE_USE_BEDROCK=0\nOTHER=1\n不是一行设置\n')
        env, src = self.adapter(environ={'ANTHROPIC_AUTH_TOKEN': '终端里的'}).credentials()
        self.assertEqual(env, {'ANTHROPIC_BASE_URL': 'fake://ok', 'ANTHROPIC_AUTH_TOKEN': TOKEN, 'CLAUDE_CODE_USE_BEDROCK': '0'})
        self.assertTrue(src.endswith('config/ai/claude.env'))

    def test_file_readable_by_others_refused(self):
        f = self.creds()
        os.chmod(f, 0o644)
        with self.assertRaises(C.SopError):
            self.adapter().credentials()

    def test_fallback_environment_only_anthropic(self):
        env, src = self.adapter(environ={'ANTHROPIC_BASE_URL': 'u', 'ANTHROPIC_AUTH_TOKEN': 't',
                                         'CLAUDE_CODE_SESSION_ID': '本会话的', 'CLAUDE_CONFIG_DIR': '/x', 'HOME': '/h'}).credentials()
        self.assertEqual(env, {'ANTHROPIC_BASE_URL': 'u', 'ANTHROPIC_AUTH_TOKEN': 't'})
        self.assertEqual(src, '环境变量')
        self.assertEqual(self.adapter(environ={'HOME': '/h'}).credentials(), ({}, ''))


class TestHeadless(Base):
    def run_one(self, mode='ok', timeout=60, budget=None, wt='ticket-a-1-01'):
        self.creds(mode)
        a = self.adapter()
        d = self.taskpack(budget=budget)
        st = self.state(a, self.R / wt)
        out = a.run_headless(self.ctx(d, wt), d / 'task', st, timeout=timeout)
        return a, d, st, out

    def test_ok_in_sandbox(self):
        a, d, st, out = self.run_one(budget=0.3)
        self.assertEqual(out.rc, 0)
        self.assertFalse(out.timeout)
        self.assertAlmostEqual(out.cost, 0.0123)
        self.assertEqual(out.cost_basis, '工具报告')
        self.assertEqual(out.text, '收到')
        self.assertTrue(out.session)
        # 会话日志在外面的状态目录里，文件名就是会话编号
        jl = [x for x in out.logs if x.endswith('.jsonl')]
        self.assertEqual(len(jl), 1)
        self.assertTrue(jl[0].startswith(str(st)) and jl[0].endswith(f'{out.session}.jsonl'))
        rec = self.seen(st)[0]
        # 密钥是从 config/ai/claude.env 带进去的那份假的；外面这个会话的环境变量一个都没带进去
        self.assertEqual(rec['token'], TOKEN)
        self.assertNotIn('CLAUDE_CODE_SESSION_ID', rec['env_names'])
        self.assertNotIn('CLAUDECODE', rec['env_names'])
        self.assertEqual(rec['home'], os.environ['HOME'])
        self.assertEqual(rec['settings']['projects'], {str(self.R / 'ticket-a-1-01'): {'hasTrustDialogAccepted': True}})
        self.assertIn('读 README.md', rec['prompt'])
        self.assertIn('/sop/task/task.md', rec['prompt'])
        self.assertEqual(rec['argv'][rec['argv'].index('--max-budget-usd') + 1], '0.3')
        for f in C.FORBIDDEN_FLAGS:
            self.assertNotIn(f, rec['argv'])
        # 结果文件过检查（9.2）
        W = self.R / 'ticket-a-1-01'
        gd = str(self.R / '.git' / 'worktrees' / W.name)
        ok, line, _ = check_result(str(d / 'out' / 'result.json'), gd, None, None, 'review')
        self.assertTrue(ok, line)
        # 原始输出留在状态目录里，没有密钥
        self.assertNotIn(TOKEN, (st / C.OUTPUT_FILE).read_text())

    def test_list_output(self):
        _, _, _, out = self.run_one('list')
        self.assertEqual((out.rc, out.text), (0, '收到'))
        self.assertTrue(out.session)

    def test_quota_found_in_logs(self):
        _, _, _, out = self.run_one('quota')
        self.assertNotEqual(out.rc, 0)
        ok, _, rep = quota_scan(out.logs)
        self.assertFalse(ok)
        self.assertTrue(rep['hits'])

    def test_is_error_with_rc0_counts_as_failure(self):
        _, _, _, out = self.run_one('iserror')
        self.assertEqual(out.rc, 1)
        self.assertIn('error_during_execution', out.text)

    def test_garbage_output(self):
        _, _, _, out = self.run_one('garbage')
        self.assertEqual(out.rc, 1)
        self.assertEqual(out.cost_basis, '没读到工具的报告')
        self.assertIn('这不是 JSON', out.text)

    def test_leaked_secret_scrubbed(self):
        _, _, st, out = self.run_one('leak')
        self.assertNotEqual(out.rc, 0)
        self.assertNotIn(TOKEN, out.text)
        self.assertIn('***', out.text)
        self.assertNotIn(TOKEN, (st / C.OUTPUT_FILE).read_text())

    def test_timeout(self):
        t0 = time.time()
        _, _, st, out = self.run_one('slow', timeout=2)
        self.assertLess(time.time() - t0, 20)
        self.assertTrue(out.timeout)
        self.assertNotIn(TOKEN, out.text)

    def test_parse_output(self):
        self.assertIsNone(C.parse_output('不是'))
        self.assertEqual(C.parse_output('前面一行\n{"type": "result", "result": "x"}')['result'], 'x')
        self.assertIsNone(C.parse_output('[{"type": "system"}]'))


class TestProbe(Base):
    def probes_left(self):
        return set(glob.glob('/tmp/sop-probe-*'))

    def test_ok_records_version_and_reminds(self):
        self.creds()
        config.record_tool('claude', path='/旧', version='1.0.0', kind='ai', others=[{'path': '/别处'}])
        before = self.probes_left()
        r = self.adapter().probe()
        self.assertTrue(r.ok, r.message)
        self.assertEqual(r.version, '9.9.9')
        self.assertIn('收到', r.message)
        self.assertAlmostEqual(r.cost, 0.0123)
        self.assertEqual(self.probes_left(), before)        # 临时小项目和状态目录都删了
        e = config.tools()['claude']
        self.assertEqual((e['version'], e['probed_version'], e['probe_ok'], e['path']), ('9.9.9', '9.9.9', True, str(self.exe)))
        self.assertEqual(e['others'], [{'path': '/别处'}])
        self.assertIn('还没做过真实 AI 演练', r.remind)
        # 演练过这一版就不提醒；演练的版本和现在的不一样就提醒重跑
        base.mark_drilled('claude', '9.9.9')
        self.assertEqual(self.adapter().probe().remind, '')
        base.mark_drilled('claude', '9.9.8')
        r = self.adapter().probe()
        self.assertIn('9.9.8', r.remind)
        self.assertIn('要重跑一次演练', r.remind)
        # 体检重新登记时，自检和演练记的都留着
        config.record_tools({'claude': config.tool_entry(path='/x', version='9.9.9', kind='ai')})
        e = config.tools()['claude']
        self.assertEqual((e['probed_version'], e['drilled_version'], e['probe_ok']), ('9.9.9', '9.9.8', True))

    def test_quota_stops_without_retry(self):
        self.creds('quota')
        r = self.adapter().probe()
        self.assertFalse(r.ok)
        self.assertTrue(r.quota)
        self.assertIn('充值', r.message)
        self.assertIn('没有重试', r.message)
        e = config.tools()['claude']
        self.assertFalse(e['probe_ok'])
        self.assertNotIn('probed_version', e)

    def test_failure_and_no_secret(self):
        self.creds('leak')
        r = self.adapter().probe()
        self.assertFalse(r.ok)
        self.assertNotIn(TOKEN, r.message)
        self.assertNotIn(TOKEN, json.dumps(r.details, ensure_ascii=False))

    def test_no_credentials_no_call(self):
        with mock_env({'HOME': os.environ['HOME']}):
            r = C.ClaudeAdapter(exe=self.exe, environ={}).probe()
        self.assertFalse(r.ok)
        self.assertIn('claude.env', r.message)
        self.assertIn('W37', r.message)
        self.assertEqual(r.cost, 0.0)

    def test_missing_flags_no_call(self):
        self.creds()
        old = self.tmp / 'bin' / 'claude-old'
        shutil.copy(FAKE, old)
        r = C.ClaudeAdapter(exe=old).probe()
        self.assertFalse(r.ok)
        self.assertEqual(r.details['missing_flags'], ['--max-budget-usd'])
        self.assertNotIn('claude', config.tools())      # 没调用、没登记

    def test_not_found(self):
        with mock_env({'PATH': str(self.tmp / '空')}):
            a = C.ClaudeAdapter(exe=None)
            a.location = lambda: ('', '')
            r = a.probe()
        self.assertFalse(r.ok)
        self.assertIn('没找到 Claude Code', r.message)

    def test_fake_adapter_probe_shape(self):
        from adapters.ai.fake.adapter import FakeAdapter
        r = FakeAdapter().probe()
        self.assertIsInstance(r, base.ProbeResult)
        self.assertTrue(r.ok)
