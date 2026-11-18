"""自测共用的小工具：每个测试一个 /tmp 下的临时根目录，SOP_HOME、运行时目录都指过去。"""
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
TMP_ROOT = pathlib.Path(os.environ.get('SOP_TEST_TMP', '/tmp/sop-test'))
GIT_ID = {'GIT_AUTHOR_NAME': 'tester', 'GIT_AUTHOR_EMAIL': 'tester@example.invalid',
          'GIT_COMMITTER_NAME': 'tester', 'GIT_COMMITTER_EMAIL': 'tester@example.invalid'}


def rmtree(p):
    """删目录（封存成只读的状态目录要先恢复写权限）。"""
    if os.path.exists(p):
        subprocess.run(['chmod', '-R', 'u+w', str(p)], capture_output=True)
        shutil.rmtree(p, ignore_errors=True)


def sh(*args, cwd=None, env=None, check=True, input=None):
    e = {**os.environ, **GIT_ID, **(env or {})}
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=e, capture_output=True, text=True, input=input)
    if check and p.returncode:
        raise RuntimeError(f'{args}: 退出码 {p.returncode}\n{p.stdout}\n{p.stderr}')
    return p.stdout.strip()


class TempHome(unittest.TestCase):
    """每个测试一个临时根目录，测试结束删掉（设 SOP_KEEP=1 留着看）。"""

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix=f'{type(self).__name__}-', dir=TMP_ROOT))
        self.home = self.tmp / 'sop-home'
        self.home.mkdir()
        self._env = mock_env({'SOP_HOME': str(self.home), 'SOP_RUNTIME_DIR': str(self.tmp / 'run')})
        self._env.__enter__()

    def tearDown(self):
        self._env.__exit__(None, None, None)
        if not os.environ.get('SOP_KEEP'):
            rmtree(self.tmp)


@contextlib.contextmanager
def mock_env(values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def py(code_or_file, *args, env=None, check=True):
    """另起一个 Python 进程（模拟另一个终端里的 sop）。"""
    e = {**os.environ, 'PYTHONPATH': str(REPO), **(env or {})}
    return subprocess.run([sys.executable, '-c', code_or_file, *map(str, args)], env=e, capture_output=True, text=True)


def make_remote_and_clone(tmp, name='demo'):
    """一个充当 GitHub 的本机远程（main 上一个文件），加一个裸仓库形式的本机克隆（设计书 5.1 的 .git）。"""
    tmp = pathlib.Path(tmp)
    remote = tmp / 'github' / f'{name}.git'
    remote.parent.mkdir(parents=True, exist_ok=True)
    sh('git', 'init', '-q', '--bare', '-b', 'main', remote)
    seed = tmp / 'seed'
    sh('git', 'clone', '-q', remote, seed)
    (seed / 'README.md').write_text('代码\n')
    sh('git', 'add', '.', cwd=seed); sh('git', 'commit', '-qm', '初始', cwd=seed); sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=seed)
    root = tmp / 'Project' / name
    root.mkdir(parents=True)
    sh('git', 'clone', '-q', '--bare', remote, root / '.git')
    sh('git', '--git-dir', root / '.git', 'config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*')
    sh('git', '--git-dir', root / '.git', 'fetch', '-q', 'origin')
    return remote, root / '.git'
