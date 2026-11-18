# 给 AI 的规则（由 SOP 工具包生成，不要改）

- 向用户汇报、写文档、写提交说明，一律用中文大白话。
- 给用户的每个问题标上【业务】或【技术】。
- 不要自己建分支、建工作目录、推送、开 PR、合并（除非任务包明确要求合并）。
- 不要改受保护的文件：sop.json、.github/workflows/、任何层级的 AGENTS*.md、CLAUDE*.md、.claude/、.agents/、.codex/、.opencode/、.pi/、
  docs/agents/、docs/standards/、docs/baseline/，以及档案声明的规范配置文件。
- 不要修改已有的测试来让测试通过。
- 拿不准的时候不要猜：把问题写进结果文件，标明是业务问题还是技术问题。
