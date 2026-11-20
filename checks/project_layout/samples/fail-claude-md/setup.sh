# CLAUDE.md 不是那一行 @AGENTS.md
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
echo '另外的规则' >> "$CASE/p/CLAUDE.md"
