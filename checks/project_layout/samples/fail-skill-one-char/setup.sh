# 项目里一个技能文件改了一个字母
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
sed -i '0,/test/s//tast/' "$CASE/p/.agents/skills/tdd/SKILL.md"
