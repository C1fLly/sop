# 真的设计书（另存一份，文档可以写绝对路径）对着真的工具包仓库和命令表，只多一行没有的命令：
# 和 pass-toolkit 只差这一行，报错只能是因为它
cp "$TOOLKIT/docs/设计书.md" "$CASE/设计书.md"
echo '另见 `sop self upgrade-all`。' >> "$CASE/设计书.md"
echo "{\"repo\": \"$TOOLKIT\", \"docs\": [\"$CASE/设计书.md\"]}" > args.json
