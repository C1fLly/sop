# 多装了一个不用的技能（wizard，第一版不用）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
cp -a "$TOOLKIT/skills/mattpocock/skills/engineering/wizard" "$CASE/p/.claude/skills/wizard"
