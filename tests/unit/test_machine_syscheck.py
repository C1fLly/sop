"""3-07：系统升级后先重跑隔离自检（设计书 4.5）；3-11：M6 跑隔离自检（本机那份加专用 Docker 那份）、通过后记登记。
用造出来的系统组件和假的自检命令测，不碰这台电脑的登记、不跑真的自检。"""
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
    def script(self, body, name='selftest'):
        p = self.tmp / name
        p.write_text(f'#!{sys.executable}\nimport sys, time\n{body}\n')
        p.chmod(0o755)
        return [str(p)]

    def test_default_command(self):
        """默认依次跑同一个工具包版本里的本机那份、专用 Docker 那份，用跑 sop 的这个 Python；环境变量能换成一条（流程沙箱用）。"""
        with mock_env({'SOP_SELFTEST_CMD': ''}):
            cmds = syscheck.selftest_cmds()
        self.assertEqual(cmds, [[sys.executable, '-I', str(REPO / 'runner' / 'selftest.py')],
                                [sys.executable, '-I', str(REPO / 'runner' / 'docker' / 'selftest_docker.py')]])
        for c in cmds:
            self.assertTrue(pathlib.Path(c[-1]).exists())
        with mock_env({'SOP_SELFTEST_CMD': '/x/fake'}):
            self.assertEqual(syscheck.selftest_cmds(), [['/x/fake']])

    def test_two_parts_both_must_pass(self):
        """两份都跑：都过才算过；一份没过也接着跑完另一份，不符合的行都列出来，汇总合成一行。"""
        local_ok = self.script('print("隔离自检：159 项，0 项不符合")', 'local')
        docker_ok = self.script('print("专用 Docker 的隔离自检：13 项，0 项不符合")', 'docker')
        docker_bad = self.script('print("不符合 普通容器把根目录挂进去：看不到 ~/tools/sop")\n'
                                 'print("专用 Docker 的隔离自检：13 项，1 项不符合")\nsys.exit(1)', 'docker-bad')
        local_bad = self.script('print("不符合 看不到 ~/.ssh")\nprint("隔离自检：159 项，1 项不符合")\nsys.exit(1)', 'local-bad')
        self.assertEqual(syscheck.run_selftest([local_ok, docker_ok]), (True, ['隔离自检：172 项，0 项不符合']))
        ok, lines = syscheck.run_selftest([local_ok, docker_bad])
        self.assertFalse(ok)
        self.assertEqual(lines, ['不符合 普通容器把根目录挂进去：看不到 ~/tools/sop', '隔离自检：172 项，1 项不符合'])
        ok, lines = syscheck.run_selftest([local_bad, docker_bad])
        self.assertFalse(ok)
        self.assertEqual(lines[-1], '隔离自检：172 项，2 项不符合')
        self.assertEqual(len([x for x in lines if x.startswith('不符合')]), 2)

    def test_docker_part_cannot_start(self):
        """专用 Docker 起不来（没装 Docker、服务管理器不在）：算没通过，带上它的报错，汇总里说有一份没跑完。"""
        local_ok = self.script('print("隔离自检：159 项，0 项不符合")', 'local')
        docker_down = self.script('print("专用 Docker 起不来，停下：60 秒没起来")\nsys.exit(2)', 'selftest_docker.py')
        ok, lines = syscheck.run_selftest([local_ok, docker_down])
        self.assertFalse(ok)
        self.assertIn('隔离自检中途出错了（退出码 2）：selftest_docker.py', lines[0])
        self.assertIn('专用 Docker 起不来', '\n'.join(lines))
        self.assertEqual(lines[-1], '隔离自检：159 项，0 项不符合（有一份没跑完，没算在里面）')

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


class TestPrepare(TempHome):
    """M6（装机时）：不管登记里有没有、变没变，都跑一遍隔离自检；通过了记登记，之后第一次推进流程不用再自检。"""

    def run_prepare(self, fake):
        out = []
        return syscheck.prepare(collect=fake.collect, selftest=fake.selftest, out=out.append), '\n'.join(out)

    def test_pass_records_then_gate_skips(self):
        f = Fake(PARTS)
        ok, out = self.run_prepare(f)
        self.assertTrue(ok)
        self.assertEqual(f.tested, 1)
        self.assertIn('隔离自检通过（159 项，0 项不符合），已记下现在的系统组件版本', out)
        self.assertEqual(config.system()['components'], PARTS)
        self.assertEqual(stat.S_IMODE(os.stat(paths.config_dir() / 'system.json').st_mode), 0o600)
        self.assertEqual(gate(f), (True, ''))           # 装机时登记好了：推进流程直接走
        self.assertEqual(f.tested, 1)

    def test_runs_even_when_registered(self):
        """登记里已经是现在的样子，M6 照样跑（重装、修好之后重跑 M6 都要真的验一遍）。"""
        config.record_system(PARTS)
        f = Fake(PARTS)
        self.assertTrue(self.run_prepare(f)[0])
        self.assertEqual(f.tested, 1)

    def test_fail_keeps_registry(self):
        config.record_system({**PARTS, 'bubblewrap': '0.10.0'})
        f = Fake(PARTS, ok=False, lines=['不符合 看不到 ~/.ssh', '隔离自检：172 项，1 项不符合'])
        ok, out = self.run_prepare(f)
        self.assertFalse(ok)
        self.assertIn('隔离自检没通过', out)
        self.assertIn('不符合 看不到 ~/.ssh', out)
        self.assertIn('sop repair', out)
        self.assertEqual(config.system()['components']['bubblewrap'], '0.10.0')
        f2 = Fake(PARTS, ok=False)
        self.assertFalse(gate(f2)[0])                   # 没过：推进流程时还会自检
        self.assertEqual(f2.tested, 1)

    def test_main_entry(self):
        """python3 -m machine.syscheck 就是 M6；用假的自检跑，过了退出码 0、登记写在临时根目录里。"""
        from tests.helpers import py
        fake = self.tmp / 'fake-selftest'
        fake.write_text(f'#!{sys.executable}\nprint("隔离自检：3 项，0 项不符合")\n')
        fake.chmod(0o755)
        p = py('import runpy; runpy.run_module("machine.syscheck", run_name="__main__")', env={'SOP_SELFTEST_CMD': str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('隔离自检通过（3 项，0 项不符合）', p.stdout)
        self.assertTrue((paths.config_dir() / 'system.json').exists())
