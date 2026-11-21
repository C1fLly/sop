"""流程沙箱：sop machine setup 把 M2 到 M7 串起来（设计书 4.5；任务 3-12）。三种剧本：顺利、中途断、某步不过。

整个「电脑」都是临时的：主目录 HOME、XDG_CONFIG_HOME、工具目录、工具包根目录都在 /tmp/sop-test 下；
环境变量从零拼（不继承本机终端里的 PATH、ANTHROPIC_ 开头的密钥），PATH 只有一个放假程序的目录加系统目录。
- 工具清单换成假的（tests/fakes/machine/tools.toml，经 SOP_TOOLS_TOML），安装脚本是假的：不连网、不要管理员密码；
- gh 是假的（假安装脚本把 tests/fakes/gh/gh 放到规定位置），ssh、claude、sudo 都是假的；wt 是假的（tests/fakes/machine/wt）；
- M4 的自检照样在真的受限环境（bubblewrap）里跑假的 claude，不花钱；M6 的隔离自检用假的（tests/fakes/selftest）；
- M7 写的是临时主目录里的全局规则文件。
sop machine setup 在新会话里跑（没有控制终端），所以 M4 问密钥时 getpass 从标准输入读，回答从标准输入给。
每个测试开头先确认找到的都是假的、主目录是临时的。"""
import json
import os
import re
import pathlib
import shutil
import signal
import subprocess
import sys
import time

from tests import safehome
from tests.helpers import REPO, TMP_ROOT, TempHome

FAKES = REPO / 'tests' / 'fakes'
TOKEN = 'fake-token-3-12-abcdefgh'
ANSWERS = f'1\nhttps://ok.fake.invalid\n{TOKEN}\n\n'      # M4：自己配的服务、地址、密钥、密钥填在默认那一项
M2_ALL = ['uv', 'nvm', 'node', 'pnpm', 'gh', 'docker']


class SetupCase(TempHome):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.user_home = t / 'home'
        self.tools = t / 'tools'
        self.scen = t / 'scenario'
        self.fakegh = t / 'fakegh'
        self.bin = t / 'bin'
        for d in (self.user_home, self.tools, self.scen, self.fakegh, self.bin, t / 'tmp'):
            d.mkdir()
        os.symlink(FAKES / 'ssh' / 'ssh', self.bin / 'ssh')
        os.symlink(FAKES / 'machine' / 'sudo', self.bin / 'sudo')
        shutil.copy(FAKES / 'claude' / 'claude', self.bin / 'claude')
        (self.fakegh / 'auth.json').write_text(json.dumps({'logged_in': False}))
        (self.user_home / '.bashrc').write_text('# 用户原来的终端启动文件\nalias ll="ls -l"\n')
        self.selftest(True)
        self.env = {
            'HOME': str(self.user_home), 'XDG_CONFIG_HOME': str(self.user_home / '.config'), 'USER': os.environ.get('USER', 'tester'),
            'LOGNAME': os.environ.get('USER', 'tester'), 'LANG': 'C.UTF-8', 'TMPDIR': str(t / 'tmp'),
            'PATH': f'{self.bin}:/usr/local/bin:/usr/bin:/bin',
            'SOP_HOME': str(self.home), 'SOP_RUNTIME_DIR': str(t / 'run'), 'SOP_TOOLS_DIR': str(self.tools),
            'SOP_TOOLS_TOML': str(FAKES / 'machine' / 'tools.toml'), 'FAKE_SETUP_DIR': str(self.scen),
            'FAKEGH_HOME': str(self.fakegh), 'FAKEGH_NAME': '测 试', 'FAKESSH_LOG': str(t / 'ssh.log'),
            'SOP_SELFTEST_CMD': str(FAKES / 'selftest' / 'selftest'), 'SOP_FAKE_SELFTEST': str(self.scen / 'selftest.json'),
        }
        self.assert_all_fake()

    # ---------- 确认找到的都是假的 ----------
    def assert_all_fake(self):
        p = self.env['PATH']
        self.assertEqual(os.path.realpath(shutil.which('claude', path=p)), str(self.bin / 'claude'))
        self.assertEqual(os.path.realpath(shutil.which('ssh', path=p)), str(FAKES / 'ssh' / 'ssh'))
        self.assertEqual(os.path.realpath(shutil.which('sudo', path=p)), str(FAKES / 'machine' / 'sudo'))
        self.assertFalse(any(k.startswith(('ANTHROPIC_', 'CLAUDE_', 'GH_', 'GITHUB_')) for k in self.env))
        for k in ('HOME', 'XDG_CONFIG_HOME', 'SOP_HOME', 'SOP_TOOLS_DIR', 'TMPDIR'):
            self.assertTrue(self.env[k].startswith(str(TMP_ROOT) + '/'), k)
        # 规定位置的 gh 在 PATH 最前面（shellenv.environ 加的），装好以后找到的是假的那一份
        out = subprocess.run([sys.executable, '-I', '-c',
                              'import sys; sys.path.insert(0, sys.argv[1]); from machine import shellenv; print(shellenv.environ()["PATH"])',
                              str(REPO)], env=self.env, capture_output=True, text=True).stdout.strip()
        self.assertTrue(out.startswith(str(self.tools)), out)

    # ---------- 剧本 ----------
    def selftest(self, ok):
        (self.scen / 'selftest.json').write_text(json.dumps({'pass': ok, 'log': str(self.scen / 'selftest.log'),
                                                             'journal': str(self.tmp / 'no-journal.git')}))

    def setup(self, *args, answers=ANSWERS, timeout=300):
        cmd = [sys.executable, '-I', str(REPO / 'kernel' / 'main.py'), 'machine', 'setup', *args]
        p = subprocess.Popen(cmd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)      # 新会话：没有控制终端，getpass 从标准输入读
        try:
            out, err = p.communicate(answers, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)                       # 连它带起的子进程一起结束
            out, err = p.communicate()
            self.fail(f'sop machine setup {timeout} 秒没结束：\n{out[-4000:]}\n{err[-2000:]}')
        r = subprocess.CompletedProcess(cmd, p.returncode, out, err)
        if os.environ.get('SOP_SHOW'):
            print(r.stdout[-6000:], r.stderr[-3000:])
        return r

    def setup_until(self, marker, answers=ANSWERS, timeout=120):
        """执行 sop machine setup，等 marker 文件出现时强制结束整组进程（模仿断电、关了终端）。返回输出。"""
        cmd = [sys.executable, '-I', str(REPO / 'kernel' / 'main.py'), 'machine', 'setup']
        p = subprocess.Popen(cmd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True)
        p.stdin.write(answers)
        p.stdin.close()
        t0 = time.time()
        while time.time() - t0 < timeout and p.poll() is None and not marker.exists():
            time.sleep(0.2)
        hit = marker.exists()
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
        out = p.stdout.read()
        p.stdout.close()
        p.wait()
        self.assertTrue(hit, out[-3000:])
        return out

    # ---------- 看结果 ----------
    def installs(self):
        f = self.scen / 'installs.log'
        return f.read_text().split() if f.exists() else []

    def lines(self, name):
        f = self.scen / name
        return f.read_text().splitlines() if f.exists() else []

    def auth(self):
        return json.loads((self.fakegh / 'auth.json').read_text())

    def ai_cost(self, r):
        """这一次 sop machine setup 在 AI 自检上花了多少（屏幕上最后那句）。假的 claude 每调一次报 0.0123 美元，
        所以大于 0 就是真调了（在这台「电脑」上，调的是假的）、等于 0 就是没调。"""
        m = re.findall(r'这次在 AI 自检上一共花了 (\d+\.\d+) 美元', r.stdout)
        self.assertTrue(m, r.stdout[-3000:])
        return float(m[-1])

    def tools_json(self):
        f = self.home / 'config' / 'tools.json'
        return json.loads(f.read_text()).get('tools', {}) if f.exists() else {}

    def progress(self):
        return json.loads((self.home / 'config' / 'setup.json').read_text())

    def rules(self):
        return (self.user_home / '.claude' / 'CLAUDE.md').read_text()

    def snapshot(self, *dirs):
        out = {}
        for d in dirs:
            for p in sorted(pathlib.Path(d).rglob('*')):
                if p.is_file() and not p.is_symlink():
                    st = p.stat()
                    out[str(p)] = (st.st_mtime_ns, p.read_bytes())
        return out

    def assertOk(self, r):
        self.assertEqual(r.returncode, 0, r.stdout[-5000:] + r.stderr[-3000:])

    def assertNoSecret(self, text):
        self.assertNotIn(TOKEN, text)


class TestHappy(SetupCase):
    def test_fresh_then_again(self):
        """全新的电脑：M2 到 M7 一步一步做完、每步出口检查通过；再执行一次全部跳过，不再真调 AI、不再跑隔离自检，什么都不改。"""
        r = self.setup()
        self.assertOk(r)
        out = r.stdout
        # 六步按先后做，每步「做好了，出口检查通过」
        idx = [out.index(f'】{c} ') for c in ('M2', 'M3', 'M4', 'M5', 'M6', 'M7')]
        self.assertEqual(idx, sorted(idx))
        for c in ('M2', 'M3', 'M4', 'M5', 'M6', 'M7'):
            self.assertIn(f'{c} ', out)
        self.assertEqual(out.count('做好了，出口检查通过'), 6, out[-4000:])
        self.assertIn('这台电脑装好了', out)
        self.assertIn('sop machine doctor', out)
        # M2：假安装脚本每样装了一次，都在规定位置；终端启动文件原来的字没动、末尾加了那一段；缓存目录建了
        self.assertEqual(self.installs(), M2_ALL + ['wt'])
        self.assertTrue((self.tools / 'gh' / 'bin' / 'gh').exists())
        rc = (self.user_home / '.bashrc').read_text()
        self.assertTrue(rc.startswith('# 用户原来的终端启动文件\nalias ll="ls -l"\n'))
        self.assertIn('SOP 工具包管理的段落', rc)
        self.assertTrue((self.tools / 'cache' / 'pnpm').is_dir())
        # M3：网页登录一次、生成密钥并传上去、提交身份按账号设
        a = self.auth()
        self.assertEqual(len([c for c in a['calls'] if c[:2] == ['auth', 'login']]), 1)
        self.assertEqual(len(a['ssh_keys']), 1)
        self.assertTrue((self.user_home / '.ssh' / 'id_ed25519').exists())
        self.assertIn('users.noreply.github.com', (self.user_home / '.gitconfig').read_text())
        # M4：登记文件 0600，自检真跑了一次（假 claude），花了钱照实说；密钥不出现在屏幕上
        env = self.home / 'config' / 'ai' / 'claude.env'
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertIn('https://ok.fake.invalid', env.read_text())
        self.assertTrue(self.tools_json()['claude']['probe_ok'])
        self.assertNoSecret(out + r.stderr)
        self.assertAlmostEqual(self.ai_cost(r), 0.0123)
        # M5：wt 装好、wt doctor 跑过；M6：隔离自检跑了一次、登记记下了；M7：全局规则写了
        self.assertTrue((self.tools / 'wt' / 'wt').exists())
        self.assertGreaterEqual(len(self.lines('wt.log')), 1)
        self.assertEqual(len(self.lines('selftest.log')), 1)
        self.assertTrue((self.home / 'config' / 'system.json').exists())
        self.assertIn('SOP 工具包管理的段落', self.rules())
        self.assertEqual(self.lines('sudo.log'), [])            # 没走到要管理员密码的那一步
        prog = self.progress()
        self.assertNotIn('running', prog)
        self.assertEqual(prog['last']['result'], 'ok')
        self.assertEqual(sorted(prog['passed']), ['M2', 'M3', 'M4', 'M5', 'M6', 'M7'])

        # 再执行一次：全部「已经合格，跳过」；不装、不登录、不真调 AI、不跑隔离自检；文件一个没改
        before = self.snapshot(self.user_home, self.tools)
        r2 = self.setup(answers='')
        self.assertOk(r2)
        self.assertEqual(r2.stdout.count('已经合格，跳过'), 6, r2.stdout[-4000:])
        self.assertIn('这次不再真调 AI', r2.stdout)
        self.assertEqual(self.ai_cost(r2), 0)
        self.assertEqual(self.installs(), M2_ALL + ['wt'])
        self.assertEqual(len([c for c in self.auth()['calls'] if c[:2] == ['auth', 'login']]), 1)
        self.assertEqual(len(self.lines('selftest.log')), 1)
        self.assertEqual(self.snapshot(self.user_home, self.tools), before)

        # --recheck：M4 真调一次、M6 重跑一次，别的照样跳过
        r3 = self.setup('--recheck', answers='')
        self.assertOk(r3)
        self.assertAlmostEqual(self.ai_cost(r3), 0.0123)
        self.assertEqual(len(self.lines('selftest.log')), 2)
        self.assertEqual(self.installs(), M2_ALL + ['wt'])

    def test_ai_changed_then_real_call(self):
        """M4 合格过：登记文件换了（重填了密钥），或者 Claude Code 升级了，下次就真调一次；没变就不调。"""
        self.assertOk(self.setup())
        time.sleep(0.01)
        env = self.home / 'config' / 'ai' / 'claude.env'
        env.write_text(env.read_text())          # 内容一样、修改时间变了：算「变了」
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertNotIn('这次不再真调 AI', r.stdout)
        self.assertAlmostEqual(self.ai_cost(r), 0.0123)
        # 升级 Claude Code（假的 claude 换个版本号）
        exe = self.bin / 'claude'
        exe.write_text(exe.read_text().replace("print('9.9.9 (Claude Code)')", "print('9.9.10 (Claude Code)')"))
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertAlmostEqual(self.ai_cost(r), 0.0123)
        self.assertEqual(self.tools_json()['claude']['probed_version'], '9.9.10')
        # 机器级登记里最近一次自检没通过（例如推进流程时自检失败过）：真调
        tj = self.home / 'config' / 'tools.json'
        d = json.loads(tj.read_text())
        d['tools']['claude']['probe_ok'] = False
        tj.write_text(json.dumps(d))
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertAlmostEqual(self.ai_cost(r), 0.0123)
        # 什么都没变：不调
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertIn('这次不再真调 AI', r.stdout)
        self.assertEqual(self.ai_cost(r), 0)


class TestInterrupted(SetupCase):
    def test_killed_during_m2_then_resume(self):
        """M2 装 Node 时整组进程被强制结束（关了终端、断电）。再执行：先说上次断在 M2；uv、nvm 不重装，从 Node 接着装，做完全部。"""
        (self.scen / 'hang-node').touch()
        out = self.setup_until(self.scen / 'hanging-node')
        self.assertIn('M2 安装工具', out)
        self.assertEqual(self.installs(), ['uv', 'nvm', 'node'])
        self.assertEqual(self.progress()['running']['step'], 'M2')
        self.assertFalse((self.tools / 'nvm' / 'bin' / 'node').exists())       # 装到一半，规定位置没有半截的
        self.assertEqual(self.auth()['calls'] if 'calls' in self.auth() else [], [])   # 还没到 M3

        r = self.setup()
        self.assertOk(r)
        self.assertIn('上次执行 sop machine setup 时，「M2 安装工具」那一步没做完就断了', r.stdout)
        self.assertIn('uv：已经装好了', r.stdout)
        self.assertEqual(self.installs(), ['uv', 'nvm', 'node', 'node', 'pnpm', 'gh', 'docker', 'wt'])
        self.assertIn('这台电脑装好了', r.stdout)
        self.assertNotIn('running', self.progress())

    def test_killed_during_m5_then_resume(self):
        """M5 装 wt 时被强制结束：M2 到 M4 已经做好。再执行：M2 到 M4 跳过（不重装、不再登录、不再真调 AI），从 M5 接着做完。"""
        (self.scen / 'hang-wt').touch()
        self.setup_until(self.scen / 'hanging-wt')
        self.assertEqual(self.progress()['running']['step'], 'M5')
        self.assertEqual(sorted(self.progress()['passed']), ['M2', 'M3', 'M4'])
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertIn('「M5 安装 wt」那一步没做完就断了', r.stdout)
        out = r.stdout
        for c in ('M2 安装工具', 'M3 登录 GitHub', 'M4 登录 AI 工具'):
            self.assertIn(f'{c}：已经合格，跳过', out)
        self.assertIn('M5 安装 wt：做好了', out)
        self.assertEqual(self.installs(), M2_ALL + ['wt', 'wt'])
        self.assertEqual(self.ai_cost(r), 0)
        self.assertEqual(len([c for c in self.auth()['calls'] if c[:2] == ['auth', 'login']]), 1)
        self.assertEqual(len(self.lines('selftest.log')), 1)

    def test_second_setup_waits_for_first(self):
        """同一时刻只能有一个 sop machine setup：第一个卡在 M2 时，第二个说「另一个窗口正在执行」、什么都不做。"""
        (self.scen / 'hang-nvm').touch()
        cmd = [sys.executable, '-I', str(REPO / 'kernel' / 'main.py'), 'machine', 'setup']
        p = subprocess.Popen(cmd, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        try:
            t0 = time.time()
            while not (self.scen / 'hanging-nvm').exists() and time.time() - t0 < 60:
                time.sleep(0.2)
            r = self.setup(answers='')
            self.assertEqual(r.returncode, 3, r.stdout)
            self.assertIn('另一个窗口正在执行 sop machine setup', r.stdout)
            self.assertEqual(self.installs(), ['uv', 'nvm'])
        finally:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


class TestStepFails(SetupCase):
    def test_m5_fails_then_fixed(self):
        """M5 的出口检查不过（wt doctor 报一项失败）：停在 M5、退出码 1、说清是哪一项，M6、M7 不做。
        处理好以后再执行：M2 到 M4 跳过（不再真调 AI），M5 通过，接着做 M6、M7。"""
        (self.scen / 'wt-doctor-fail').write_text('假的失败：bash 版本太旧')
        r = self.setup()
        self.assertEqual(r.returncode, 1, r.stdout[-3000:])
        out = r.stdout
        self.assertIn('停在「M5 安装 wt」', out)
        self.assertIn('不通过：假的失败：bash 版本太旧', out)
        self.assertIn('再执行一次 sop machine setup', out)
        self.assertNotIn('】M6', out)
        self.assertEqual(self.lines('selftest.log'), [])                 # M6 没跑
        self.assertFalse((self.user_home / '.claude' / 'CLAUDE.md').exists())   # M7 没做
        prog = self.progress()
        self.assertEqual(prog['last'], {**prog['last'], 'result': 'stopped', 'step': 'M5'})
        self.assertNotIn('running', prog)
        self.assertAlmostEqual(self.ai_cost(r), 0.0123)

        (self.scen / 'wt-doctor-fail').unlink()
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertNotIn('没做完就断了', r.stdout)
        for c in ('M2 安装工具', 'M3 登录 GitHub', 'M4 登录 AI 工具'):
            self.assertIn(f'{c}：已经合格，跳过', r.stdout)
        self.assertIn('M5 安装 wt：已经合格，跳过', r.stdout)       # 问题在外面修好了，这一步不用再做什么
        self.assertIn('M6 准备受限环境：做好了', r.stdout)
        self.assertEqual(self.installs(), M2_ALL + ['wt'])
        self.assertEqual(self.ai_cost(r), 0)
        self.assertEqual(len(self.lines('selftest.log')), 1)
        self.assertIn('SOP 工具包管理的段落', self.rules())

    def test_m2_install_fails(self):
        """M2 里 pnpm 装不上：停在 M2，说是 pnpm；后面的都不做（没登录、没写登记）。"""
        (self.scen / 'fail-pnpm').touch()
        r = self.setup()
        self.assertEqual(r.returncode, 1, r.stdout[-3000:])
        self.assertIn('停在「M2 安装工具」', r.stdout)
        self.assertIn('pnpm', r.stdout[r.stdout.index('装完核对'):])
        self.assertEqual(self.installs(), ['uv', 'nvm', 'node', 'pnpm'])
        self.assertNotIn('calls', self.auth())
        self.assertFalse((self.home / 'config' / 'ai').exists())

    def test_m6_selftest_fails(self):
        """M6 隔离自检不过：停在 M6，指向维修窗口，登记不记；M7 不做。修好后再执行，M6 重跑（登记没记过），过了接着做 M7。"""
        self.selftest(False)
        r = self.setup()
        self.assertEqual(r.returncode, 1, r.stdout[-3000:])
        self.assertIn('停在「M6 准备受限环境」', r.stdout)
        self.assertIn('sop repair', r.stdout)
        self.assertFalse((self.home / 'config' / 'system.json').exists())
        self.assertFalse((self.user_home / '.claude' / 'CLAUDE.md').exists())
        self.selftest(True)
        r = self.setup(answers='')
        self.assertOk(r)
        self.assertEqual(len(self.lines('selftest.log')), 2)
        self.assertIn('M6 准备受限环境：做好了', r.stdout)

    def test_m3_login_cancelled(self):
        """M3 网页登录没完成（关了浏览器）：停在 M3，不往下走；再执行时登录成了就接着做。"""
        self.env['FAKEGH_LOGIN_FAIL'] = '1'
        r = self.setup()
        self.assertEqual(r.returncode, 1, r.stdout[-3000:])
        self.assertIn('停在「M3 登录 GitHub」', r.stdout)
        self.assertIn('网页登录没完成', r.stdout)
        self.assertFalse((self.home / 'config' / 'ai').exists())
        del self.env['FAKEGH_LOGIN_FAIL']
        r = self.setup()
        self.assertOk(r)
        self.assertIn('M2 安装工具：已经合格，跳过', r.stdout)
        self.assertIn('M3 登录 GitHub：做好了', r.stdout)


class TestForgotHome(SetupCase):
    def test_forgot_home_is_refused(self):
        """3-59：测试漏设了 HOME（主目录是测试进程那个公用的假主目录，3-12 出事时这里是本机真的主目录）。
        别的都齐了、照样能装，sop machine setup 还是一开头就停下：什么都不装、不登录、不写进度，公用的假主目录一样都没变。"""
        env = {**self.env, 'HOME': os.environ[safehome.MARK], safehome.MARK: os.environ[safehome.MARK]}
        del env['XDG_CONFIG_HOME']
        shared = self.snapshot(safehome.SHARED_HOME)
        before = self.snapshot(self.user_home, self.tools, self.home)
        self.env = env
        r = self.setup()
        self.assertEqual(r.returncode, 1, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn('自测的保险：sop machine setup', r.stdout)
        self.assertIn('公用的假主目录', r.stdout)
        self.assertNotIn('【第 1 步', r.stdout)
        self.assertEqual(self.installs(), [])
        self.assertEqual(self.lines('sudo.log'), [])
        self.assertFalse((self.home / 'config' / 'setup.json').exists())
        self.assertEqual(self.snapshot(safehome.SHARED_HOME), shared)
        self.assertEqual(self.snapshot(self.user_home, self.tools, self.home), before)
