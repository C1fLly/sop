# 声明的档案在工具包这个版本里没有：算失败（不能因为找不到档案就当成「不适用」）
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
mkdir -p "$CASE/profiles/stack"
python3 - "$CASE/p/sop.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1])); s['profiles']['stack'] = ['nosuch']; json.dump(s, open(sys.argv[1], 'w'))
PY
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\", \"tier\": \"fast\", \"profiles\": \"$CASE/profiles\"}" > args.json
