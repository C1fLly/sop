# 许可文件没带过去
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
rm "$CASE/p/.claude/LICENSE-mattpocock-skills"
