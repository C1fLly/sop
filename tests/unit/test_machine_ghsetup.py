"""3-10：M3 登录 GitHub（machine/ghsetup.py）。
主目录 HOME、工具目录、XDG_CONFIG_HOME 都是 /tmp 下临时的；gh 是假的（tests/fakes/gh/gh，放在临时工具目录的规定位置
~/tools/gh/bin），ssh 是假的（tests/fakes/ssh/ssh）。每个测试开头先确认找到的是假的，不碰真的 GitHub 和本机的登录、SSH、gitconfig。
ssh-keygen 用真的，只往临时主目录里生成测试用的密钥，测完整个删掉。"""
import json
import os
import pathlib
import shutil
import stat
import subprocess

from machine import ghsetup
from tests.helpers import REPO, TMP_ROOT, TempHome, mock_env

FAKE_GH = REPO / 'tests' / 'fakes' / 'gh' / 'gh'
FAKE_SSH = REPO / 'tests' / 'fakes' / 'ssh' / 'ssh'
LOGIN_ARGV = ['auth', 'login', '--hostname', 'github.com', '--git-protocol', 'ssh', '--web', '--skip-ssh-key',
              '--scopes', 'admin:public_key']


def snapshot(d):
    """目录下每个文件的内容（看有没有被改）。"""
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(pathlib.Path(d).rglob('*')) if p.is_file()}


class Base(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.user_home = t / 'home'
        self.tools = t / 'tools'
        self.ghhome = t / 'fakegh'
        for d in (self.user_home, t / 'bin', self.ghhome, self.tools / 'gh' / 'bin'):
            d.mkdir(parents=True)
        os.symlink(FAKE_GH, self.tools / 'gh' / 'bin' / 'gh')
        os.symlink(FAKE_SSH, t / 'bin' / 'ssh')
        self.sshlog = t / 'ssh.log'
        self.out = open(t / 'gh-out.txt', 'w')
        self._env2 = mock_env({'HOME': str(self.user_home), 'XDG_CONFIG_HOME': str(self.user_home / '.config'),
                               'SOP_TOOLS_DIR': str(self.tools), 'FAKEGH_HOME': str(self.ghhome), 'FAKEGH_NAME': '测 试',
                               'PATH': f'{t / "bin"}:{os.environ["PATH"]}', 'FAKESSH_LOG': str(self.sshlog)})
        self._env2.__enter__()
        self.auth({'logged_in': False})
        self.said = []
        # 找到的一定是假的 gh、假的 ssh，主目录在临时目录里
        env = ghsetup.environ()
        self.assertEqual(ghsetup.gh_path(env), str(self.tools / 'gh' / 'bin' / 'gh'))
        self.assertEqual(os.path.realpath(shutil.which('ssh', path=env['PATH'])), str(FAKE_SSH))
        self.assertTrue(str(pathlib.Path.home()).startswith(str(TMP_ROOT)))
        self.assertTrue(env['HOME'].startswith(str(TMP_ROOT)))

    def tearDown(self):
        self.out.close()
        self._env2.__exit__(None, None, None)
        super().tearDown()

    def auth(self, d=None):
        f = self.ghhome / 'auth.json'
        if d is not None:
            f.write_text(json.dumps(d))
        return json.loads(f.read_text())

    def setup_(self):
        return ghsetup.setup(say=self.said.append, stdio=self.out)

    def gitconfig(self):
        f = self.user_home / '.gitconfig'
        return f.read_text() if f.exists() else ''

    def git_get(self, k):
        return subprocess.run(['git', '-C', '/', 'config', '--get', k], capture_output=True, text=True,
                              env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'}).stdout.strip()

    def logged_in(self, scopes=('gist', 'read:org', 'repo', 'admin:public_key'), keys=()):
        self.auth({'logged_in': True, 'scopes': list(scopes), 'ssh_keys': list(keys), 'protocol': 'ssh'})

    def preset_identity(self):
        (self.user_home / '.gitconfig').write_text('[user]\n\tname = 原来的名字\n\temail = me@example.invalid\n')

    def make_key(self, name='id_ed25519'):
        d = self.user_home / '.ssh'
        d.mkdir(mode=0o700, exist_ok=True)
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'old', '-f', str(d / name)], check=True)
        return d / name


class TestFresh(Base):
    def test_fresh_machine_end_to_end(self):
        res = self.setup_()
        self.assertTrue(res.ok, (res.failures, self.said))
        a = self.auth()
        # 登录：网页登录，只多要 admin:public_key；没有 workflow、delete_repo
        logins = [c for c in a['calls'] if c[:2] == ['auth', 'login']]
        self.assertEqual(logins, [LOGIN_ARGV])
        self.assertEqual(sorted(a['scopes']), ['admin:public_key', 'gist', 'read:org', 'repo'])
        self.assertNotIn('workflow', ' '.join(LOGIN_ARGV))
        # 密钥：新生成的 ed25519，私钥只有自己能读，公钥传上去了
        key = self.user_home / '.ssh' / 'id_ed25519'
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.user_home / '.ssh').stat().st_mode), 0o700)
        pub = (self.user_home / '.ssh' / 'id_ed25519.pub').read_text().split()
        self.assertEqual(pub[0], 'ssh-ed25519')
        self.assertEqual(a['ssh_keys'], [' '.join(pub[:2])])
        adds = [c for c in a['calls'] if c[:2] == ['ssh-key', 'add']]
        self.assertEqual(len(adds), 1)
        self.assertIn('--title', adds[0])
        self.assertTrue(adds[0][adds[0].index('--title') + 1].startswith('sop '))
        # 主机钥匙：从假 GitHub 取的两行
        kh = (self.user_home / '.ssh' / 'known_hosts').read_text().splitlines()
        self.assertEqual(len(kh), 2)
        self.assertTrue(all(line.startswith('github.com ') for line in kh))
        # 提交身份：按 GitHub 账号设，邮箱是不公开的那种
        self.assertEqual(self.git_get('user.name'), '测 试')
        self.assertEqual(self.git_get('user.email'), '1234567+tester@users.noreply.github.com')
        self.assertTrue(any('user.email' in s and 'noreply' in s for s in self.said))
        # SSH 一律 BatchMode、不自己记主机钥匙
        for line in self.sshlog.read_text().splitlines():
            self.assertIn('BatchMode=yes', line)
            self.assertIn('StrictHostKeyChecking=yes', line)
        self.assertEqual(res.account, 'tester')
        self.assertEqual(res.ssh_account, 'tester')
        # 再跑一次：已经合格，跳过，什么都不改
        before = snapshot(self.user_home)
        n = len(self.auth()['calls'])
        res2 = self.setup_()
        self.assertTrue(res2.ok)
        self.assertTrue(any('跳过' in s for s in self.said))
        self.assertEqual(snapshot(self.user_home), before)
        new_calls = self.auth()['calls'][n:]
        self.assertTrue(all(c[:2] == ['auth', 'status'] for c in new_calls), new_calls)

    def test_name_falls_back_to_login(self):
        with mock_env({'FAKEGH_NAME': ''}):
            res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual(self.git_get('user.name'), 'tester')

    def test_check_only_changes_nothing(self):
        before = snapshot(self.user_home)
        res = ghsetup.check()
        self.assertFalse(res.ok)
        text = '\n'.join(res.failures)
        self.assertIn('gh 还没登录', text)
        self.assertIn('SSH 连不通', text)
        self.assertIn('提交身份没设', text)
        self.assertEqual(snapshot(self.user_home), before)
        self.assertFalse([c for c in self.auth().get('calls', []) if c[:2] != ['auth', 'status']])

    def test_login_cancelled_changes_nothing(self):
        with mock_env({'FAKEGH_LOGIN_FAIL': '1'}):
            res = self.setup_()
        self.assertFalse(res.ok)
        self.assertTrue(any('网页登录没完成' in s for s in self.said))
        self.assertFalse((self.user_home / '.ssh').exists())
        self.assertEqual(self.gitconfig(), '')

    def test_no_gh(self):
        os.unlink(self.tools / 'gh' / 'bin' / 'gh')
        env = ghsetup.environ()
        env['PATH'] = f'{self.tools / "gh" / "bin"}:{self.tmp / "bin"}'      # 连 /usr/bin 的 gh 也看不到
        res = ghsetup.check(env)
        self.assertFalse(res.ok)
        self.assertIn('还没装 gh', res.failures[0])


class TestExisting(Base):
    def test_existing_identity_untouched(self):
        self.preset_identity()
        before = self.gitconfig()
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual(self.gitconfig(), before)
        self.assertFalse(any('提交身份' in s for s in self.said))

    def test_only_email_missing(self):
        (self.user_home / '.gitconfig').write_text('[user]\n\tname = 原来的名字\n')
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual(self.git_get('user.name'), '原来的名字')
        self.assertEqual(self.git_get('user.email'), '1234567+tester@users.noreply.github.com')

    def test_existing_key_not_overwritten(self):
        key = self.make_key()
        before = (key.read_bytes(), key.with_suffix('.pub').read_bytes())
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual((key.read_bytes(), key.with_suffix('.pub').read_bytes()), before)
        self.assertEqual(self.auth()['ssh_keys'], [' '.join(before[1].decode().split()[:2])])
        self.assertFalse(any('生成了' in s for s in self.said))

    def test_other_key_type_kept_and_new_one_added(self):
        rsa = self.make_key('id_rsa')       # 名字叫 id_rsa（内容是什么不要紧），工具包不动它，另生成 id_ed25519
        before = rsa.read_bytes()
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual(rsa.read_bytes(), before)
        self.assertTrue((self.user_home / '.ssh' / 'id_ed25519').exists())

    def test_half_key_is_left_alone(self):
        d = self.user_home / '.ssh'
        d.mkdir(mode=0o700)
        (d / 'id_ed25519').write_text('我的私钥\n')
        self.logged_in()
        self.preset_identity()
        (d / 'known_hosts').write_text('github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n')
        res = self.setup_()
        self.assertFalse(res.ok)
        self.assertTrue(any('只有一个' in s for s in self.said))
        self.assertEqual((d / 'id_ed25519').read_text(), '我的私钥\n')
        self.assertFalse((d / 'id_ed25519.pub').exists())
        self.assertEqual(self.auth()['ssh_keys'], [])

    def test_known_hosts_only_appended(self):
        d = self.user_home / '.ssh'
        d.mkdir(mode=0o700)
        old = 'example.com ssh-ed25519 AAAAOLD\n|1|hashed|entry= ssh-rsa AAAAB'       # 最后一行没有换行
        (d / 'known_hosts').write_text(old)
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        text = (d / 'known_hosts').read_text()
        self.assertTrue(text.startswith(old + '\n'))
        self.assertEqual(len(text.splitlines()), 4)
        # 再补一次不会重复
        self.assertEqual(ghsetup.add_known_hosts(ghsetup.host_keys(ghsetup.environ())), 0)

    def test_old_login_without_key_scope_gets_refreshed(self):
        self.logged_in(scopes=('gist', 'read:org', 'repo'))
        res = self.setup_()
        self.assertTrue(res.ok, res.failures)
        calls = self.auth()['calls']
        self.assertFalse([c for c in calls if c[:2] == ['auth', 'login']])
        self.assertIn(['auth', 'refresh', '--hostname', 'github.com', '--scopes', 'admin:public_key'], calls)
        self.assertEqual(len([c for c in calls if c[:2] == ['ssh-key', 'add']]), 2)    # 第一次缺权限，补了再传

    def test_key_already_on_account(self):
        key = self.make_key()
        pub = ' '.join(key.with_suffix('.pub').read_text().split()[:2])
        self.logged_in(keys=[pub])
        self.preset_identity()
        res = self.setup_()        # 只缺主机钥匙
        self.assertTrue(res.ok, res.failures)
        self.assertFalse([c for c in self.auth()['calls'] if c[:2] == ['ssh-key', 'add']])


class TestCheck(Base):
    def ready(self, scopes=('gist', 'read:org', 'repo', 'admin:public_key')):
        self.setup_()
        a = self.auth()
        a['scopes'] = list(scopes)
        self.auth(a)

    def test_wide_scopes_only_warn(self):
        self.ready(scopes=('gist', 'read:org', 'repo', 'workflow', 'delete_repo'))
        res = ghsetup.check()
        self.assertTrue(res.ok, res.failures)
        self.assertEqual(len(res.warnings), 1)
        self.assertIn('delete_repo、workflow', res.warnings[0])
        self.assertIn('提醒', '\n'.join(ghsetup.report(res)))

    def test_ssh_other_account(self):
        self.ready()
        with mock_env({'FAKESSH_LOGIN': 'someone-else'}):
            res = ghsetup.check()
        self.assertFalse(res.ok)
        self.assertIn('someone-else', res.failures[0])

    def test_ssh_network(self):
        self.ready()
        with mock_env({'FAKESSH_MODE': 'timeout'}):
            res = ghsetup.check()
            self.assertEqual(res.ssh_problem, 'network')
            self.assertIn('22 端口', res.failures[0])
            # 网络不通时引导不去生成、上传密钥
            n = len(self.auth()['calls'])
            ghsetup.setup(say=self.said.append, stdio=self.out)
            self.assertFalse([c for c in self.auth()['calls'][n:] if c[:1] == ['ssh-key']])

    def test_logged_out_later(self):
        self.ready()
        a = self.auth()
        a['logged_in'] = False
        self.auth(a)
        res = ghsetup.check()
        self.assertFalse(res.ok)
        self.assertIn('gh 还没登录', res.failures[0])

    def test_report(self):
        self.ready()
        lines = ghsetup.report(ghsetup.check())
        self.assertIn('通过', lines[0])
        self.assertIn('tester', lines[0])

    def test_main_usage(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ghsetup.main(['--bad']), 2)
