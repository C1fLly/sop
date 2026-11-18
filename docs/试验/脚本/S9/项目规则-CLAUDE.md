# 项目规则

## 这是什么

一个记账系统的样例：后端在 `services/api`（Java），页面在 `apps/web`（Vue）。使用者没有编程基础，只验收行为，不看代码。

## 预置的技术决定（不要就这些再问用户）

- 后端：Java 25，Maven。数据库是 PostgreSQL。在 `services/api` 下用 `mvn -B test` 跑全部测试。
- 后端测试连真的数据库：用 Testcontainers 起 `postgres:18.6`，照 `LedgerTest` 的写法。镜像已经在本机，不要换别的镜像或版本。
- 测试切入点已经定好，不用再和用户确认：`Ledger` 类的公开方法。
- 不引入新的依赖。
- 提交说明、文档、向用户的汇报都用中文大白话。

## 这个环境的规矩

- 这里没有远程仓库的访问权：不要 `git push`、不要 `git fetch`、不要开 PR、不要用 `gh`。推送由外面的流程命令做。
- 不要建别的分支或工作目录，就在当前目录、当前分支上干活。
- git 提交时会打印一行「Unable to create …packed-refs.lock: Read-only file system」，这是正常的，提交其实成功了。
- 不要改这些受保护的内容：`CLAUDE.md`、`.claude/`、`docs/agents/`。

## Agent skills

### Issue tracker

工单和规格是 `.scratch/` 下的本地 markdown 文件。See `docs/agents/issue-tracker.md`.

### Domain docs

single-context。See `docs/agents/domain.md`.
