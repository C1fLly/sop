"""3-12：sop machine setup 的串联（machine/setup.py）、M4「合格过且没变就不再真调」的判断（machine/aisetup.py）、
假清单（SOP_TOOLS_TOML）。各步换成假的函数，只测串联本身；整条真的各步在流程沙箱 tests/sandbox/test_machine_setup.py 里测。
工具包根目录、主目录都是 /tmp 下临时的；不调用任何 AI（M4 的适配器换成假的对象，probe 一调就让测试失败）。"""
import io
import json
import os
import pathlib
import time
from contextlib import redirect_stdout
from unittest import mock

from machine import aisetup, catalog, cli, components, config, setup
from kernel.errors import SopError
from tests.helpers import REPO, TMP_ROOT, TempHome, mock_env


class Steps:
    """假的几步：按剧本返回结果，记下被调了哪几步。"""

    def __init__(self, plan):
        self.plan = plan
        self.called = []

    def steps(self):
        out = []
        for code in self.plan:
            def fn(ctx, code=code):
                self.called.append(code)
                r = self.plan[code]
                if isinstance(r, BaseException):
                    raise r
                return r
            out.append((code, f'第{code}步', fn))
        return tuple(out)


class Base(TempHome):
    def run_setup(self, plan, recheck=False):
        s = Steps(plan)
        said = []
        rc = setup.run(recheck=recheck, say=said.append, steps=s.steps())
        return rc, s.called, '\n'.join(said)

    def prog(self):
        return config.load('setup')


class TestRun(Base):
    def test_all_ok(self):
        rc, called, out = self.run_setup({'M2': setup.StepResult(True, ['装好了']),
                                          'M3': setup.StepResult(True, skipped=True),
                                          'M4': setup.StepResult(True, cost=0.02, record={'tools': {'claude': {'version': '1'}}})})
        self.assertEqual(rc, 0)
        self.assertEqual(called, ['M2', 'M3', 'M4'])
        self.assertIn('M3 第M3步：已经合格，跳过', out)
        self.assertIn('M2 第M2步：做好了，出口检查通过', out)
        self.assertIn('0.0200 美元', out)
        p = self.prog()
        self.assertNotIn('running', p)
        self.assertEqual(p['last']['result'], 'ok')
        self.assertEqual(p['passed']['M4']['tools'], {'claude': {'version': '1'}})
        self.assertEqual(oct(os.stat(config._path('setup')).st_mode & 0o777), '0o600')
        # 再跑一次，M4 跳过：上次记下的不被冲掉
        rc, _, _ = self.run_setup({'M4': setup.StepResult(True, skipped=True)})
        self.assertEqual(self.prog()['passed']['M4']['tools'], {'claude': {'version': '1'}})

    def test_stop_at_failed_step(self):
        rc, called, out = self.run_setup({'M2': setup.StepResult(True), 'M3': setup.StepResult(False, ['登录没成']),
                                          'M4': setup.StepResult(True)})
        self.assertEqual(rc, 1)
        self.assertEqual(called, ['M2', 'M3'])
        self.assertIn('登录没成', out)
        self.assertIn('停在「M3 第M3步」', out)
        p = self.prog()
        self.assertNotIn('running', p)
        self.assertEqual((p['last']['result'], p['last']['step']), ('stopped', 'M3'))
        self.assertEqual(sorted(p['passed']), ['M2'])
        # 下一次不说「断了」（是没通过，不是断了）
        _, _, out = self.run_setup({'M2': setup.StepResult(True)})
        self.assertNotIn('没做完就断了', out)

    def test_soperror_is_failure(self):
        rc, called, out = self.run_setup({'M2': SopError('终端启动文件的标记对不上'), 'M3': setup.StepResult(True)})
        self.assertEqual(rc, 1)
        self.assertEqual(called, ['M2'])
        self.assertIn('终端启动文件的标记对不上', out)

    def test_ctrl_c_then_resume_message(self):
        rc, called, out = self.run_setup({'M2': setup.StepResult(True), 'M3': KeyboardInterrupt(), 'M4': setup.StepResult(True)})
        self.assertEqual(rc, setup.INTERRUPTED)
        self.assertEqual(called, ['M2', 'M3'])
        self.assertIn('中途停了', out)
        self.assertEqual(self.prog()['running']['step'], 'M3')
        rc, called, out = self.run_setup({'M2': setup.StepResult(True, skipped=True), 'M3': setup.StepResult(True),
                                          'M4': setup.StepResult(True)})
        self.assertEqual(rc, 0)
        self.assertIn('「M3 第M3步」那一步没做完就断了', out)
        self.assertNotIn('running', self.prog())

    def test_busy(self):
        fd, _ = setup._lock()
        try:
            rc, called, out = self.run_setup({'M2': setup.StepResult(True)})
        finally:
            os.close(fd)
        self.assertEqual(rc, setup.BUSY)
        self.assertEqual(called, [])
        self.assertIn('另一个窗口正在执行', out)
        self.assertEqual(self.run_setup({'M2': setup.StepResult(True)})[0], 0)   # 锁放开了

    def test_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(['setup', '--bogus']), 2)
            self.assertEqual(setup.main(['--bogus']), 2)
            cli.main(['help'])
        self.assertIn('sop machine setup', buf.getvalue())
        self.assertNotIn('还没做好（第 1 期第三段的任务 3-12）', buf.getvalue())
        with mock.patch.object(setup, 'run', return_value=0) as run:
            self.assertEqual(cli.main(['setup', '--recheck']), 0)
            run.assert_called_once_with(recheck=True)
            self.assertEqual(cli.main(['setup']), 0)
            run.assert_called_with(recheck=False)


class FakeAdapter:
    """假的 Claude Code 适配器：只给位置和版本；probe 一调就算测试失败（这里的判断都不该花钱）。"""

    def __init__(self, path, version='2.0.1'):
        self.path, self.ver = str(path), version

    def location(self):
        return self.path, self.path

    def version(self):
        return self.ver

    def probe(self):
        raise AssertionError('不该真调')


class TestStillGood(TempHome):
    def setUp(self):
        super().setUp()
        self.exe = self.tmp / 'claude'
        self.exe.write_text('#!/bin/sh\n')
        self.a = FakeAdapter(self.exe)
        self.f = aisetup.write_env('claude', {'ANTHROPIC_BASE_URL': 'https://x.fake.invalid', 'ANTHROPIC_AUTH_TOKEN': 'fake-k'})
        self.assertTrue(str(self.f).startswith(str(TMP_ROOT)))

    def passed(self, ok=True, version='2.0.1'):
        with config.editing('tools') as d:
            d.setdefault('tools', {})['claude'] = {'probe_ok': ok, 'probed_version': version}

    def test_same(self):
        rec = aisetup.fingerprint('claude', self.a)
        self.passed()
        self.assertTrue(aisetup.still_good('claude', rec, self.a))
        self.assertNotIn('fake-k', json.dumps(rec))           # 只记文件的编号、大小、时间，不记内容

    def test_changes(self):
        rec = aisetup.fingerprint('claude', self.a)
        self.passed()
        self.assertFalse(aisetup.still_good('claude', None, self.a))                       # 没记过
        self.assertFalse(aisetup.still_good('claude', rec, FakeAdapter(self.exe, '2.0.2')))  # 升级了
        self.assertFalse(aisetup.still_good('claude', rec, FakeAdapter(self.tmp / 'other')))  # 换了一份
        self.passed(ok=False)
        self.assertFalse(aisetup.still_good('claude', rec, self.a))                        # 最近一次自检没过
        self.passed(version='2.0.0')
        self.assertFalse(aisetup.still_good('claude', rec, self.a))
        self.passed()
        os.chmod(self.f, 0o644)
        self.assertFalse(aisetup.still_good('claude', rec, self.a))                        # 别人能读了
        os.chmod(self.f, 0o600)
        self.assertTrue(aisetup.still_good('claude', rec, self.a))
        time.sleep(0.01)
        aisetup.write_env('claude', {'ANTHROPIC_BASE_URL': 'https://x.fake.invalid', 'ANTHROPIC_AUTH_TOKEN': 'fake-k2'})
        self.assertFalse(aisetup.still_good('claude', rec, self.a))                        # 重填了
        self.f.unlink()
        self.assertIsNone(aisetup.fingerprint('claude', self.a))
        self.assertFalse(aisetup.still_good('claude', rec, self.a))

    def test_precheck_no_call(self):
        self.f.write_text("ANTHROPIC_BASE_URL='https://x.fake.invalid'\n")
        r = aisetup.check_tool('claude', self.a)          # 没密钥：不调 probe（调了 FakeAdapter 会报错）
        self.assertFalse(r.ok)
        self.assertIn('没有密钥', r.message)

    def test_step_m4_skip_and_recheck(self):
        self.passed()
        rec = {'claude': aisetup.fingerprint('claude', self.a)}
        said = []
        ctx = setup.Ctx(recheck=False, say=said.append, passed={'M4': {'tools': rec}})
        with mock.patch.dict(aisetup.TOOLS['claude'], adapter=lambda: self.a):
            r = setup.step_m4(ctx)
            self.assertTrue(r.ok and r.skipped)
            self.assertIn('不再真调', r.lines[0])
            ctx.recheck = True
            with mock.patch.object(aisetup, 'setup', return_value=aisetup.Result(True, [])) as s:
                r = setup.step_m4(ctx)
            s.assert_called_once()
            self.assertFalse(r.skipped)
            self.assertEqual(r.record, {'tools': rec})


class TestStepM6(TempHome):
    def test_skip_when_registered_same(self):
        now = {k: f'v-{k}' for k in config.SYSTEM_PARTS}
        ctx = setup.Ctx(recheck=False, say=lambda *_: None, passed={})
        with mock.patch.object(components, 'collect', return_value=now), \
                mock.patch('machine.syscheck.prepare', return_value=True) as prep:
            r = setup.step_m6(ctx)                        # 还没登记过：跑
            self.assertFalse(r.skipped)
            self.assertEqual(prep.call_count, 1)
            config.record_system(now)
            r = setup.step_m6(ctx)                        # 登记和现在一样：不跑
            self.assertTrue(r.ok and r.skipped)
            self.assertEqual(prep.call_count, 1)
            ctx.recheck = True
            setup.step_m6(ctx)                            # --recheck：跑
            self.assertEqual(prep.call_count, 2)
            ctx.recheck = False
            config.record_system({**now, 'kernel': 'old'})
            setup.step_m6(ctx)                            # 系统升级了：跑
            self.assertEqual(prep.call_count, 3)


class TestCatalogOverride(TempHome):
    def test_scripts_relative_to_catalog(self):
        fake = REPO / 'tests' / 'fakes' / 'machine' / 'tools.toml'
        real = catalog.load()
        self.assertEqual(catalog.find('uv', real).install_kind()[1], REPO / 'machine' / 'install' / 'uv.sh')
        with mock_env({'SOP_TOOLS_TOML': str(fake)}):
            tools = catalog.load()
            uv = catalog.find('uv', tools)
            self.assertEqual(uv.install_kind()[1], fake.parent / 'install' / 'uv.sh')
            self.assertTrue(all(t.install_kind()[0] == 'apt' or t.install_kind()[1].exists() for t in tools))
        self.assertEqual(catalog.load(), real)

    def test_m2_problems(self):
        with mock_env({'HOME': str(self.tmp), 'SOP_TOOLS_DIR': str(self.tmp / 'tools'),
                       'SOP_TOOLS_TOML': str(REPO / 'tests' / 'fakes' / 'machine' / 'tools.toml')}):
            self.assertEqual(pathlib.Path.home(), self.tmp)
            probs = '\n'.join(setup.m2_problems())
            self.assertIn('uv：还没装', probs)
            self.assertNotIn('git', probs)                 # 系统的 git 合格
            self.assertNotIn('wt', probs)                  # M5 的不归 M2
            self.assertIn('缓存目录还没建', probs)
            self.assertIn('终端启动文件', probs)
            (self.tmp / '.bashrc').write_text('# >>> SOP 工具包管理的段落（不要手改，重新安装时会被换回来）>>>\n')
            self.assertIn('标记', '\n'.join(setup.m2_problems()))
