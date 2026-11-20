# 少了守门检查的流程文件
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
rm "$CASE/p/.github/workflows/sop-guard.yml"
