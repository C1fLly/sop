"""自测的保险（3-59）：整个测试进程一开始就换成一个假主目录，测试起的子进程默认都继承它。

3-12 出过事：一个测试起 `sop machine setup` 时用的是本机终端的整套环境变量（真的 HOME，只有 SOP_HOME 是临时的），
往本机的 ~/.bashrc 写了一段。所以 tests 这个包一被导入（run_all.py、单独跑某个测试文件都会先导入它）就：

- HOME、XDG_CONFIG_HOME、XDG_CACHE_HOME、XDG_DATA_HOME、XDG_STATE_HOME 指到 /tmp/sop-test 下现建的一个公用假主目录；
- 去掉 AI 工具、GitHub、Docker、SSH 代理、nvm 一类的变量（ANTHROPIC_ 开头的密钥、本会话的 CLAUDE_ 变量等）；
- PATH 去掉本机主目录下的目录（真的 claude、codex、pi 在 ~/.local/bin），只留仓库自己的 .venv；
  测试要用的几样本机工具（uv、uvx、wt，只用不改）链接到假主目录的 bin 里，放在 PATH 最前面；
- 假主目录里放一份只有测试身份的 ~/.gitconfig（以前测试顺带用着本机真的那份）；
- 设 SOP_UNDER_TEST=<假主目录>。工具包里会写主目录的入口（kernel/paths.guard_home）看到它：
  主目录是这个公用的假主目录（测试没给自己单独设 HOME），或者是本机真的主目录，都停下不做。

测试要明确用本机真的主目录（只读，例如从 ~/tools/wt 克隆一份）时用这里的 REAL_HOME。
"""
import atexit
import os
import pathlib
import pwd
import shutil
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
TMP_ROOT = pathlib.Path(os.environ.get('SOP_TEST_TMP', '/tmp/sop-test'))
MARK = 'SOP_UNDER_TEST'
REAL_HOME = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
DROP_PREFIXES = ('ANTHROPIC_', 'CLAUDE', 'OPENAI_', 'CODEX_', 'OPENCODE_', 'GEMINI_', 'GH_', 'GITHUB_', 'DOCKER_', 'NVM_',
                 'SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'GPG_AGENT_INFO', 'PNPM_HOME', 'npm_config_')
KEEP_TOOLS = ('uv', 'uvx', 'wt')       # 测试要用的本机工具（只用不改）
XDG = {'XDG_CONFIG_HOME': '.config', 'XDG_CACHE_HOME': '.cache', 'XDG_DATA_HOME': '.local/share', 'XDG_STATE_HOME': '.local/state'}


def _under(p, root):
    p, root = os.path.realpath(p), os.path.realpath(root)
    return p == root or p.startswith(root + os.sep)


def _clean_path(path, safe_bin):
    keep = [d for d in path.split(os.pathsep) if d and (not _under(d, REAL_HOME) or _under(d, REPO))]
    return os.pathsep.join([str(safe_bin), *keep])


def write_gitconfig(home):
    """假主目录里放一份只有测试身份的 ~/.gitconfig：本机真的那份以前一直被测试顺带用着（提交要有身份）。"""
    (pathlib.Path(home) / '.gitconfig').write_text('[user]\n\tname = tester\n\temail = tester@example.invalid\n')


def install():
    """换成假主目录。子进程又导入 tests 时（同一个假主目录已经在用）什么都不做。返回假主目录。"""
    mark = os.environ.get(MARK)
    if mark and os.path.isdir(mark) and os.environ.get('HOME') == mark:
        return pathlib.Path(mark)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    home = pathlib.Path(tempfile.mkdtemp(prefix='shared-home-', dir=TMP_ROOT))
    safe_bin = home / 'bin'
    safe_bin.mkdir()
    write_gitconfig(home)
    old_path = os.environ.get('PATH', '/usr/bin:/bin')
    for name in KEEP_TOOLS:
        exe = shutil.which(name, path=old_path)
        if exe:
            os.symlink(os.path.realpath(exe), safe_bin / name)
    for k in [k for k in os.environ if k.startswith(DROP_PREFIXES)]:
        del os.environ[k]
    os.environ['HOME'] = str(home)
    for k, sub in XDG.items():
        (home / sub).mkdir(parents=True, exist_ok=True)
        os.environ[k] = str(home / sub)
    os.environ['PATH'] = _clean_path(old_path, safe_bin)
    os.environ[MARK] = str(home)
    if not os.environ.get('SOP_KEEP'):
        atexit.register(shutil.rmtree, home, ignore_errors=True)
    return home


SHARED_HOME = install()
