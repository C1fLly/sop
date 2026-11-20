# 改了一个字，又把版本记录里那个文件的指纹改成新的：目录指纹对不上，仍要报
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
F=$S/engineering/tdd/SKILL.md; OLD=$(git hash-object "$F")
sed -i "0,/a/s//e/" "$F"; NEW=$(git hash-object "$F")
sed -i "s/$OLD/$NEW/" "$CASE/skills/source.json"
