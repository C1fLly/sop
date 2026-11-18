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
            shutil.rmtree(self.tmp, ignore_errors=True)


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
