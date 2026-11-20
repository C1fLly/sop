# 本机的项目根少了 .shared/（不是 wt 按工具包模板建的）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" --root "$CASE/demo"
rm -rf "$CASE/demo/.shared"
echo "{\"dir\": \"$CASE/demo/main\", \"toolkit\": \"$TOOLKIT\", \"root\": \"$CASE/demo\"}" > args.json
