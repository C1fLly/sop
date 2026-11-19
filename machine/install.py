"""M2 安装工具：uv、nvm、Node、pnpm、gh，缓存目录、终端启动文件里那一段（设计书 4.3、4.5；3-08）；
免管理员的 Docker 和清单里用系统软件包装的几样（3-09）。

- 安装脚本在 machine/install/ 下，由 tools.toml 的 install 字段指定；都装到 ~/tools 下的规定位置，不改终端启动文件。
- 电脑上另有一份不在规定位置的（旧的 ~/.nvm、~/.local/bin/uv……）照装不误、旧的不动（M2）：
  运行安装脚本时把环境里指向旧的那几个变量（NVM_DIR、UV_…、npm_config_…）去掉，换成规定位置的。
- 装之前先跑清单里的检查命令，已经合格的跳过；装完再跑一次检查命令，过了才算装好。

- 要管理员密码的（清单里 admin = true 的系统软件包、Docker 的系统规则）：先用一句大白话说要做什么，再由系统问密码（sudo）。
  系统软件包几样合成一次 apt；Docker 自己那一步在它的安装脚本里（machine/install/docker-rootless.sh）。

整个 M2、出口检查、中途断了接着做，由 sop machine setup（3-12）串起来；这里只管装。
本模块也能直接跑（3-12 做好之前虚拟机验证用）：python3 -m machine.install [工具名…]（不给名字就是 MINE 那几样，不要密码）
"""
import subprocess
import sys

from kernel import paths
from . import catalog, config, shellenv

MINE = ('uv', 'nvm', 'node', 'pnpm', 'gh')     # 3-08 装的几样，不要管理员密码
DOCKER = ('uidmap', 'dbus-user-session', 'docker')   # 3-09：免管理员 Docker 和它要的系统软件包
SUDO_PROMPT = '[sudo] 请输入 %u 的登录密码：'


def script_env(tools_dir=None, net=None, base=None):
    """安装脚本的环境：原来的环境去掉指向别处那份的变量，换上规定位置的，加上网络设置里的代理和软件源。"""
    net = config.network() if net is None else net
    return {**shellenv.environ(tools_dir, net, base), **config.proxy_env(net)}


def prepare(tools_dir=None, net=None, rc=None):
    """建缓存目录、写终端启动文件里那一段。返回几句大白话。"""
    t = paths.tools_dir() if tools_dir is None else tools_dir
    net = config.network() if net is None else net
    for d in shellenv.CACHE_DIRS:
        (t / d).mkdir(parents=True, exist_ok=True)
    changed = shellenv.install_block(rc, t, net)
    where = rc or shellenv.rc_file()
    return [f'缓存目录在 {t / "cache"} 下',
            f'终端启动文件 {where} 里工具包那一段{"写好了（新开的终端才生效）" if changed else "本来就是最新的，没改"}']


def install_apt(tools, *, net=None, run=subprocess.run, out=None):
    """用系统的软件包装这几样（要管理员密码）：先说一句要做什么，再由系统问密码；几样合成一次 apt。返回 (成没成, 一句大白话)。"""
    if not tools:
        return True, ''
    net = config.network() if net is None else net
    pkgs = [t.install_kind()[1] for t in tools]
    print(f'接下来用系统的软件包装 {"、".join(pkgs)}（{"；".join(t.what for t in tools)}），要管理员权限。\n'
          '系统会问这台电脑的登录密码（就是开机登录用的那个），输入时屏幕上什么都不显示，输完按回车。', flush=True)
    proxies = [f'{k}={v}' for k, v in config.proxy_env(net).items() if k.islower()]
    # 刚开机时系统可能正在自己更新、占着软件包的锁：等它最多 5 分钟
    cmd = ['sudo', '-p', SUDO_PROMPT, 'env', *proxies, 'DEBIAN_FRONTEND=noninteractive', 'NEEDRESTART_SUSPEND=1', 'sh', '-c',
           'apt-get -o DPkg::Lock::Timeout=300 update -qq && '
           'apt-get -o DPkg::Lock::Timeout=300 install -y -qq --no-install-recommends "$@" >/dev/null', 'sop-apt', *pkgs]
    p = run(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT if out else None)
    if p.returncode != 0:
        return False, (f'系统软件包 {"、".join(pkgs)} 没装上（密码不对、这个账号不能用 sudo、不是在终端里运行的，'
                       f'或者连不上软件源；退出码 {p.returncode}）')
    return True, f'系统软件包 {"、".join(pkgs)} 装好了'


def install_tool(tool, *, env=None, out=None):
    """先查；不合格就跑它的安装脚本，再查一次。返回 (结果, 一句大白话)。"""
    r = catalog.run_check(tool)
    if r.ok:
        return r, f'{tool.name}：已经装好了（版本 {r.version_text}），跳过'
    kind, script = tool.install_kind()
    if kind != 'script':
        return r, f'{tool.name}：要用系统的软件包 {script} 装，还没装上'
    p = subprocess.run(['bash', str(script)], env=script_env() if env is None else env,
                       stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT if out else None)
    after = catalog.run_check(tool)
    if p.returncode != 0:
        return after, f'{tool.name}：安装脚本出错退出（退出码 {p.returncode}），没装好'
    if not after.installed:
        return after, f'{tool.name}：安装脚本跑完了，但检查命令还是找不到它：{after.output[:300]}'
    if not after.ok:
        return after, f'{tool.name}：装上了，版本 {after.version_text}，不够清单要的 {tool.version}'
    return after, f'{tool.name}：装好了（版本 {after.version_text}，在 {tool.location}）'


def install(names=MINE, out=None, *, run=subprocess.run):
    """按清单里的先后装这几样，一样不成就停。用系统软件包装的几样先合成一次装（要管理员密码）。返回 (全成没有, [大白话])。"""
    tools = catalog.load()
    unknown = set(names) - {t.name for t in tools}
    if unknown:
        raise catalog.CatalogError(f'工具清单里没有：{"、".join(sorted(unknown))}')
    msgs = prepare()
    for m in msgs:
        print(m, flush=True)
    apt = [t for t in tools if t.name in names and t.install_kind()[0] == 'apt' and not catalog.run_check(t).ok]
    ok, msg = install_apt(apt, run=run, out=out)
    if msg:
        msgs.append(msg)
        print(msg, flush=True)
    if not ok:
        return False, msgs
    env = script_env()
    for t in tools:
        if t.name not in names:
            continue
        r, msg = install_tool(t, env=env, out=out)
        msgs.append(msg)
        print(msg, flush=True)
        if not r.ok:
            return False, msgs
    return True, msgs


def main(argv):
    names = tuple(argv) or MINE
    ok, _ = install(names)
    print('都装好了' if ok else '没装完，看上面哪一样没装好')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
