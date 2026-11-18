#!/usr/bin/env python3
"""核对设计书里的引用没有悬空：章节号（7.4、第 6 节）、步骤编号（T9、F12…）、未决事项（W10）、原则（Y12）、试验（S4）。
用法: python3 check_refs.py <设计书.md>   有悬空的引用时退出码为 1。"""
import re, sys
s = open(sys.argv[1], encoding='utf-8').read(); lines = s.split('\n')
secs = set(); top = set()
for l in lines:
    m = re.match(r'^(#{2,3}) (\d+(?:\.\d+)?) ', l)
    if m:
        secs.add(m.group(2)); top.add(m.group(2).split('.')[0])
ids = set()
for l in lines:
    m = re.match(r'^\| ([A-Z]\d{1,2}) \|', l)
    if m: ids.add(m.group(1))
    m = re.match(r'^### 第 (\d[abc]?) 期', l)
bad = []
body = re.sub(r'`[^`]*`', '', s)            # 行内代码里的数字不算引用
body = re.sub(r'```.*?```', '', body, flags=re.S)
for m in re.finditer(r'第 (\d+) 节', body):
    if m.group(1) not in top: bad.append(m.group(0))
# 形如 7.4 的章节引用：前面不是数字、字母、小数点、美元符号，后面不是数字或「美元/分钟/秒/倍」之类
for m in re.finditer(r'(?<![\d.A-Za-z$])(\d{1,2}\.\d{1,2})(?![\d.]|\s*(?:美元|分钟|秒|倍|小时|GB|MB|核|天|%|到 \d))', body):
    v = m.group(1); a = int(v.split('.')[0])
    ctx = body[max(0, m.start()-12):m.end()+6].replace('\n', ' ')
    if 1 <= a <= 20 and v not in secs:
        if re.search(r'(Ubuntu|版本|\d\.\d\.\d|LTS|v0|V5|0\.\d|wt )', ctx) or re.search(r'[\d]\.\d+\.\d', ctx): continue
        bad.append(f'{v}（上下文：…{ctx}…）')
for m in re.finditer(r'(?<![A-Za-z0-9_/.-])([TFPIMREHGWYS])(\d{1,2})(?![\dA-Za-z_])', body):
    k = m.group(1) + m.group(2)
    if k not in ids: bad.append(k + '（上下文：…' + body[max(0, m.start()-10):m.end()+10].replace('\n', ' ') + '…）')
print(f'章节 {len(secs)} 个，编号 {len(ids)} 个；悬空的引用 {len(bad)} 处')
for b in sorted(set(bad)): print('  悬空：', b)
sys.exit(1 if bad else 0)
