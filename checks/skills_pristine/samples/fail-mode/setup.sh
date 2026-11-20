# 内容不动，只给一个技能文件加上执行权限
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
chmod +x "$S/productivity/grill-me/SKILL.md"
