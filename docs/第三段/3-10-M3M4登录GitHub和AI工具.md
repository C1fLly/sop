# 3-10 M3、M4：登录 GitHub、登录 AI 工具

2026-11-21，主控窗口派的子代理做的。**没有真的调用 AI，0 美元**（M4 的出口检查调的是 3-27 已经真跑过的自检 `probe`，这次只用假的 claude 测）。没碰真的 GitHub，没碰本机的 gh 登录、`~/.ssh`、`~/.gitconfig`、AI 工具的配置；没开虚拟机。

## 做之前查到的

- 本机的 gh 是 `/usr/bin/gh` 2.103.3。在 `/tmp` 下的临时 HOME、临时 `GH_CONFIG_DIR` 里看了 `gh auth login`、`gh auth status`、`gh ssh-key add`、`gh auth refresh` 的帮助（没读本机的 gh 登录）：
  - 网页登录时 gh 至少申请 `repo`、`read:org`、`gist` 三项，这三项去不掉（`--remove-scopes` 也去不掉），`--scopes` 只能再加。
  - `-p ssh` 时 gh 会自己找或生成 SSH 密钥、问要不要传（英文问答），`--skip-ssh-key` 跳过。
  - 没登录时 `gh auth status` 退出码 1；`--json hosts` 给 `{"hosts":{}}`、退出码总是 0（所以出口检查用不带 `--json` 的那种）。
  - 登录凭据默认存系统的钥匙串，没有钥匙串时退回到 `~/.config/gh` 里的明文文件（gh 自己说的）。工具包不改这个默认。
- 设计书 4.5：M3 出口检查「`gh auth status` 通过，SSH 连通」，只申请用得到的权限、不要 `workflow`；M4 出口检查「启用的每个适配器自检通过」，只真发一次最短的调用、不看工具自己的「是否已登录」；官方账号如实说没验证过（W37）。

## 做了什么

### M3 `machine/ghsetup.py`

- **引导** `setup()`：先跑出口检查，过了就跳过。不过时：
  1. gh 没登录：用 gh 的网页登录（终端里出一次性代码、浏览器里填），命令是 `gh auth login --hostname github.com --git-protocol ssh --web --skip-ssh-key --scopes admin:public_key`。**只多要 `admin:public_key`**（把这台电脑的 SSH 公钥传到账号上要用），加上 gh 去不掉的 `repo`、`read:org`、`gist`；不要 `workflow`、`delete_repo`。SSH 密钥不让 gh 去问（英文问答），由工具包自己做。
  2. 用 `gh api user` 取账号名、编号、名字。
  3. **Git 提交身份**：`user.name`、`user.email` 没设的才设（`git config --global`，写 `~/.gitconfig`），名字用 GitHub 上填的名字（没填用账号名），邮箱用 GitHub 给的不公开邮箱 `<编号>+<账号>@users.noreply.github.com`；已经设了的一项都不动。**这是主控窗口按 3-22 的推荐替用户定的，用户可以否决。**
  4. **SSH**：先试 `ssh -T git@github.com`（`BatchMode=yes` 不停下来问、`StrictHostKeyChecking=yes` 不自己记主机钥匙、10 秒连不上就算）。
     - 说「主机钥匙不认识」：从登录后的 `gh api meta` 取 GitHub 自己说的 SSH 主机钥匙（走加密网页、带着登录），补进 `~/.ssh/known_hosts`：只往后加，已有的行一个字不动，同一行不重复加。这样不用「第一次见到就信」。
     - 说「不认密钥」：`~/.ssh/id_ed25519` 没有才生成（ed25519、**不设口令**：工具包的脚本推送时不能停下来问口令；受限环境本来就看不到 `~/.ssh`，6.2），已有的一把都不动、不覆盖（只有私钥或只有公钥的半套也不动，停下说清）；用 `gh ssh-key add` 传上去（标题「sop <电脑名>」）。以前登录的凭据没有 `admin:public_key` 时，用 `gh auth refresh --scopes admin:public_key` 补一次（浏览器再点一下）再传；GitHub 说已经有这把了也算成。
     - 连不上（网络）：不去生成、上传密钥，照实说。
  5. 做完再跑一遍出口检查，结果给 `report()`。
- **出口检查** `check()`（不改任何东西）：gh 在不在（PATH 里规定位置 `~/tools/gh/bin` 在最前面）；`gh auth status --hostname github.com` 通过；权限里有 `workflow`、`delete_repo` 这类用不着的只**提醒**（以前登录的不替他改，说怎么收窄）；SSH 连通，而且连上的就是 gh 登录的那个账号（不是同一个就不通过：推送会用另一个账号的身份）；Git 提交身份设了（M5 的 `wt doctor` 没有它算失败）。
- 跑 gh、ssh、git 的环境：规定位置的工具在 PATH 最前面、网络设置里的代理、去掉外面带进来的 `GIT_` 变量和 `GH_REPO`、`GH_HOST`。
- `python3 -m machine.ghsetup`（引导再检查）、`--check`（只检查），给 3-12 的 `sop machine setup` 用、虚拟机验证用。

### M4 `machine/aisetup.py`

- **登记文件** `~/tools/sop/config/ai/<工具名>.env`（问题 5）：`config/`、`config/ai/` 都是 0700，文件 0600，先写临时文件再换名；每行 `名字='值'`（值不能带换行、单引号）。地址那一项叫 `ANTHROPIC_BASE_URL`（以 `BASE_URL` 结尾，3-50 的体检按它试连，单元测试核对了）。
- **引导** `setup()`：
  - 已经登记过、自检通过：跳过，一个问题不问（自检照样真发一次最短的调用，花几美分，照实说）。登记过但自检没过：说原因，问要不要重填；**余额不足一类的错：不问重填、不重试**，直接停下提示充值。
  - 先问用的是「1 自己配的服务」还是「2 官方账号登录」。选 2：如实说「没有验证过（W37）」，什么都不登记，这一步算不通过。
  - 终端里已经设了 `ANTHROPIC_BASE_URL` 和密钥（这台开发机就是这样）：给他看地址（去掉里面的账号密码、参数），密钥不显示，问一句「就用这一份吗」，答是就把终端里 `ANTHROPIC_` 开头的几项照搬（和 3-27 适配器没有登记文件时的退路是同一套）；`CLAUDE_CODE_` 开头的是当前会话自己的，不带。
  - 否则让他填地址（要 `http://` 或 `https://` 开头）和密钥（`getpass`，输入时屏幕上不显示；空的、带空格单引号的不收），再问密钥是填在 `ANTHROPIC_AUTH_TOKEN`（默认）还是 `ANTHROPIC_API_KEY`（服务商说明里写的是这个时选 2）。
  - 写好就跑出口检查。
- **出口检查** `check()`：对「启用的」每个工具（第 1 期只有 Claude Code 有适配器，`TOOLS` 里只有它；Codex、OpenCode、Pi 的适配器在第 5 期，报告里写明这一步现在不登记它们）：登记文件在、只有自己能读（别人能读就让先 `chmod 600`，不发调用）、有地址、有密钥，前面哪样不对都不发调用；都对就调 3-27 的 `ClaudeAdapter.probe()`：在 `/tmp` 一次性小项目里、受限环境里真发一次最短的调用。报告里写花了多少、版本提醒（还没做过真实 AI 演练）、余额不足时「先暂停，充值以后再跑一次（这次没有重试）」。
- 出口检查要求**登记文件存在**：适配器在没有登记文件时会退回用终端里的环境变量（3-27），但从别的终端、桌面上启动 `sop` 时没有那几个变量，所以 M4 不认这条退路，没登记就不通过。
- 密钥不打印、不进报告；单元测试核对了所有屏幕上的话和提问里都没有密钥原文。
- `python3 -m machine.aisetup`、`--check`。

### 假的东西

- 假 gh（`tests/fakes/gh/gh`）：`$FAKEGH_HOME/auth.json` 存在时登录状态按它来（`auth status` 照真 gh 的样子列账号、协议、权限；`auth login` 只认网页登录，权限是去不掉的三项加 `--scopes`，`$FAKEGH_LOGIN_FAIL` 模仿关了浏览器；`auth refresh`；没登录时其他命令报要先登录；`api meta` 给假的主机钥匙；`ssh-key add` 没有 `admin:public_key` 时照 GitHub 的样子报错；每条 auth、ssh-key 命令记下来）。没有这个文件时照旧一律「登录了」，原来的剧本不受影响。`api user` 多给了 `id`、`name`。
- 假 ssh（`tests/fakes/ssh/ssh`，新的）：必须带 `BatchMode=yes`；`known_hosts` 里要有假 gh 给的主机钥匙；`~/.ssh` 里的公钥要在假 GitHub 上；都对说「Hi <账号>!」、退出码 1；能模仿连接超时、连上的是另一个账号。
- 假 claude：多认 `https://<表现>.fake.invalid` 这种地址（M4 只收 `http(s)` 开头的地址）。

## 测试

- `tests/unit/test_machine_ghsetup.py` 19 项：每项开头先确认找到的 gh 是临时工具目录规定位置的假 gh、ssh 是假的、主目录在 `/tmp/sop-test` 下；`XDG_CONFIG_HOME` 也指到临时主目录（不然 Git 可能去读写本机的 `~/.config/git/config`）。ssh-keygen 用真的，只在临时主目录里生成测试用的密钥。
  - 全新的电脑走一遍：登录命令一字不差、权限只有那四项；生成的密钥权限 600、`.ssh` 700、公钥传上去一次、标题「sop …」；`known_hosts` 加了两行；提交身份按账号设（名字、不公开邮箱）；所有 SSH 都带 `BatchMode=yes`、`StrictHostKeyChecking=yes`；再跑一次「跳过」、主目录一个文件没变、只查了 `auth status`。
  - GitHub 上没填名字时用账号名；只做检查时什么都不改、三样都报出来；登录取消了什么都不写；没装 gh。
  - 已有的提交身份不动（文件一字不差）、只缺邮箱只补邮箱；已有的 `id_ed25519` 不覆盖、传的是它；另有一把 `id_rsa` 不动、另生成 `id_ed25519`；半套密钥不动、停下；`known_hosts` 原来的行（最后一行没换行的）不动、只往后加、再补不重复；以前登录没有 `admin:public_key` 的补一次权限再传；公钥已经在账号上不再传。
  - 检查：多了 `workflow`、`delete_repo` 只提醒；SSH 连上另一个账号不通过；SSH 网络不通说「22 端口」、引导不去生成上传密钥；后来退出登录了不通过；报告；用法。
- `tests/unit/test_machine_aisetup.py` 18 项：开头确认用的是假 claude、登记文件在 `/tmp/sop-test` 下。自检在真的 bubblewrap 里跑（和 3-27 一样）。
  - 检查：没登记、别人能读、没地址、没密钥都不发调用；登记好了通过、有花费、有演练提醒、报告里有「第 5 期」、没有密钥；余额不足 `quota`、只调一次；报错不算通过。
  - 引导：手填地址密钥（文件 600、两层目录 700、内容对、适配器读得到、来源是这份文件、体检取到的地址对、没留临时文件、屏幕上没有密钥）；选 `ANTHROPIC_API_KEY`；照搬终端里的（只带 `ANTHROPIC_` 开头的，提问里的地址去掉了账号密码和参数）；不照搬改手填；官方账号（W37、不写文件、不调用）；地址不对、密钥带空格、密钥空的都不写；已经好了跳过、一个问题不问；余额不足不问重填、只调一次；坏了不重填 / 重填；写文件拒绝换行、单引号、坏名字、空值；整个 `setup()`。
- 全部自测：做之前（主控窗口跑的）单元测试 307 项、流程沙箱 32 个剧本、总检查 95 个样例，全部通过。做完：见文末。**全部自测里没有会真调 AI 的测试**（M4 的自检在单元测试里一律用假 claude，`Counting` 那个子类核对调了几次）。

## 有没有改动本机

- 跑的程序：只读地看了几个 gh 命令的帮助（`/tmp` 下的临时 HOME、临时 `GH_CONFIG_DIR`，跑完删了；`gh auth status` 在那里报「没登录」——那是临时目录，没读本机的登录）；单元测试和全部自测（都在 `/tmp/sop-test` 下）。
- 做之后核对：`~/.gitconfig`、`~/.ssh`、`~/.ssh/known_hosts`、`~/.config/gh` 的修改时间都是 11 月 8 日（没被改过）；`~/tools/sop/config` 仍不存在。只看了修改时间，没打开这几样里的文件。
- 没调到真的 gh（测试里 gh 是假的，开头核对过；查帮助用的 `/usr/bin/gh` 不登录、不连网）；没在 GitHub 上建改删任何东西；没用 sudo、没动 Docker。

## 没做的

- **真的 GitHub 上走一遍 M3 没做**：要浏览器点授权、会往账号上加 SSH 公钥，不能在本机用用户的账号试。所以这几样只在推理上成立，3-15 在虚拟机里验收时会真走：`--web --git-protocol ssh --skip-ssh-key` 这一组合在真 gh 上还会不会再问别的；`gh api meta` 的 `ssh_keys` 是不是「类型 内容」这种样子（GitHub 文档是这样写的）；`gh ssh-key add` 缺权限时报错里是不是带 `admin:public_key`（真 gh 是这么提示的，假 gh 照抄）、重复传时是不是带 already。
- **问题 4 的那份凭据**（只勾 `repo`、用户在网页上建的）：网页登录拿不到只有 `repo` 的凭据；用那份凭据要走 `gh auth login --with-token`，而 gh 说那种凭据至少要 `repo`、`read:org`、`gist`。虚拟机里（3-15）怎么登录，到时按实际情况定。M3 的引导现在只做网页登录这一种。
- 已有的密钥设了口令：工具包认不出来，SSH 会报「不认密钥」，引导去传公钥之后仍不通，报告说「或者密钥设了口令」。没有专门处理。
- SSH 只试 22 端口；22 端口被挡、要走 443（`ssh.github.com`）的网络没做（3-50 的体检会先报出来）。
- Codex、OpenCode、Pi 的登记：它们的适配器在第 5 期，那时把它们加进 `aisetup.TOOLS`（地址那一项的名字以 `BASE_URL` 结尾）。
- 没接到 `sop machine setup`（3-12 串）；**提醒 3-12**：M4 的出口检查每跑一次就真花一次钱（几美分），「已经合格的跳过」那一层判断要不要每次都跑它，3-12 定（例如登记里 `probe_ok` 是真、版本没变就不重跑）。
- M4 的出口检查这次没有真的调 AI：`probe` 本身 3-27 真跑过（读的是终端里的环境变量）；M4 新加的只是把地址和密钥写进登记文件、再由适配器读出来，这一段单元测试核对了适配器读到的就是写进去的那一份。

## 和设计书的出入（留给 3-48）

- 4.5 M3：写明网页登录的命令和权限（gh 去不掉 `repo`、`read:org`、`gist`，另只加 `admin:public_key`）；SSH 密钥工具包自己生成（没有才生成、不设口令）、`gh ssh-key add` 传；GitHub 的主机钥匙从 `gh api meta` 取、补进 `known_hosts`；出口检查另加「SSH 连上的是同一个账号」「Git 提交身份设了」两条；权限偏大只提醒。
- 4.5 M3 补上 Git 提交身份（3-22 发现的）：没设时按 GitHub 账号设、不公开邮箱、已设的不动（主控窗口替用户定的）。4.3 的例外里 `~/.gitconfig`、`~/.ssh` 已经有了。
- 4.5 M4：登记文件的格式和权限；终端里已经有设置时可以照搬；出口检查要求登记文件存在（不认适配器的环境变量退路）；第 1 期「启用的」只有 Claude Code。
- 3-27 记的「问题 5 的退路（没有登记文件时用终端里的环境变量）」：适配器里照旧留着；M4 的出口检查不认它。

## 自己出的错

- 「多了用不着的权限」那项测试第一次按我写的先后（workflow、delete_repo）比，实际按字母排在前面的是 delete_repo，改了测试。
- 体检取到的 AI 服务地址带了结尾的 `/`（3-50 只试主机的根路径），测试第一次没写。

## 自测结果（做完）

单元测试 307 → 344 项（多了这 37 项：M3 19 项、M4 18 项），流程沙箱 32 个剧本，总检查 95 个样例，全部通过（跑了一遍）。原来用假 gh 的剧本和单元测试都没受影响（假 gh 只有 `auth.json` 存在时才换成新的登录状态）。

## 留在外面的东西

没有。看 gh 帮助用的临时目录、自测输出都删了；`/tmp` 下没留 `sop-probe-*`、`sop-wt-doctor-*`。
