# 之后技能、档案照规矩改了的几样（术语表、规范文件、检查流程）和代码、README：结构照样对
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
P=$CASE/p
echo '- 订单：客户下的一笔单' >> "$P/GLOSSARY.md"
rm "$P/docs/standards/README.md"; echo '规则' > "$P/docs/standards/rules.md"
echo '# 档案加的一步' >> "$P/.github/workflows/sop-check.yml"
mkdir -p "$P/services/api" "$P/.scratch/_product"; echo 'print(1)' > "$P/services/api/app.py"; echo '# demo' > "$P/README.md"
