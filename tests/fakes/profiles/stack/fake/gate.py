#!/usr/bin/env python3
"""档案 fake 的门禁（在受限环境里跑）。剧本：$SOP_FAKE_GATE（JSON）{"<范围>:<步骤>:<第几次>" 或 "<范围>:<步骤>": {"pass": false, "tests": 0}}。
报告写到 /sop/out/report.json；截图：把 ui/screens/*.png 复制到 /sop/out/screens/，和 docs/baseline/ 比，不同的列为界面变化。"""
import hashlib
import json
import os
import shutil
import sys

level = sys.argv[1]
task = json.load(open('/sop/task/task.json'))
script = json.load(open(os.environ['SOP_FAKE_GATE'])) if os.environ.get('SOP_FAKE_GATE') and os.path.exists(os.environ['SOP_FAKE_GATE']) else {}
rule = script.get(f'{task["scope"]}:{task["step"]}:{task["attempt"]}') or script.get(f'{task["scope"]}:{task["step"]}') or {}
ui = []
os.makedirs('/sop/out/screens', exist_ok=True)
for f in sorted(os.listdir('ui/screens')) if os.path.isdir('ui/screens') else []:
    shutil.copy(os.path.join('ui/screens', f), os.path.join('/sop/out/screens', f))
    base = os.path.join('docs/baseline', f)
    h = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest()   # noqa: E731
    if not os.path.exists(base) or h(base) != h(os.path.join('ui/screens', f)):
        ui.append(f'docs/baseline/{f}')
# 这个目录在这台电脑上装过几次依赖（setup.py 每装一次记一行；3-58 的沙箱拿它核对「装过、没重复装」）
deps = sum(1 for _ in open('.fake-deps/installed.log')) if os.path.exists('.fake-deps/installed.log') else 0
rep = {'level': level, 'pass': rule.get('pass', True), 'tests': rule.get('tests', 3), 'ui_changes': ui, 'deps_installs': deps,
       'why': rule.get('why', '' if rule.get('pass', True) else '测试不通过（剧本）')}
json.dump(rep, open('/sop/out/report.json', 'w'), ensure_ascii=False)
print(json.dumps(rep, ensure_ascii=False))
sys.exit(0 if rep['pass'] else 1)
