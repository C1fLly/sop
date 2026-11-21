# 本机有个空目录 guide/（make_sample.sh 建的），但 Git 不记空目录，GitHub 上取出来就没有：不算有
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 手册在 `guide/`' >> "$CASE/r/doc.md"
