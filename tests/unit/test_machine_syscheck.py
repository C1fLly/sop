"""3-07：系统升级后先重跑隔离自检（设计书 4.5）。用造出来的系统组件和假的自检命令测，不碰这台电脑的登记、不跑真的自检。"""
import os
import pathlib
import stat
import sys

from kernel import paths
from machine import config, syscheck
from tests.helpers import REPO, TempHome, mock_env

PARTS = {'kernel': '7.0.0-43-generic #43-Ubuntu SMP', 'bubblewrap': '0.11.1 (package 0.11.1-1ubuntu0.3)',
         'userns_rule': 'missing', 'userns_policy': 'restrict=1 bwrap-userns-restrict=0123456789ab', 'tiocsti': '0'}


class Fake:
    """假的查系统组件和假的自检：记下被调用了几次。"""

    def __init__(self, parts, ok=True, lines=('隔离自检：159 项，0 项不符合',)):
        self.parts, self.ok, self.lines = dict(parts), ok, list(lines)
        self.collected = self.tested = 0

    def collect(self):
        self.collected += 1
        return dict(self.parts)

    def selftest(self):
        self.tested += 1
        return self.ok, self.lines


def gate(fake):
    out = []
    return syscheck.gate(collect=fake.collect, selftest=fake.selftest, out=out.append), '\n'.join(out)


class TestGate(TempHome):
    def test_unchanged_no_selftest_nothing_written(self):
        """和登记一样：直接推进，不自检；只读地比一下，连锁文件都不建。"""
        config.record_system(PARTS)
        before = sorted(os.listdir(paths.config_dir()))
        f = Fake(PARTS)
        ok, out = gate(f)
        self.assertTrue(ok)
        self.assertEqual((f.tested, out), (0, ''))
        self.assertEqual(sorted(os.listdir(paths.config_dir())), before)

    def test_never_registered(self):
        """还没登记过（第一次推进流程）：先自检，通过了记下来。"""
        f = Fake(PARTS)
        ok, out = gate(f)
        self.assertTrue(ok)
        self.assertEqual(f.tested, 1)
        self.assertIn('还没有隔离自检通过的记录', out)
        self.assertIn('隔离自检通过（159 项，0 项不符合），已记下现在的系统组件版本', out)
        self.assertEqual(config.system()['components'], PARTS)
        self.assertEqual(stat.S_IMODE(os.stat(paths.config_dir()).st_mode), 0o700)

    def test_changed_then_pass(self):
        """内核只换了一次编译、bubblewrap 打了安全补丁：两样都说出来，先自检，通过后登记换成现在的。"""
        config.record_system({**PARTS, 'kernel': '7.0.0-43-generic #42-Ubuntu SMP',
                              'bubblewrap': '0.11.1 (package 0.11.1-1ubuntu0.2)'})
        f = Fake(PARTS)
        ok, out = gate(f)
        self.assertTrue(ok)
        self.assertEqual(f.tested, 1)
        self.assertIn('系统有变化', out)
        self.assertIn('系统内核：上次是「7.0.0-43-generic #42-Ubuntu SMP」，现在是「7.0.0-43-generic #43-Ubuntu SMP」', out)
        self.assertIn('受限环境用的 bubblewrap：上次是「0.11.1 (package 0.11.1-1ubuntu0.2)」', out)
        self.assertNotIn('塞按键', out)
        self.assertLess(out.index('先重跑一遍隔离自检'), out.index('隔离自检通过（'))
        self.assertEqual(config.system()['components'], PARTS)
        # 再来一次：不再自检
        self.assertEqual(gate(f), (True, ''))
        self.assertEqual(f.tested, 1)

    def test_changed_then_fail(self):
        """自检不过：停下，说哪几项不符合、指向维修窗口；登记不改，下次还会自检。"""
        old = {**PARTS, 'tiocsti': '0'}
        config.record_system(old)
        f = Fake({**PARTS, 'tiocsti': '1'}, ok=False,
                 lines=['不符合 内核已禁用往终端塞按键（对话步骤的前提）（应为 True，实际 False ）', '隔离自检：159 项，1 项不符合'])
        for n in (1, 2):
            ok, out = gate(f)
            self.assertFalse(ok)
            self.assertEqual(f.tested, n)
            self.assertIn('往终端塞按键的开关（要是关着的）：上次是「0」，现在是「1」', out)
            self.assertIn('隔离自检没通过', out)
            self.assertIn('不符合 内核已禁用往终端塞按键', out)
            self.assertIn('流程一步都没有推进', out)
            self.assertIn('sop repair', out)
            self.assertEqual(config.system()['components'], old)

    def test_records_what_was_tested(self):
        """记下的是自检之前查到的那一份（自检验的就是它），不是自检之后再查一遍。"""
        f = Fake(PARTS)
        real = f.selftest

        def selftest():
            f.parts['bubblewrap'] = '0.12.0'          # 自检跑的时候系统又变了
            return real()
        ok = syscheck.gate(collect=f.collect, selftest=selftest, out=lambda *_: None)
        self.assertTrue(ok)
        self.assertEqual(config.system()['components']['bubblewrap'], PARTS['bubblewrap'])

    def test_other_sop_already_did_it(self):
        """几个 sop 同时启动：拿到锁之后再比一次，别的 sop 已经自检过、登记好了就不再跑。"""
        config.record_system({**PARTS, 'bubblewrap': '0.10.0'})
        f = Fake(PARTS)

        def collect():
            if f.collected == 1:                      # 第一次比完、拿锁之前，另一个 sop 自检通过并登记了
                config.record_system(PARTS)
            return f.collect()
        ok = syscheck.gate(collect=collect, selftest=f.selftest, out=lambda *_: None)
        self.assertTrue(ok)
        self.assertEqual((f.collected, f.tested), (2, 0))

    def test_broken_registry_is_an_error(self):
        """登记文件坏了：明说是哪个文件，不当成空的。"""
        paths.config_dir().mkdir(parents=True)
        (paths.config_dir() / 'system.json').write_text('{坏的')
        with self.assertRaises(config.ConfigError) as e:
            gate(Fake(PARTS))
        self.assertIn('system.json', str(e.exception))


class TestRunSelftest(TempHome):
    def script(self, body):
        p = self.tmp / 'selftest'
        p.write_text(f'#!{sys.executable}\nimport sys, time\n{body}\n')
        p.chmod(0o755)
        return [str(p)]

    def test_default_command(self):
        """默认跑同一个工具包版本里的 runner/selftest.py，用跑 sop 的这个 Python；环境变量能换掉（流程沙箱用）。"""
        with mock_env({'SOP_SELFTEST_CMD': ''}):
            cmd = syscheck.selftest_cmd()
        self.assertEqual(cmd, [sys.executable, '-I', str(REPO / 'runner' / 'selftest.py')])
        self.assertTrue(pathlib.Path(cmd[-1]).exists())
        with mock_env({'SOP_SELFTEST_CMD': '/x/fake'}):
            self.assertEqual(syscheck.selftest_cmd(), ['/x/fake'])

    def test_pass(self):
        ok, lines = syscheck.run_selftest(self.script('print("符合   看不到 ~/.ssh")\nprint("隔离自检：1 项，0 项不符合")'))
        self.assertEqual((ok, lines), (True, ['隔离自检：1 项，0 项不符合']))

    def test_fail_lists_bad_rows(self):
        ok, lines = syscheck.run_selftest(self.script(
            'print("符合   a")\nprint("不符合 b（应为 False，实际 True ）")\nprint("隔离自检：2 项，1 项不符合")\nsys.exit(1)'))
        self.assertFalse(ok)
        self.assertEqual(lines, ['不符合 b（应为 False，实际 True ）', '隔离自检：2 项，1 项不符合'])

    def test_crash(self):
        """跑到一半出错（比如 bubblewrap 起不来、探针跑不起来）：算没通过，带上最后几行报错。"""
        ok, lines = syscheck.run_selftest(self.script('raise RuntimeError("探针在受限环境里跑不起来：bwrap: setting up uid map")'))
        self.assertFalse(ok)
        self.assertIn('隔离自检中途出错了（退出码 1）', lines[0])
        self.assertIn('bwrap: setting up uid map', '\n'.join(lines))

    def test_timeout_and_missing(self):
        ok, lines = syscheck.run_selftest(self.script('time.sleep(30)'), timeout=0.5)
        self.assertFalse(ok)
        self.assertIn('还没跑完，按没通过处理', lines[0])
        ok, lines = syscheck.run_selftest([str(self.tmp / 'no-such-selftest')])
        self.assertFalse(ok)
        self.assertIn('隔离自检跑不起来', lines[0])

    def test_exit_zero_counts_even_without_summary(self):
        """通过看退出码；退出码非 0 就不算通过，哪怕没有「不符合」的行。"""
        self.assertEqual(syscheck.run_selftest(self.script('pass')), (True, []))
        ok, lines = syscheck.run_selftest(self.script('print("隔离自检：3 项，0 项不符合")\nsys.exit(3)'))
        self.assertFalse(ok)
        self.assertEqual(lines, ['隔离自检：3 项，0 项不符合'])
