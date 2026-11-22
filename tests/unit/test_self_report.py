"""3-42：sop self report（kernel/selfreport.py）和去掉密钥（kernel/redact.py）。

- 每一种密钥写法、每一种个人信息都有样例，整份抹过之后一个都不剩；
- 反着试：拿掉任何一条规则，就有样例漏出来（每条规则都有只靠它才抹得掉的样例）；
- config/ai/*.env 里的值是运行时从登记文件读出来的：测试现造一个随机的值写进临时的登记文件，不写在代码里；
- 只用假 gh（tests/fakes/gh/gh），问题单记在假 gh 的 issues.json 里，不碰真 GitHub。

样例里像密钥的串都是运行时拼出来的随机串（代码里没有完整的密钥写法，免得被 GitHub 的密钥扫描当成真的）。
"""
import contextlib
import io
import json
import os
import pathlib
import random
import stat
import string
import subprocess
import unittest
from unittest import mock

from kernel import journal as J, paths, redact, selfreport as S
from kernel.errors import SopError
from tests.helpers import REPO, TempHome, make_remote_and_clone, mock_env, sh

FAKE_GH = REPO / 'tests' / 'fakes' / 'gh' / 'gh'
RNG = random.Random(3042)
LOWER = string.ascii_lowercase
LD = string.ascii_lowercase + string.digits


def rnd(n, alphabet=LD):
    return ''.join(RNG.choice(alphabet) for _ in range(n))


def mixed(n):
    """大写、小写、数字都有的随机串。"""
    s = [RNG.choice(string.ascii_uppercase), RNG.choice(LOWER), RNG.choice(string.digits)]
    s += [RNG.choice(string.ascii_letters + string.digits) for _ in range(n - 3)]
    RNG.shuffle(s)
    return ''.join(s)


# 只靠某一条规则才抹得掉的样例：(规则, 样例原文, 要抹掉的串)。
# 每个样例故意避开别的规则（例如只用小写和数字，兜底的「大小写数字都有的长串」就认不出），所以拿掉这一条就漏
KNOWN = 'svc' + rnd(21)                     # 当成 config/ai/*.env 里读出来的值（这里直接交给 Redactor）
HOME = '/srv/homes/zq' + rnd(4, LOWER)
USER = 'alice' + rnd(3, LOWER)
HOST = 'bluebox' + rnd(3, LOWER)
GITNAME = 'Wang Xiaoming'
PROJECT = 'shop' + rnd(4, LOWER)
B64 = [rnd(64, LD + '+/') for _ in range(3)]
PRIV = '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----'
PRIV_END = '-----END ' + 'OPENSSH PRIVATE KEY-----'


def samples():
    t_auth, t_tok, t_bearer = rnd(30), rnd(28), rnd(26)
    pw = 'pw' + rnd(10)
    ant = 'sk-' + 'ant-api03-' + rnd(40, LD + '_-')
    oai1, oai2 = 'sk-' + 'proj-' + rnd(40), 'sk-' + rnd(32)
    ghp, ghpat, gho = 'gh' + 'p_' + rnd(36), 'github' + '_pat_' + rnd(22) + '_' + rnd(30), 'gh' + 'o_' + rnd(36)
    aws = 'AK' + 'IA' + rnd(16, string.ascii_uppercase + string.digits)
    goog = 'AI' + 'za' + rnd(35, LOWER + '-')
    slack = 'xo' + 'xb-' + rnd(12) + '-' + rnd(24)
    jwt = 'ey' + 'J' + rnd(20) + '.ey' + 'J' + rnd(20) + '.' + rnd(25)
    env_v, json_v, yaml_v, flag_v, exp_v = rnd(14, LOWER), rnd(15, LOWER), rnd(13, LOWER), rnd(12, LOWER), rnd(16, LOWER)
    long_t = mixed(40)
    return [
        ('known', f'连到 {KNOWN} 的时候超时了', [KNOWN]),
        ('private_key', f'读到：\n{PRIV}\n' + '\n'.join(B64) + f'\n{PRIV_END}\n后面', B64),
        ('private_key', '日志从中间截断的私钥：\n' + '\n'.join(B64[1:]) + f'\n{PRIV_END}\n', B64[1:]),
        ('private_key', f'没有结尾的私钥：\n{PRIV}\n' + '\n'.join(B64), B64),
        ('auth_header', f'curl -H "Authorization: Bearer {t_auth}" https://api.example.com', [t_auth]),
        ('auth_header', f'Authorization: token {t_tok}', [t_tok]),
        ('auth_header', f'请求头里带着 Bearer {t_bearer}', [t_bearer]),
        ('url_userinfo', f'postgres://app:{pw}@db:5432/main', [pw]),
        ('anthropic', f'服务说 {ant} 不对', [ant]),
        ('openai', f'密钥 {oai1} 和 {oai2} 都试了', [oai1, oai2]),
        ('github', f'推送用的 {ghp}、{ghpat}、{gho}', [ghp, ghpat, gho]),
        ('aws', f'账号 {aws}', [aws]),
        ('google', f'地图 {goog}', [goog]),
        ('slack', f'通知 {slack}', [slack]),
        ('jwt', f'登录凭据 {jwt}', [jwt]),
        ('assignment', f'MY_DB_PASSWORD={env_v}\n{{"apiKey": "{json_v}"}}\nclient_secret: {yaml_v}\nfoo --token {flag_v}\n'
                       f"export SERVICE_AUTH='{exp_v}'", [env_v, json_v, yaml_v, flag_v, exp_v]),
        ('long_token', f'不认识的服务的密钥 {long_t} 失效了', [long_t]),
        ('email', '联系 bob.chen@corp.example.com', ['bob.chen@corp.example.com']),
        ('home', f'文件在 {HOME}/tools/sop/config', [HOME]),
        ('host', f'在 {HOST} 上跑的', [HOST]),
        ('user', f'用户 {USER} 执行的', [USER]),
        ('name', f'提交人 {GITNAME}', [GITNAME]),
        ('project', f'项目 {PROJECT} 停在 F15', [PROJECT]),
        ('ip', '代理 203.0.113.7:3128', ['203.0.113.7']),
    ]


SAMPLES = samples()          # 随机串只造一次，后面都用这一份


def redactor(skip=()):
    return redact.Redactor(known=[KNOWN], homes=[HOME], users=[USER], hosts=[HOST], names=[GITNAME], projects=[PROJECT], skip=skip)


class TestRedact(unittest.TestCase):
    def test_every_sample_is_masked(self):
        for key, text, secrets in SAMPLES:
            with self.subTest(rule=key, text=text[:40]):
                out, counts = redactor().apply(text)
                for s in secrets:
                    self.assertNotIn(s, out)
                self.assertTrue(counts)

    def test_all_together(self):
        text = '\n'.join(t for _, t, _ in SAMPLES)
        out, _ = redactor().apply(text)
        for _, _, secrets in SAMPLES:
            for s in secrets:
                self.assertNotIn(s, out)

    def test_each_rule_is_needed(self):
        """反着试：拿掉任何一条规则，它的样例就漏出来。"""
        keys = [k for k, _, _ in redactor().rules()]
        covered = {k for k, _, _ in SAMPLES}
        self.assertEqual(set(keys), covered, '每条规则都要有样例')
        for key in keys:
            with self.subTest(rule=key):
                leaked = []
                for k, text, secrets in SAMPLES:
                    if k != key:
                        continue
                    out, _ = redactor(skip={key}).apply(text)
                    leaked += [s for s in secrets if s in out]
                self.assertTrue(leaked, f'拿掉规则 {key} 之后样例一个都没漏：样例没测到这条规则')

    def test_ordinary_text_untouched(self):
        text = ('提交 0123456789abcdef0123456789abcdef01234567，会话 0b6c2f0e-1111-2222-3333-444455556666\n'
                'Python 3.14.0、Git 2.53.0、Ubuntu 26.04\n代理 http://127.0.0.1:8765\n'
                'git@github.com:C1fLly/sop.git、https://github.com/C1fLly/sop/issues/1\n'
                "KeyError: 'ai'\n" '{"input_tokens": 1234, "kind": "工具包问题"}\nPWD=/tmp/x\n'
                'File "kernel/engine.py", line 176, in step\n')
        out, counts = redactor().apply(text)
        self.assertEqual(out, text, counts)

    def test_open_private_key_keeps_rest(self):
        """没有结尾的私钥只抹它自己那几行，后面的日志不能跟着没了（第一版用「抹到最后」，整份日志后半截都没了）。"""
        text = f'{PRIV}\nProc-Type: 4,ENCRYPTED\n\n' + '\n'.join(B64) + '\n后面的日志 Traceback\n还有一行\n'
        out, _ = redactor().apply(text)
        self.assertIn('后面的日志 Traceback\n还有一行', out)
        for s in B64:
            self.assertNotIn(s, out)

    def test_idempotent(self):
        text = '\n'.join(t for _, t, _ in SAMPLES)
        once, _ = redactor().apply(text)
        twice, counts = redactor().apply(once)
        self.assertEqual(once, twice)
        self.assertEqual(counts, {})

    def test_known_value_variants(self):
        v = 'p@ss/' + rnd(10) + '"x'
        r = redact.Redactor(known=[v])
        for form in (v, json.dumps(v)[1:-1], __import__('urllib.parse').parse.quote(v, safe='')):
            self.assertNotIn(form, r.apply(f'值是 {form} 。')[0])

    def test_secret_names(self):
        for n in ('ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'apiKey', 'accessToken', 'DB_PASSWORD', 'client-secret', 'GH_TOKEN'):
            self.assertTrue(redact.name_is_secret(n), n)
        for n in ('PWD', 'OLDPWD', 'KeyError', 'input_tokens', 'GIT_AUTHOR_NAME', 'ANTHROPIC_BASE_URL', 'session_id'):
            self.assertFalse(redact.name_is_secret(n), n)


class TestEnvFile(TempHome):
    def test_values_read_at_runtime(self):
        d = paths.config_dir() / 'ai'
        d.mkdir(parents=True)
        tok, url = rnd(24), f'https://{rnd(10, LOWER)}.example.net/v1'
        (d / 'claude.env').write_text(f"# 注释\nANTHROPIC_BASE_URL='{url}'\nexport ANTHROPIC_AUTH_TOKEN=\"{tok}\"\n\nOTHER={rnd(3)}\n")
        (d / 'codex.env').write_text(f'OPENAI_API_KEY={tok}x\n')
        vals = redact.env_file_values(paths.config_dir())
        self.assertIn(tok, vals)
        self.assertIn(url, vals)
        self.assertIn(tok + 'x', vals)
        with mock.patch.object(redact, 'gh_token', lambda: None):
            r = redact.for_this_machine(paths.config_dir())
        out, _ = r.apply(f'服务 {url} 回 401，用的 {tok}')
        self.assertNotIn(tok, out)
        self.assertNotIn(url, out)


class FakeGhHome(TempHome):
    """PATH 里只放假的 gh；gh 的登记、主目录都是临时的。工具包仓库用默认的（C1fLly/sop），问题单只进假 gh 的 issues.json。"""

    def setUp(self):
        super().setUp()
        t = self.tmp
        for d in ('fakegh', 'ghcfg'):
            (t / d).mkdir()
        self.gh_token = 'gh' + 'o_' + rnd(36)
        (t / 'fakegh' / 'auth.json').write_text(json.dumps({'logged_in': True, 'scopes': ['repo'], 'token': self.gh_token}))
        self.svc_token = rnd(26, LOWER)
        self.env_token = rnd(22, LOWER)
        self._env2 = mock.patch.dict(os.environ, {'PATH': f'{FAKE_GH.parent}:{os.environ["PATH"]}', 'GH_CONFIG_DIR': str(t / 'ghcfg'),
                                                  'FAKEGH_HOME': str(t / 'fakegh'), 'ACME_SERVICE_TOKEN': self.env_token})
        self._env2.start()
        for k in ('SOP_REPORT_REPO', 'SOP_TOOLKIT_REPO'):
            os.environ.pop(k, None)
        d = paths.config_dir() / 'ai'
        d.mkdir(parents=True)
        self.url = f'https://{rnd(9, LOWER)}.example.net'
        (d / 'claude.env').write_text(f"ANTHROPIC_BASE_URL='{self.url}'\nANTHROPIC_AUTH_TOKEN='{self.svc_token}'\n")
        self.said = []

    def tearDown(self):
        self._env2.stop()
        super().tearDown()

    def issues(self):
        f = self.tmp / 'fakegh' / 'issues.json'
        return json.loads(f.read_text()) if f.exists() else []

    def run_report(self, argv, answers=(), tty=False, project=None):
        ans = list(answers)
        with mock.patch.object(S, 'find_project', lambda: None):
            return S.run(argv, ask=lambda q: (self.said.append(f'问：{q}'), ans.pop(0))[1], say=self.said.append, tty=tty,
                         project=project)

    def log_file(self):
        f = self.tmp / 'step.log'
        text = '\n'.join(t for _, t, _ in SAMPLES)
        f.write_text(f'{text}\n服务地址 {self.url}\n密钥 {self.svc_token}\n环境变量里的 {self.env_token}\ngh 的 {self.gh_token}\n'
                     f'主目录 {os.environ["HOME"]}/x\n')
        return f

    def secrets(self):
        return [s for _, _, ss in SAMPLES for s in ss if s not in (HOME, USER, HOST, GITNAME, PROJECT, KNOWN)] + \
            [self.url, self.svc_token, self.env_token, self.gh_token, os.environ['HOME']]

    def draft(self):
        return sorted(paths.sop_home().joinpath('reports').glob('*.md'))[-1]


class TestReport(FakeGhHome):
    def test_report_with_yes(self):
        rc = self.run_report(['--text', '执行 sop 时停在 F15，说门禁连报告都没写出来', '--log', str(self.log_file()), '--yes'])
        self.assertEqual(rc, 0, self.said)
        iss = self.issues()
        self.assertEqual(len(iss), 1)
        self.assertEqual(iss[0]['repo'], 'C1fLly/sop')
        body = iss[0]['body']
        for s in self.secrets():
            self.assertNotIn(s, body)
            self.assertNotIn(s, iss[0]['title'])
        head = sh('git', '-C', REPO, 'rev-parse', 'HEAD', env={'GIT_OPTIONAL_LOCKS': '0'})
        self.assertIn(head, body)
        self.assertIn('门禁连报告都没写出来', iss[0]['title'])
        for part in ('## 现象', '## 工具包版本', '## 电脑', '## 附上的日志', '## 自动抹掉的'):
            self.assertIn(part, body)
        self.assertIn('[已抹掉：密钥]', body)
        d = self.draft()
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(d.parent.stat().st_mode), 0o700)
        self.assertEqual(json.loads(S.sent_file(d).read_text())['url'], 'https://github.com/C1fLly/sop/issues/1')
        self.assertTrue(any('issues/1' in x for x in self.said))
        with self.assertRaises(SopError):            # 同一份不重复登记
            self.run_report(['--send', str(d), '--yes'])
        self.assertEqual(len(self.issues()), 1)

    def test_not_tty_only_draft(self):
        rc = self.run_report(['--text', '体检崩了', '--log', str(self.log_file())])
        self.assertEqual(rc, 0)
        self.assertEqual(self.issues(), [])
        d = self.draft()
        text = d.read_text()
        for s in self.secrets():
            self.assertNotIn(s, text)
        self.assertTrue(any('--send' in x for x in self.said), self.said)
        self.assertEqual(self.run_report(['--send', str(d)]), 0)        # 还是不在终端里、没 --yes：不登记
        self.assertEqual(self.issues(), [])
        self.assertEqual(self.run_report(['--send', str(d), '--yes']), 0)
        self.assertEqual(len(self.issues()), 1)

    def test_tty_asks(self):
        self.assertEqual(self.run_report([], answers=['我在建项目', ''], tty=True), 0)    # 先问现象，再问登不登记：回车 = 不登记
        self.assertEqual(self.issues(), [])
        self.assertTrue(any('公开' in x for x in self.said if x.startswith('问：')))
        self.assertIn('我在建项目', self.draft().read_text())
        self.assertEqual(self.run_report(['--send', str(self.draft())], answers=['y'], tty=True), 0)
        self.assertEqual(len(self.issues()), 1)

    def test_send_redacts_edited_draft(self):
        self.run_report(['--text', '体检崩了'])
        d = self.draft()
        extra = 'sk-' + 'proj-' + rnd(40)
        d.write_text(d.read_text() + f'\n我补一句：用的密钥是 {extra}，服务 {self.url}\n')
        self.assertEqual(self.run_report(['--send', str(d), '--yes']), 0)
        body = self.issues()[0]['body']
        self.assertNotIn(extra, body)
        self.assertNotIn(self.url, body)
        self.assertNotIn(extra, d.read_text())
        self.assertTrue(any('又抹掉了' in x for x in self.said))

    def test_gh_not_logged_in(self):
        (self.tmp / 'fakegh' / 'auth.json').write_text(json.dumps({'logged_in': False}))
        with self.assertRaises(SopError) as c:
            self.run_report(['--text', 'x', '--yes'])
        self.assertIn('登记问题单', str(c.exception))
        self.assertFalse(S.sent_file(self.draft()).exists())
        self.assertEqual(self.issues(), [])

    def test_not_github(self):
        os.environ['SOP_TOOLKIT_REPO'] = str(self.tmp / 'toolkit.git')
        self.assertEqual(self.run_report(['--text', 'x', '--yes']), 0)
        self.assertEqual(self.issues(), [])
        self.assertTrue(any('不在 GitHub 上' in x for x in self.said))

    def test_bad_args(self):
        with self.assertRaises(SopError):
            self.run_report(['--bogus'])
        with self.assertRaises(SopError):
            self.run_report(['--log', str(self.tmp / 'nope.log')])

    def test_slug(self):
        for url in ('https://github.com/C1fLly/sop.git', 'git@github.com:C1fLly/sop.git', 'https://github.com/C1fLly/sop'):
            self.assertEqual(S.github_slug(url), 'C1fLly/sop')
        self.assertIsNone(S.github_slug('/tmp/sop.git'))

    def test_cli_dispatch(self):
        from kernel import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(S, 'find_project', lambda: None), \
                mock.patch('sys.stdin', io.StringIO()):
            rc = cli.main(['self', 'report', '--text', '从命令行'])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn('问题单草稿', out.getvalue())
        self.assertEqual(self.issues(), [])


class TestReportInProject(FakeGhHome):
    def test_project_events_and_errors(self):
        from kernel.project import Project
        remote, gitdir = make_remote_and_clone(self.tmp, name=PROJECT)
        seed = self.tmp / 'seed'
        (seed / 'sop.json').write_text(json.dumps({'toolkit': {'repo': 'https://github.com/C1fLly/sop.git', 'version': 'abc1234'},
                                                   'visibility': 'private'}))
        sh('git', 'add', '.', cwd=seed); sh('git', 'commit', '-qm', 'sop.json', cwd=seed); sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=seed)
        sh('git', '--git-dir', gitdir, 'fetch', '-q', 'origin')
        (gitdir.parent / '.shared').mkdir()
        p = Project(gitdir.parent)
        p.journal.init_branch()
        p.journal.append(J.event(f'feature/x-1', 'F15', 'failed', reason='门禁连报告都没写出来', hold=True),
                         J.event('feature/x-1', 'F15', 'note', kind='工具包问题', text=f'token={self.env_token} 在 {os.environ["HOME"]}'))
        p.journal.close()
        (p.state / 'runs').mkdir(parents=True)
        (p.state / 'runs' / 'error-1.txt').write_text(f'Traceback (most recent call last):\n  File "x.py"\nRuntimeError: 连 {self.url} 用 {self.svc_token}\n')
        rc = self.run_report(['--yes'], project=p)
        self.assertEqual(rc, 0, self.said)
        iss = self.issues()
        self.assertEqual(len(iss), 1)
        body = iss[0]['body']
        self.assertIn('门禁连报告都没写出来', body)
        self.assertIn('error-1.txt', body)
        self.assertIn('RuntimeError', iss[0]['title'])
        self.assertIn('abc1234', body)
        self.assertNotIn(PROJECT, body + iss[0]['title'])          # 私有项目的名字也抹掉
        self.assertIn('<项目名>', body)
        for s in (self.env_token, self.url, self.svc_token, os.environ['HOME']):
            self.assertNotIn(s, body)


if __name__ == '__main__':
    unittest.main()
