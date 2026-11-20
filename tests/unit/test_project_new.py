"""3-23：sop project new 的本机部分（kernel/projectnew.py，设计书 7.2 的 I0、I1、I3、I4）和目录结构检查（checks/project_layout）。

- 装哪些技能：附录 B 直接列的，加上从技能原文里查出来的被依赖的，正好是附录 B 那 21 个。
- 复制出来的技能和工具包副本逐字一致：按 Git 的算法算每个技能目录的树编号，和 skills/source.json 里记的上游指纹算出来的比，
  提交以后再用 Git 自己的 rev-parse 比一次；许可文件同样比。
- 全过程：剧本里的人回答 I0、I1；I2 用本机的 wt（只用不改）在 /tmp 的假远程上代替 GitHub（3-24 才接真的）；
  主目录、TMPDIR 都指到临时目录，PATH 里的 gh 是只记账的假的。
- 命中红线时停下，GitHub 那一边一次都没被调用，项目根没建。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest

from checks.project_layout import check as layout_check, core
from checks.skills_pristine.check import blob_id, scan, tree_id
from kernel import paths, precheck, projectnew as P, wtx
from kernel.errors import SopError
from kernel.human import NoHuman, ScriptedHuman
from tests.helpers import REPO, TempHome, mock_env, sh

WT = shutil.which('wt')
FAKE_GH = '#!/bin/sh\necho "$*" >> "$FAKEGH_LOG"\nexit 1\n'
# 附录 B 的技能：直接列了用途的 16 个，加「随它一起安装」「内部用」的 5 个；不含 wizard（第一版不用）、setup-matt-pocock-skills（由 I4 代替）
APPENDIX_B = {'wayfinder', 'research', 'grill-with-docs', 'grilling', 'domain-modeling', 'handoff', 'to-spec', 'to-tickets',
              'implement', 'tdd', 'implement-spec', 'code-review', 'pr', 'retro', 'writing-for-agents', 'codebase-design',
              'diagnosing-bugs', 'prototype', 'triage', 'improve-codebase-architecture', 'wait-what'}
SOURCE = json.loads((REPO / 'skills' / 'source.json').read_text())


def upstream_tree(src_dir):
    """技能副本里一个技能目录在上游提交里的树编号（用 source.json 记的每个文件的指纹算）。"""
    rel = os.path.relpath(src_dir, REPO / 'skills' / 'mattpocock')
    return tree_id({k: tuple(v) for k, v in SOURCE['files'].items()}, rel)


def local_tree(d):
    files, odd = scan(d)
    assert not odd, odd
    return tree_id({'x/' + k: v for k, v in files.items()}, 'x')


def answers(**over):
    """I0、I1 的剧本：默认每问都选第一个（不碰红线），I1 选私有。"""
    s = {f'project:I0-{q["id"]}': [{'answer': str(over.get(q['id'], 1))}] for q in P.REDLINE}
    s['project:I1'] = [{'answer': str(over.get('I1', 2))}]
    return s


class TestSkillList(unittest.TestCase):
    def test_install_list_is_appendix_b(self):
        got = core.install_list(str(REPO))
        self.assertEqual(set(got), APPENDIX_B)
        self.assertEqual(set(got) - set(core.WANTED), {'grilling', 'domain-modeling', 'tdd', 'codebase-design', 'writing-for-agents'})
        for n, d in got.items():                       # 去掉分类那一层：副本里是 skills/mattpocock/skills/<分类>/<技能>/
            self.assertEqual(pathlib.Path(d).parent.parent, REPO / 'skills' / 'mattpocock' / 'skills', n)

    def test_calls_found_from_skill_text(self):
        cat = core.catalog(str(REPO))
        self.assertEqual(core.calls(cat['implement'], cat), {'tdd', 'code-review'})
        self.assertEqual(core.calls(cat['grill-with-docs'], cat), {'grilling', 'domain-modeling'})
        self.assertEqual(core.calls(cat['retro'], cat), {'writing-for-agents'})
        self.assertEqual(core.calls(cat['tdd'], cat), {'codebase-design', 'code-review'})
        self.assertEqual(core.calls(cat['to-spec'], cat), set())      # 只是「没配置就让用户去运行 setup-matt-pocock-skills」，不算调用
        self.assertIn('setup-matt-pocock-skills', (pathlib.Path(cat['to-spec']) / 'SKILL.md').read_text())


class TestWriteFiles(TempHome):
    def setUp(self):
        super().setUp()
        self.d = self.tmp / 'main'
        P.write_template(self.d, 'demo', 'public', 'https://example.invalid/sop.git', 'a' * 40)
        self.installed = P.install_skills(self.d)

    def test_skills_byte_identical_to_copy(self):
        self.assertEqual(set(self.installed), APPENDIX_B)
        for n, src in core.install_list(str(REPO)).items():
            want = upstream_tree(src)
            for base in core.SKILL_DIRS:
                self.assertEqual(local_tree(self.d / base / n), want, f'{base}/{n}')
        for base in core.SKILL_DIRS:
            self.assertEqual(sorted(os.listdir(self.d / base)), sorted(APPENDIX_B))
        for f in core.LICENSE_DEST:                    # 许可文件原样带过去，放在技能目录之外
            self.assertEqual(blob_id((self.d / f).read_bytes()), SOURCE['files']['LICENSE'][1])
            self.assertFalse(f.startswith(core.SKILL_DIRS))

    def test_templates_and_agent_docs(self):
        tpl = REPO / 'templates' / 'project'
        for f in ('AGENTS.md', 'CLAUDE.md', 'GLOSSARY.md', '.gitignore', '.github/workflows/sop-check.yml',
                  '.github/workflows/sop-guard.yml', 'docs/standards/README.md'):
            self.assertEqual((self.d / f).read_bytes(), (tpl / f).read_bytes(), f)
        self.assertEqual((self.d / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        self.assertIn('## Agent skills', (self.d / 'AGENTS.md').read_text())   # setup-matt-pocock-skills 会写的那一段
        seed = pathlib.Path(core.catalog(str(REPO))['setup-matt-pocock-skills'])
        for dest, f in (('issue-tracker.md', 'issue-tracker-local.md'), ('triage-labels.md', 'triage-labels.md'), ('domain.md', 'domain.md')):
            self.assertEqual((self.d / 'docs' / 'agents' / dest).read_bytes(), (seed / f).read_bytes())
        sop = json.loads((self.d / 'sop.json').read_text())
        self.assertEqual(sop, {'project': 'demo', 'toolkit': {'repo': 'https://example.invalid/sop.git', 'version': 'a' * 40},
                               'profiles': {'stack': [], 'end': []}, 'visibility': 'public'})
        ok, line, _ = layout_check.run(str(self.d), str(REPO))
        self.assertTrue(ok, line)

    def test_no_overwrite(self):
        with self.assertRaises(SopError):
            P.install_skills(self.d)
        d2 = self.tmp / 'other'
        d2.mkdir()
        (d2 / 'AGENTS.md').write_text('别人的\n')
        with self.assertRaises(SopError):
            P.write_template(d2, 'demo', 'private', 'r', 'v')
        self.assertEqual((d2 / 'AGENTS.md').read_text(), '别人的\n')

    def test_exec_bit_kept(self):
        src = self.tmp / 'x.sh'
        src.write_text('#!/bin/sh\n')
        src.chmod(0o775)
        P._copy_file(src, self.tmp / 'y' / 'x.sh')
        P._copy_file(self.d / 'AGENTS.md', self.tmp / 'y' / 'a.md')
        self.assertEqual((self.tmp / 'y' / 'x.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.tmp / 'y' / 'a.md').stat().st_mode & 0o777, 0o644)


class LocalGitHub:
    """I2 的替身（3-24 接真的）：在 /tmp 造一个像 gh repo create --add-readme 那样带一个 README 提交的远程，再经接入层 wt init。"""

    def __init__(self, tmp):
        self.tmp, self.calls = pathlib.Path(tmp), []

    def create(self, name, root, visibility):
        self.calls.append(('create', name, visibility))
        self.remote = self.tmp / 'github' / f'{name}.git'
        seed = self.tmp / 'readme-seed'
        sh('git', 'init', '-q', '--bare', '-b', 'main', self.remote)
        sh('git', 'init', '-q', '-b', 'main', seed)
        (seed / 'README.md').write_text(f'# {name}\n')
        sh('git', '-C', seed, 'add', '-A'); sh('git', '-C', seed, 'commit', '-qm', 'Initial commit')
        sh('git', '-C', seed, 'push', '-q', self.remote, 'HEAD:main')
        wtx.init(name, root, f'tester/{name}', self.remote)

    def publish(self, root, visibility):
        self.calls.append(('publish', str(root), visibility))


class FlowBase(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.user_home = t / 'home'
        for d in (self.user_home, t / 'tmpdir', t / 'bin', t / 'projects'):
            d.mkdir()
        (self.user_home / '.gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n')
        (t / 'bin' / 'gh').write_text(FAKE_GH)
        (t / 'bin' / 'gh').chmod(0o755)
        self.ghlog = t / 'gh.log'
        self.script = t / 'human.json'
        self._env2 = mock_env({'HOME': str(self.user_home), 'TMPDIR': str(t / 'tmpdir'), 'PATH': f'{t / "bin"}:{os.environ["PATH"]}',
                               'FAKEGH_LOG': str(self.ghlog), 'SOP_TOOLS_DIR': str(t / 'tools'), 'SOP_PROJECTS_DIR': str(t / 'projects'),
                               'SOP_TOOLKIT_REPO': 'https://example.invalid/sop.git', 'GIT_CONFIG_NOSYSTEM': '1'})
        self._env2.__enter__()
        self.root = t / 'projects' / 'demo'
        self.gh = LocalGitHub(t)

    def tearDown(self):
        self._env2.__exit__(None, None, None)
        super().tearDown()

    def human(self, script):
        self.script.write_text(json.dumps(script, ensure_ascii=False))
        return ScriptedHuman('demo', str(self.script))

    def records(self):
        d = paths.state_dir('demo') / 'init'
        return {f.name: json.loads(f.read_text()) for f in d.iterdir()} if d.is_dir() else {}


@unittest.skipUnless(WT, '本机没有 wt')
class TestNewProjectFlow(FlowBase):
    def test_whole_local_part(self):
        root = P.new_project('demo', self.human(answers(I1=2)), github=self.gh)
        self.assertEqual(root, self.root)
        self.assertEqual(self.gh.calls, [('create', 'demo', 'private'), ('publish', str(self.root), 'private')])
        # 5.1 的结构：裸仓库、.shared（工具包的模板）、main/；目录结构检查（带项目根）通过
        self.assertEqual(sh('git', '--git-dir', root / '.git', 'rev-parse', '--is-bare-repository'), 'true')
        self.assertEqual(wtx.worktrees(root), ['main'])
        ok, line, _ = layout_check.run(str(root / 'main'), str(REPO), str(root))
        self.assertTrue(ok, line)
        precheck.verify('demo', root, wtx.worktrees(root))
        # 在本机提交了一次（接在 GitHub 的 README 提交后面），还没推送（I5 是 3-24 的事）
        g = ['git', '--git-dir', root / '.git']
        self.assertEqual(sh(*g, 'rev-list', '--count', 'main'), '2')
        self.assertEqual(sh(*g, 'rev-parse', 'main~1'), sh('git', '--git-dir', self.gh.remote, 'rev-parse', 'main'))
        self.assertEqual(sh('git', '-C', root / 'main', 'status', '--porcelain'), '')
        self.assertEqual(sh(*g, 'show', 'main:README.md'), '# demo')
        # 提交进去的技能：Git 自己算的树编号和上游提交里的一样
        for n, src in core.install_list(str(REPO)).items():
            for base in core.SKILL_DIRS:
                self.assertEqual(sh(*g, 'rev-parse', f'main:{base}/{n}'), upstream_tree(src), f'{base}/{n}')
        for f in core.LICENSE_DEST:
            self.assertEqual(sh(*g, 'rev-parse', f'main:{f}'), SOURCE['files']['LICENSE'][1])
        sop = json.loads(sh(*g, 'show', 'main:sop.json'))
        self.assertEqual(sop['visibility'], 'private')
        self.assertEqual(sop['toolkit'], {'repo': 'https://example.invalid/sop.git', 'version': sh('git', '-C', REPO, 'rev-parse', 'HEAD')})
        # I0、I1 的回答暂存本机
        rec = self.records()
        self.assertEqual(rec['redline.json']['hits'], [])
        self.assertEqual(set(rec['redline.json']['answers']), {q['id'] for q in P.REDLINE})
        self.assertEqual(rec['visibility.json']['visibility'], 'private')
        self.assertFalse(self.ghlog.exists())                       # 本机这几步没找 gh
        self.assertEqual(sorted(os.listdir(self.user_home)), ['.gitconfig'])
        self.assertEqual(os.listdir(self.tmp / 'tmpdir'), [])

    def test_public_recorded(self):
        P.new_project('demo', self.human(answers(I1=1)), github=self.gh)
        sop = json.loads((self.root / 'main' / 'sop.json').read_text())
        self.assertEqual(sop['visibility'], 'public')
        self.assertEqual(self.gh.calls[0], ('create', 'demo', 'public'))


class TestRedLineAndStops(FlowBase):
    def test_each_red_line_stops_before_any_repo(self):
        for q in P.REDLINE:
            for hit in q['hit']:
                with self.subTest(q=q['id'], answer=hit):
                    shutil.rmtree(paths.state_dir('demo'), ignore_errors=True)
                    with self.assertRaises(P.RedLine) as e:
                        P.new_project('demo', self.human(answers(**{q['id']: hit})), github=self.gh)
                    self.assertIn(q['service'], str(e.exception))
                    self.assertEqual(self.gh.calls, [])               # GitHub 那一边一次都没调
                    self.assertFalse(self.root.exists())
                    rec = self.records()
                    self.assertEqual([h['id'] for h in rec['redline.json']['hits']], [q['id']])
                    self.assertNotIn('visibility.json', rec)          # 命中红线就停，I1 没问

    def test_every_non_hit_answer_passes_i0(self):
        for q in P.REDLINE:
            for n in range(1, len(q['options']) + 1):
                if n in q['hit']:
                    continue
                with self.subTest(q=q['id'], answer=n):
                    shutil.rmtree(paths.state_dir('demo'), ignore_errors=True)     # 剧本用到第几条记在状态目录里
                    rec = P.ask_redlines('demo', self.human({k: v for k, v in answers(**{q['id']: n}).items() if 'I0' in k}))
                    self.assertEqual(rec['hits'], [])

    def test_github_part_not_done_yet(self):
        """默认的 GitHub 那一半还没做（3-24）：问完 I0、I1 停下，说明白，什么都没建。"""
        with self.assertRaises(SopError) as e:
            P.new_project('demo', self.human(answers()))
        self.assertIn('3-24', str(e.exception))
        self.assertFalse(self.root.exists())
        self.assertEqual(set(self.records()), {'redline.json', 'visibility.json'})

    def test_refuses_existing_root_before_asking(self):
        self.root.mkdir()
        (self.root / 'x').write_text('')
        with self.assertRaises(SopError):
            P.new_project('demo', self.human(answers()), github=self.gh)
        self.assertEqual(self.records(), {})
        self.assertEqual(self.gh.calls, [])

    def test_needs_a_person(self):
        with self.assertRaises(SopError) as e:
            P.new_project('demo', NoHuman(), github=self.gh)
        self.assertIn('终端', str(e.exception))
        self.assertEqual(self.records(), {})

    def test_needs_git_identity(self):
        (self.user_home / '.gitconfig').unlink()
        with self.assertRaises(SopError) as e:
            P.new_project('demo', self.human(answers()), github=self.gh)
        self.assertIn('提交身份', str(e.exception))
        self.assertEqual(self.gh.calls, [])
        self.assertFalse(self.root.exists())

    def test_cli(self):
        """经命令行：sop project new demo（剧本回答），问完停在 GitHub 那一步；项目名不对、参数不对时说用法。"""
        self.script.write_text(json.dumps(answers(), ensure_ascii=False))
        env = {**os.environ, 'PYTHONPATH': str(REPO), 'SOP_HUMAN_SCRIPT': str(self.script)}
        run = lambda *a: subprocess.run([sys.executable, '-m', 'kernel.cli', 'project', 'new', *a], cwd=self.tmp, env=env,   # noqa: E731
                                        capture_output=True, text=True, stdin=subprocess.DEVNULL)
        r = run('demo')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('3-24', r.stdout)
        self.assertEqual(set(self.records()), {'redline.json', 'visibility.json'})
        self.assertFalse(self.root.exists())
        for bad in (('Demo',), (), ('a', 'b')):
            self.assertEqual(run(*bad).returncode, 2)
        env.pop('SOP_HUMAN_SCRIPT')
        r = run('demo2')                                            # 没有终端、没有剧本：说要在终端里回答
        self.assertEqual(r.returncode, 1)
        self.assertIn('终端', r.stdout)


if __name__ == '__main__':
    unittest.main()
