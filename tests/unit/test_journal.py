"""第 2 步：事件日志（设计书 8.2）、放行事件的序号（6.4）、归属名不重复（6.4）。"""
import json
import os
import subprocess
import sys
import threading

from kernel import journal as J
from tests.helpers import REPO, TempHome, make_remote_and_clone, sh

WRITE_SEQ = '''
import sys
from kernel import journal as J
j = J.Journal(sys.argv[1])
for i in range(int(sys.argv[2])):
    files = j.append(J.event('feature/a-1', f'X{i}', 'done'))
    print('写好了', files[0], flush=True)
'''

BURST = '''
import sys, json
from kernel import journal as J
j = J.Journal(sys.argv[1])
for i in range(int(sys.argv[3])):
    j.append(J.event(sys.argv[2], f'S{i}', 'done'))
print(json.dumps({'pushes': j.pushes, 'retries': j.retries}))
'''

GRAB = '''
import sys
from kernel import journal as J
j = J.Journal(sys.argv[1])
try:
    j.append(J.register_name(sys.argv[2], kind='feature')); print('成功')
except J.NameTaken:
    print('被拒')
'''


def remote_has(remote, path):
    return subprocess.run(['git', '--git-dir', str(remote), 'cat-file', '-e', f'{J.REF}:{path}']).returncode == 0


class JournalCase(TempHome):
    def setUp(self):
        super().setUp()
        self.remote, self.gitdir = make_remote_and_clone(self.tmp)
        self.j = J.Journal(self.gitdir)
        self.j.init_branch()

    def tearDown(self):
        self.j.close()
        super().tearDown()

    def run_py(self, code, *args, env=None):
        return subprocess.run([sys.executable, '-c', code, str(self.gitdir), *map(str, args)], capture_output=True, text=True,
                              env={**os.environ, 'PYTHONPATH': str(REPO), **(env or {})})


class TestBasics(JournalCase):
    def test_separate_branch(self):
        self.j.append(J.event('feature/a-1', 'F1', 'done', cost=0.4))
        tree = sh('git', '--git-dir', self.remote, 'ls-tree', '-r', '--name-only', J.REF).splitlines()
        self.assertTrue(tree and all(t.startswith('events/') for t in tree))
        self.assertNotEqual(subprocess.run(['git', '--git-dir', str(self.remote), 'merge-base', 'main', J.REF]).returncode, 0)
        self.assertEqual(sh('git', '--git-dir', self.gitdir, 'worktree', 'list').count('\n'), 0)

    def test_order_and_dirs(self):
        self.j.append(J.event('ticket/a-1/01', 'T1', 'start'))
        self.j.append(J.event('ticket/a-1/01', 'T1', 'done'), J.event('ticket/a-1/02', 'T1', 'start'))
        self.j.append(J.event('project', 'P0', 'done'), J.event('feature/b-1', 'F1', 'start'))
        evs = self.j.read(['feature/a-1'])
        self.assertEqual([(e['scope'], e['step'], e['type']) for e in evs],
                         [('ticket/a-1/01', 'T1', 'start'), ('ticket/a-1/01', 'T1', 'done'), ('ticket/a-1/02', 'T1', 'start')])
        self.assertEqual([e['step'] for e in self.j.read(['project'])], ['P0'])

    def test_chinese(self):
        self.j.append(J.event('feature/a-1', 'F17', 'failed', reason='页面上「保存」按钮没反应'))
        self.assertEqual(self.j.read(['feature/a-1'])[0]['reason'], '页面上「保存」按钮没反应')


class TestGroupCommit(JournalCase):
    def test_threads_merge_into_fewer_pushes(self):
        errors, n_threads, per = [], 8, 5

        def worker(k):
            for i in range(per):
                files = self.j.append(J.event(f'ticket/a-1/{k:02d}', f'T{i}', 'done'))
                if not remote_has(self.remote, files[0]):    # 返回之前一定已经推上去了
                    errors.append(files[0])
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errors, [])
        evs = self.j.read(['feature/a-1'])
        self.assertEqual(len(evs), n_threads * per)
        for k in range(n_threads):   # 每张工单自己的事件，先后没有乱
            self.assertEqual([e['step'] for e in evs if e['scope'] == f'ticket/a-1/{k:02d}'], [f'T{i}' for i in range(per)])
        self.assertLess(self.j.pushes, n_threads * per, '同时排着的事件应当合成一次推送')

    def test_processes_linear_history(self):
        procs = [subprocess.Popen([sys.executable, '-c', BURST, str(self.gitdir), f'ticket/a-1/{k}', '10'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": str(REPO)}) for k in range(3)]
        for p in procs:
            out, err = p.communicate(timeout=120); self.assertEqual(p.returncode, 0, err[-800:])
        self.assertEqual(len(self.j.read(['feature/a-1'])), 30)
        merges = sh('git', '--git-dir', self.remote, 'rev-list', '--merges', J.REF)
        self.assertEqual(merges, '', '日志分支的历史应当是一条直线')


class TestWtFetch(JournalCase):
    """3-53：wt 拉取（git fetch --all）会改 refs/remotes/origin/ 下的所有指针；事件日志不能和它改同一个指针。"""

    def test_journal_leaves_origin_refs_alone(self):
        self.j.append(J.event('project', 'P0', 'done'))
        self.j.fetch()
        self.j.read(['project'])
        self.assertFalse(subprocess.run(['git', '--git-dir', str(self.gitdir), 'show-ref', '--verify', '--quiet',
                                         'refs/remotes/origin/sop/journal']).returncode == 0,
                         '事件日志自己的指针不应放在 refs/remotes/origin/ 下')

    def test_fetch_all_while_writing(self):
        stop, fails, n = threading.Event(), [], [0]

        def fetch_all():          # 像 wt new 那样拉取
            while not stop.is_set():
                p = subprocess.run(['git', '--git-dir', str(self.gitdir), 'fetch', '--all', '--prune', '--quiet'],
                                   capture_output=True, text=True)
                n[0] += 1
                if p.returncode:
                    fails.append(p.stderr.strip()[-200:])
        t = threading.Thread(target=fetch_all)
        t.start()
        try:
            for i in range(80):
                self.j.append(J.event('project', f'X{i}', 'note'))
        finally:
            stop.set(); t.join()
        self.assertGreater(n[0], 20)
        self.assertEqual(fails[:3], [], f'拉取 {n[0]} 次里失败 {len(fails)} 次')
        self.assertEqual(len(self.j.read(['project'])), 80)


class TestReleases(JournalCase):
    def test_seq_and_latest(self):
        self.j.append(J.release('feat/a-1', 'docs/baseline/home.png', 'b1' * 20, 'T11'))
        self.j.append(J.release('feat/a-1', 'docs/baseline/home.png', 'b2' * 20, 'T11'),
                      J.release('feat/a-1', 'docs/baseline/home.png', 'b3' * 20, 'T11'),
                      J.release('feat/b-1', 'docs/baseline/home.png', 'c1' * 20, 'T11'))
        r = self.j.releases('feat/a-1')
        self.assertEqual(r['docs/baseline/home.png']['seq'], 3)
        self.assertEqual(r['docs/baseline/home.png']['blob'], 'b3' * 20)
        self.assertEqual(self.j.releases('feat/b-1')['docs/baseline/home.png']['seq'], 1)


class TestNames(JournalCase):
    def test_second_use_rejected(self):
        self.j.append(J.register_name('feat/login-1', kind='feature'))
        self.assertTrue(self.j.name_used('feat/login-1'))
        with self.assertRaises(J.NameTaken):
            self.j.append(J.register_name('feat/login-1', kind='feature'))
        # 同一批里另一项不受影响
        self.j.append(J.event('feature/login-2', 'F1', 'start'))

    def test_two_processes_same_name(self):
        procs = [subprocess.Popen([sys.executable, '-c', GRAB, str(self.gitdir), 'plan/product-1'], stdout=subprocess.PIPE,
                                  text=True, env={**os.environ, 'PYTHONPATH': str(REPO)}) for _ in range(4)]
        outs = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
        self.assertEqual(outs, ['成功', '被拒', '被拒', '被拒'])


class TestCrash(JournalCase):
    def test_killed_before_push(self):
        """演一次「sop 在推送前被强制结束」：报告写好了的都在远程上，没报告的都不在；重新读出来和远程一致。"""
        p = self.run_py(WRITE_SEQ, 5, env={'SOP_TEST_DIE_BEFORE_PUSH': '3'})
        self.assertEqual(p.returncode, 137)
        said = [l.split()[1] for l in p.stdout.splitlines() if l.startswith('写好了')]
        self.assertEqual(len(said), 2)
        for f in said:
            self.assertTrue(remote_has(self.remote, f))
        fresh = J.Journal(self.gitdir)
        evs = fresh.read(['feature/a-1'])
        self.assertEqual([e['step'] for e in evs], ['X0', 'X1'])


class TestOffline(JournalCase):
    def test_offline_stops(self):
        os.rename(self.remote, str(self.remote) + '.gone')
        try:
            with self.assertRaises(J.Offline):
                self.j.append(J.event('feature/a-1', 'F1', 'start'))
        finally:
            os.rename(str(self.remote) + '.gone', self.remote)
