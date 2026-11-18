# 项目规则

## 这是什么

一个记账的命令行小工具。使用者没有编程基础，只验收行为，不看代码。

## 预置的技术决定（不要就这些再问用户）

- 形态：命令行工具。语言：Python 3，只用标准库，不引入第三方依赖，不联网。
- 数据：存本机的 JSON 文件。
- 测试：标准库 unittest，放在 `tests/` 下，用 `python3 -m unittest discover -s tests` 运行。
- 测试切入点已经定好，不用再和用户确认：每个模块的公开函数；命令行通过 `main(argv)` 函数测试。
- 界面文字、文档、提交说明、向用户的汇报都用中文大白话。

## 这个环境的规矩

- 这里没有远程仓库的访问权：不要 `git push`、不要 `git fetch`、不要开 PR、不要用 `gh`。推送由外面的流程命令做。
- 不要自己建工作目录或分支。要一个工单的工作目录时执行 `sopreq new-worktree <工单编号>`，它会打印出建好的目录。
- 每合并完一张工单，执行 `sopreq merged <工单编号>`，等它回答 ok。
- 不要改这些受保护的内容：`CLAUDE.md`、`.claude/`、`docs/agents/`。

## Agent skills

### Issue tracker

工单和规格是 `.scratch/` 下的本地 markdown 文件。See `docs/agents/issue-tracker.md`.

### Domain docs

single-context。See `docs/agents/domain.md`.
