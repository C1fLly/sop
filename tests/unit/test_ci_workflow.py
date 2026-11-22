"""3-40：工具包仓库自己的检查流程 .github/workflows/check.yml、准备电脑的 tests/ci/prepare.sh、tests/run_all.py 的四个部分。

内核只用标准库，这里不读 YAML，按行核对几条不能丢的规矩：
- 四个检查 unit、sandbox、checks、docs 都在、名字固定（3-41 的分支保护按名字列），跑的是 run_all.py 里有的部分；
- 单元测试、流程沙箱带 --no-skip（GitHub 上缺了 wt 之类不能悄悄跳过）；
- 用到的 Action 都钉在 40 位提交编号上；只有只读权限；不用 pull_request_target；机密只有 WT_DEPLOY_KEY；
- prepare.sh 不在 GitHub Actions 里就什么都不做、直接停下（它要 sudo、改内核开关、往 ~/.ssh 放钥匙）。
真的在 GitHub 上跑是 3-41。
"""
import os
import pathlib
import re
import subprocess
import sys
import unittest

from tests.helpers import REPO, TempHome

FLOW = REPO / '.github' / 'workflows' / 'check.yml'
PREPARE = REPO / 'tests' / 'ci' / 'prepare.sh'
sys.path.insert(0, str(REPO / 'tests'))
import run_all  # noqa: E402


def jobs(text):
    """按缩进切出每个检查：{检查名: 那一段的文字}。"""
    body = text.split('\njobs:\n', 1)[1]
    out, name = {}, None
    for line in body.split('\n'):
        m = re.match(r'^  ([A-Za-z0-9_-]+):\s*$', line)
        if m:
            name = m.group(1)
            out[name] = ''
        elif name:
            out[name] += line + '\n'
    return out


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = FLOW.read_text(encoding='utf-8')
        self.code = '\n'.join(l for l in self.text.split('\n') if not l.lstrip().startswith('#'))

    def test_four_checks_named_and_runnable(self):
        js = jobs(self.code)
        self.assertEqual(sorted(js), sorted(run_all.PARTS))
        for name, body in js.items():
            self.assertRegex(body, rf'(?m)^    name: {name}$', f'{name} 的显示名要和编号一样（分支保护按名字认）')
            runs = re.findall(r'run: (uv run python tests/run_all\.py .*)', body)
            self.assertEqual(len(runs), 1, name)
            args = runs[0].split()[4:]
            self.assertEqual([a for a in args if a != '--no-skip'], [name], f'{name} 只跑自己那一部分')
            if name in ('unit', 'sandbox'):
                self.assertIn('--no-skip', args, f'{name} 在 GitHub 上不许悄悄跳过')
            self.assertIn('run: tests/ci/prepare.sh', body)
            self.assertIn('runs-on: ubuntu-26.04', body, '工具包只支持 Ubuntu 26.04，不用会自己换系统的 ubuntu-latest')

    def test_actions_pinned_to_commits(self):
        uses = re.findall(r'uses: (\S+)', self.code)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r'^[\w.-]+/[\w.-]+@[0-9a-f]{40}$', f'{u} 要钉在提交编号上')

    def test_permissions_triggers_secrets(self):
        self.assertRegex(self.code, r'\npermissions:\n  contents: read\n')
        self.assertNotIn('write', re.search(r'\npermissions:\n((?:  .*\n)+)', self.code).group(1))
        self.assertNotIn('pull_request_target', self.code)
        self.assertEqual(set(re.findall(r'secrets\.([A-Za-z0-9_]+)', self.code)), {'WT_DEPLOY_KEY'})
        self.assertEqual(self.code.count('persist-credentials: false'), self.code.count('actions/checkout@'))

    def test_host_keys_fetched_with_token(self):
        """3-63：取 GitHub 主机钥匙的接口不带凭据会按共用地址限次数被拒（403），要用这次检查自带的只读 github.token。"""
        js = jobs(self.code)
        for name in ('unit', 'sandbox'):
            self.assertRegex(js[name], r'(?m)^          GITHUB_TOKEN: \$\{\{ github\.token \}\}$', name)
        for name in ('checks', 'docs'):
            self.assertNotIn('GITHUB_TOKEN', js[name], f'{name} 不取钥匙，不给凭据')
        code = '\n'.join(l for l in PREPARE.read_text(encoding='utf-8').split('\n') if not l.lstrip().startswith('#'))
        i = code.index('https://api.github.com/meta')
        self.assertIn('Authorization: Bearer %s', code[i - 300:i])
        self.assertIn('-K -', code[i - 100:i], '凭据经标准输入给 curl，不放在命令行上')
        self.assertIn('unset GITHUB_TOKEN', code[i:], '取完钥匙就去掉凭据')
        self.assertLess(i, code.index('machine/install/wt.sh'))
        self.assertLess(code.index('unset GITHUB_TOKEN'), code.index('machine/install/wt.sh'))


class RunAllParts(unittest.TestCase):
    def test_unknown_part_refused(self):
        r = subprocess.run([sys.executable, str(REPO / 'tests' / 'run_all.py'), 'nope'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('不认识的部分', r.stderr)

    def test_doc_check_target_exists(self):
        self.assertEqual(len(run_all.DOC_CHECKS), 2)      # 章节号、步骤编号；命令和路径（3-62）
        for c in run_all.DOC_CHECKS:
            for p in c:
                if not p.startswith('-') and p != '.':
                    self.assertTrue((REPO / p).is_file(), p)
        self.assertIn('docs/设计书.md', run_all.DOCS)


class Prepare(TempHome):
    def test_refuses_outside_github_actions(self):
        env = {k: v for k, v in os.environ.items() if k not in ('GITHUB_ACTIONS', 'RUNNER_TEMP', 'GITHUB_PATH')}
        env['PATH'] = '/nonexistent'     # 就算往下走了也什么都运行不了
        before = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*'))
        for extra in ({}, {'GITHUB_ACTIONS': 'true'}, {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': str(self.tmp)}):
            r = subprocess.run(['/bin/bash', str(PREPARE)], env={**env, **extra}, capture_output=True, text=True,
                               cwd=self.tmp)
            self.assertEqual(r.returncode, 1, extra)
            self.assertIn('本机不要跑', r.stderr)
        self.assertEqual(sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*')), before)   # 什么都没写
        self.assertFalse((pathlib.Path(env['HOME']) / '.ssh').exists())

    def test_versions_pinned(self):
        text = PREPARE.read_text(encoding='utf-8')
        self.assertRegex(text, r'\nUV_VERSION=\d+\.\d+\.\d+\n')
        self.assertRegex(text, r'\nWT_VERSION=\d+\.\d+\.\d+\n')
