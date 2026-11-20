# 项目里一个技能文件只加了执行权限
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
chmod +x "$CASE/p/.claude/skills/grilling/SKILL.md"
