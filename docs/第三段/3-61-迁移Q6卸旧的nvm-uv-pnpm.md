# 3-61：环境迁移 Q6（卸旧的 nvm、uv、pnpm）

2026-11-21，主控窗口派的子代理做的。没动隔离、放行事件、事件日志；没碰 GitHub、Docker；没调用 AI，0 美元。**本机没卸任何东西、没改本机的 `~/.bashrc` 等终端启动文件、没用 sudo**：单元测试和手动验证全在 `/tmp` 下造的主目录里做，「新开一个终端」那一步套了整个系统只读、不联网的 bubblewrap。

## 做了什么

新模块 `machine/migrate/oldtools.py`（`q6_tools`），`sop machine migrate` 在 Docker 的 Q6（3-32）之后接着做，只卸 Q3 里选了「卸掉」、自己装在主目录里的旧 nvm、uv、pnpm：

- **卸哪几样**：旧 nvm 目录（连同里面的各个 Node 版本和全局包）；旧 uv 程序（如 `~/.local/bin/uv`）连同它旁边的 `uvx`，和 uv 官方安装程序留的 `~/.config/uv/uv-receipt.json`（记的安装位置是这个旧 uv 时才删）；`~/.local/share/uv`（旧 uv 装的 Python、uv tool）；旧 pnpm 目录（`~/.local/share/pnpm`）。指向它们里面的链接（例如 `~/.local/bin/ruff` → 旧 uv 的 uv tool）一起删。gh、wt、系统软件包装的 Node、snap 等**第一版只打印怎么卸**（`sudo apt purge …`、`rm …`）。
- **Q3 改了一处**：在另一份里面的（`~/.nvm` 里的 node）不再单独问，写明「跟着 `~/.nvm` 一起留或卸」，`choices.json` 里记 `inside`。
- **规定位置那份没装好的不卸**（nvm 那一样要 nvm、node 都过清单的检查命令）。
- **按 3-60 的「谁还在用」逐条摆出来，这几种这一样就不卸**（说清楚怎么办，再执行一次 `sop machine migrate`）：装在旧的里面（或第一行写死用旧的运行）的 AI 工具、而别处（PATH、官方默认位置、规定位置）找不到另一份；旧的里面全局装的包在规定位置那份里没有（pnpm 本身除外，M2 装）；旧 uv 装的 uv tool 在 `~/tools/uv/tools` 里没有；**用户级后台服务、开机自启、桌面图标指着旧的**（任务清单没写这一条，我加的，见「替用户定的」）。靠 Node 运行的（Pi）不挡，由下面「新开一个终端」那一步核对。别的（Python 环境、写死旧 Python 的命令、旧 nvm 里的 Node 版本）列在确认的清单里「卸掉以后要你自己处理」。
- **终端启动文件只删那几行**：3-60 列出来的行（SOP 那一段、注释不算）。pnpm 官方装法（`pnpm setup`）加的是一整段 `# pnpm` … `# pnpm end`，3-60 只认出 `export PNPM_HOME=` 那一行；只删这一行，后面的 `export PATH="$PNPM_HOME:$PATH"` 会把一个空的 PATH 项（= 当前目录）放进去，所以认出是官方那一段就整段删；不是那一段、别的行还用着 `PNPM_HOME` 时这一样不卸。行末有 `\` 接着下一行的不拆。先在临时文件上删好、用 `bash -n`（zsh、fish 的用 `zsh -n`、`fish --no-execute`，电脑上没有那种终端就不查）核对语法，坏了这一样不卸。**uv 安装程序加的 `. "$HOME/.local/bin/env"`（和 fish 那份）在 `~/.local/bin` 还有别的命令时留着，`env`、`env.fish` 文件也留着**；只剩旧 uv 自己才一起删（3-60 的发现）。
- **再确认一次**：逐条打印要删的目录和文件（带大小）、要删的每一行、留着的 env 那几行和原因、卸掉以后要自己处理的；问「确定现在卸掉它们吗」，默认「否」。之前什么都不动。
- **真卸**：先把要改的终端启动文件原样备份到 `~/tools/backup/migrate-<日期>/startup-files-<时分秒>/`（0600）；改之前再读一遍，和刚才看到的不一样就一样都不改；只删那几行（先写临时文件再换名，权限照旧；是链接就改它指的文件）。
- **新开一个终端看看**：用干净的环境（HOME、PATH 取 `/etc/environment` 的）真起 `bash -i -c`（桌面上开的那种）和 `bash -l -i -c`（登录的那种：ssh、`bash -l`），看 `type -a -P node pnpm uv`：**跳过马上要删的旧的之后**，第一个得在 `~/tools` 里。不对或者没看成，把终端启动文件原样写回去、目录一样不删、说清楚。
- 对了才删目录和文件。删之前核对路径：只删主目录里面的；`~/.local`、`~/.local/bin`、`~/.local/share`、`~/.config`、`~/.cache`、`~/bin`、`~/tools` 本身和 `~/tools` 里面的、挂载点都不删（规划时就核对，有一项不对这一样不卸）。
- **卸完再看**：要删的都不在了；再清点一遍（`inventory.other_tools` + `users.old_roots`），这几样不再出现；终端启动文件里指着它们的行没有了（留着的 env 那几行不算）；**再开一次新终端，这次不跳过，第一个找到的就得是 `~/tools` 里的**——这就是 3-08 留下的「登录的终端里 `~/.local/bin` 排在前面、旧 uv 先被用到」，卸掉旧 uv 后验它没了。最后提醒靠 Node 运行的 Pi 等「新开一个终端打开一次试试」。结果记在 `config/migrate/uninstall.json` 的 `tools`。
- 改了 `users.py` 三处：「谁还在用」的条目多记几样给 Q6 用（全局包的包名 `package`、uv tool 的 `name`、AI 工具的命令名 `command`），列法和给人看的字一样没变。`flow.py` 去掉「卸载这一步还没做好（任务 3-61）」，接上 `oldtools.q6_tools`；`machine/cli.py` 用法说明。

## 验证

- 单元测试 `tests/unit/test_migrate_oldtools.py` 12 项，都在测试自己的临时目录里造主目录（照 Ubuntu 自带的 `.bashrc` 开头、`/etc/skel/.profile` 的样子，加 nvm、uv、pnpm 三个官方安装程序加的几行和工具包那一段）和规定位置的假 nvm、Node、pnpm、uv；「新开一个终端」真起 bash，外面套 `bwrap --ro-bind / / --bind <测试临时目录> --unshare-net`：
  - 三样全卸：**卸之前登录的终端里 uv 先找到的是旧的 `~/.local/bin/uv`（3-08 重现出来了）、桌面上开的终端是规定位置的**；卸完两种终端里 node、pnpm、uv 第一个都是 `~/tools` 的；目录、`uvx`、uv tool 的链接、记录文件删了，`env`、`env.fish`、claude、pi、`~/bin/mdview` 在；`.bashrc` 正好少了 nvm 三行和 pnpm 那一整段、`.zshrc` 少了一行、`.profile` 一字没变；备份和原来一样、0600；别的文件修改时间和大小都没变；再清点「别的工具」是空的。
  - 直接回车：一样不动、备份目录都不建。
  - 挡住：Codex 装在旧 nvm 里别处没有 + 用户级服务指着旧 Node → nvm 不卸；pnpm 全局包、uv tool 没重装 → 那两样不卸；旧 uv 程序照卸；`.bashrc` 一字没动。Codex 另有一份在 `~/.local/bin` → 不挡。
  - `~/.bashrc` 里没有工具包那一段（新终端里找不到规定位置的 Node）→ 启动文件原样写回、一个文件没少。
  - PNPM_HOME 不是官方那一段的写法 → pnpm 不卸、nvm 照卸。删了语法就坏（`if [ -d ~/.nvm ]` 那种）→ nvm 不卸、文件不动。`~/.local/bin` 里只剩旧 uv → env 那一行和 env 文件一起删。规定位置的 Node 没装好 → 不卸。测试漏设 HOME → 自测的保险挡住、什么都没动。路径核对。整条 `flow.migrate`：node 不单独问、gh 只打印 `rm`、卸完。
  - **反着试过三处**：新终端那一步不跳过旧的（等于不认 3-08 那种情况）→ 4 项不过；没核对对不放回启动文件 → 1 项不过；env 那一行不留 → 2 项不过。
- **手动验证**（`/tmp/sop-3-61/scripts/e2e.py`，用完删了）：在整个系统只读、`/run/user/<编号>` 盖掉、不联网的 bubblewrap 里，HOME 指到 `/tmp/sop-3-61/home`（照本机样子造：旧 nvm 里 Node v26.13.0 和全局 pnpm、`~/.local/bin` 里旧 uv、uvx、env、claude、pi，Pi 靠 Node 的启动脚本，`.bashrc` 用 `/etc/skel/.bashrc` 原文加三个安装程序的几行和工具包那一段，`.profile` 用 `/etc/skel/.profile` 加 env 那一行，`.zshrc`、fish 那份），用正式的默认做法（`Probe`、`Host` 不换，`Ask` 按问题自动答）跑 `flow.migrate`：卸之前登录的终端 `uv` 是旧的 0.5.0、卸完是规定位置的；`.bashrc` 正好少 10 行，`.profile`、`.zshrc`、fish 那份没变；退出码 0。第一遍 Q2 因为本机有 `/usr/bin/gh` 而假的规定位置没有 gh，去装 gh、断网连不上就停了（什么都没下载，正是「新的没装好就停」）；加了假 gh 再跑。

## 自测

全部自测（`uv run python tests/run_all.py`，7 分 20 秒）：单元测试 489 → 501 项，流程沙箱 43 个剧本，总检查 95 个样例，全部通过（退出码 0）。测试都用 `tests/safehome.py` 的临时主目录，没有真调 AI 的。

## 替用户定的（可否决）

1. 指着旧的的用户级后台服务、开机自启、桌面图标也挡住卸载（任务清单只写了 AI 工具、全局包、uv tool）：不挡的话开机时它悄悄起不来。
2. 卸不卸由「新开的终端」核对：真起一次 `bash -i` 和 `bash -l -i`，会执行小白自己的终端启动文件（和他自己开一个终端一样）；两种都要对才删。**登录的那种终端不读 `.bashrc`（没有 `.profile`、或者 `.bash_profile` 不读它）时，新终端里找不到规定位置的 uv，就一样不卸**（宁可不卸）。
3. 只核对 bash。zsh、fish 的启动文件只删行、核对语法，不核对新开的 zsh、fish 里用的是谁（工具包那一段只写在 `~/.bashrc`，3-08）。
4. gh、wt、系统软件包装的 Node 等第一版只打印怎么卸；`~/.npm`、`~/.cache/uv`、`~/.cache/pnpm`、`~/.local/state/pnpm`、`~/.config/pnpm` 这类缓存和设置不删（不是「它的目录」，也不碍事）。
5. 挡住的那几样只能先在规定位置重装、或者自己删掉（给了命令）再执行一次，没有「这个我不要了，照卸」的选项。

## 没做的

- 本机没跑（会卸本机的东西）；没开虚拟机（只动主目录里的文件，临时目录里就能造全；真 nvm、真 uv、真 pnpm 的官方装法加的行是按它们的官方脚本写的样子造的，没有在虚拟机里真装一遍再卸）。
- Pi 用规定位置的 Node 真的能打开（设计书 4.8「装完要验一次」）没验：测试里没有真的 Pi、真的 Node，只核对了新终端里 node 是规定位置那份，卸完提醒小白打开一次。
- `crontab` 里指着旧位置的、项目 `node_modules` 里按旧 Node 编出来的原生扩展：3-60 就没列，这次也没管。
- 3-60 认不出的旧的（`NVM_DIR` 指在别处的旧 nvm 等）这次也卸不了。

## 和设计书的出入（留给 3-48）

1. 4.8「nvm、uv」那一行补 pnpm（`~/.local/share/pnpm`），写明：删的是哪几样（含 `uvx`、`uv-receipt.json`、指进去的链接）；终端启动文件先备份、只删那几行，pnpm 官方那一段整段删；uv 的 `env` 那一行在 `~/.local/bin` 还有别的命令时留着（3-60 也提了）。
2. 卸之前「谁还在用」挡住的几种（含后台服务），和「改完启动文件、新开终端核对过才删目录，不对就放回」这一步。
3. Q3 里在另一份里面的（`~/.nvm` 里的 node）不单独问。
4. 3-08 的「登录终端里旧 uv 排在前面」：卸掉旧 uv 后没了（本次验过）；**旧 uv 留着时这个问题一直在**，设计书 4.8「新旧两份，一个终端里只有一份生效，看终端启动文件里那几行指向谁」要补一句：Ubuntu 的 `.profile` 在登录终端里把 `~/.local/bin` 放到最前面，旧 uv 在那里时登录终端用的是旧的。

## 自己出的错

- 第一稿里留了几处没写完的东西（uv tool 的提示写成了半句、`plan_paths` 里一段什么都不做的循环、`guard_home` 写成了 `if … is None: pass`），跑测试之前读一遍时改掉了。
- 第一版「只剩旧 uv」那项测试没造 `.profile`，登录的终端不读 `.bashrc`、找不到规定位置的 uv，工具包照规矩没卸、测试不过；行为是对的，测试补上 Ubuntu 默认的 `.profile`（同时写进了「替用户定的」第 2 条）。
- 手动验证第一遍自动答题的匹配写错，nvm 没选上；第一遍还因为本机有 `/usr/bin/gh` 在 Q2 去装 gh（断网，没下载到东西）。改了脚本重跑。
