# sop.json 没写公开还是私有
python3 "$TOOLKIT/checks/project_layout/make_sample.py" "$CASE/p"
echo "{\"dir\": \"$CASE/p\", \"toolkit\": \"$TOOLKIT\"}" > args.json
python3 -c 'import json,sys; f=sys.argv[1]; d=json.load(open(f)); d.pop("visibility"); json.dump(d, open(f, "w"))' "$CASE/p/sop.json"
