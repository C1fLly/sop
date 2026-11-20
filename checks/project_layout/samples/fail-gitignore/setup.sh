# .gitignore 里没有 .env（每个工作目录里链接进来的 .env 会被提交）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
echo 'node_modules/' > "$CASE/p/.gitignore"
