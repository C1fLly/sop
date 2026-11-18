# 流程定义

每个流程一个 TOML 文件，只读，工具包自带（设计书 3.3、8.1）。字段：

| 字段 | 含义 |
|---|---|
| `id`、`name` | 编号和名称 |
| `actor` | 执行者：`script`（特权侧脚本）、`restricted_script`（受限脚本）、`ai_headless`（AI 自动）、`ai_interactive`（AI 交互）、`human`（人） |
| `kind` | AI 和受限脚本的受限环境放法（6.3 的表）：`ticket_impl`、`planning`、`std_draft`、`readonly`、`restricted_script`、`implement_spec` |
| `action` | 特权侧做这一步的处理函数，或 AI 步骤的任务包模板 |
| `skill` | AI 步骤要调用的技能 |
| `session` | `new`（全新会话，状态目录从模板现建）或续接组的名字（同一组续接同一个会话） |
| `condition` | 执行条件；不满足时记「步骤跳过」 |
| `confirm` | 人的确认步骤：确认过、没被重新打开时，回放直接越过它 |
| `changes_confirmed` | 会改动已确认的内容，因此能发「重新打开」（8.3） |
| `on_fail` | 不通过时去哪 |
| `max_attempts`、`on_exhausted` | 这一步最多做几次，做满了再被派到时改去哪（T6 最多 3 轮 → T7 → T8） |
| `max_fails`、`on_fails_exhausted` | 这一步最多不通过几次，超过了去哪（T9 复查打回最多 2 轮 → T8） |
| `goto` | 做完以后去哪（不在主线上的步骤，例如 T6 修完回 T4） |
| `side` | 不在主线上，只有被派到才做 |
| `hold` | 做完以后停下，等功能那一级处理（T8 技术决策） |
| `allowed` | 可改范围（相对工作目录，`**` 表示任意层级）；受保护路径另外一律不许 |
| `checks` | 出口检查 |
| `timeout_min`、`budget_usd` | 时长上限（分钟）、费用上限（默认空，8.4） |
