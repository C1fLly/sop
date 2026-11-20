# 少了一个文件：Codex 认的「只允许人触发」标记
cp -a "$TOOLKIT/skills" "$CASE/skills"; S=$CASE/skills/mattpocock/skills
echo "{\"dir\": \"$CASE/skills\"}" > args.json
rm "$S/productivity/grill-me/agents/openai.yaml"
