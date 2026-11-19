# 3-08 M2 安装：nvm、uv、pnpm、缓存目录

2026-11-19。主控窗口派的子代理做的。没调用 AI、没花钱。真的安装只在虚拟机里做（`tests/vm/vm.sh new m2`，全新的 `one` 底盘），虚拟机里也没用 sudo；本机只跑了单元测试和全部自测，没在本机的 HOME 里装任何东西、没改本机的终端启动文件。

## 做了什么

- **安装脚本** `machine/install/`（`tools.toml` 里早就写好了名字，3-03 留给这里）：
  - `lib.sh`：共用的几样。只往 `$SOP_TOOLS`（平常是 `~/tools`）下装；下载先放临时目录；连接被断开这类一时的错也重试；GitHub 上的最新版本跟着网页跳转取，不用 GitHub 的接口；载入 nvm 时不管环境里原来的 `NVM_DIR` 指向哪。
  - `uv.sh`：官方安装脚本，装到 `~/tools/uv/bin`。用 `UV_UNMANAGED_INSTALL`：不改终端启动文件，**也不在 `~/.config/uv` 留记录文件**（见「和设计书的出入」第 1 条）。
  - `nvm.sh`：官方安装脚本，`NVM_DIR=~/tools/nvm`、`PROFILE=/dev/null`（不改终端启动文件）、`METHOD=script`（只下载几个脚本，不用 git）。
  - `node.sh`：用规定位置的 nvm 装当前的长期支持版（`SOP_NODE_VERSION` 可指定，留给项目的 `.nvmrc`），默认版本设成具体的版本号。
  - `pnpm.sh`：往那份默认 Node 下 `npm install -g pnpm`。
  - `gh.sh`：官方发布的压缩包，**按官方的校验值核对**后装到 `~/tools/gh`；先放旁边再换名顶上去，装到一半断了原来那份还在。
  - 每个脚本都可以 `SOP_<名字>_VERSION` 指定版本，不给就装最新的。
- **`machine/shellenv.py`：同一份环境变量两处用**——写进 `~/.bashrc` 末尾一段带开头结尾标记的几行（4.3 说的「几行设置」），安装脚本和检查命令运行时也用它。内容：`NVM_DIR`、npm 缓存、pnpm 的三个 `pnpm_config_` 变量（包仓库、缓存、状态都在 `~/tools/cache/pnpm/` 下）、`PNPM_HOME`、uv 的缓存、Python、Python 的可执行文件、uv 装的命令，gh 关掉统计和升级提示，最后载入 nvm、把 `~/tools/uv/bin`、`~/tools/gh/bin`、`~/tools/pnpm/bin` 放到 PATH 最前面。网络设置里设了 npm、PyPI 的源时也写进去（4.4「安装脚本按它配置各工具」）。
  - 已经有这一段就原地换掉，没有就加在末尾；**段落外的字一个不动**；内容没变不写（修改时间也不动）；`.bashrc` 是链接就写到它指的文件；开头结尾标记对不上（只剩一头、有两段、顺序反了）或不是 UTF-8 就不改、明说。
  - 缓存目录：`~/tools/cache/uv`、`npm`、`pnpm`（4.3 的 `~/tools/cache/<工具名>`）。
- **`machine/install.py`**：`prepare()` 建缓存目录、写那一段；`install_tool()` 先跑清单里的检查命令，合格就跳过，不合格跑安装脚本、再查一次，过了才算装好；`install()` 按清单的先后装 uv、nvm、Node、pnpm、gh，一样不成就停。安装脚本的环境：去掉指向别处那份的变量（`NVM_`、`UV_`、`PNPM_`、`npm_config_`、`pnpm_config_` 开头的），换成规定位置的，加上 `network.json` 里的代理。`python3 -m machine.install` 可以直接跑（3-12 的 `sop machine setup` 做好之前，虚拟机验证用）。
- **改了 `tools.toml` 的检查命令**（nvm、Node、pnpm、gh），`catalog.run_check` 也改成在同一份「只认规定位置」的环境里跑。原来 Node 的检查是「载入规定位置的 nvm.sh 再跑 `node`」：终端里原来的 `NVM_DIR` 指着旧的 `~/.nvm` 时，载入的是新脚本、用的却是旧目录；规定位置还没装 Node 时，PATH 里旧的 node 也会被当成规定位置的那份。现在 Node、pnpm 用规定位置那份 nvm 的默认版本（`$NVM_BIN/node`），不靠 PATH。
- **虚拟机验证脚本** `tests/vm/m2.sh`（把工作区的代码打包拷进虚拟机）和 `tests/vm/m2-guest.sh`（在虚拟机里跑）；`--old` 先用各工具官方的默认装法装一份旧的。不进 `run_all.py`。
- README 的目录表补了这几样。

## 结果

### 单元测试

新加 `tests/unit/test_machine_install.py` 12 项：那一段的内容（缓存都在 `~/tools/cache/<工具名>` 下、没有 `npm_config_` 开头的 pnpm 设置、软件源设了才写、路径带特殊字符不写）、放进 bash 里真的跑一遍变量都对；加、换、再装一次不写不动修改时间、权限照旧、用户在后面加的行不动、最后一行没换行、文件不存在、是链接；四种标记对不上和不是 UTF-8 时一个字不改；**环境里留着旧 nvm（`NVM_DIR`、`NVM_BIN`、PATH 都指着一份有 Node 26 的旧 nvm）时，规定位置什么都没有就一样都不算装了、只装了 nvm 时 Node 不算装了**；版本从规定位置取；安装脚本的环境；先查再装再查、已合格不再跑脚本、脚本出错、装完找不到、版本不够；真的安装脚本都在、bash 语法对、不写终端启动文件、没给工具目录或还没装 nvm 时明说退出。

全部自测：做之前单元测试 107 项、流程沙箱 24 个剧本、总检查 62 个样例全过；做之后单元测试 119 项（多了这 12 项）、其余一样，全部通过。

### 虚拟机（全新的 Ubuntu 26.04.1，`one` 底盘）

最后一次全新装（第 4 遍）：

| 项 | 结果 |
|---|---|
| 装了什么 | uv 0.13.9、nvm 0.41.0、Node 26.13.1、pnpm 12.21.0、gh 2.105.0，共 30 秒 |
| 代理 | 只从 `network.json` 来（跑安装时把环境里的代理变量都去掉了），能下载 |
| 清单的检查命令 | 这一部分装的 5 样，加上底盘本来就有的 git 2.53.0、curl 8.18.0、dbus-user-session 都「合格」；bubblewrap、uidmap、免管理员 Docker、wt「没装」，不归这一步（要管理员密码的 apt 软件包归第零步、3-09；Docker 3-09；wt 3-22） |
| 新开的终端（不是登录的那种，和桌面上开一个终端一样） | node、npm、pnpm、uv、gh 都是 `~/tools` 下那一份；Node 能跑；pnpm 装一个依赖能用，包仓库在 `~/tools/cache/pnpm/store`；pnpm 全局装的命令在 `~/tools/pnpm/bin`；uv 装 Python 3.13.18 在 `~/tools/uv/python`，`python3.13` 在 `~/tools/uv/bin`；uv 建项目装依赖能用；gh 能跑 |
| `~/tools` 之外新出现或改了的 | 只有 `~/.bashrc`（加了那一段）和主目录本身（多了 `tools` 这个目录） |
| 再装一次 | 5 样都「已经装好了，跳过」；`~/.bashrc` 修改时间、内容都没变 |
| 占的空间 | nvm 330 MB、uv（含一份 Python）143 MB、gh 41 MB、缓存 44 MB |

**有旧的那一遍**（还原成全新后，先用官方默认装法装了：`~/.nvm` 里 Node 24 和 pnpm 11、`~/.local/bin` 里的 uv 和它装的 Python 3.12、`~/.local/share/pnpm` 里另一份 pnpm；三个官方脚本都改了 `~/.bashrc`，uv 还在 `~/.config/uv` 留了记录文件）：

- 装之前终端里用的是旧的（`NVM_DIR=~/.nvm`）。M2 在这个终端里跑，5 样照装不误。
- 清单的检查命令在两种环境里（没读终端启动文件的、读了的——旧的那几行也在里面）结果一样，都认的是规定位置那份。
- 新开的终端里 node、pnpm、uv、gh、python3.13 都是 `~/tools` 下那一份，能用。
- **旧的一样没动**：`~/.nvm`、`~/.local`、`~/.config`、`~/.cache` 下 12670 个文件和目录，大小、修改时间、权限都一样；`~/.local/bin` 下的程序和 uv 的记录文件内容（校验值）一样；`~/.profile` 没动；`~/.bashrc` 原来的内容一个字没动，只在末尾加了那一段。
- **登录的终端里 uv 用的是旧的**（`~/.local/bin/uv`），node、pnpm 是新的。原因：Ubuntu 的 `~/.profile` 先读 `~/.bashrc`，再把 `~/.local/bin` 加到 PATH 最前面。桌面上开的终端不是登录的那种，用的是新的；ssh 登录、`bash -l` 是登录的那种。见「没做的」。

## 没做的

- **登录终端里 `~/.local/bin` 排在前面**（上面最后一条）。只影响电脑上另有一份 uv（或别的命令）在 `~/.local/bin` 的情况，而且只在登录的终端里；工具包自己总是用规定位置的完整路径，不受影响。要不要处理（例如往 `~/.profile` 末尾也加一段），留给 3-31 环境迁移（那里本来就要处理「终端里那几行指向谁」），没拆新任务。
- 只验了 bash 的 `~/.bashrc`。用户换成 zsh 等别的终端程序的，第一版不管（Ubuntu 默认是 bash）。
- `sop machine setup` 把这一步和 Docker、登录等串起来、出口检查、断了接着做，是 3-12；这里只有 `python3 -m machine.install` 给虚拟机验证用。中途断了重跑这一点顺带看到了一次（见「自己出的错」第 3 条）。
- 体检（3-06）把装好的登记进 `tools.json` 没在虚拟机里跑。
- 没做离线安装（3-14）、没用国内的 Node、PyPI 源试（网络设置里的 npm、PyPI 源只有单元测试）。Node 的下载源（nvm 的 `NVM_NODEJS_ORG_MIRROR`）网络设置里没有这一项，没接。
- nvm 下载 Node 的临时文件在 `~/tools/nvm/.cache`（nvm 没有改这个位置的变量），在 `~/tools` 里，不在 `~/tools/cache/nvm`。
- gh 登录之后会写 `~/.config/gh`，是 4.3 列的例外，M3（3-10）的事。

## 和设计书的出入（留给 3-48 并入）

1. **uv 不再留 `~/.config/uv/uv-receipt.json`。** 4.3「在主目录下、但不在 `tools` 里」列着它。改用 uv 安装脚本的 `UV_UNMANAGED_INSTALL` 后不写这个文件：电脑上另有一份旧 uv 时，新装的记录文件会顶掉旧的那份的记录，旧的 `uv self update` 就会去升级新的这一份，不符合「旧的不动」。代价是规定位置的 uv 不能 `uv self update`，升级重跑工具包的安装脚本。虚拟机里核对过：旧 uv 的记录文件装前装后校验值一样。4.3 那一句可以删。
2. 缓存的具体位置：pnpm 的包仓库、缓存、状态在 `~/tools/cache/pnpm/store`、`cache`、`state`（W36 试验用的是 `cache/pnpm-store` 等三个并列目录；改成都在 `<工具名>` 下）；npm 的在 `~/tools/cache/npm`；pnpm 全局装的命令在 `~/tools/pnpm/bin`（4.3 的表里没有 `~/tools/pnpm` 这一行）。
3. 那一段还关掉了 gh 的统计（`GH_TELEMETRY=0`）和升级提示：不关的话 gh 每跑一次都往 `~/.local/state/gh/device-id` 写东西（虚拟机里看到的），4.3 没列这个例外。gh 官方的环境变量说明里有这一项。
4. gh 装在 `~/tools/gh`（3-03 记过，设计书没写），用官方压缩包、核对校验值。
5. 各安装脚本默认装最新的版本（GitHub 上最新发布的、Node 当前的长期支持版），可用 `SOP_<名字>_VERSION` 指定；设计书没写取哪个版本。

## 自己出的错

1. 第一遍虚拟机里 pnpm 全局装东西不成：pnpm 12 全局装的命令在 `$PNPM_HOME/bin`，我照 W36 把 `$PNPM_HOME` 本身放进了 PATH。改成 `~/tools/pnpm/bin`。
2. 第一遍发现 gh 往 `~/.local/state/gh/device-id` 写了东西（W36 没装 gh，没碰到）。查了 gh 自己的环境变量说明，加 `GH_TELEMETRY=0` 后虚拟机里试过不再写。
3. 第二遍（还原成全新后）经本机代理下载 nvm 的安装脚本时连接断了，`curl --retry` 默认不重试这种错，nvm 没装上。同一遍后面的「再装一次」从 nvm 接着装完了。改成连接出错也重试（`--retry-all-errors`）、把 curl 的报错显示出来，第四遍全新装一次过。第三遍（有旧的）用的还是改之前的下载写法，那一遍没碰到断线。
4. 测试里有一条判断写成了子串比较（`npm_config_store` 恰好是 `pnpm_config_store_dir` 的一部分），第一次跑报错，改成比整行开头。
5. 最后一次虚拟机验证之后，又把 `python3 -m machine.install` 的输出改了一下（原来结尾把每样的结果重复打印一遍），只动了打印，没再开虚拟机跑。

## 留下的东西

- 虚拟机 `m2` 用完删了（`vm.sh list` 是空的）；本机 `/tmp` 下这次的临时文件都删了。
- 本机：没在 HOME 里装任何东西，没改终端启动文件；只跑了单元测试和全部自测（都在 `/tmp` 的临时目录里）。
