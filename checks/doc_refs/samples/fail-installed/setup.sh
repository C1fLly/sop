# 装好的 ~/tools/sop/ 下没有 docs（设计书原来第 8 行就是这样悬空的）
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 设计书在 `~/tools/sop/docs/设计书.md`' >> "$CASE/r/doc.md"
