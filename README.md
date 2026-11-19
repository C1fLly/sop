# AI 开发 SOP 工具包

让没有编程基础的人指挥 AI 开发企业生产级项目的一套工具（命令 `sop`）。设计见 `docs/设计书.md`。

第 1 期第二段写了内核（事件日志、流程引擎、受限运行器、检查库的通用部分、「假 AI」、流程沙箱）；目前是第三段：机器层和接入，按 `docs/第三段/任务清单.md` 一个一个小任务做。

## 目录

| 目录 | 内容 |
|---|---|
| `kernel/` | 内核：读流程定义、读写事件日志、拼任务包、调用执行者、校验结果（Python，只用标准库） |
| `runner/` | 受限运行器：在读不到凭据的环境里启动 AI 和一切项目代码 |
| `flows/` | 流程定义（TOML） |
| `checks/` | 检查库，每个检查附「应通过」和「应报错」的样例 |
| `prompts/` | 任务包模板 |
| `machine/` | 机器层：基础工具清单 `tools.toml`、机器级配置和登记（`~/tools/sop/config/` 下的网络设置、工具位置、系统组件版本）、体检（分区判断、剩余空间、系统组件版本、工具在不在规定位置、AI 工具，`sop machine doctor`）、系统升级后推进流程之前先重跑隔离自检（`syscheck.py`）、`sop machine` 命令 |
| `adapters/ai/` | AI 工具适配器（目前只有测试用的 `fake`） |
| `profiles/` | 技术栈、端、部署档案（目前只有测试用的） |
| `templates/` | 新项目仓库的初始文件、wt 用的模板 |
| `tests/` | 自测：单元测试、流程沙箱、假的 `gh`；`tests/vm/` 是验证用的虚拟机脚本（按名字现建、一键还原，不在 `run_all.py` 里） |
| `docs/` | 设计书、审查记录、试验记录 |

## 跑自测

```bash
uv run python tests/run_all.py
```

uv 只用系统自带的 Python（`pyproject.toml` 里禁止它另外下载）。所有测试都在 `/tmp` 下的临时目录里做，不碰 `~/tools/sop/state`、`~/tools/sop/config`。
