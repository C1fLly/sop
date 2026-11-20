# 没有版本记录：不能证明是哪个提交
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
rm "$CASE/skills/source.json"
