# 仓库里没有的文件
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 见 `kernel/nothere.py`' >> "$CASE/r/doc.md"
