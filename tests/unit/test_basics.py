"""第 1 步：工具包根目录、项目锁、端口登记。对应第二段验收「同一个项目开两个 sop，第二个只能看；两个项目的 sop 同时分配端口不打架」。"""
import json
import os
import signal
import subprocess
import sys
import time

from kernel import locks, paths, ports
from kernel.errors import Busy
from tests.helpers import REPO, TempHome, py

HOLD = '''
import sys, time
from kernel.locks import ProjectLock
l = ProjectLock(sys.argv[1]).acquire()
print('拿到了', flush=True)
time.sleep(float(sys.argv[2]))
'''


class TestPaths(TempHome):
    def test_home_is_temp(self):
        self.assertEqual(paths.sop_home(), self.home)
        self.assertTrue(str(paths.state_dir('demo')).startswith(str(self.home)))

    def test_project_name(self):
        for bad in ('Demo', 'a_b', '../x', '', 'a/b'):
            with self.assertRaises(ValueError):
                paths.state_dir(bad)

    def test_runtime_dir_private(self):
        d = paths.runtime_dir()
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)


class TestProjectLock(TempHome):
    def test_second_is_read_only(self):
        p = subprocess.Popen([sys.executable, '-c', HOLD, 'demo', '30'], env={**os.environ, 'PYTHONPATH': str(REPO)},
                             stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), '拿到了')
            with self.assertRaises(Busy) as cm:
                locks.ProjectLock('demo').acquire()
            self.assertIn('只能看', str(cm.exception))
            self.assertIn(str(p.pid), str(cm.exception))
            # 别的项目不受影响
            locks.ProjectLock('other').acquire().release()
        finally:
            p.kill(); p.wait()

    def test_lock_freed_when_killed(self):
        p = subprocess.Popen([sys.executable, '-c', HOLD, 'demo', '30'], env={**os.environ, 'PYTHONPATH': str(REPO)},
                             stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), '拿到了')
        os.kill(p.pid, signal.SIGKILL); p.wait()
        locks.ProjectLock('demo').acquire().release()   # 被强制结束后锁自动放开


ALLOC = '''
import sys, json
from kernel import ports
out = [ports.allocate(sys.argv[1], f'w{i}') for i in range(int(sys.argv[2]))]
print(json.dumps(out))
'''


class TestPorts(TempHome):
    def test_same_key_same_ports(self):
        a = ports.allocate('demo', 'feat-a-1')
        self.assertEqual(ports.allocate('demo', 'feat-a-1'), a)
        ports.release('demo', 'feat-a-1')
        self.assertNotIn('demo/feat-a-1', ports.all_allocations())

    def test_two_projects_at_once(self):
        procs = [subprocess.Popen([sys.executable, '-c', ALLOC, proj, '6'], env={**os.environ, 'PYTHONPATH': str(REPO)},
                                  stdout=subprocess.PIPE, text=True) for proj in ('alpha', 'beta', 'alpha2', 'beta2')]
        got = []
        for p in procs:
            out, _ = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0)
            got += json.loads(out)
        flat = [x for block in got for x in block]
        self.assertEqual(len(flat), len(set(flat)), '有端口被分了两次')
        self.assertEqual(len(ports.all_allocations()), 24)
