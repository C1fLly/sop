# 3-13 第零步 `bootstrap.sh`

2026-11-19。主控窗口派的子代理做的。没调用 AI、没花钱。真的 apt、sudo 只在虚拟机里做（`tests/vm/vm.sh new`，全新的 `one`、`home` 底盘，虚拟机里用了 sudo，用户 2026-11-19 已答应）；本机没用 sudo、没在本机 HOME 里装东西，只跑了单元测试和全部自测（都在 `/tmp` 的临时目录里）。工具包的 GitHub 仓库还没建（3-41），这次没建它，用本机临时起的小网页服务代替。

## 做了什么

- **`bootstrap.sh`**（仓库根目录，只用 bash，4.2、4.5 的 M0）。按顺序：
  1. 看系统：只支持 Ubuntu 26.04（4.1），不许用管理员账号跑（会装进 `/root`），要有系统自带的 python3。
  2. 网络：读已有的代理设置，顺序是环境变量、桌面（GNOME）网络设置里手动填的代理、`/etc/environment`、apt 的设置；用 wget 试连 GitHub、系统用的 Ubuntu 软件源、工具包仓库，把结果摆给小白（「对就直接回车；不对就输入 n」）。连不上或小白说不对才问代理，问的时候写「不知道就直接回车」；写法不对重问；`127.0.0.1:7890` 这种没写 `http://` 的补上。连不上、小白也不知道代理就停下，指向离线包。最多问 3 次。
  3. 缺 git、curl 才用 apt 装：先说一句要密码，再一次 `sudo apt-get`（和 `install.py` 一样的写法：代理给进去、等软件包的锁最多 5 分钟）。都有就不碰 sudo。
  4. 取工具包：Git 取仓库 `main` 最新的一个提交（不支持只取一个提交的简单网页服务就整个取），放进 `~/tools/sop/versions/<提交编号>`；已经有这个版本就跳过；取到的不像工具包就不放。
  5. 用工具包里的 `machine/install/uv.sh`（3-08 写的）把 uv 装到 `~/tools/uv/bin`；已经有就跳过。
  6. 报告主目录在哪个分区（只报告、不问），用体检那份判断（`machine/disks.py`）。
  7. 记网络设置 `config/network.json`（`source` 是 detected 或 user）、写启动器 `~/tools/sop/sop`、往 `~/.bashrc` 末尾写工具包那一段。
  8. 出口检查：`sop machine tools` 能运行（4.5 M0 的「`sop` 能运行」）。最后提示「重新开一个终端，执行 `sop machine setup`」。
  - 可以重复跑：做过的跳过，内容没变的文件不重写。
  - 选项（自测、虚拟机用）：`--repo`（或 `SOP_TOOLKIT_REPO`）、`--yes`、`--proxy`。仓库地址 `DEFAULT_REPO` 现在是空的，**3-41 建好 `C1fLly/sop` 后填上**；空的时候不给 `--repo` 就明说退出。
- **定下用哪个下载工具：wget。** 查了 Ubuntu 官方发布的 26.04.1 桌面版安装清单（`releases.ubuntu.com` 上的 `.manifest`）：桌面版带 `wget 1.25.0`、`python3 3.14.3`、`ca-certificates`，**不带 curl 和 git**；服务器版三样都带。所以小白手册首页那一条命令用 wget：
  `wget --no-hsts -qO /tmp/sop-bootstrap.sh <工具包仓库>/bootstrap.sh && bash /tmp/sop-bootstrap.sh`
  先下载再运行（不用管道），这样问代理、sudo 问密码都从终端读。`--no-hsts` 是为了不在主目录留 `~/.wget-hsts`。代理只认网页代理（`http://`、`https://`），wget 不支持 socks。
- **`machine/bootstrap.py`**：bootstrap 里要用 Python 的两样（`layout` 报告分区，`finish` 写网络设置、启动器、那一段），用刚装的 uv 和系统自带的 Python 3.14 跑，只用标准库。
- **启动器改成用规定位置那份 uv**（`kernel/version.py` 的 `LAUNCHER_SH`、`kernel/launcher.py`）：原来是 PATH 里的 `uv`。第零步刚装完时 `~/tools/uv/bin` 还不在 PATH 里，电脑上另有一份旧 uv 时 PATH 里先找到的是旧的（3-08 看到过登录终端里 `~/.local/bin/uv` 排在前面）。现在先用 `~/tools/uv/bin/uv`，没有才用 PATH 里的；uv 的缓存、Python 放 `~/tools/cache/uv`、`~/tools/uv/python`（不然 uv 会在 `~/.cache/uv` 建缓存）。启动器、`launcher.py`、`versions/latest` 内容没变不重写。`SOP_PYTHON`（自测用）照旧。
- **终端启动文件那一段的 PATH 加了 `~/tools/sop`**（`machine/shellenv.py`），新开的终端敲 `sop` 就能用。
- **虚拟机验证脚本** `tests/vm/m0.sh`（本机）和 `tests/vm/m0-guest.sh`（虚拟机里）：本机把工作区现在的文件做成只有一个提交的 Git 仓库，连同 `bootstrap.sh` 放在 `/tmp` 的临时目录，起一个只听 `127.0.0.1` 的 `python3 -m http.server`（虚拟机经 10.0.2.2 访问），跑完关掉、临时目录删掉。虚拟机里照手册那一条命令用 wget 取再跑。`--desktop` 先造得像桌面版：卸掉 git、curl，用防火墙不让直接上网（只能经本机代理），环境里没有代理。不进 `run_all.py`。

## 结果

### 单元测试

新加 `tests/unit/test_bootstrap.py` 7 项：代理地址的写法（补 `http://`、去尾斜杠、socks 和端口过大不认）；四处读代理（假的 gsettings、apt-config、`/etc/environment`）；缺 git 才 sudo apt、先说一句、代理给进去、都有不碰 sudo、装不上明说；不是 26.04 什么都不建、没给仓库地址明说；**从头跑一遍**（假 wget 当网络，工具包从 `/tmp` 下的本机 Git 仓库取，uv 用跑测试的这份）：版本目录、`latest`、网络设置、那一段都对，新开的 bash 只靠 `~/.bashrc` 找到 `sop` 并能运行，主目录里只多了 `tools` 和 `.bashrc`；再跑一遍都跳过、文件修改时间不变；连不上时问代理、写错重问、填对接着做、记成 user；连不上又不知道代理就停、什么都没装。

全部自测：做之前单元测试 144 项、流程沙箱 24 个剧本、总检查 62 个样例全过；做之后单元测试 151 项（多了这 7 项）、流程沙箱 24 个剧本、总检查 62 个样例，全部通过（沙箱经启动器跑，启动器改了也都过）。

### 虚拟机（全新的 Ubuntu 26.04.1）

| 情况 | 结果 |
|---|---|
| `one` 底盘原样（有 git、curl，能直接上网，没有代理设置），小白直接回车 | 8 秒做完；git、curl 跳过；工具包、uv 0.13.9 装好；报告「只有一个能用的 Linux 分区」；网络设置记「不用代理、探测到的」；新开终端 `sop` 在 `~/tools/sop/sop`、`sop machine tools`、`sop machine doctor --readonly` 能跑；`~/tools` 之外只改了 `~/.bashrc`（和主目录本身多了 `tools`）；`~/tools` 47 MB |
| `one` 底盘造成像桌面版（`--desktop`：卸掉 git、curl，只能经本机代理上网） | 探测到「不用代理」、GitHub 和软件源连不上 → 问代理，填 `10.0.2.2:7890` → 再试全连上、回车 → 先说一句再 sudo apt 装 git、curl → 其余同上，61 秒；网络设置记的是填的代理、`source: user` |
| `home` 底盘（主目录单独一块盘） | 报告「合格：主目录不在系统盘上。系统在 /dev/vda1；主目录在 /dev/vdb1」；其余同第一行 |
| 三种各再跑一遍（环境里有代理，`--yes`） | 代理从环境变量读到；git/curl、工具包、uv 都跳过；没要密码；启动器、`launcher.py`、`latest`、`~/.bashrc` 修改时间不变（网络设置会写，因为每次确认都记时间） |

三台虚拟机（`m0` 两遍、`m0h`）用完都删了；本机临时网页服务跑完就关了（端口 8767 已没有在听），`/tmp/sop-m0.*` 删了。

## 没做的

- **工具包的 GitHub 仓库还没建**（3-41），`DEFAULT_REPO` 是空的，小白手册首页那条命令的地址也还没有。3-41 建好后：填 `DEFAULT_REPO`，取 `bootstrap.sh` 的网址用 `https://raw.githubusercontent.com/C1fLly/sop/main/bootstrap.sh`（没试过）。从 GitHub 取（`git fetch --depth 1` 走 https）没在真 GitHub 上试。
- **真的输密码那一下没验**（虚拟机 sudo 免密码），和 3-09 一样留给 3-15。桌面上开的终端没试（都是 ssh 进去跑的），桌面版的 gsettings 读代理只有单元测试（服务器版没有桌面设置）。
- 只走了「问代理」和「不用代理」两种；`/etc/environment`、apt 设置里有代理的情况只有单元测试。代理要用户名密码的没试。
- 离线包（4.2 第 3 条）是 3-14。
- 第零步没把 git、curl 的位置记进 `config/tools.json`（体检会记）。
- Ubuntu 软件源连不上时第零步也算「连不上」要小白处理；国内源、镜像（`apt_mirror`）没有接。
- 小白手册首页的那一句话（3-39）没写。

## 和设计书的出入（留给 3-48 并入）

1. **4.2 第 1 条「用哪个下载工具在虚拟机上核实后写定」：wget**（Ubuntu 26.04.1 桌面版官方清单带 wget、不带 curl、git）。命令写法见上。
2. 4.2 第 2 条「探测网络」读的是：环境变量、桌面网络设置手动填的代理、`/etc/environment`、apt 的设置；只认网页代理（wget 不支持 socks）。
3. 启动器用规定位置那份 uv（`~/tools/uv/bin/uv`），uv 的缓存和 Python 放 `~/tools` 下；终端那一段的 PATH 多了 `~/tools/sop`。4.3 没写 `sop` 怎么进 PATH。
4. 第零步只支持 Ubuntu 26.04、拒绝管理员账号运行。
5. 网络设置每次确认都会写一次（记 `checked_at`），重复跑第零步时这一个文件会变。

## 自己出的错

1. 代理地址的规则第一版没挡住 `http://x:123456`（主机名那一段把冒号也吃进去了），单元测试抓出来，改成主机名里不许有冒号。
2. 第一版问小白时想从 `/dev/tty` 读（照「经管道运行」的写法），后来定成「先下载再 bash 运行」，标准输入就是终端，改成只从标准输入读，省掉一层。
3. 第一版没探测到代理时把环境里的 `no_proxy` 也丢了；虚拟机验证前看出来改了。
4. 第一版问代理的循环里，小白说「不对」、又直接回车（本来就不用代理）时会停下说连不上；改成那种情况照用「不用代理」。
