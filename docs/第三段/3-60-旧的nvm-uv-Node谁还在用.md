# 3-60 迁移 Q1：旧的 nvm、uv、Node 还有谁在用

2026-11-21，主控窗口派的子代理做的。没动隔离、放行事件、事件日志；没碰 GitHub；没调用 AI，0 美元；没碰 Docker。

## 做了什么

设计书 4.8：「卸掉旧的之前，要先看还有谁在用它……清点（Q1）把『谁还在用旧的』列出来，卸载前逐条确认。」3-30 的清点只列了旧的 nvm、uv 在哪、多大，这次接着列「谁还在用」。

- 新模块 `machine/migrate/users.py`（`find`、`describe`），接在 `machine/migrate/inventory.py` 的 `tools` 那一部分后面：`inventory()` 的结果多一项 `tool_users`，给人看的清单在「别的工具」后面多一段「谁还在用旧的 nvm、uv、Node」。手动跑照旧是 `python3 -m machine.migrate.inventory [--json] [--save]`。
- 旧的在哪：按清点 `tools` 部分找到的 nvm、uv、Node、pnpm 的另一份（在另一份里面的，例如 `~/.nvm` 里的 node、pnpm，算在外面那一份里）。旧 uv 是 `~/.local/bin/uv` 时，它旁边 uv 安装程序放的 `uvx`、`env`、`env.fish` 也算旧 uv 的；Node 不在 nvm 里（例如 `/usr/local/bin/node`）时，它的全局包目录 `<前缀>/lib/node_modules` 也算。
- 列出来的九类，每条写明是哪一样旧的、在哪、卸了会怎样、怎么办：
  1. **AI 工具**（Claude Code、Codex、OpenCode、Pi，位置照体检的 `locate.AI_TOOLS`）：装在旧的里面的（例如 Codex 用旧 nvm 的 npm 全局装的）；第一行写死用旧的里面的程序运行的；靠 Node 运行（第一行 `#!/usr/bin/env node`，或者 sh 写的启动脚本里提到 node，Pi 就是这种）、而终端里现在找到的 `node` 是旧的。Pi 的安装程序自带 Node（`~/.local/share/pi-node/current/bin/node`）时它用自己的，不算。
  2. **命令**：`~/.local/bin`、`~/bin`、PATH 里主目录下的目录、`/usr/local/bin` 里的，链接指向旧的里面、第一行写死用旧的里面的程序（例如旧 uv 的 Python）、靠 Node 运行而现在找到的 Node 是旧的。`~/tools` 下的不看（规定位置的）。
  3. **旧的 nvm 里的 Node 版本**（标出旧的 nvm 默认用的那个）。
  4. **全局装的包**：旧 nvm 每个 Node 版本 `lib/node_modules` 里的（npm、corepack 不算），旧 pnpm 的 `global/*/node_modules` 里的，带上 `package.json` 里写的命令名。
  5. **旧的 uv 装的 Python**（`~/.local/share/uv/python/` 下）。
  6. **旧的 uv 装的命令**（uv tool，`~/.local/share/uv/tools/<名字>`），连同 `~/.local/bin` 里指向它的命令；怎么办写 `uv tool install <名字>`。
  7. **Python 环境**：在主目录里找有 `pyvenv.cfg` 的目录（项目的 `.venv`），`home`、`executable`、`bin/python` 链接指向旧的里面的列出来（写明 Python 版本、是不是 uv 建的），怎么办是删掉重建（`uv sync`）。最深 6 层，跳过 `node_modules`、`.git`、`.cache`、`.cargo`、`snap` 等、旧的目录本身、`~/tools` 下的 nvm、uv、docker、docker-sop、cache，不跨文件系统、不跟链接；最多看 20 万个目录，超了写「没找全」。用系统 Python 建的环境不列（卸旧 uv 不影响它）。
  8. **终端启动文件**（`~/.bashrc`、`.bash_profile`、`.bash_login`、`.profile`、`.zshrc`、`.zshenv`、`.zprofile`、`.zlogin`、fish 的 `config.fish` 和 `conf.d/*.fish`）：把 `$HOME`、`${HOME}`、`~` 换成主目录后写着旧位置的行；用 `$NVM_DIR` 的行，在这个文件把 `NVM_DIR` 指向旧的（或者没设、而电脑上有旧 nvm）时也算。注释行、SOP 自己那一段（`shellenv.BEGIN`…`END`）不算。
  9. **后台服务、开机自启、桌面图标**：`~/.config/systemd/user`、`~/.config/autostart`、`~/.local/share/applications` 里登记文件写着旧位置的（`%h` 也换成主目录）。
- **uv 安装程序加的 `. "$HOME/.local/bin/env"` 那一行要特别说**：它的作用是把 `~/.local/bin` 放进 PATH，而 Claude Code、Codex、Pi、wt 的命令也在那里（本机就是）。所以这一行在 `~/.local/bin` 还有别的命令时写「卸旧 uv 时这一行和 `~/.local/bin/env` 都留着（或者换成只把 `~/.local/bin` 放进 PATH 的一行）」，并列出会受影响的命令；那里只剩旧 uv 自己时才写「一起删掉」。
- 只看文件：不跑这些工具、`users.py` 一条命令都不跑（清点原来的 `dpkg-query` 照旧）、不改任何东西。旧的 nvm、uv、Node、pnpm 一样都没有时什么都不找（主目录也不走）。

## 结果

- 单元测试 `tests/unit/test_migrate_users.py` 9 项：在测试自己的临时目录里造一个主目录（规定位置 `~/tools` 另放、不在它下面），里面放旧 nvm（两个 Node 版本，全局装了 pnpm、Codex 和一个 package.json 坏了的包）、旧 uv（`~/.local/bin/uv`、`uvx`、`env`、`env.fish`，`~/.local/share/uv` 里有 Python 3.12.7 和 uv tool ruff）、旧 pnpm（全局装了 serve）、照本机样子造的 Pi 启动脚本和 Claude Code、OpenCode（ELF）、5 个 Python 环境（2 个该列：uv 建的、不是 uv 建但用旧 uv 的 Python；3 个不该列：系统 Python 的、`node_modules` 里的、太深的）、终端启动文件（含注释行、SOP 那一段、Ubuntu 自带的 `PATH="$HOME/.local/bin:$PATH"`）、两个用户级服务（一个指向旧 Node、一个是规定位置的 Docker）、`~/bin` 里三个命令。核对：九类都列对、不该列的一个没列、主目录里每样东西的修改时间和大小前后一样、除了查软件包没跑任何命令；另外：终端里先找到的是规定位置的 Node 时 Pi 和靠 Node 的命令不再列；Pi 自带 Node 时不列；`~/.local/bin` 里只剩旧 uv 时 env 那一行写「一起删掉」；终端启动文件自己把 `NVM_DIR` 指到规定位置时用 `$NVM_DIR` 的行不列；没有旧的时不多一段、不走主目录；有旧的没人用时明说「没发现」；目录超上限时写「没找全」；`runtime()` 认可执行文件开头 9 种。3-30 原有的 26 项照旧全过。
- 全部自测：见下面「自测」。
- **本机**：在「整个系统只读、断网、`/run/user/<编号>` 盖掉（连不到用户的 Docker）」的 bubblewrap 里用系统的 python3 跑了一遍清点（没用 uv，免得写缓存）：0.3 秒，只跑了 `dpkg-query -W`、`-S` 两条；看了主目录 2305 个目录。列出来的和我手动只读看到的一致：
  - 旧的：`~/.local/bin/uv`、`~/.nvm`、`~/.local/share/pnpm`（`~/.local/share/uv` 不存在，uv 没管任何 Python，和设计书 4.8 写的「本机现在的情况」一致）。
  - Pi 靠 Node 运行、现在终端里找到的是旧的 `~/.nvm/versions/node/v26.13.0/bin/node`；Claude Code、Codex、OpenCode 是单个程序，不列。
  - 旧 nvm 里 Node v26.13.0（默认）、全局装的 pnpm。
  - 终端启动文件 7 行：`~/.bashrc` 第 119-121 行（nvm 那三行）；`~/.bashrc` 第 123 行、`~/.profile` 第 29 行、`~/.zshrc` 第 2 行、`~/.config/fish/conf.d/uv.env.fish` 第 2 行（uv 安装程序加的，都写「留着」，因为 `~/.local/bin` 里还有 claude、codex、pi、wt）。fish 那份是这次才知道本机有的。
  - 没有用旧 uv 的 Python 建的环境（本来就没有），没有指向旧位置的后台服务（只有规定位置 Docker 那一个）。

## 自测

`uv run python tests/run_all.py`：单元测试 425 → 434 项，流程沙箱 43 个剧本，总检查 95 个样例，全部通过（一遍，退出码 0）。测试都用 `tests/safehome.py` 的临时主目录，没有真调 AI 的。

## 没做的

- 没接进 `sop machine migrate`（3-31 才有这条命令）；Q3「逐条确认」、Q6 真的卸旧的 nvm、uv、pnpm（删目录、删终端启动文件里那几行）都没做。查了任务清单，3-32（Q6）只写了 Docker 那部分，**卸旧的 nvm、uv、pnpm 没有任务管**，拆成新任务 **3-61**。
- `crontab` 里指向旧位置的没看（要跑 `crontab -l`，而且少见）；`NVM_DIR` 环境变量指着别处（不在 `~/.nvm`、`~/.config/nvm`）的旧 nvm 认不出来（清点 `tools` 部分就找不到它，3-06 的找法）；项目 `node_modules` 里按旧 Node 版本编出来的原生扩展，换了 Node 大版本后可能要重装，没列。
- 「靠 Node 运行」对 sh 启动脚本是看脚本里有没有 `node_modules/.bin/` 或单独的 `node` 字样认的，是猜的，给人看的那一条写了「看启动脚本认出来的」；Pi 自带 Node 的位置是读了本机 Pi 启动脚本的原文写死的一处。
- Pi 用新的 Node 能不能打开（设计书 4.8「这一点装完要验一次」）不是这次的事，没验；这次只在清单里提醒「卸之前新开一个终端确认 node 是 `~/tools/nvm` 里的那份、再打开一次 Pi」。

## 和设计书的出入（留给 3-48）

1. 4.8 的「nvm、uv：旧的选了卸载时，删掉它的目录和终端启动文件里对应的几行」要补一句：uv 安装程序加的 `. "$HOME/.local/bin/env"`（bash、zsh、`.profile`，fish 是 `~/.config/fish/conf.d/uv.env.fish`）作用是把 `~/.local/bin` 放进 PATH，Claude Code、Codex、Pi、wt 的命令也在那里，不能当成「uv 对应的几行」直接删。
2. 旧 uv 除了 `~/.local/bin/uv`，还有它的安装程序放的 `uvx`、`env`、`env.fish` 和 fish 的那一份。
3. Pi 的安装程序可能自带 Node（`~/.local/share/pi-node`），有它时 Pi 不用终端里的 Node；本机没有。

## 自己出的错

- 第一版单元测试把规定位置 `~/tools` 设成了测试临时目录本身，造出来的主目录正好在它下面，结果主目录里的命令目录全被当成「规定位置的」跳过；两项没过才发现，改成规定位置另放一处（`SOP_TOOLS_DIR`）。
- 测试文件第一版里留了两行写着 `if False` 的废代码，跑之前删了。
