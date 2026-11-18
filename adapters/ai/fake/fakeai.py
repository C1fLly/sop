#!/usr/bin/env python3
"""假 AI 本身：在受限环境里运行，照剧本动作做事。只用标准库。

动作（JSON 对象，字段都可选）：
  files      {路径: 内容}         写文件（相对当前目录；内容以 "@hex:" 开头的按十六进制写成二进制）
  append     {路径: 内容}         追加
  delete     [路径]
  sh         [命令]               依次执行（当前目录），出错就停（模拟 AI 跑命令）
  merge      分支名               把这个分支合进来；有冲突时按 merge_take 取哪一边（ours/theirs）；视觉基准一律取对方（7.5 的 T14）
  pre_files  {路径: 内容}         睡之前先写的文件（给「中途被打断」留下没提交的改动）
  commit     提交说明              git add -A 再提交（只有能提交的放法才成功，6.3）
  result     对象 / null          结果文件里的字段（和默认的合并）；null 表示不交回结果文件
  log        [行]                 往会话日志里追加的行（例如造额度报错）
  cost       数字                 报告的花费
  sleep      秒数                 先睡一会儿（给「中途被打断」用）
  exit       退出码
"""
import json
import os
import subprocess
import sys
import time
import uuid


def main():
    task = json.load(open(sys.argv[1], encoding='utf-8'))
    tid = task['scope'].rsplit('/', 1)[-1]
    raw = open(sys.argv[2], encoding='utf-8').read().replace('{ticket}', tid)   # 剧本里可以用 {ticket} 代入工单编号
    a = json.loads(raw)
    home = os.path.join(os.environ['HOME'], '.fakeai')
    os.makedirs(home, exist_ok=True)
    session = a.get('resumed') or uuid.uuid4().hex[:12]
    log = open(os.path.join(home, f'{session}.jsonl'), 'a', encoding='utf-8')
    log.write(json.dumps({'type': 'start', 'step': task['step'], 'scope': task['scope']}, ensure_ascii=False) + '\n')
    for p, c in (a.get('pre_files') or {}).items():
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        open(p, 'w', encoding='utf-8').write(c)
    if a.get('sleep'):
        log.flush(); time.sleep(float(a['sleep']))
    for p, c in (a.get('files') or {}).items():
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        if isinstance(c, str) and c.startswith('@hex:'):
            open(p, 'wb').write(bytes.fromhex(c[5:]))
        else:
            open(p, 'w', encoding='utf-8').write(c)
    for p, c in (a.get('append') or {}).items():
        open(p, 'a', encoding='utf-8').write(c)
    for p in a.get('delete') or []:
        if os.path.exists(p):
            os.unlink(p)
    for cmd in a.get('sh') or []:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        log.write(json.dumps({'type': 'tool', 'cmd': cmd, 'rc': r.returncode, 'out': (r.stdout + r.stderr)[-500:]}, ensure_ascii=False) + '\n')
        if r.returncode:
            break
    commits = []
    if a.get('merge'):
        r = subprocess.run(['git', 'merge', '--no-edit', a['merge']], capture_output=True, text=True)
        if r.returncode:   # 有冲突：按剧本取一边；图片取对方（功能分支）那一份
            files = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=U'], capture_output=True, text=True).stdout.split()
            for f in files:
                side = '--theirs' if f.startswith('docs/baseline/') else ('--ours' if a.get('merge_take', 'theirs') == 'ours' else '--theirs')
                subprocess.run(['git', 'checkout', side, '--', f])
            subprocess.run(['git', 'add', '-A'])
            subprocess.run(['git', 'commit', '--no-edit', '-q'], capture_output=True)
        commits.append(subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip())
    if a.get('commit'):
        subprocess.run(['git', 'add', '-A'], capture_output=True)
        r = subprocess.run(['git', 'commit', '-q', '-m', a['commit']], capture_output=True, text=True)
        if r.returncode == 0:
            commits.append(subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip())
        else:
            log.write(json.dumps({'type': 'tool', 'cmd': 'git commit', 'rc': r.returncode, 'out': r.stderr[-300:]}, ensure_ascii=False) + '\n')
    for line in a.get('log') or []:
        log.write((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)) + '\n')
    if a.get('result', {}) is not None:
        res = {'status': 'done', 'commits': commits, 'commands': [], 'deviations': [], 'questions': [], 'findings': [],
               'pr_body': f'{task["step"]} 的改动（假 AI）'}
        res.update(a.get('result') or {})
        os.makedirs(os.path.dirname(task['result_path']), exist_ok=True)
        json.dump(res, open(task['result_path'], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cost = float(a.get('cost', 0.1))
    log.write(json.dumps({'type': 'result', 'total_cost_usd': cost}) + '\n')
    log.close()
    print('FAKEAI ' + json.dumps({'cost': cost, 'session': session, 'text': a.get('text', '做完了（假 AI）')}, ensure_ascii=False))
    return int(a.get('exit', 0))


if __name__ == '__main__':
    sys.exit(main())
