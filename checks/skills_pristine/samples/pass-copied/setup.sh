# 原样拷一份到别处，不改：仍然一致（拷贝本身不会弄坏）
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
