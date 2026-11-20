"""流程沙箱：sop project new 整条走一遍（设计书 7.2 的 I0 到 I7；3-24）。

GitHub 是假的 gh（tests/fakes/gh/gh）：repo create 新建的仓库检查按真的来（项目检查真跑工具包的 checks/project_check，
守门检查真跑 checks/guard，公开仓库没有事件规则时守门被挡）。工具包是开发目录的快照（一个本机的「公开仓库」），
sop 从快照里执行，所以 sop.json 写的版本就是快照的提交编号，假 gh 按它取检查脚本。

防止调到真的 gh：PATH 里假的在最前面；主目录、GH_CONFIG_DIR 都是空的临时目录（真的 gh 就算被调到也没登录）；
每个剧本开头先确认 PATH 里找到的 gh 就是假的那个。不连网：仓库地址是本机路径（SOP_GITHUB_URL_PREFIX），wt doctor 的 SSH 那项因此跳过。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest

from tests.helpers import REPO, TempHome, sh
from tests.sandbox.world import FAKES, snapshot_toolkit

WT = shutil.which('wt')
FAKE_GH = FAKES / 'gh' / 'gh'


def answers(vis):
    from kernel import projectnew as P
    s = {f'project:I0-{q["id"]}': [{'answer': '1'}] for q in P.REDLINE}
    s['project:I1'] = [{'answer': '1' if vis == 'public' else '2'}]
    return s


@unittest.skipUnless(WT, '本机没有 wt')
class ProjectNewBase(TempHome):
    visibility = 'public'

    def setUp(self):
        super().setUp()
        t = self.tmp
        self.user_home, self.fakegh, self.ghcfg = t / 'home', t / 'fakegh', t / 'ghcfg'
        for d in (self.user_home, self.fakegh, self.ghcfg, t / 'tmpdir', t / 'projects', t / 'tools'):
            d.mkdir()
        (self.user_home / '.gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n'
                                                   '[init]\n\tdefaultBranch = main\n')
        self.root = t / 'projects' / 'demo'
        self.script = t / 'human.json'
        self.script.write_text(json.dumps(answers(self.visibility), ensure_ascii=False))
        # 工具包的「公开仓库」：开发目录的快照提交一次
        self.toolkit = t / 'toolkit'
        self.toolkit_remote = t / 'github' / 'sop-toolkit.git'
        self.toolkit.mkdir()
        g = {'GIT_CONFIG_GLOBAL': str(self.user_home / '.gitconfig'), 'GIT_CONFIG_NOSYSTEM': '1'}
        sh('git', 'init', '-q', '-b', 'main', self.toolkit, env=g)
        snapshot_toolkit(self.toolkit)
        sh('git', '-C', self.toolkit, 'add', '-A', env=g)
        sh('git', '-C', self.toolkit, 'commit', '-qm', '快照', env=g)
        sh('git', 'init', '-q', '--bare', '-b', 'main', self.toolkit_remote, env=g)
        sh('git', '-C', self.toolkit, 'push', '-q', self.toolkit_remote, 'HEAD:main', env=g)
        self.version = sh('git', '-C', self.toolkit, 'rev-parse', 'HEAD')
        self.envd = {**{k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'GH_', 'GITHUB_', 'WT_'))},
                     'HOME': str(self.user_home), 'TMPDIR': str(t / 'tmpdir'), 'PATH': f'{FAKE_GH.parent}:{os.environ["PATH"]}',
                     'GH_CONFIG_DIR': str(self.ghcfg), 'FAKEGH_HOME': str(self.fakegh), 'PYTHONPATH': str(self.toolkit),
                     'SOP_PROJECTS_DIR': str(t / 'projects'), 'SOP_TOOLS_DIR': str(t / 'tools'), 'GIT_CONFIG_NOSYSTEM': '1',
                     'SOP_TOOLKIT_REPO': str(self.toolkit_remote), 'SOP_GITHUB_URL_PREFIX': f'{self.fakegh}/repos/',
                     'SOP_HUMAN_SCRIPT': str(self.script), 'SOP_POLL_SECONDS': '0', 'SOP_CHECK_DEADLINE': '60'}
        found = subprocess.run(['sh', '-c', 'command -v gh; gh --version'], env=self.envd, capture_output=True, text=True).stdout
        self.assertEqual(found.splitlines()[0], str(FAKE_GH))          # 调到的一定是假的 gh
        self.assertIn('(fake)', found)

    def sop_new(self, *extra_env):
        env = {**self.envd, **dict(extra_env)}
        return subprocess.run([sys.executable, '-m', 'kernel.cli', 'project', 'new', 'demo'], cwd=self.tmp, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)

    def db(self):
        return json.loads((self.fakegh / 'db.json').read_text())

    def remote(self):
        return self.fakegh / 'repos' / 'tester' / 'demo.git'

    def rgit(self, *a):
        return sh('git', '--git-dir', self.remote(), *a)

    def progress(self):
        f = self.home / 'state' / 'demo' / 'init' / 'progress.json'
        return json.loads(f.read_text()) if f.exists() else None

    def check_trials(self):
        """I7：四个试验 PR 的检查结果符合 7.2，四个都关了、分支删了、没合并。"""
        d = self.db()
        prs = sorted(d['prs'].values(), key=lambda p: p['number'])
        self.assertEqual(len(prs), 4)
        got = {}
        for pr in prs:
            runs = [r for r in d['runs'] if r['pr'] == pr['number'] and r['head_sha'] == pr['headRefOid']]
            got[pr['head'].split('/')[1].rsplit('-', 1)[0]] = {r['name']: r['conclusion'] for r in sorted(runs, key=lambda r: r['id'])}
            self.assertEqual(pr['state'], 'CLOSED')
            self.assertNotIn('mergedAt', {k for k, v in pr.items() if v})
        self.assertEqual(got['broken']['fast'], 'failure')     # 故意出错的：项目检查不通过
        self.assertEqual(got['broken']['guard'], 'success')
        self.assertEqual(got['checkdef']['guard'], 'failure')  # 改了检查定义的：守门检查不通过
        self.assertEqual(got['released']['guard'], 'success')  # 改了受保护路径、带着放行的：守门检查通过
        self.assertEqual(got['normal'], {'fast': 'success', 'full': 'success', 'guard': 'success'})   # 正常的：都通过（门禁暂不适用）
        self.assertEqual(self.rgit('for-each-ref', '--format=%(refname)', 'refs/heads/'), 'refs/heads/main\nrefs/heads/sop/journal')
        log = {r['pr']: r['log'] for r in d['runs'] if r['name'] == 'fast'}
        self.assertIn('门禁暂不适用', log[prs[-1]['number']])
        self.assertIn('.gitignore 里没有 .env', log[prs[0]['number']])
        return got


class TestProjectNewPublic(ProjectNewBase):
    def test_whole_flow(self):
        r = self.sop_new()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('四个试验 PR 的检查结果都对', r.stdout)
        d = self.db()
        # I2：仓库是 gh 登录的账号名下的、公开；wt 设好了只许压合、合并后删分支
        self.assertEqual((d['slug'], d['visibility']), ('tester/demo', 'public'))
        s = d['settings']
        self.assertEqual((s['allow_squash_merge'], s['allow_merge_commit'], s['allow_rebase_merge'], s['delete_branch_on_merge']),
                         (True, False, False, True))
        # I5：远程 main 和本机一致：GitHub 的 README 提交加初始内容那一个；sop.json 写的是快照的版本
        local = sh('git', '--git-dir', self.root / '.git', 'rev-parse', 'refs/heads/main')
        self.assertEqual(self.rgit('rev-parse', 'refs/heads/main'), local)
        self.assertEqual(self.rgit('rev-list', '--count', 'main'), '2')
        sop = json.loads(self.rgit('show', 'main:sop.json'))
        self.assertEqual(sop['toolkit'], {'repo': str(self.toolkit_remote), 'version': self.version})
        # I6：两条分支的保护、事件规则
        self.assertEqual(d['protection']['main']['contexts'], ['fast', 'full', 'guard'])
        self.assertTrue(d['protection']['main']['enforce_admins'])
        j = d['protection']['sop/journal']
        self.assertEqual((j['contexts'], j['enforce_admins'], j['allow_force_pushes'], j['allow_deletions']), (None, True, False, False))
        self.assertEqual(len(d['policies']), 1)
        self.assertEqual(d['policies'][0]['conditions']['workflow_path'], {'include': ['.github/workflows/sop-guard.yml'], 'exclude': []})
        # I7
        self.check_trials()
        # 放行事件：只给「带着放行」的那条试验分支写了一条；四个名字都登记了
        rel = self.rgit('ls-tree', '-r', '--name-only', 'sop/journal', 'releases/').splitlines()
        self.assertEqual(len(rel), 1)
        self.assertTrue(rel[0].startswith('releases/sop-init__released-1/'))
        names = self.rgit('ls-tree', '-r', '--name-only', 'sop/journal', 'names/').splitlines()
        self.assertEqual(sorted(names), sorted(f'names/sop-init__{k}-1.json' for k in ('broken', 'checkdef', 'released', 'normal')))
        prog = self.progress()
        self.assertEqual(prog['done'], ['I2', 'I3I4', 'I5', 'I6', 'I7'])
        self.assertTrue(prog['finished'])
        # 再执行一次：说已经建好了，什么都不动
        before = json.dumps(self.db(), sort_keys=True)
        r = self.sop_new()
        self.assertEqual(r.returncode, 1)
        self.assertIn('已经建好了', r.stdout)
        self.assertEqual(json.dumps(self.db(), sort_keys=True), before)
        self.assertEqual(os.listdir(self.tmp / 'tmpdir'), [])
        self.assertEqual(os.listdir(self.ghcfg), [])

    def test_without_event_rule_guard_is_blocked(self):
        """反着试：I6 不设事件规则时（假 gh 照 2026-12-02 之后的样子），守门检查一律被挡，I7 发现、停下。"""
        r = self.sop_new(('SOP_TEST_SKIP_POLICY', '1'))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('守门检查应该通过，实际不通过', r.stdout)
        self.assertNotIn('I7', self.progress()['done'])
        self.assertTrue(all(p['state'] == 'CLOSED' for p in self.db()['prs'].values()))
        self.assertEqual(self.db()['policies'], [])


    def test_trial_results_wrong_are_caught(self):
        """反着试：剧本让「改了检查定义」的守门检查、「故意出错」的快档检查都变成通过，I7 两处都发现、停下、四个都关了。"""
        (self.fakegh / 'rules.json').write_text(json.dumps([
            {'name': 'guard', 'head': 'sop-init/checkdef-*', 'conclusion': 'success'},
            {'name': 'fast', 'head': 'sop-init/broken-*', 'conclusion': 'success'}]))
        r = self.sop_new()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('「改了检查定义」那个：守门检查应该不通过，实际通过', r.stdout)
        self.assertIn('「故意出错」那个：项目检查（快档）应该不通过，实际通过', r.stdout)
        self.assertNotIn('I7', self.progress()['done'])
        self.assertTrue(all(p['state'] == 'CLOSED' for p in self.db()['prs'].values()))
        self.assertEqual(self.rgit('for-each-ref', '--format=%(refname)', 'refs/heads/'), 'refs/heads/main\nrefs/heads/sop/journal')
        # 剧本去掉后重跑：只重做 I7（新的四个 PR 用下一个序号），这次对了
        (self.fakegh / 'rules.json').write_text('[]')
        r = self.sop_new()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.db()['prs']), 8)
        self.assertEqual(self.progress()['done'], ['I2', 'I3I4', 'I5', 'I6', 'I7'])


class TestProjectNewPrivate(ProjectNewBase):
    visibility = 'private'

    def test_whole_flow_private(self):
        r = self.sop_new()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.db()
        self.assertEqual(d['visibility'], 'private')
        self.assertEqual(d['protection'], {})          # 免费计划的私有仓库开不了保护，没开
        self.assertEqual(d['policies'], [])
        self.assertFalse(d['settings']['allow_auto_merge'])
        notes = [json.loads(self.rgit('show', f'sop/journal:{f}')) for f in
                 self.rgit('ls-tree', '-r', '--name-only', 'sop/journal', 'events/project/').splitlines()]
        self.assertTrue(any(n.get('step') == 'I6' and '开不了分支保护' in n['text'] for n in notes))
        self.check_trials()


class TestProjectNewResume(ProjectNewBase):
    def test_resume_after_each_break(self):
        """在 I2 之后、I3I4 写到一半、I5 之后、I7 开了 PR 之后各断一次，重跑都接着做完，结果和一口气做完的一样。"""
        for where in ('after-I2', 'mid-I3I4', 'after-I5', 'mid-I7'):
            r = self.sop_new(('SOP_TEST_BREAK', where))
            self.assertNotEqual(r.returncode, 0, where)
            self.assertIn('（测试）在', r.stdout + r.stderr, where)
        r = self.sop_new()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('上次没建完，接着做', r.stdout)
        self.assertEqual(self.progress()['done'], ['I2', 'I3I4', 'I5', 'I6', 'I7'])
        d = self.db()
        # 断在 I7 中间那次开的 PR 被关掉了；最后一次的四个用了下一个序号
        last = sorted(d['prs'].values(), key=lambda p: p['number'])[-4:]
        self.assertEqual(sorted(p['head'] for p in last), sorted(f'sop-init/{k}-2' for k in ('broken', 'checkdef', 'released', 'normal')))
        self.assertTrue(all(p['state'] == 'CLOSED' for p in d['prs'].values()))
        self.assertEqual(self.rgit('rev-list', '--count', 'main'), '2')
        self.assertEqual(self.rgit('for-each-ref', '--format=%(refname)', 'refs/heads/'), 'refs/heads/main\nrefs/heads/sop/journal')
        ok = subprocess.run([sys.executable, str(self.toolkit / 'checks' / 'project_layout' / 'check.py'), '/dev/stdin'],
                            input=json.dumps({'dir': str(self.root / 'main'), 'toolkit': str(self.toolkit), 'root': str(self.root)}),
                            capture_output=True, text=True, env=self.envd)
        self.assertEqual(ok.returncode, 0, ok.stdout)


if __name__ == '__main__':
    unittest.main()
