# 不带参数的命令后面多了一个词（sop status 不带参数）
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 看进度：`sop status now`' >> "$CASE/r/doc.md"
