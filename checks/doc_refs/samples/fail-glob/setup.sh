# * 当通配也一个都对不上
bash "$TOOLKIT/checks/doc_refs/make_sample.sh" "$CASE/r"
echo "{\"repo\": \"$CASE/r\", \"docs\": [\"doc.md\"]}" > args.json
echo '- 见 `docs/试验/第二段-*.md`' >> "$CASE/r/doc.md"
