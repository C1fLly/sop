"""流程沙箱：系统升级后先重跑隔离自检（设计书 4.5，任务 3-07）。

演法：上次隔离自检通过时登记的 bubblewrap 是旧版本（0.10.0），现在这台电脑上是另一个版本，等于系统升级换了 bubblewrap。
隔离自检用假的（tests/fakes/selftest），它记下跑的那一刻日志分支在哪个提交，用来证明「先自检、后推进」。"""
from tests.sandbox.base import FS, SandboxCase

OLD_BWRAP = '0.10.0 (package 0.10.0-1ubuntu0.1)'


class TestSystemUpgrade(SandboxCase):
    def upgraded(self):
        """功能已经开了、还没推进；把登记里的 bubblewrap 改成旧的。返回这时日志分支的位置。"""
        self.start([('01', [], '无')])
        now = self.w.registered()['bubblewrap']
        self.assertNotEqual(now, OLD_BWRAP)
        self.w.set_registered(bubblewrap=OLD_BWRAP)
        return now, self.w.journal_tip()

    def test_selftest_first_then_advance(self):
        """bubblewrap 版本变了：先自检，自检那一刻流程一步没动；通过后记下新版本，接着把功能做完；之后不再自检。"""
        now, tip = self.upgraded()
        self.w.selftest = {'pass': True}
        r = self.go()
        out = r.stdout
        self.assertIn('受限环境用的 bubblewrap：上次是「0.10.0', out)
        self.assertLess(out.index('先重跑一遍隔离自检'), out.index('隔离自检通过（'))
        runs = self.w.selftest_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['journal_tip'], tip)          # 自检的时候日志分支还没动：先自检
        self.assertFeatureDone(r)                                # 后推进
        self.assertNotEqual(self.w.journal_tip(), tip)
        self.assertEqual(self.w.registered()['bubblewrap'], now)  # 通过了才更新登记
        # 再执行 sop：登记和现在一样，不再自检
        self.w.selftest = None                                   # 这时再自检，假的自检会报错
        r = self.go()
        self.assertNotIn('隔离自检', r.stdout)
        self.assertEqual(len(self.w.selftest_runs()), 1)

    def test_selftest_fails_then_stop(self):
        """自检不过：停下、退出码非 0、指向维修窗口，流程一步不推进，登记不改；下次 sop 还会重新自检。修好后才接着走。"""
        now, tip = self.upgraded()
        before = self.steps(FS)
        self.w.selftest = {'pass': False}
        for n in (1, 2):
            r = self.go(ok=False)
            self.assertEqual(r.returncode, 1, r.stdout[-3000:] + r.stderr[-2000:])
            self.assertIn('隔离自检没通过', r.stdout)
            self.assertIn('不符合 假的：bubblewrap 升级后，受限环境里看得到 ~/.ssh', r.stdout)
            self.assertIn('sop repair', r.stdout)
            self.assertEqual(len(self.w.selftest_runs()), n)
            self.assertEqual(self.w.journal_tip(), tip)             # 日志分支一个事件都没多
            self.assertEqual(self.steps(FS), before)
            self.assertEqual(self.w.registered()['bubblewrap'], OLD_BWRAP)
        # 看进度不自检、照常能看
        r = self.w.sop('status')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.w.selftest_runs()), 2)
        # 维修窗口修好了：再执行 sop，重新自检、通过、做完
        self.w.selftest = {'pass': True}
        r = self.go()
        self.assertEqual(len(self.w.selftest_runs()), 3)
        self.assertFeatureDone(r)
        self.assertEqual(self.w.registered()['bubblewrap'], now)
