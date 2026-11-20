# 许可文件放进了技能目录里（技能目录一个字不许改）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
mv "$CASE/p/.agents/LICENSE-mattpocock-skills" "$CASE/p/.agents/skills/tdd/LICENSE"
