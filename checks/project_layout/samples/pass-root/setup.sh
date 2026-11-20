# 本机的项目根：裸仓库、.shared/hooks/、main/ 都在
python3 "$TOOLKIT/checks/project_layout/make_sample.py" --root "$CASE/demo"
echo "{\"dir\": \"$CASE/demo/main\", \"toolkit\": \"$TOOLKIT\", \"root\": \"$CASE/demo\"}" > args.json
