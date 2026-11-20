# 往项目的技能目录里多放一个文件（比如把约定写进了技能目录）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
echo '工具包的约定' > "$CASE/p/.claude/skills/implement/notes.md"
