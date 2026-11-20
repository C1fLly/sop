# 声明了档案，门禁命令跑了但没通过
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
mkdir -p "$CASE/profiles/stack/demo"
printf 'gate-fast = ["false"]\ngate-full = ["true"]\n' > "$CASE/profiles/stack/demo/commands.toml"
python3 - "$CASE/p/sop.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])); s['profiles']['stack'] = ['demo']; json.dump(s, open(sys.argv[1], 'w'))
PY
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\", \"tier\": \"fast\", \"profiles\": \"$CASE/profiles\"}" > args.json
