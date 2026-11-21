# 以「/」结尾要是目录，kernel/cli.py 是文件
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 见 `kernel/cli.py/`' >> "$CASE/r/doc.md"
