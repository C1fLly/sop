"""3-44：sop self check（修完工具包之后的把关，设计书 16.5 第 4 条）。

在 /tmp 里造一个小小的「工具包开发目录」：tests/run_all.py 是假的（按环境变量 FAKE_FAIL 让某几样没过，把收到的参数记下来），
复查用假的 claude（tests/fakes/claude/claude，fake://reject 等几种），在真的受限环境（bubblewrap）里跑；隔离自检换成假的。
不花钱、不连网、不起专用 Docker。真的调 AI 复查在 tests/real_ai/selfcheck_review.py，手动跑。
"""
import json
import os
import pathlib
import re
import shutil
import sys
from unittest import mock

from adapters.ai.claude import adapter as C
from kernel import selfcheck as S
from kernel.errors import SopError
from machine import config
from tests.helpers import REPO, TempHome, mock_env, sh

FAKE_CLAUDE = REPO / 'tests' / 'fakes' / 'claude' / 'claude'
TOKEN = 'fake-token-3-44-abcdefgh'

FAKE_RUN_ALL = r'''import os, sys, pathlib
args = sys.argv[1:]
part = [a for a in args if a != '--no-skip'][0]
with open(os.environ['FAKE_CALLS'], 'a') as fh:
    fh.write(' '.join(args) + '\n')
if os.environ.get('FAKE_TOUCH') == part:
    pathlib.Path('README.md').write_text('检查的时候又改了\n')
if part in os.environ.get('FAKE_FAIL', '').split():
    print({'unit': 'FAIL: test_x (tests.unit.test_y.T.test_x)\nFAILED (failures=1)',
           'sandbox': 'ERROR: test_happy (tests.sandbox.test_happy.H)\n有 1 项被跳过（--no-skip 算没通过）：',
           'checks': '不符合 doc_refs/bad：退出码 0（应为 1）\n总检查：3 个样例，1 个不合格：doc_refs',
           'docs': '章节 3 个，编号 0 个；悬空的引用 0 处\n  悬空： README.md：`nope/`'}[part])
    print('有没通过的')
    sys.exit(1)
print({'unit': 'Ran 3 tests\n\nOK', 'sandbox': 'Ran 2 tests\n\nOK', 'checks': '总检查：3 个样例，0 个不合格', 'docs': '悬空的引用 0 处'}[part])
print('全部通过')
'''


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / 'dev'
        (self.repo / 'tests').mkdir(parents=True)
        (self.repo / 'kernel').mkdir()
        (self.repo / 'runner').mkdir()
        (self.repo / 'tests' / 'run_all.py').write_text(FAKE_RUN_ALL)
        (self.repo / 'kernel' / 'commands.py').write_text('DONE = {}\n')
        (self.repo / 'kernel' / 'steps.py').write_text('def f():\n    return 1\n')
        (self.repo / 'runner' / 'x.py').write_text('X = 1\n')
        (self.repo / 'README.md').write_text('工具包\n')
        (self.repo / '.gitignore').write_text('*.log\n')
        sh('git', 'init', '-q', '-b', 'main', self.repo)
        sh('git', 'add', '-A', cwd=self.repo)
        sh('git', 'commit', '-qm', '起点', cwd=self.repo)
        self.calls = self.tmp / 'calls.txt'
        self._e2 = mock_env({'FAKE_CALLS': str(self.calls), 'FAKE_FAIL': '', 'FAKE_TOUCH': ''})
        self._e2.__enter__()
        self.exe = self.tmp / 'bin' / 'claude'
        self.exe.parent.mkdir()
        shutil.copy(FAKE_CLAUDE, self.exe)
        self.creds('ok')
        self.reviews = 0
        # 锁换成这个测试自己的：外面的 sop self check 正拿着真的那把锁跑全部自测（含这些测试），用同一把会一直等下去（3-44 实测）
        self._lock = mock.patch.object(S, 'LOCK', self.tmp / 'selfcheck.lock')
        self._lock.start()

    def tearDown(self):
        self._lock.stop()
        self._e2.__exit__(None, None, None)
        super().tearDown()

    def creds(self, mode):
        d = config.paths.config_dir() / 'ai'
        d.mkdir(parents=True, exist_ok=True)
        f = d / 'claude.env'
        f.write_text(f'ANTHROPIC_BASE_URL="fake://{mode}"\nANTHROPIC_AUTH_TOKEN={TOKEN}\n')
        os.chmod(f, 0o600)

    def change(self, rel='README.md', text='工具包（改过）\n'):
        f = self.repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def adapter(self):
        a = C.ClaudeAdapter(exe=self.exe)
        real = a.run_headless

        def counted(*args, **kw):
            self.reviews += 1
            return real(*args, **kw)
        a.run_headless = counted
        return a

    def check(self, **kw):
        lines = []
        r = S.run(self.repo, adapter=self.adapter(), out=lines.append, **kw)
        self.addCleanup(shutil.rmtree, r['logdir'], True)
        r['lines'] = lines
        return r


class Passes(Base):
    def test_all_good(self):
        self.change()
        r = self.check()
        self.assertTrue(r['passed'], r)
        self.assertEqual(r['verdict'], '过了')
        self.assertEqual([i['name'] for i in r['items']], ['单元测试', '流程沙箱', '总检查', '文档检查', '复查'])
        self.assertEqual(self.calls.read_text().splitlines(), ['--no-skip unit', '--no-skip sandbox', 'checks', 'docs'])
        self.assertEqual(self.reviews, 1)
        self.assertAlmostEqual(r['cost_usd'], 0.0123)
        self.assertEqual(r['files'], ['README.md'])
        rep = json.loads((pathlib.Path(r['logdir']) / 'report.json').read_text())
        self.assertEqual(rep['verdict'], '过了')
        self.assertIn('单元测试：通过（3 项）', '\n'.join(r['lines']))
        self.assertIn('总检查：通过（3 个样例）', '\n'.join(r['lines']))

    def test_cli_last_line_is_verdict(self):
        self.change()
        out = []
        with mock.patch.object(S, 'run', lambda *a, **k: {'passed': True, 'verdict': '过了', 'cost_usd': 0.5, 'logdir': '/tmp/x'}), \
                mock.patch('builtins.print', lambda *a, **k: out.append(' '.join(map(str, a)))):
            self.assertEqual(S.cli(['--repo', str(self.repo)]), 0)
        self.assertEqual(out[-1], '过了')
        self.assertIn('复查花了 0.5000 美元', out)
        with mock.patch('builtins.print', lambda *a, **k: out.append(' '.join(map(str, a)))):
            self.assertEqual(S.cli(['--bogus']), 2)
            self.assertEqual(S.cli(['--repo']), 2)


class ChecksFail(Base):
    def test_each_check_failure_is_caught(self):
        want = {'unit': ('单元测试', 'FAIL: test_x'), 'sandbox': ('流程沙箱', '被跳过'),
                'checks': ('总检查', '不符合 doc_refs/bad'), 'docs': ('文档检查', '悬空： README.md')}
        self.change()
        for part, (label, key) in want.items():
            with self.subTest(part=part), mock_env({'FAKE_FAIL': part}):
                self.reviews = 0
                r = self.check()
                self.assertFalse(r['passed'])
                self.assertTrue(r['verdict'].startswith('没过，卡在哪：'), r['verdict'])
                self.assertIn(f'{label}没过', r['verdict'])
                self.assertIn(key, '\n'.join(r['lines']))
                self.assertEqual(self.reviews, 0, '前面没过就不复查')
                self.assertNotIn('复查', r['verdict'].split('：', 1)[1], '没做的复查不算「卡在哪」')

    def test_all_four_run_even_if_first_fails(self):
        self.change()
        with mock_env({'FAKE_FAIL': 'unit docs'}):
            r = self.check()
        self.assertEqual(len(self.calls.read_text().splitlines()), 4)
        self.assertIn('单元测试没过', r['verdict'])
        self.assertIn('文档检查没过', r['verdict'])

    def test_one_at_a_time(self):
        """同一台电脑上同时只跑一个把关（两份全部自测同时跑会互相干扰）：锁被占着时等，放开后接着跑。"""
        import fcntl
        import threading
        import time
        self.change()
        fd = os.open(S.LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        got, lines = {}, []
        t = threading.Thread(target=lambda: got.update(r=S.run(self.repo, adapter=self.adapter(), out=lines.append)))
        t.start()
        time.sleep(1)
        self.assertFalse(self.calls.exists(), '锁被占着时不该开始跑检查')
        self.assertIn('另一个把关正在跑', ' '.join(lines))
        os.close(fd)
        t.join(60)
        shutil.rmtree(got['r']['logdir'], True)
        self.assertTrue(got['r']['passed'], got['r']['verdict'])

    def test_no_change(self):
        r = self.check()
        self.assertFalse(r['passed'])
        self.assertIn('没有任何改动', r['verdict'])
        self.assertFalse(self.calls.exists())

    def test_change_during_check(self):
        self.change()
        with mock_env({'FAKE_TOUCH': 'sandbox'}):
            r = self.check()
        self.assertFalse(r['passed'])
        self.assertIn('改动又变了', r['verdict'])


class Review(Base):
    def test_reject(self):
        self.change()
        self.creds('reject')
        r = self.check()
        self.assertFalse(r['passed'])
        self.assertIn('复查有问题：假的问题：删掉了一个测试', r['verdict'])

    def test_unreadable_is_not_a_pass(self):
        self.change()
        for mode, key in (('mangled', '不是 JSON'), ('noreview', '没写结果文件'), ('iserror', '没做完'),
                          ('garbage', '没做完'), ('quota', '余额不足')):
            with self.subTest(mode=mode):
                self.creds(mode)
                r = self.check()
                self.assertFalse(r['passed'], mode)
                self.assertIn('复查', r['verdict'])
                self.assertIn(key, r['verdict'])

    def test_no_claude(self):
        self.change()
        lines = []
        r = S.run(self.repo, adapter=C.ClaudeAdapter(exe=self.tmp / 'nope' / 'claude'), out=lines.append)
        shutil.rmtree(r['logdir'], True)
        self.assertFalse(r['passed'])
        self.assertIn('复查', r['verdict'])

    def test_taskpack_and_readonly_placement(self):
        """复查用只读放法；任务包里有 diff、改了哪些文件、固定格式；小项目里是改动之后的样子（含新文件，不含被忽略的）。"""
        self.change('runner/x.py', 'X = 2\n')
        self.change('kernel/new.py', 'Y = 1\n')
        self.change('junk.log', '被忽略\n')
        self.change(S.DRILL, 'print("演练")\n')
        seen = {}

        def fake(ctx, taskpack, st, timeout=None, budget=None):
            tp = pathlib.Path(taskpack)
            seen.update(kind=ctx.kind, budget=budget, task=(tp / 'task.md').read_text(), diff=(tp / 'change.diff').read_text(),
                        files=(tp / 'files.txt').read_text(), x=(ctx.chdir / 'runner' / 'x.py').read_text(),
                        new=(ctx.chdir / 'kernel' / 'new.py').exists(), junk=(ctx.chdir / 'junk.log').exists())
            (ctx.out_dir / 'review.json').write_text(json.dumps({'结论': '通过', '理由': ['看过了'], '问题': []}))
            return C.Outcome(rc=0, cost=0.01, session='s', logs=[], text='好', cost_basis='工具报告')
        a = C.ClaudeAdapter(exe=self.exe)
        a.run_headless = fake
        r = S.run(self.repo, isolation=True, adapter=a, selftest=lambda repo: (True, ['隔离自检：1 项，0 项不符合']),
                  out=lambda *x: None)
        shutil.rmtree(r['logdir'], True)
        self.assertEqual(seen['kind'], 'readonly')
        self.assertEqual(seen['budget'], S.REVIEW_BUDGET)
        self.assertIn('"结论": "通过" 或 "有问题"', seen['task'])
        self.assertIn('请格外仔细看：隔离：runner/x.py', seen['task'])
        self.assertIn('+X = 2', seen['diff'])
        self.assertIn('+Y = 1', seen['diff'])
        self.assertNotIn('被忽略', seen['diff'])
        self.assertEqual(seen['files'].split(), ['kernel/new.py', 'runner/x.py', 'tests/drill.py'])
        self.assertEqual(seen['x'], 'X = 2\n')
        self.assertTrue(seen['new'])
        self.assertFalse(seen['junk'])

    def test_read_review_strict(self):
        f = self.tmp / 'r.json'
        good_pass = {'结论': '通过', '理由': ['看过了'], '问题': []}
        good_bad = {'结论': '有问题', '理由': ['看过了'], '问题': [{'文件': 'a.py', '说明': '错了'}]}
        for obj in (good_pass, good_bad, {'结论': '通过', '理由': ['看过了']}):
            f.write_text(json.dumps(obj, ensure_ascii=False))
            self.assertIsNone(S.read_review(f)[3], obj)
        bad = ['不是 JSON', '[]', json.dumps({**good_pass, '结论': '过了'}), json.dumps({**good_pass, '结论': 'PASS'}),
               json.dumps({**good_pass, '理由': []}), json.dumps({**good_pass, '理由': '一句'}), json.dumps({**good_pass, '理由': ['']}),
               json.dumps({**good_pass, '问题': [{'说明': '有一条'}]}), json.dumps({**good_bad, '问题': []}),
               json.dumps({**good_bad, '问题': [{'文件': 'a.py'}]}), json.dumps({**good_bad, '问题': '一条'}),
               json.dumps({'理由': ['看过了']})]
        for text in bad:
            f.write_text(text)
            v, _, _, why = S.read_review(f)
            self.assertIsNone(v, text)
            self.assertTrue(why, text)
        self.assertEqual(S.read_review(self.tmp / 'nope.json')[3], '没写结果文件')


class ThreePlaces(Base):
    def test_needs_isolation_flag(self):
        self.change('runner/x.py', 'X = 2\n')
        r = self.check()
        self.assertFalse(r['passed'])
        self.assertIn('--isolation', r['verdict'])
        self.assertIn('隔离自检和破坏演练', r['verdict'])
        self.assertEqual(self.reviews, 0)
        self.assertIn('独立审查', '\n'.join(r['lines']))

    def test_drill_missing_is_said_not_passed(self):
        self.change('kernel/journal.py', 'X = 1\n')
        ran = []
        r = self.check(isolation=True, selftest=lambda repo: (ran.append(repo), (True, ['隔离自检：172 项，0 项不符合']))[1])
        self.assertEqual(ran, [self.repo])
        self.assertFalse(r['passed'])
        self.assertIn('破坏演练：还没有（3-47 还没做', r['verdict'])
        self.assertIn('不能算过', r['verdict'])
        self.assertIn('隔离自检：通过（隔离自检：172 项，0 项不符合）', '\n'.join(r['lines']))

    def test_with_drill(self):
        self.change('runner/x.py', 'X = 2\n')
        ok = lambda repo: (True, ['隔离自检：172 项，0 项不符合'])   # noqa: E731
        bad = lambda repo: (False, ['不符合：受限侧读到了凭据', '隔离自检：172 项，1 项不符合'])   # noqa: E731
        for drill_rc, selftest, passed, key in ((0, ok, True, '过了'), (1, ok, False, '破坏演练没过'),
                                               (0, bad, False, '隔离自检没过')):
            with self.subTest(drill=drill_rc, selftest=selftest is ok):
                self.change(S.DRILL, f'import sys\nprint("演练")\nsys.exit({drill_rc})\n')
                self.reviews = 0
                r = self.check(isolation=True, selftest=selftest)
                self.assertEqual(r['passed'], passed, r['verdict'])
                self.assertIn(key, r['verdict'])
                self.assertEqual(self.reviews, 1 if passed else 0)

    def test_detection(self):
        def diff(path, *lines):
            return f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n' + '\n'.join(lines) + '\n'
        cases = [
            (['runner/placement.py'], '', {'隔离': ['runner/placement.py']}),
            (['runner/docker/service.py'], '', {'隔离': ['runner/docker/service.py']}),
            (['kernel/wtx.py', 'templates/wt/hooks/post-checkout'], '', {'隔离': ['kernel/wtx.py', 'templates/wt/hooks/post-checkout']}),
            (['machine/syscheck.py'], '', {'隔离': ['machine/syscheck.py']}),
            (['kernel/journal.py'], '', {'事件日志': ['kernel/journal.py']}),
            (['checks/guard/guard.py', 'checks/protected/base.txt'], '', {'放行事件': ['checks/guard/guard.py', 'checks/protected/base.txt']}),
            (['kernel/steps.py'], diff('kernel/steps.py', "+        rel = [J.release(f.branch, path, x['blob'], 'F17')]"),
             {'放行事件': ['kernel/steps.py']}),
            (['kernel/version.py'], diff('kernel/version.py', "-        rel.append(J.release(name, path, blob, verb))"),
             {'放行事件': ['kernel/version.py']}),
            (['kernel/steps.py'], diff('kernel/steps.py', ' J.release(x)  # 没改的上下文', '+    return 2'), {}),
            (['docs/a.md'], diff('docs/a.md', '+ J.release( 写在文档里'), {}),
            (['runnerx/a.py', 'kernel/journal.py.bak', 'README.md'], '', {}),
        ]
        for files, d, want in cases:
            with self.subTest(files=files):
                self.assertEqual(S.three_places(files, d), want)

    def test_moving_out_counts(self):
        sh('git', 'mv', 'runner/x.py', 'kernel/x.py', cwd=self.repo)
        files, d = S.changes(self.repo, 'HEAD')
        self.assertEqual(files, ['kernel/x.py', 'runner/x.py'])
        self.assertIn('隔离', S.three_places(files, d))


class Changes(Base):
    def test_does_not_touch_repo(self):
        self.change()
        self.change('kernel/new.py', 'Y = 1\n')
        idx = self.repo / '.git' / 'index'
        head = sh('git', 'rev-parse', 'HEAD', cwd=self.repo)
        sh('git', 'status', '--porcelain', cwd=self.repo)          # 先让 Git 自己把索引刷新好（它会顺手写索引）
        before = (idx.read_bytes(), idx.stat().st_mtime_ns)
        files, d = S.changes(self.repo, head)
        self.assertEqual(files, ['README.md', 'kernel/new.py'])
        self.assertIn('+Y = 1', d)
        self.assertEqual(before, (idx.read_bytes(), idx.stat().st_mtime_ns), '把关取改动时不能写索引')
        self.assertIn('?? kernel/new.py', sh('git', 'status', '--porcelain', cwd=self.repo, env={'GIT_OPTIONAL_LOCKS': '0'}))

    def test_base(self):
        self.assertEqual(S.resolve_base(self.repo)[1], 'HEAD（没有 origin/main）')
        first = sh('git', 'rev-parse', 'HEAD', cwd=self.repo)
        self.change()
        sh('git', 'commit', '-qam', '修了', cwd=self.repo)
        self.assertEqual(S.resolve_base(self.repo, first)[0], first)
        self.assertEqual(S.changes(self.repo, first)[0], ['README.md'])
        sh('git', 'update-ref', 'refs/remotes/origin/main', first, cwd=self.repo)
        self.assertEqual(S.resolve_base(self.repo), (first, 'origin/main'))
        with self.assertRaises(SopError):
            S.resolve_base(self.repo, 'nope')

    def test_find_repo(self):
        self.assertEqual(S.find_repo(str(self.repo)), self.repo.resolve())
        with self.assertRaises(SopError):
            S.find_repo(str(self.tmp))


class SameAsGitHub(Base):
    def test_checks_match_workflow(self):
        """把关跑的四条命令和 GitHub 上 .github/workflows/check.yml 一样；少一道、参数不一样都不过（反着试：去掉任一道检查）。"""
        sys.path.insert(0, str(REPO / 'tests'))
        import run_all
        from tests.unit.test_ci_workflow import jobs
        text = (REPO / '.github' / 'workflows' / 'check.yml').read_text(encoding='utf-8')
        code = '\n'.join(x for x in text.split('\n') if not x.lstrip().startswith('#'))
        flow = {}
        for name, body in jobs(code).items():
            run = re.findall(r'run: uv run python tests/run_all\.py (.*)', body)
            flow[name] = tuple(run[0].split())
        mine = {part: args for part, _, args in S.CHECKS}
        self.assertEqual(mine, flow)
        self.assertEqual(sorted(mine), sorted(run_all.PARTS))

    def test_three_places_cover_the_code(self):
        """三处的路径都真的在工具包里（改了名字这里要跟着改）；放行的写法认得出工具包里真有的几处。"""
        for prefixes in S.THREE.values():
            for p in prefixes:
                self.assertTrue((REPO / p).exists(), p)
        hits = 0
        for f in ('kernel/steps.py', 'kernel/version.py', 'kernel/projectgh.py', 'kernel/journal.py'):
            hits += sum(1 for line in (REPO / f).read_text(encoding='utf-8').splitlines() if S.RELEASE_LINE.search(line))
        self.assertGreaterEqual(hits, 5)
