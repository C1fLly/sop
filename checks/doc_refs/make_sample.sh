# 给总检查的样例造一个小的「工具包仓库」：$1 是位置。命令表用工具包真的那份 kernel/commands.py，
# 文档 doc.md 里把每种该通过的写法都写一遍（应报错的样例在这之后再往 doc.md 里加一行错的）。
set -euo pipefail
R=$1
mkdir -p "$R/kernel" "$R/adapters/ai/claude" "$R/docs/试验/脚本" "$R/templates/project/docs/standards" "$R/guide" "$R/.github/workflows"
cp "$TOOLKIT/kernel/commands.py" "$R/kernel/commands.py"
echo '# 入口' > "$R/kernel/cli.py"
echo '# 适配器' > "$R/adapters/ai/claude/adapter.py"
echo '# 一份记录' > "$R/docs/试验/第一段-小结.md"
echo 'name: x' > "$R/.github/workflows/check.yml"
echo '# 规范' > "$R/templates/project/docs/standards/README.md"
cat > "$R/doc.md" <<'EOF'
# 应通过的写法

- 命令：`sop`、`sop status`、`sop machine doctor --readonly`、`sop feature new <功能名>`、`sop feature new login`、
  `sop project clone <所有者/项目名>`、`sop machine …`、`sop feature …`（一组命令的统称）、`sop self bootstrap`（内部用的）。
- 还没做的（命令表 PLANNED 里写着排在哪）：`sop self rollback`、`sop backup restore <备份文件>`、`sop check [步骤]`。
- 仓库里的路径：`kernel/cli.py`、`kernel/cli.py:12`、`kernel/`、`adapters/ai/<工具名>/`、`docs/试验/第一段-*.md`、
  `.github/workflows/check.yml`、`~/tools/sop/dev/kernel/cli.py`。
- 不是工具包仓库里的，不查：`~/tools/sop/state/<项目名>/`、`~/tools/wt`、`/var/lib/docker`、`.git/config`、
  `feat/<功能>`、`https://example.invalid/a/b`、`notes/`。
- 项目仓库里的（和工具包的 docs/ 同名）：`docs/standards/`（模板里有）、`docs/product/risk.json`（第 2a 期起才有）。
- 行内的普通字：sop nothing，kernel/nothing.py（不在反引号里，不算引用）。

```
`sop nothing-in-code-block`
`kernel/nothing-in-code-block.py`
```
EOF
