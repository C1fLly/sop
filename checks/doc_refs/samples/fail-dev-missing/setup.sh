# 开发仓库里写的位置没有
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 见 `~/tools/sop/dev/kernel/nothere.py`' >> "$CASE/r/doc.md"
