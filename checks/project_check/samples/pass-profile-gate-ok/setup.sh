# 声明了档案 stack/demo，它的全档门禁命令跑通了
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
mkdir -p "$CASE/profiles/stack/demo"
printf 'gate-fast = ["false"]\ngate-full = ["python3", "{profile}/gate.py"]\n' > "$CASE/profiles/stack/demo/commands.toml"
printf 'import os, sys\nsys.exit(0 if os.path.isfile("sop.json") else 1)\n' > "$CASE/profiles/stack/demo/gate.py"
python3 - "$CASE/p/sop.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])); s['profiles']['stack'] = ['demo']; json.dump(s, open(sys.argv[1], 'w'))
PY
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\", \"tier\": \"full\", \"profiles\": \"$CASE/profiles\"}" > args.json
