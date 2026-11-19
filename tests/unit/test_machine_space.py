"""3-05：体检的剩余空间（W39）和系统组件版本登记（设计书 4.3、4.5）。用造出来的数和临时目录测，不碰这台电脑的磁盘和系统文件。"""
import json
import os
import pathlib
import subprocess
import unittest
from types import SimpleNamespace

from kernel import paths
from machine import components, config, space
from tests.helpers import TempHome, mock_env

GB = space.GB


def vfs(free_gb, total_gb=100, reserved_gb=0, frsize=4096):
    """造一个 statvfs 的结果：f_bavail 是普通用户能用的，f_bfree 还含留给管理员的那一块。"""
    blk = lambda g: int(g * GB) // frsize
    return SimpleNamespace(f_frsize=frsize, f_blocks=blk(total_gb), f_bavail=blk(free_gb), f_bfree=blk(free_gb + reserved_gb))


def fake_statvfs(table):
    def statvfs(path):
        v = table[path]
        if isinstance(v, OSError):
            raise v
        return v
    return statvfs


class FakeFindmnt:
    def __init__(self, sources, fail=False):
        self.sources, self.fail = sources, fail

    def __call__(self, cmd, **kw):
        assert cmd[0] == 'findmnt', cmd
        if self.fail:
            raise FileNotFoundError(cmd[0])
        src = self.sources[cmd[-1]]
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'filesystems': [{'target': cmd[-1], 'source': src}]}), '')


class TestSpace(unittest.TestCase):
    def test_two_filesystems_enough(self):
        s = space.check('/home/u', statvfs=fake_statvfs({'/': vfs(50), '/home/u': vfs(300, 500)}), same=False)
        self.assertEqual([(x.which, x.path, x.minimum) for x in s], [('system', '/', 10 * GB), ('home', '/home/u', 20 * GB)])
        self.assertFalse(space.any_low(s))
        text = space.describe(s)
        self.assertIn('系统盘（/）还剩 50.0 GB（共 100.0 GB），够用（低于 10 GB 时提醒）', text)
        self.assertIn('主目录所在的分区（/home/u）还剩 300.0 GB', text)
        self.assertNotIn('sop machine clean', text)

    def test_system_low(self):
        """系统盘剩 9.9 GB：提醒，指向 sop machine clean；主目录那边够用，不提醒。"""
        s = space.check('/home/u', statvfs=fake_statvfs({'/': vfs(9.9), '/home/u': vfs(300, 500)}), same=False)
        self.assertEqual([x.low for x in s], [True, False])
        text = space.describe(s)
        self.assertIn('要注意：系统盘（/）只剩 9.9 GB（共 100.0 GB），低于 10 GB 的提醒线', text)
        self.assertIn('进不了桌面', text)
        self.assertIn('sop machine clean', text)
        self.assertEqual(text.count('sop machine clean'), 1)

    def test_home_low(self):
        """主目录分区剩 19 GB：按 20 GB 的线提醒；系统盘剩 12 GB 够用（它的线是 10 GB）。"""
        s = space.check('/home/u', statvfs=fake_statvfs({'/': vfs(12), '/home/u': vfs(19, 500)}), same=False)
        self.assertEqual([x.low for x in s], [False, True])
        self.assertIn('主目录这边满了', space.describe(s))

    def test_same_filesystem_uses_20(self):
        """系统和主目录是同一个分区（第二、三种电脑）：只报一行，按 20 GB。剩 15 GB 在 10 GB 的线上不提醒，这里要提醒。"""
        s = space.check('/home/u', statvfs=fake_statvfs({'/home/u': vfs(15)}), same=True)
        self.assertEqual([(x.which, x.minimum) for x in s], [('both', 20 * GB)])
        self.assertTrue(space.any_low(s))
        self.assertIn('系统盘（主目录也在上面）（/home/u）只剩 15.0 GB', space.describe(s))

    def test_boundary_and_reserved(self):
        """正好等于提醒线不提醒；剩余按普通用户能用的算，留给管理员的那一块不算。"""
        s = space.check('/h', statvfs=fake_statvfs({'/': vfs(10, frsize=1000), '/h': vfs(19.9, reserved_gb=5)}), same=False)
        self.assertEqual(s[0].free, 10 * GB)
        self.assertEqual([x.low for x in s], [False, True])

    def test_cannot_read(self):
        s = space.check('/h', statvfs=fake_statvfs({'/': vfs(50), '/h': PermissionError(13, '权限不够')}), same=False)
        self.assertIsNone(s[1].free)
        self.assertFalse(s[1].low)
        self.assertIn('主目录所在的分区（/h）剩多少空间查不出来（权限不够）', space.describe(s))

    def test_same_filesystem_judgement(self):
        st = lambda devs: (lambda p: SimpleNamespace(st_dev=devs[p]))
        none = FakeFindmnt({})
        self.assertTrue(space.same_filesystem('/', '/home/u', run=none, stat=st({'/': 5, '/home/u': 5})))
        # btrfs：每个子卷的设备号不一样，来源名去掉子卷后缀是同一个 → 同一个
        btrfs = FakeFindmnt({'/': '/dev/vda2[/@]', '/home/u': '/dev/vda2[/@home]'})
        self.assertTrue(space.same_filesystem('/', '/home/u', run=btrfs, stat=st({'/': 30, '/home/u': 31})))
        # 加密加两个逻辑卷：底下是同一个分区，但是两个文件系统，各按各的线
        lvs = FakeFindmnt({'/': '/dev/mapper/vg-root', '/home/u': '/dev/mapper/vg-home'})
        self.assertFalse(space.same_filesystem('/', '/home/u', run=lvs, stat=st({'/': 1, '/home/u': 2})))
        # 查不出来：按不是同一个，两行都报，不会少报
        self.assertFalse(space.same_filesystem('/', '/home/u', run=FakeFindmnt({}, fail=True), stat=st({'/': 1, '/home/u': 2})))

        def gone(p):
            raise FileNotFoundError(p)
        self.assertFalse(space.same_filesystem('/', '/nowhere', run=none, stat=gone))

    def test_this_computer_read_only(self):
        """在跑测试的这台电脑上只读地查一遍：系统盘和主目录都查得出来。"""
        s = space.check()
        self.assertIn(len(s), (1, 2))
        self.assertTrue(all(x.free is not None and x.total >= x.free for x in s))
        self.assertTrue(space.describe(s))


class FakeRun:
    """假的 bwrap、dpkg-query：记下跑了哪些命令。"""

    def __init__(self, bwrap='bubblewrap 0.11.1', pkg='0.11.1-1ubuntu0.3'):
        self.bwrap, self.pkg, self.calls = bwrap, pkg, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[0])
        out = {'bwrap': self.bwrap, 'dpkg-query': self.pkg}[cmd[0]]
        if out is None:
            raise FileNotFoundError(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, out, '')


def uname(release='7.0.0-43-generic', version='#43-Ubuntu SMP PREEMPT_DYNAMIC Fri Oct 23 13:25:25 UTC 2026'):
    return lambda: SimpleNamespace(release=release, version=version)


class TestComponents(TempHome):
    def setUp(self):
        super().setUp()
        self.tools = self.tmp / 'tools'
        self.tools.mkdir()
        self._tenv = mock_env({'SOP_TOOLS_DIR': str(self.tools)})
        self._tenv.__enter__()
        self.aa = self.tmp / 'apparmor.d'
        (self.aa / 'local').mkdir(parents=True)
        self.proc = self.tmp / 'proc-sys'
        for f, v in ((components.RESTRICT, '1'), (components.TIOCSTI, '0')):
            (self.proc / f).parent.mkdir(parents=True, exist_ok=True)
            (self.proc / f).write_text(v + '\n')
        (self.aa / components.BWRAP_RULE).write_text('profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }\n')
        self.rule = self.aa / components.docker_rule_name()
        self.rule.write_text(f'"{components.rootlesskit_path()}" flags=(unconfined) {{\n  userns,\n}}\n')
        self.run = FakeRun()

    def tearDown(self):
        self._tenv.__exit__(None, None, None)
        super().tearDown()

    def now(self, **kw):
        return components.collect(run=kw.get('run', self.run), uname=kw.get('uname', uname()), apparmor=self.aa, proc_sys=self.proc)

    def test_collect_and_record(self):
        c = self.now()
        self.assertEqual(set(c), set(config.SYSTEM_PARTS))
        self.assertEqual(c['kernel'], '7.0.0-43-generic #43-Ubuntu SMP PREEMPT_DYNAMIC Fri Oct 23 13:25:25 UTC 2026')
        self.assertEqual(c['bubblewrap'], '0.11.1 (package 0.11.1-1ubuntu0.3)')
        self.assertTrue(c['userns_rule'].startswith(components.docker_rule_name() + ' '))
        self.assertRegex(c['userns_policy'], r'^restrict=1 bwrap-userns-restrict=[0-9a-f]{12}$')
        self.assertEqual(c['tiocsti'], '0')
        self.assertEqual(self.run.calls, ['bwrap', 'dpkg-query'])   # 只跑了两条只读的命令
        self.assertEqual(len(config.system_changes(c)), len(config.SYSTEM_PARTS))   # 还没登记过
        self.assertIn('还没登记过', components.describe(c, config.system_changes(c)))
        components.record(c)
        self.assertEqual(config.system_changes(self.now()), [])
        self.assertEqual(oct((paths.config_dir() / 'system.json').stat().st_mode & 0o777), '0o600')
        text = components.describe(c, [])
        for want in ('系统内核：7.0.0-43-generic。', 'bubblewrap（受限环境用的）：0.11.1。',
                     f'那条系统规则：有（{components.docker_rule_name()}）', '限制普通用户建隔离空间：开着', '往终端塞按键：已禁用'):
            self.assertIn(want, text)
        self.assertNotIn('不一样', text)

    def test_every_change_is_seen(self):
        """系统升级会动的每一样，变了都看得出来，而且只报变了的那一样。"""
        components.record(self.now())

        def changed(**kw):
            return [k for k, _, _ in config.system_changes(self.now(**kw))]
        self.assertEqual(changed(uname=uname(release='7.0.0-44-generic')), ['kernel'])
        self.assertEqual(changed(uname=uname(version='#43-Ubuntu SMP PREEMPT_DYNAMIC Sat Nov 7 10:00:00 UTC 2026')), ['kernel'])
        self.assertEqual(changed(run=FakeRun(pkg='0.11.1-1ubuntu0.4')), ['bubblewrap'])   # 只打了安全补丁
        self.assertEqual(changed(run=FakeRun(bwrap='bubblewrap 0.12.0', pkg='0.12.0-1')), ['bubblewrap'])
        steps = [
            (lambda: self.rule.write_text(self.rule.read_text() + '# 改了一行\n'), 'userns_rule'),
            (lambda: (self.aa / 'local' / self.rule.name).write_text('owner /tmp/** rw,\n'), 'userns_rule'),
            (lambda: (self.proc / components.RESTRICT).write_text('0\n'), 'userns_policy'),
            (lambda: (self.aa / components.BWRAP_RULE).write_text('改了\n'), 'userns_policy'),
            (lambda: (self.proc / components.TIOCSTI).write_text('1\n'), 'tiocsti'),
        ]
        for act, part in steps:
            act()
            self.assertEqual(changed(), [part])
            components.record(self.now())
        text = components.describe(self.now(), [('tiocsti', '0', '1')])
        self.assertIn('要注意：往终端塞按键没有禁用', text)
        self.assertIn('和上次登记的不一样：往终端塞按键的开关', text)
        self.assertIn('先重跑隔离自检', text)

    def test_missing_things(self):
        """没装 bubblewrap、没有 dpkg、还没装免管理员 Docker、老内核没有塞按键的开关、系统没有限制开关。"""
        self.rule.unlink()
        (self.proc / components.TIOCSTI).unlink()
        (self.proc / components.RESTRICT).unlink()
        (self.aa / components.BWRAP_RULE).unlink()
        c = self.now(run=FakeRun(bwrap=None, pkg=None))
        self.assertEqual((c['bubblewrap'], c['userns_rule'], c['tiocsti']), ('missing', 'missing', 'missing'))
        self.assertEqual(c['userns_policy'], 'restrict=missing bwrap-userns-restrict=missing')
        self.assertEqual(self.now(run=FakeRun(pkg=None))['bubblewrap'], '0.11.1')
        text = components.describe(c)
        self.assertIn('bubblewrap（受限环境用的）：没装', text)
        self.assertIn('那条系统规则：还没有', text)
        self.assertIn('没有禁用「往终端塞按键」的开关', text)
        self.assertIn('系统没有「限制普通用户建隔离空间」这个开关', text)
        config.record_system(c)   # 「没有」也照样记，装上之后就看得出变了
        self.assertEqual(config.system_changes(c), [])

    def test_rule_name_follows_real_path(self):
        """规则按 rootlesskit 的真实路径起名（官方安装脚本的起名办法）；工具目录是链接时解开。"""
        with mock_env({'SOP_TOOLS_DIR': '/home/xiaobai/tools'}):
            self.assertEqual(components.docker_rule_name(), 'home.xiaobai.tools.docker.bin.rootlesskit')
        link = self.tmp / 'tools-link'
        link.symlink_to(self.tools)
        with mock_env({'SOP_TOOLS_DIR': str(link)}):
            self.assertEqual(components.rootlesskit_path(), os.path.realpath(self.tools / 'docker/bin/rootlesskit'))

    def test_this_computer_read_only(self):
        """在跑测试的这台电脑上只读地查一遍：五样都有值；记进的是临时根目录，不是真的 ~/tools/sop/config。"""
        with mock_env({'SOP_TOOLS_DIR': os.path.expanduser('~/tools')}):
            c = components.collect()
        self.assertEqual(set(c), set(config.SYSTEM_PARTS))
        self.assertTrue(all(isinstance(v, str) and v for v in c.values()))
        self.assertTrue(c['kernel'].startswith(os.uname().release))
        components.record(c)
        self.assertTrue(str(paths.config_dir()).startswith(str(self.tmp)))
        self.assertEqual(config.system_changes(c), [])


if __name__ == '__main__':
    unittest.main()
