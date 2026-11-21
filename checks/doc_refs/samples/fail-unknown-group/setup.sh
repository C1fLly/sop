# 以省略号结尾的统称，但没有以这几个词开头的命令
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 部署：`sop deploy …`' >> "$CASE/r/doc.md"
