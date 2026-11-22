"""流程沙箱：退回上一个版本（sop self rollback，7.11、16.5 第 2 条，3-43）。

- 修补版在功能进行中换上之后发现它有毛病（门禁命令表写错了，F15 一跑就崩）：退回上一个版本（也是修补版之间），
  主线 sop.json 改回旧版本，经启动器执行的 sop 用的就是旧版本，接着把功能做完；再退一次说清没有上一个版本了。
- 上一个版本只在本机已装好的里找：挪走它就说清退不回去，什么都不改。
- 上一个版本和现在的隔着大版本：有进行中的功能时被拒并说清原因；功能放弃之后可以退（7.11 只挡功能进行中）。
"""
import os

from tests.sandbox.base import FS, SandboxCase
from tests.sandbox.test_upgrade import broken, major


class TestRollbackPatchMidFeature(SandboxCase):
    def test_rollback_then_finish(self):
        good = self.w.version
        r = self.w.sop('self', 'rollback')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('没有上一个版本可以退', r.stdout)
        self.start([('01', [], '无')])
        # 出了一个「修补版」（只改了档案的命令表），换上之后 F15 崩了：它有毛病
        bad = self.w.publish_toolkit('修补版：可惜门禁命令表写错了', lambda d: broken(d))
        r = self.w.sop('self', 'upgrade', bad)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.go(ok=False)
        self.assertIn(('F15', 'failed'), self.steps(FS))
        self.assertNotIn(('F15', 'done'), self.steps(FS))
        # 上一个版本不在本机：退不回去，什么都不改
        vers = self.w.home / 'versions'
        os.rename(vers / good, vers / 'moved-away')
        r = self.w.sop('self', 'rollback')
        os.rename(vers / 'moved-away', vers / good)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('本机没有装这个版本', r.stdout)
        self.assertIn('不联网下载', r.stdout)
        self.assertIn(bad, self.main_file('sop.json'))
        # 退回：修补版之间，功能进行中也可以
        r = self.w.sop('self', 'rollback')
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn(f'上一个 {good[:8]}（修补版）', r.stdout)
        self.assertIn(f'工具包已退回到 {good[:8]}', r.stdout)
        self.assertIn(good, self.main_file('sop.json'))
        rel = self.w.releases(f'upgrade/{good[:8]}-1')                 # 和升级同一条路：靠放行事件过守门检查
        self.assertIn('sop.json', [x['path'] for x in rel])
        # 退回之后经启动器执行的 sop 用的是旧版本：F15 不再崩，功能做完；之前通过的步骤不重做
        r = self.go()
        self.assertFeatureDone(r)
        s = self.steps(FS)
        self.assertIn(('F15', 'done'), s)
        self.assertEqual(sum(1 for x in s if x == ('F1', 'done')), 1)
        self.assertEqual(sum(1 for x in s if x == ('F13', 'confirm')), 1)
        # 有毛病的那个版本是退掉的，不算「上一个」：再退就说没有了
        r = self.w.sop('self', 'rollback')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('没有上一个版本可以退', r.stdout)
        self.assertIn(good, self.main_file('sop.json'))


class TestRollbackMajorRefused(SandboxCase):
    def test_major_refused_mid_feature(self):
        old = self.w.version
        # 没有进行中的功能时换上大版本（7.11 允许）
        big = self.w.publish_toolkit('大版本', lambda d: major(d))
        r = self.w.sop('self', 'upgrade', big)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn('大版本', r.stdout)
        self.start([('01', [], '无')])
        tip = self.w.rgit('rev-parse', 'main')
        r = self.w.sop('self', 'rollback')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('大版本', r.stdout)
        self.assertIn('还在进行中，不能退', r.stdout)
        self.assertIn('sop feature drop', r.stdout)
        self.assertIn(big, self.main_file('sop.json'))
        self.assertEqual(self.w.rgit('rev-parse', 'main'), tip)           # 主线一点没动
        # 放弃功能之后，没有进行中的功能：可以退回大版本
        r = self.w.sop('feature', 'drop', '--yes')
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        r = self.w.sop('self', 'rollback')
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn(f'工具包已退回到 {old[:8]}（大版本）', r.stdout)
        self.assertIn(old, self.main_file('sop.json'))
