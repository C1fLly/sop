"""流程沙箱：工具包的修补版在功能进行中换上（7.11、W18、16.5）；大版本被拒。

工具包的错：初始版本的门禁命令表写错了（gate-full 指向不存在的脚本），F15 一跑就崩。
修补版只改了档案的命令表（脚本），流程定义和技能一字不变；大版本改了流程定义。"""
from tests.sandbox.base import F, FB, FS, SandboxCase


def broken(dest):
    p = dest / 'profiles' / 'stack' / 'fake' / 'commands.toml'
    p.write_text(p.read_text().replace('gate.py", "full"]', 'gate-typo.py", "full"]'))


def patch_fix(dest):
    pass       # 修好的：就是开发目录现在的样子


def major(dest):
    p = dest / 'flows' / 'ticket.toml'
    p.write_text(p.read_text() + '\n# 大版本：流程定义变了\n')


class TestPatchMidFeature(SandboxCase):
    tweak = staticmethod(broken)

    def test_patch_then_finish(self):
        self.start([('01', [], '无')])
        r = self.go(ok=False)
        self.assertIn(('F15', 'failed'), self.steps(FS))
        self.assertNotIn(('F15', 'done'), self.steps(FS))
        old = self.w.version
        # 大版本：有进行中的功能，被拒
        big = self.w.publish_toolkit('大版本', lambda d: major(d))
        r = self.w.sop('self', 'upgrade', big)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('不能换大版本', r.stdout)
        self.assertIn(old, self.main_file('sop.json'))
        # 修补版：换上
        fix = self.w.publish_toolkit('修补版：门禁命令表写错了')
        r = self.w.sop('self', 'upgrade', fix)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn('修补版', r.stdout)
        self.assertIn(fix, self.main_file('sop.json'))
        rel = self.w.releases(f'upgrade/{fix[:8]}-1')
        self.assertIn('sop.json', [x['path'] for x in rel])           # 升级的 PR 靠放行事件过守门检查
        # 接着做：F15 用新版本跑，做完；之前通过的步骤不重做
        r = self.go()
        self.assertFeatureDone(r)
        s = self.steps(FS)
        self.assertEqual(sum(1 for x in s if x == ('F13', 'confirm')), 1)
        self.assertIn(('F15', 'done'), s)
        self.assertIn(fix, self.main_file('sop.json'))
        # 主线是被合进功能分支的（只做合并），功能分支不是被重新建的
        self.assertEqual(sum(1 for x in s if x == ('F1', 'done')), 1)
