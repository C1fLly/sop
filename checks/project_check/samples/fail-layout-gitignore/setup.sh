# I7 里「故意出错」的那个 PR：.gitignore 里去掉了 .env，目录结构检查报错（还没有档案，门禁那一项是「不适用」）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
grep -vx '.env' "$CASE/p/.gitignore" > "$CASE/g" && mv "$CASE/g" "$CASE/p/.gitignore"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\", \"tier\": \"fast\"}" > args.json
