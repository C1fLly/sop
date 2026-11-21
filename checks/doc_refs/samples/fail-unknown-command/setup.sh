# 命令表里没有的命令
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 体检：`sop doctor`' >> "$CASE/r/doc.md"
