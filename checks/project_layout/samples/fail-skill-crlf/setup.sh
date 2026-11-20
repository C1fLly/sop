# 项目里一个技能文件只把第一行的换行改成 Windows 换行
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
sed -i '1s/$/\r/' "$CASE/p/.claude/skills/grilling/SKILL.md"
