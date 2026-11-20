# 往技能目录里多放一个文件（比如工具包想加的约定写进了技能目录）
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
echo "工具包的约定" > "$S/engineering/tdd/notes.md"
