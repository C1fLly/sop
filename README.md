# AI 开发 SOP 工具包

让没有编程基础的人指挥 AI 开发企业生产级项目的一套工具（命令 `sop`）。设计见 `docs/设计书.md`。

第 1 期第二段写了内核（事件日志、流程引擎、受限运行器、检查库的通用部分、「假 AI」、流程沙箱）；目前是第三段：机器层和接入，按 `docs/第三段/任务清单.md` 一个一个小任务做。

## 目录

| 目录 | 内容 |
|---|---|
| `bootstrap.sh` | 第零步引导脚本（只用 bash）：网络、git 和 curl、取工具包、装 uv、启动器，最后提示 `sop machine setup`；`--offline` 给离线包用 |
| `kernel/` | 内核：读流程定义、读写事件日志、拼任务包、调用执行者、校验结果（Python，只用标准库） |
| `runner/` | 受限运行器：在读不到凭据的环境里启动 AI 和一切项目代码；`runner/docker/` 是专用 Docker（换根脚本、按项目的用户级后台服务和资源分组 `service.py`、它那份隔离自检） |
| `flows/` | 流程定义（TOML） |
| `checks/` | 检查库，每个检查附「应通过」和「应报错」的样例 |
| `prompts/` | 任务包模板 |
| `machine/` | 机器层：基础工具清单 `tools.toml`、机器级配置和登记（`~/tools/sop/config/` 下的网络设置、工具位置、系统组件版本）、体检（分区判断、剩余空间、系统组件版本、工具在不在规定位置、AI 工具，`sop machine doctor`）、M6 隔离自检（本机那份加专用 Docker 那份，通过后记登记）和系统升级后推进流程之前先重跑（`syscheck.py`）、M7 各 AI 工具全局规则文件里的受管段落（`globalrules.py`，原文 `global-rules.md`）、离线包（`offline/`：在能上网的电脑上 `pack.sh` 打成一个文件，断网的电脑上 `bash <文件>` 走第零步）、M3 登录 GitHub（gh 网页登录、SSH 密钥和 GitHub 的主机钥匙、没设的 Git 提交身份，`ghsetup.py`）、M4 登录 AI 工具（服务地址和密钥登记在 `config/ai/<工具名>.env`，出口检查调适配器自检，`aisetup.py`）、M5 安装 wt 和它的出口检查（`install/wt.sh`、`wtsetup.py`）、M2 安装 uv、nvm、Node、pnpm、gh、免管理员的 Docker 和它要的系统软件包（`install/` 下的安装脚本、`install.py`；装系统软件包时等住软件包的锁的那一小段 `install/apt.sh`，第零步里抄了一份；终端启动文件里那一段和缓存目录 `shellenv.py`）、`sop machine setup` 把 M2 到 M7 串起来（每步出口检查、合格的跳过、中途断了接着做，进度在 `config/setup.json`，`setup.py`）、`sop machine` 命令 |
| `skills/` | 技能副本：mattpocock/skills 在提交 `5863806` 时的 `skills/` 和许可文件，原样（`skills/mattpocock/`），版本记录 `source.json`；总检查的 `checks/skills_pristine` 每次逐字核对，见 `skills/README.md` |
| `adapters/ai/` | AI 工具适配器：Claude Code（`adapters/ai/claude/`）、测试用的假 AI（`adapters/ai/fake/`） |
| profiles/（还没有） | 技术栈、端、部署档案，第 2a 期起放进来；流程沙箱用的测试档案在 `tests/fakes/profiles/stack/fake/` |
| `templates/` | 新项目仓库的初始文件（`sop project new` 的 I3 原样复制，见 `kernel/projectnew.py`；装哪些技能、目录结构检查在 `checks/project_layout/`；GitHub 那一半 I2、I5 到 I7 在 `kernel/projectgh.py`；检查流程 `sop-check.yml` 跑的项目检查是 `checks/project_check/`）、wt 用的模板 |
| `tests/` | 自测：单元测试、流程沙箱、假的 `gh`（`sop project new` 新建的仓库检查真跑，见它开头的说明）；`tests/vm/` 是验证用的虚拟机脚本（按名字现建、一键还原；`m2.sh`、`docker.sh` 在虚拟机里验 M2 安装，`m6m7.sh` 验 M6、M7，`m0.sh` 验第零步，`offline.sh` 验离线包，`dockersvc.sh` 验专用 Docker 的服务和分组，`dockeridle.sh` 验它用时才起、闲了停，`twoproj.sh` 验两个项目同时开（3-19），`aptlock.sh` 验系统正在自己更新软件时装系统软件包会等它（3-56）；不在 `run_all.py` 里） |
| `docs/` | 设计书、审查记录、试验记录 |

## 跑自测

```bash
uv run python tests/run_all.py
```

不给部分就跑四样：单元测试 `unit`、流程沙箱 `sandbox`、总检查 `checks`、文档检查 `docs`（设计书里的章节号、步骤编号没有悬空；设计书和各 README 里写的 `sop …` 在命令表 `kernel/commands.py` 里、写的仓库里的路径存在，`checks/doc_refs/`），也可以只给其中几样。`--no-skip`：有测试被跳过就算没通过。

**修完工具包之后的把关（3-44）**：`sop self check [--repo <开发目录>] [--base <起点>] [--isolation]`（代码 `kernel/selfcheck.py`）。在开发目录里把这四样一样一样跑完（命令和 GitHub 上的一样），再请另一个模型（Claude Code，只读放法）复查相对起点的改动，动了隔离、放行事件、事件日志三处的还要加 `--isolation` 跑隔离自检（会起专用 Docker）和破坏演练（3-47 还没做时如实说「还没有」、不算过）；最后一句只说「过了」或「没过，卡在哪」。`tests/selfcheck_demo.py` 在 `/tmp` 的副本上造几种没过的改动验它（手动跑，不花钱）；真调 AI 复查的是 `tests/real_ai/selfcheck_review.py`。

工具包仓库放到 GitHub 上以后，`.github/workflows/check.yml` 把这四样分成同名的四个检查各跑一遍（3-40；单元测试、流程沙箱带 `--no-skip`）；跑检查的临时电脑由 `tests/ci/prepare.sh` 准备（只在 GitHub 上跑，本机不要跑）。隔离自检、真实 AI 演练只在本机跑。

uv 只用系统自带的 Python（`pyproject.toml` 里禁止它另外下载）。所有测试都在 `/tmp` 下的临时目录里做，不碰 `~/tools/sop/state`、`~/tools/sop/config`。

**自测的保险（3-59）**：`tests` 这个包一被导入，整个测试进程的主目录（HOME、XDG_*）就换成 `/tmp/sop-test` 下现建的公用假主目录，去掉 AI、GitHub、Docker、SSH 代理一类的变量，PATH 去掉本机主目录下的目录（要用的 uv、uvx、wt 链接进假主目录的 `bin`），见 `tests/safehome.py`；`TempHome` 再给每个测试一个自己的主目录。工具包里会写主目录的入口（`sop machine setup`、M2 安装、`~/.bashrc` 那一段、M3、M4、M5、M7）先过 `kernel/paths.py` 的 `guard_home`：主目录是那个公用的假主目录（测试漏设了 HOME），或者是本机真的主目录、环境却像在自测里（`SOP_HOME` 等不是默认的、HOME 没设），都停下不做。测试要只读地用本机真的主目录（例如 `~/tools/wt`）时用 `tests.safehome.REAL_HOME`。
