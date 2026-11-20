# 只把第一行的换行改成 Windows 换行，看起来一字没改
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
sed -i '1s/$/\r/' "$S/productivity/grilling/SKILL.md"
