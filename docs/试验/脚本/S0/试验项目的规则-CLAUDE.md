# 项目规则

## 这是什么

给一家小公司用的内部小工具。使用者没有编程基础，只验收行为，不看代码。

## 预置的技术决定（不要就这些再问用户）

- 形态：命令行工具。
- 语言：Python 3，只用标准库，不引入第三方依赖，不联网。
- 数据：存本机的 JSON 文件。
- 测试：标准库 unittest，放在 `tests/` 下，用 `python3 -m unittest discover -s tests` 运行。
- 界面文字、文档、提交说明都用中文。

## 向用户提问的规矩

- 每个问题的标题前标上【业务】或【技术】。【业务】指用户凭自己的业务常识就能回答的；【技术】指需要编程知识才能回答的。
- 用大白话提问，不用术语；必须用术语时顺手解释。
- 用户对【技术】题回答「按你的推荐」时，按推荐执行，并在 `docs/adr/` 记一条决策记录。

## Agent skills

### Issue tracker

工单和规格是 `.scratch/` 下的本地 markdown 文件。See `docs/agents/issue-tracker.md`.

### Domain docs

single-context。See `docs/agents/domain.md`.
