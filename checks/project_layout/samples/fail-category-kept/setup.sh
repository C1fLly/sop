# 复制时没有去掉分类那一层（.claude/skills/engineering/tdd/）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
S=$CASE/p/.claude/skills; rm -rf "$S"; mkdir -p "$S"; cp -a "$TOOLKIT/skills/mattpocock/skills/engineering" "$S/engineering"
