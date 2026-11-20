# 技能的配置文件被改了
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
echo '多一行' >> "$CASE/p/docs/agents/domain.md"
