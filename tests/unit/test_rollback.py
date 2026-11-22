"""sop self rollback（7.11、16.5 第 2 条，3-43）：版本栈、项目外面用的版本（versions/latest）退回上一个、中途断了不留坏指向。

项目里的退回（改主线 sop.json、走 PR、功能进行中大版本被拒）在流程沙箱 tests/sandbox/test_rollback.py。
这里在临时 SOP_HOME 里现造几个「版本目录」（各是一个 Git 仓库，提交编号就是目录名），经真的启动器执行，看用的是哪一个。
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import types
from unittest import mock

from kernel import version
from kernel.errors import SopError
from kernel.gitx import Git
from tests.helpers import REPO, TempHome, sh


def make_version(vers, label, flows_extra=''):
    """造一个装好的版本目录：kernel/main.py 打出自己的名字，launcher.py 用真的（末尾加一行注释，各版本内容不同）。返回提交编号。"""
    build = vers.parent / f'build-{label}'
    (build / 'kernel').mkdir(parents=True)
    (build / 'kernel' / 'main.py').write_text(f'import sys\nprint("我是版本 {label}", *sys.argv[1:])\n')
    (build / 'kernel' / 'launcher.py').write_text((REPO / 'kernel' / 'launcher.py').read_text() + f'# {label}\n')
    shutil.copytree(REPO / 'flows', build / 'flows')
    if flows_extra:
        (build / 'flows' / 'ticket.toml').write_text((build / 'flows' / 'ticket.toml').read_text() + flows_extra)
    sh('git', 'init', '-q', build)
    sh('git', '-C', build, 'add', '-A')
    sh('git', '-C', build, 'commit', '-qm', label)
    v = sh('git', '-C', build, 'rev-parse', 'HEAD')
    vers.mkdir(parents=True, exist_ok=True)
    os.rename(build, vers / v)
    return v


class TestStack(TempHome):
    def test_stack(self):
        self.assertEqual(version.stack([]), [])
        self.assertEqual(version.stack(['A', 'A', 'B']), ['A', 'B'])
        self.assertEqual(version.stack(['A', 'B', 'C']), ['A', 'B', 'C'])
        self.assertEqual(version.stack(['A', 'B', 'A']), ['A'])              # 退回过的 B 不再算「上一个」
        self.assertEqual(version.stack(['A', 'B', 'C', 'B']), ['A', 'B'])
        self.assertEqual(version.stack(['A', 'B', 'A', 'C']), ['A', 'C'])

    def test_project_versions_from_main_history(self):
        """项目的版本栈按主线 sop.json 的历史：A→B→退回 A→C，改了别的字段不算换版本。"""
        repo = self.tmp / 'proj'
        sh('git', 'init', '-q', '-b', 'main', repo)
        for v, vis in (('A', 'public'), ('A', 'private'), ('B', 'private'), ('A', 'private'), ('C', 'private')):
            (repo / 'sop.json').write_text(json.dumps({'toolkit': {'repo': 'x', 'version': v}, 'visibility': vis}))
            (repo / 'other').write_text(v + vis)
            sh('git', '-C', repo, 'add', '-A'); sh('git', '-C', repo, 'commit', '-qm', v)
        sh('git', '-C', repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        p = types.SimpleNamespace(git=Git(repo / '.git'))
        self.assertEqual(version.project_versions(p), ['A', 'C'])


class TestMachineRollback(TempHome):
    def setUp(self):
        super().setUp()
        self.vers = self.home / 'versions'
        self.v1 = make_version(self.vers, 'v1')
        self.v2 = make_version(self.vers, 'v2')
        version.write_launcher(self.v1)      # 第零步装的
        version.write_launcher(self.v2)      # 后来 sop self install 装的
        self.outside = self.tmp / 'outside'
        self.outside.mkdir()

    def run_sop(self, *args):
        """经真的启动器（~/tools/sop/sop → launcher.py → versions/latest）执行，不在项目里。"""
        return subprocess.run([str(self.home / 'sop'), *args], cwd=self.outside, capture_output=True, text=True,
                              env={**os.environ, 'SOP_PYTHON': sys.executable})

    def rollback(self):
        out = []
        with mock.patch('builtins.print', lambda *a, **k: out.append(' '.join(map(str, a)))):
            try:
                rc = version.rollback([], str(self.outside))
            except SopError as e:
                return 1, str(e)
        return rc, '\n'.join(out)

    def latest(self):
        return (self.vers / 'latest').read_text()

    def test_rollback_switches_launcher(self):
        self.assertIn('我是版本 v2', self.run_sop('machine', 'tools').stdout)
        rc, out = self.rollback()
        self.assertEqual(rc, 0, out)
        self.assertIn(f'从 {self.v2[:8]} 退回到 {self.v1[:8]}', out)
        self.assertEqual(self.latest(), self.v1)
        self.assertTrue((self.home / 'launcher.py').read_text().endswith('# v1\n'))
        r = self.run_sop('machine', 'tools')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('我是版本 v1 machine tools', r.stdout)       # 退回之后 sop 用的是旧版本
        self.assertEqual(sorted(p.name for p in self.home.iterdir() if p.name.startswith('.')), [])
        self.assertEqual(sorted(p.name for p in self.vers.iterdir() if p.name.startswith('.')), [])   # 没留临时文件
        # v2 是因为有毛病才退掉的：再退就说没有上一个了，什么都不改
        rc, out = self.rollback()
        self.assertEqual(rc, 1)
        self.assertIn('没有上一个版本可以退', out)
        self.assertEqual(self.latest(), self.v1)
        # 之后装了修好的 v3，再退回到的是 v1（不是退掉的 v2）
        v3 = make_version(self.vers, 'v3')
        version.write_launcher(v3)
        self.assertEqual(self.rollback()[0], 0)
        self.assertEqual(self.latest(), self.v1)

    def test_no_previous(self):
        shutil.rmtree(self.home / 'versions' / self.v2)
        (self.vers / 'history').unlink(); (self.vers / 'latest').unlink()
        version.write_launcher(self.v1)      # 只装过这一个
        rc, out = self.rollback()
        self.assertEqual(rc, 1)
        self.assertIn(f'项目外面一直用的就是现在这个工具包版本 {self.v1[:8]}', out)
        # 一个版本都没装
        (self.vers / 'latest').unlink(); (self.vers / 'history').unlink()
        rc, out = self.rollback()
        self.assertEqual(rc, 1)
        self.assertIn('还没有安装任何工具包版本', out)

    def test_history_starts_with_old_latest(self):
        """有 history 之前就装着的版本（3-43 之前第零步装的）也退得回去；同一个版本重复写不改历史。"""
        (self.vers / 'history').unlink()
        (self.vers / 'latest').write_text(self.v1)
        version.write_launcher(self.v2)
        self.assertEqual((self.vers / 'history').read_text().split(), [self.v1, self.v2])
        h = self.vers / 'history'
        os.utime(h, (1_000_000_000, 1_000_000_000))
        version.write_launcher(self.v2)
        self.assertEqual(h.stat().st_mtime, 1_000_000_000)
        self.assertEqual(self.rollback()[0], 0)
        self.assertEqual(self.latest(), self.v1)

    def test_previous_not_usable_refused(self):
        """上一个版本不在、不完整、被改过、不是那个提交：都拒绝，latest 和启动器一点不动（不会指向不能用的版本）。"""
        d1 = self.vers / self.v1
        before = {f: (self.home / f).read_bytes() for f in ('sop', 'launcher.py', 'versions/latest', 'versions/history')}

        def same():
            for f, b in before.items():
                self.assertEqual((self.home / f).read_bytes(), b, f)
            self.assertIn('我是版本 v2', self.run_sop().stdout)

        def moved():
            os.rename(d1, self.tmp / 'away')
            return lambda: os.rename(self.tmp / 'away', d1)

        def incomplete():
            os.rename(d1 / 'kernel' / 'main.py', self.tmp / 'main.py')
            return lambda: os.rename(self.tmp / 'main.py', d1 / 'kernel' / 'main.py')

        def edited():
            f = d1 / 'flows' / 'ticket.toml'
            old = f.read_text()
            f.write_text(old + '# 被改过\n')
            return lambda: f.write_text(old)

        def other_commit():
            sh('git', '-C', d1, 'commit', '-q', '--allow-empty', '-m', '另一个提交')
            return lambda: sh('git', '-C', d1, 'reset', '-q', '--hard', self.v1)

        for name, breaker, want in (('不在', moved, '本机没有装这个版本'), ('不完整', incomplete, '不完整'),
                                    ('被改过', edited, '被改过'), ('不是那个提交', other_commit, '不是这个版本')):
            with self.subTest(name):
                undo = breaker()
                try:
                    rc, out = self.rollback()
                    self.assertEqual(rc, 1)
                    self.assertIn(want, out)
                    self.assertIn('什么都没改', out)
                    same()
                finally:
                    undo()
        self.assertEqual(self.rollback()[0], 0)

    def test_interrupted_never_points_to_missing_version(self):
        """退回到一半断了（每个文件换名的那一下、写临时文件的那一下各断一次）：latest 指的一定是装好的完整版本，sop 照样能用；
        再执行一次 sop self rollback 能接着退好。"""
        def fresh():
            version.write_launcher(self.v1); version.write_launcher(self.v2)
            (self.vers / 'history').write_text(f'{self.v1}\n{self.v2}\n')

        real_replace, real_fsync, real_open = os.replace, os.fsync, io.open
        home = str(self.home)

        class Half:
            """写到一半断电：只写进前一半就出错。"""
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *e):
                self.fh.close()
                return False

            def write(self, text):
                self.fh.write(text[:len(text) // 2])
                self.fh.flush()
                raise OSError('模拟断电：写到一半')

        for where in ('replace', 'fsync', 'half'):
            for k in range(1, 4):
                with self.subTest(where=where, k=k):
                    fresh()
                    calls = []

                    def boom(real):
                        def f(*a, **kw):
                            calls.append(a)
                            if len(calls) == k:
                                raise OSError('模拟断电')
                            return real(*a, **kw)
                        return f

                    def half_open(file, mode='r', *a, **kw):
                        fh = real_open(file, mode, *a, **kw)
                        if 'w' in mode and str(file).startswith(home):
                            calls.append(file)
                            if len(calls) == k:
                                return Half(fh)
                        return fh
                    if where == 'half':     # 写文件的那一下断（不管是写临时文件还是直接写正式文件，都拦得到）
                        ctx = contextlib.ExitStack()
                        ctx.enter_context(mock.patch('io.open', half_open))
                        ctx.enter_context(mock.patch('builtins.open', half_open))
                    else:
                        ctx = mock.patch(f'kernel.version.os.{where}', boom(real_replace if where == 'replace' else real_fsync))
                    with ctx:
                        try:
                            self.rollback()
                        except OSError:
                            pass
                    self.assertEqual(len(calls), k, '没断在想断的地方')
                    for d in (self.home, self.vers):     # 断了也不留临时文件
                        self.assertEqual([x.name for x in d.iterdir() if x.name.startswith('.')], [], d)
                    cur = self.latest()
                    self.assertIn(cur, (self.v1, self.v2))
                    self.assertEqual(version.installed_ok(cur)[0], self.vers / cur)
                    r = self.run_sop()
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn('我是版本 v', r.stdout)
                    # 接着退：结果和没断过一样
                    if cur == self.v2:
                        self.assertEqual(self.rollback()[0], 0)
                    self.assertEqual(self.latest(), self.v1)
                    self.assertIn('我是版本 v1', self.run_sop().stdout)
                    self.assertIn('没有上一个版本可以退', self.rollback()[1])

    def test_major_allowed_outside_project(self):
        """项目外面没有「进行中的功能」，7.11 只在功能进行中挡大版本：流程定义不一样也能退。"""
        v3 = make_version(self.vers, 'v3', flows_extra='\n# 大版本\n')
        version.write_launcher(v3)
        self.assertEqual(version.classify(self.vers / self.v2, self.vers / v3), 'major')
        self.assertEqual(self.rollback()[0], 0)
        self.assertEqual(self.latest(), self.v2)

    def test_usage(self):
        with mock.patch('builtins.print'):
            self.assertEqual(version.rollback(['x'], str(self.outside)), 2)
        self.assertEqual(self.latest(), self.v2)

