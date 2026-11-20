# 3-23 `sop project new` 本机部分（I0、I1、I3、I4）

2026-11-20 做完（主控窗口派的子代理做的）。没有调用 AI，0 美元。没动隔离（特权侧核对、受限环境、专用 Docker 都没碰）；没碰 GitHub。

## 做了什么

- 新模块 `kernel/projectnew.py`，命令 `sop project new <项目名>`（不在项目里也能用，`kernel/cli.py` 加了入口）：
  - **I0 红线预问**：6 问，都是选择题（打 1、2、3），业务语言：受监管业务（持牌金融、医疗数据、未成年人信息）、多少人用、最忙时同时多少人、停一小时损失多大、钱怎么走（只接现成收款服务，还是自己做清算分账）、有没有人要求自己发登录凭证或自己做加密。命中就停，说清原因和可以找哪类专业服务；这时候还没建任何仓库、也没建项目目录。回答暂存本机 `~/tools/sop/state/<项目名>/init/redline.json`（P1 沿用）。
  - **I1 公开还是私有**：把 7.2 的对比表一行一行用大白话摆出来，加一句「企业项目多半只能选私有」，选完写选择记录 `init/visibility.json`，之后写进 `sop.json` 的 `visibility`。
  - **I2 留了接口** `GitHubSide.create()`（3-24 用 `wt init --create` 接上）；默认的那一份直接停下，说「GitHub 那一半还没做（3-24），回答已记下，什么都没建」。I5 到 I7 同样留了 `GitHubSide.publish()`。
  - **I3 写项目模板**：`templates/project/` 原样复制进项目的 `main/`（真的 I2 之后那里只有 GitHub 建仓库时带的 README），再写 `sop.json`（项目名、工具包仓库和版本、档案段两个空列表、公开还是私有；风险等级等 P1）。模板加了 `.gitignore`（`.env`、`.claude/settings.local.json`：准备脚本会把 `.env` 链接进每个工作目录，不忽略就会被提交）；`AGENTS.md` 末尾加了 `setup-matt-pocock-skills` 本来会写的「## Agent skills」那一段（工单存本地文件、默认五个标签、单一术语表，各指向 `docs/agents/` 的文件）。
  - **I4 装技能和技能配置**：从工具包副本 `skills/mattpocock/skills/<分类>/<技能>/` 逐字节复制到 `.claude/skills/<技能>/` 和 `.agents/skills/<技能>/`（去掉分类那一层；执行权限按原文件，不覆盖已有的东西、不跟软链接）。许可文件原样放在技能目录之外：`.claude/LICENSE-mattpocock-skills`、`.agents/LICENSE-mattpocock-skills`。`docs/agents/` 写 `setup-matt-pocock-skills` 目录里那三份种子文件，原样：`issue-tracker.md`（本地文件那份）、`triage-labels.md`、`domain.md`。
  - I3、I4 写完跑出口检查（下面的目录结构检查，带项目根），过了在本机提交一次（特权侧自己的 Git、关钩子），**不推送**（I5 是 3-24 的事）。
  - 开头先查：项目名合法、`~/Project/<项目名>` 不存在或是空的、有人能回答（不在终端里就停）；问完 I0、I1 后、建仓库之前查 Git 的提交身份设了没有（3-22 发现新电脑上没人设，没设就停、什么都没建）。
- **装哪些技能，由脚本从技能原文里查**（附录 B 末尾那句）：`checks/project_layout/core.py` 里只列附录 B 直接写了用途的 16 个（`WANTED`），再一层层找它们调用的技能。原文调用别的技能只有两种写法：一行里有「Skill tool」、名字在引号或反引号里（`Call the Skill tool with "tdd"`）；或者「the \`x\` skill」。查出来的 5 个是 `grilling`、`domain-modeling`、`tdd`、`codebase-design`、`writing-for-agents`，合计 21 个，正好是附录 B 那张表（不含 `wizard`、`setup-matt-pocock-skills`）。`setup-matt-pocock-skills` 被很多技能提到，但都是「没配置就让用户去运行它」，不算调用（7.2 定了不运行它）。
- **新检查 `checks/project_layout/`**（14.2「目录结构、技能文件与工具包一致」，I3 的出口检查）：5.2 的初始文件都在；`AGENTS.md`、`CLAUDE.md` 和工具包模板逐字一致；`.gitignore` 里有 `.env`；`sop.json` 读得出、该有的几项都在；两处技能目录有且只有那 21 个，每个和副本逐字一致（内容一个字节、换行、执行权限、多了少了都报，算法和 `skills_pristine` 同一份）；两份许可、`docs/agents/` 三份和工具包里的逐字一致；给了项目根时再看 5.1（裸仓库、`.shared/hooks/`、`main/`）。之后会被技能或档案照规矩改的（术语表、`docs/standards/`、检查流程）只要求在。样例 18 个（总检查 71 → 89）：应通过 3 个（刚建好、之后照规矩改了几样、带项目根），应报错 15 个（技能改一个字、只改换行、只加执行权限、技能目录多一个文件、少装被依赖的 `writing-for-agents`、多装 `wizard`、没去掉分类那一层、少许可、许可放进技能目录、`docs/agents/` 改了、`CLAUDE.md` 改了、`sop.json` 没写公开私有、`.gitignore` 没有 `.env`、少守门流程文件、项目根少 `.shared/`），每个都只报出它那一处。样例用 `checks/project_layout/make_sample.py` 造现场（就是调 I3、I4 的那两个函数）。
- `kernel/paths.py` 加 `projects_dir()`（`~/Project`，自测用 `SOP_PROJECTS_DIR` 换掉）。
- 单元测试 `tests/unit/test_project_new.py` 15 项（249 → 264）。

## 复制出来的和副本逐字一致，怎么证明的

- 每个装进去的技能目录（两处各 21 个）按 Git 的算法算树编号，和用 `skills/source.json` 里记的上游每个文件的指纹算出来的比，一个不差；两份许可文件的指纹等于 `source.json` 里 `LICENSE` 那一项（`f1dd2c0…`）。
- 全过程那项测试提交以后，再用 Git 自己的 `git rev-parse main:.claude/skills/<技能>`、`main:.agents/skills/<技能>` 比一次，也和上游的一样。
- 反着试：把复制改成跳过 `agents/openai.yaml`，逐字一致的测试、模板那项测试失败，全过程两项在出口检查那一步停下（报错）；改回来全过。
- 技能副本本身（`skills/mattpocock/`）一个字没动；总检查里的 `skills_pristine/pass-toolkit` 照旧通过。

## 测试怎么做的、结果

- 全过程（2 项）：剧本里的人回答 I0、I1；I2 用一个替身（在 `/tmp` 造一个像 `gh repo create --add-readme` 那样带一个 README 提交的假远程，再经接入层 `wtx.init` 用本机的 wt（只用不改）建项目根）。结果：5.1 的结构对、目录结构检查（带项目根）通过、特权侧核对通过；本机 main 上两个提交（GitHub 的 README 那个加我们的初始内容），远程还是只有 README 那个；工作目录干净；`sop.json` 的版本是正在运行的工具包的提交编号；回答记录在；gh 一次没找；临时主目录里除了测试自己放的 `.gitconfig` 什么都没多，`TMPDIR` 是空的。选公开那一遍 `visibility` 是 `public`。
- 红线（2 项）：6 问的每一个命中选项单独试，都停下、说出对应的专业服务、GitHub 替身一次都没被调、项目根没建、I1 没问；每一个不命中的选项都过。
- 停下的几种（5 项）：GitHub 那一半没做时问完就停、什么都没建；项目根已有东西时一句都不问就停；没人回答时停；没设 Git 提交身份时停在建仓库之前；命令行 `sop project new demo` 照剧本问完、停在 3-24 那一句（退出码 1），项目名不合法或参数不对说用法（退出码 2），没终端没剧本说要在终端里回答。
- 写文件（6 项）：装的技能就是附录 B 的 21 个、查依赖的两种写法、逐字一致、模板和种子文件逐字一致、不覆盖已有文件、执行权限按原文件。

自测：做之前（主控窗口跑的）单元测试 249 项、流程沙箱 24 个剧本、总检查 71 个样例，全部通过。做完跑了两遍（第一遍跑的时候我改了两份说明文件，怕沙箱里的工具包快照前后不一，又跑一遍）：两遍都是单元测试 264 项、流程沙箱 24 个、总检查 89 个样例，全部通过。

## 替用户定的事（可否决，留给 3-48 写进设计书）

- **红线规模三问的分界**（1.3 第二条「由脚本换算」，设计书没给数）：几百万人以上用、最忙时同时十万人以上、停一小时是大事故必须几分钟内在另一处顶上，三样有一样就算超出。其余答案（含「几万到几十万人」「几千到几万人同时在用」）都放行。
- 红线第三条用业务语言问了两问：钱的事（自己做清算、分账、替别人收付款算命中；只接微信支付、支付宝这类现成服务不算）；有没有人要求自己发登录凭证、自己做加密。
- 许可文件的位置：`.claude/LICENSE-mattpocock-skills`、`.agents/LICENSE-mattpocock-skills`，不放进 `.claude/skills/`、`.agents/skills/` 里（那两个目录里只放技能目录，免得哪个 AI 工具把一个普通文件当成技能来认，这一点没试过）。它们在 `.claude/`、`.agents/` 下，本来就是受保护路径。
- `docs/agents/` 三份原样用 `setup-matt-pocock-skills` 的种子文件，没有改写。种子文件里工单的状态行写的是英文 `Status:`、没有覆盖行和风险行，和工具包自己的工单格式（`checks/README.md`：「状态：」「覆盖：」「风险：」）对不上。附录 B 早就记着「工单要有覆盖行和风险行：写在项目规则或工单格式的配置文件里，没有验证」，要等第 2a 期 W25 核对技能实际产出时一起定，这次没动。
- I3、I4 写完在本机提交一次、不推送；I5 只管推。

## 和设计书的出入（留给 3-48）

- 7.2 I3 的出口检查「目录结构检查」现在是 `checks/project_layout`，查什么见上；14.2 说它「两处」运行，GitHub 上的项目检查流程还没接它（门禁要到第 2a 期才接上档案；接的时候要像守门检查那样按 `sop.json` 取工具包那个版本）。
- 5.2 没写 `.gitignore`、许可文件；7.2 没写 I0、I1 的回答暂存在 `state/<项目名>/init/`。
- 附录 B「由脚本从技能原文里查出来」：查法是上面那两种写法，`setup-matt-pocock-skills` 例外。

## 没做的

- GitHub 那一半（I2 建仓库、I5 推主线、I6 日志分支和保护和事件规则、I7 四个试验 PR）：3-24。I2 的 owner（GitHub 账号名）、仓库地址也在那里定。
- 中途断了重跑：现在项目根已有东西就不接着做。I2 之后、I5 之前断了怎么接，等 3-24 把整条串起来时一起做。
- `sop.json` 里工具包仓库的地址：取 `SOP_TOOLKIT_REPO`，没有时用 `DEFAULT_REPO`，现在是空的（和 `bootstrap.sh` 一样等 3-41），所以真用时会停在「工具包仓库的地址还没定」。
- 没有在真的终端里手打一遍（`TtyHuman` 是第二段写的，这次只经剧本测）。

## 自己出的错

- 第一次跑单元测试，「每个不命中的选项都过」那项 10 处报错：剧本用到第几条记在状态目录里，子测试之间没清，后面的就取不到回答。加了每次清空。
- 想用软链接把新检查单独挂到一个临时目录里跑总检查，检查脚本按自己的位置找 `checks` 包，软链接下找不到，全部崩了。顺带发现：**检查脚本在导入那一步就崩时退出码是 1，总检查会把「应报错」的样例算成「符合」**（`lib.cli` 只兜得住 `run()` 里的错，兜不住导入）。这次 15 个应报错样例的结论我逐条看过，都是报出了它那一处、不是崩了；总检查本身没改，记在这里。

## 本机有没有被改

- `~/tools/wt`：`GIT_OPTIONAL_LOCKS=0 git status --porcelain --ignored` 前后都是空的，提交还是 `9502f8c`。
- 单元测试的主目录、`TMPDIR`、项目目录（`SOP_PROJECTS_DIR`）、工具包根目录都在 `/tmp` 下的临时目录里，测完删了。没碰 `~/Project`、`~/tools/sop/state`、`~/tools/sop/config`。
- 跑全部自测前打了时间记号，跑完查主目录下比它新的东西：只有聊天软件、Codex、Cursor 自己的日志和数据库，`~/.gitconfig`、`~/.bashrc`、`~/.ssh/` 的修改时间没变。
- 没用 sudo，没动 Docker、虚拟机，没碰 GitHub（gh 一律是假的），没调用 AI。

## 留在外面的东西

- `/tmp/sop-3-23-run/`：时间记号和两遍全部自测的输出，做完删了。别的临时目录（试检查、反着试的备份）用完当场删了。
