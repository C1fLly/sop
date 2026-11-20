# 故意改一个字：tdd 技能正文里第一个「a」换成「e」
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
sed -i "0,/a/s//e/" "$S/engineering/tdd/SKILL.md"
