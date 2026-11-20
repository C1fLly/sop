"""3-24：sop project new 的 GitHub 那一半（kernel/projectgh.py）的几个小块，和假 gh 新补的接口（照 S4、W40 实测的 GitHub 回答）。
整条流程在流程沙箱 tests/sandbox/test_project_new.py。PATH 里只放假的 gh，主目录、GH_CONFIG_DIR 是空的临时目录。"""
import json
import os
import subprocess
import unittest

from kernel import paths, projectgh as G, projectnew as P
from kernel.errors import SopError
from kernel.human import ScriptedHuman
from tests.helpers import REPO, TempHome, mock_env

FAKE_GH = REPO / 'tests' / 'fakes' / 'gh' / 'gh'


class FakeGhBase(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        for d in ('home', 'fakegh', 'ghcfg', 'projects'):
            (t / d).mkdir()
        (t / 'home' / '.gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n')
        self._env2 = mock_env({'HOME': str(t / 'home'), 'PATH': f'{FAKE_GH.parent}:{os.environ["PATH"]}', 'GH_CONFIG_DIR': str(t / 'ghcfg'),
                               'FAKEGH_HOME': str(t / 'fakegh'), 'SOP_PROJECTS_DIR': str(t / 'projects'),
                               'SOP_TOOLKIT_REPO': 'https://example.invalid/sop.git', 'GIT_CONFIG_NOSYSTEM': '1',
                               'SOP_GITHUB_URL_PREFIX': f'{t / "fakegh" / "repos"}/'})
        self._env2.__enter__()
        self.assertIn('(fake)', subprocess.run(['gh', '--version'], capture_output=True, text=True).stdout)

    def tearDown(self):
        self._env2.__exit__(None, None, None)
        super().tearDown()

    def gh(self, *args, input=None):
        return subprocess.run(['gh', *args], capture_output=True, text=True, input=input)


class TestFakeGh(FakeGhBase):
    def test_repo_create_and_settings(self):
        self.assertEqual(self.gh('repo', 'view', 'tester/x', '--json', 'name').returncode, 1)     # 还没有
        self.assertEqual(self.gh('api', 'user', '--jq', '.login').stdout.strip(), 'tester')
        self.assertEqual(self.gh('repo', 'create', 'other/x', '--private', '--add-readme').returncode, 1)   # 别人名下的建不了
        self.assertEqual(self.gh('repo', 'create', 'tester/x', '--private', '--add-readme').returncode, 0)
        self.assertEqual(self.gh('repo', 'view', 'tester/x', '--json', 'name').returncode, 0)
        self.assertEqual(self.gh('repo', 'create', 'tester/x', '--private').returncode, 1)          # 已经有了
        remote = self.tmp / 'fakegh' / 'repos' / 'tester' / 'x.git'
        show = subprocess.run(['git', '--git-dir', remote, 'show', 'main:README.md'], capture_output=True, text=True).stdout
        self.assertEqual(show, '# x\n')
        r = self.gh('api', '-X', 'PATCH', 'repos/tester/x', '-F', 'allow_merge_commit=false', '-F', 'allow_auto_merge=true',
                    '-f', 'squash_merge_commit_title=PR_TITLE', '--jq', '[.allow_merge_commit,.allow_auto_merge,.private]|@tsv')
        self.assertEqual(r.stdout.strip(), 'false\tfalse\ttrue')   # 私有仓库免费计划不支持自动合并：这一项被忽略（wt 认这种情况）

    def test_protection_private_refused_public_ok(self):
        self.gh('repo', 'create', 'tester/x', '--private', '--add-readme')
        body = json.dumps(G.MAIN_PROTECTION)
        r = self.gh('api', '-X', 'PUT', 'repos/tester/x/branches/main/protection', '--input', '-', input=body)
        self.assertEqual(r.returncode, 1)
        self.assertIn('Upgrade to GitHub Pro', r.stderr)            # S4 实测的原话

    def test_policy_needs_include_and_exclude(self):
        self.gh('repo', 'create', 'tester/x', '--public', '--add-readme')
        bad = json.loads(json.dumps(G.GUARD_POLICY))
        del bad['conditions']['workflow_path']['exclude']
        r = self.gh('api', '-X', 'POST', 'repos/tester/x/actions/policies', '--input', '-', input=json.dumps(bad))
        self.assertEqual(r.returncode, 1)
        self.assertIn('422', r.stderr)                              # W40 第一次就是这样被拒的
        r = self.gh('api', '-X', 'POST', 'repos/tester/x/actions/policies', '--input', '-', input=json.dumps(G.GUARD_POLICY))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = G._policies(json.loads(self.gh('api', 'repos/tester/x/actions/policies').stdout))
        self.assertEqual([p['name'] for p in got], [G.POLICY_NAME])


class StubProject:
    """check_protection 只用到 p.gh(..., as_json=True)。"""

    def __init__(self, answers):
        self.answers = answers

    def gh(self, *args, as_json=False, **kw):
        return self.answers[args[1].split('/', 3)[3]]


class TestCheckProtection(unittest.TestCase):
    GOOD = {'branches/main/protection': {'required_status_checks': {'contexts': ['guard', 'fast', 'full']},
                                         'enforce_admins': {'enabled': True}, 'allow_force_pushes': {'enabled': False},
                                         'allow_deletions': {'enabled': False}},
            'branches/sop/journal/protection': {'enforce_admins': {'enabled': True}, 'allow_force_pushes': {'enabled': False},
                                                'allow_deletions': {'enabled': False}},
            'actions/policies': [G.GUARD_POLICY]}

    def bad(self, path, change):
        a = json.loads(json.dumps(self.GOOD))
        change(a[path])
        return G.GitHub().check_protection(StubProject(a), 'tester/x')

    def test_good(self):
        self.assertEqual(G.GitHub().check_protection(StubProject(self.GOOD), 'tester/x'), [])

    def test_each_wrong_setting_reported(self):
        cases = [('branches/main/protection', lambda m: m['required_status_checks']['contexts'].remove('full'), '必须通过的检查'),
                 ('branches/main/protection', lambda m: m['enforce_admins'].update(enabled=False), '对管理员'),
                 ('branches/main/protection', lambda m: m['allow_force_pushes'].update(enabled=True), 'allow_force_pushes'),
                 ('branches/sop/journal/protection', lambda m: m['allow_deletions'].update(enabled=True), '日志分支'),
                 ('actions/policies', lambda m: m[0]['conditions']['workflow_path']['include'].append('.github/workflows/sop-check.yml'), '事件规则'),
                 ('actions/policies', lambda m: m.clear(), '有 0 条')]
        for path, change, word in cases:
            with self.subTest(word=word):
                got = self.bad(path, change)
                self.assertEqual(len(got), 1, got)
                self.assertIn(word, got[0])


class TestCreateStops(FakeGhBase):
    def answers(self):
        s = {f'project:I0-{q["id"]}': [{'answer': '1'}] for q in P.REDLINE}
        s['project:I1'] = [{'answer': '2'}]
        f = self.tmp / 'human.json'
        f.write_text(json.dumps(s))
        return ScriptedHuman('demo', str(f))

    def test_existing_repo_on_account(self):
        """GitHub 账号下已经有同名仓库：停下，本机什么都没建，GitHub 上那个不动。"""
        self.gh('repo', 'create', 'tester/demo', '--public', '--add-readme')
        before = (self.tmp / 'fakegh' / 'db.json').read_text()
        with self.assertRaises(SopError) as e:
            P.new_project('demo', self.answers())
        self.assertIn('已经有一个叫 demo 的仓库', str(e.exception))
        self.assertFalse((self.tmp / 'projects' / 'demo').exists())
        self.assertEqual((self.tmp / 'fakegh' / 'db.json').read_text(), before)
        self.assertNotIn('slug', G.load_progress('demo'))

    def test_half_built_root_on_resume(self):
        """重跑时项目目录建到一半（上次 wt init 断在中间）：停下，说挪走它再执行；不在上面接着建。"""
        G.save_progress('demo', visibility='private', done=[], slug='tester/demo', url='x')
        d = paths.state_dir('demo') / 'init'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'redline.json').write_text(json.dumps({'hits': []}))
        (d / 'visibility.json').write_text(json.dumps({'visibility': 'private'}))
        root = self.tmp / 'projects' / 'demo'
        (root / '.git').mkdir(parents=True)
        with self.assertRaises(SopError) as e:
            P.new_project('demo', self.answers())
        self.assertIn('建到一半就断了', str(e.exception))
        self.assertEqual(os.listdir(root), ['.git'])

    def test_resume_needs_consistent_records(self):
        G.save_progress('demo', visibility='public', done=[])
        d = paths.state_dir('demo') / 'init'
        (d / 'redline.json').write_text(json.dumps({'hits': []}))
        (d / 'visibility.json').write_text(json.dumps({'visibility': 'private'}))
        with self.assertRaises(SopError) as e:
            P.new_project('demo', self.answers())
        self.assertIn('对不上', str(e.exception))


if __name__ == '__main__':
    unittest.main()
