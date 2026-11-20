# 声明了档案 stack/demo，但它的命令表里没有快档门禁命令：算失败（问题 6）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
mkdir -p "$CASE/profiles/stack/demo"
printf 'setup = ["true"]\ngate-full = ["true"]\n' > "$CASE/profiles/stack/demo/commands.toml"
python3 - "$CASE/p/sop.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])); s['profiles']['stack'] = ['demo']; json.dump(s, open(sys.argv[1], 'w'))
PY
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\", \"tier\": \"fast\", \"profiles\": \"$CASE/profiles\"}" > args.json
