# 少装了一个被依赖的技能（retro 要调用的 writing-for-agents）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
rm -rf "$CASE/p/.agents/skills/writing-for-agents"
