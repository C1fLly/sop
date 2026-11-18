# 核对：四个 AI 工具的本机情况

状态：已完成（2026-11-17）。只看了帮助说明、状态查询和官方文档，**没有调用任何 AI，没有花钱**。

这不是第 0 期九项试验之一，是试验 S1、S2、S5 开始前的事实核对。结论已填进设计书 10.2 和附录 C。

## 做了什么

环境：Ubuntu 26.04.1 LTS，内核 7.0.0-43。

| 做的事 | 命令 |
|---|---|
| 看版本 | `claude --version`、`codex --version`、`opencode --version`、`pi --version` |
| 看帮助 | `codex --help`、`codex exec --help`、`codex exec resume --help`、`codex login --help`、`codex sandbox --help`、`codex doctor --help`、`codex features --help`；`opencode --help`、`opencode run --help`、`opencode auth --help`、`opencode session --help`、`opencode debug --help`、`opencode service --help`；`pi --help`、`pi auth --help` |
| 看登录状态 | `codex login status`、`codex doctor`；`opencode auth list`（单独运行和经后台服务各一次）；`pi auth check --provider <名称> --no-refresh`（试了七家）；`pi --list-models --offline` |
| 看功能 | `codex features list`、`opencode debug agents`、`opencode debug paths` |
| 读官方文档 | Codex 的技能页、OpenCode 的技能页、Pi 的技能页。经网页摘要工具读取，不是逐字读原文 |

输出里凡是像密钥的长字符串都遮住了。没有打开任何工具的密钥文件、配置文件和会话记录。

## 结果

### 版本

| 工具 | 版本 | 装在哪 |
|---|---|---|
| Claude Code | 2.1.325 | `~/.local/bin/claude` |
| Codex | 0.169.0 | `~/.local/bin/codex`，指向 `~/.codex/packages/standalone/` |
| OpenCode | 2.3.0 | `~/.opencode/bin/opencode` |
| Pi | 1.5.2 | `~/.local/bin/pi`，指向 `~/.pi/agent/bin/pi` |

### 登录状态

用户说三个工具都已登录。工具自己的查询结果如下，**和「已登录」对不上，但也不能据此断定用不了**：

| 工具 | 查询结果 | 说明 |
|---|---|---|
| Codex | `codex login status` 报告「未登录」，退出码 1 | `codex doctor` 显示它接的不是官方账号，而是配置文件里的一个自定义服务（名称 `custom`，地址 `nailongapi.top`，模型 `gpt-6-astra`），这种接法不需要官方登录。`codex doctor` 探测到这个地址连得上 |
| OpenCode | `opencode auth list` 报告「没有已登录的账号」，两种运行方式结果相同 | 它有可能靠配置文件接服务，这个查询未必列得出来 |
| Pi | 模型清单里有 18 个 Anthropic 的模型，另有一家名称为 `2` 的服务，只有一个模型 `gpt-6-astra`。`pi auth check` 对 Anthropic 报告「已就绪」，对 `gpt-6-astra` 报告 `invalid` | Anthropic 的「已就绪」是假象，见下一节。`invalid` 是指密钥无效还是指查询的写法不对，没有弄清 |

**三个工具到底能不能应答，只有真的各发一句话才知道。** 写这份记录时这一步没做。后来用户确认三个工具接的都是自定义服务、都能应答；同一天试验 S2 的第三部分实测确认：三个工具在受限环境里都能应答，见 `S2-隔离机制.md`。

### 一个会让结果失真的地方

本次 Claude Code 会话的环境变量里有 `ANTHROPIC_AUTH_TOKEN`。它不在任何启动文件里，是会话自己带进来的，从这个会话里启动的程序都读得到。

Pi 把这个变量当成自己的 Anthropic 密钥。去掉这个变量再查，Pi 对 Anthropic 报告「未就绪」。

所以：

- 在 Claude Code 会话里试另外三个工具时，启动前必须去掉这个变量。否则试出来的是「借用本会话的密钥」，不是工具自己的登录，结果不算数。
- 这对设计也有意义：密钥不只在文件里，还会顺着环境变量传给子进程。受限侧启动时要清理环境变量，并入试验 S2。

### 各工具的命令和能力

见设计书 10.2 的表，不在这里重复。

## 结论

1. 三个工具都已安装，版本如上。设计书未决事项 W5 的「安装」部分完成。
2. 工具自带的「是否已登录」查询在这台电脑上不能当依据。适配器的自检要判断「已登录」，只能真的发一次最短的调用。
3. 试另外三个工具前要去掉环境变量里的 Anthropic 密钥。
4. 两个技能目录（`.claude/skills` 和 `.agents/skills`）在纸面上够四个工具用；OpenCode 两处都认，可能重复，由 S5 实测。
5. Codex 不认技能文件里「只允许人触发」的标记，认的是技能目录里的 `agents/openai.yaml`。后来做 S0 时核对了技能仓库原文：每个技能目录里已经自带这个文件，所以复制技能时要整个目录一起复制，不需要另打补丁。
6. 后三个工具的帮助里都没有费用限定参数。
7. 三个工具的技能调用写法各不相同（`$技能名`、`@技能编号`、`/skill:技能名`），官方文档都没说自动调用下能否触发，由 S1 的后续部分实测。

## 没做的

- （已由 S2 第三部分补做）三个工具各发一句话，确认能应答。
- （已由 S5 和 S1 的后续部分补做）三个工具在自动调用下触发技能。
- （已由 S5 补做）三个工具识别复制过去的技能。
- 三个工具的会话续接：按用户的决定没做，见设计书 W24。
- Codex 子代理的官方说明：页面没取到。
- Pi 有没有子代理：没有核实。
- 官方文档没有逐字读原文。

## 核对留下的文件

`/tmp/sop-help/`（各条帮助说明的完整输出）。在临时目录，重启后会消失，结论以本文件和设计书 10.2 为准。
