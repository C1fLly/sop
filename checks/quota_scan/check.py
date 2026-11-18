#!/usr/bin/env python3
"""检查「会话日志里的额度类报错」（设计书 7.12、W29）。在哪运行：本机，每个 AI 步骤结束后。
AI 服务报额度不足时，断掉的可能只是 AI 派出去的帮手，主会话自己重试后照常结束（S7 重做时报了 8 次「403 insufficient balance」）。
从外面看不出来，所以扫一遍这一步的会话日志。参数：paths（会话日志的文件或目录）。
通过：没找到。不通过：找到了，报告里列出每一处（文件、行号、摘录）。"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

PATTERNS = [
    re.compile(r'insufficient[ _]balance', re.I),
    re.compile(r'insufficient[ _]quota', re.I),
    re.compile(r'exceeded your current quota', re.I),
    re.compile(r'quota (?:exceeded|exhausted)', re.I),
    re.compile(r'credit balance is too low', re.I),
    re.compile(r'rate[ _]limit(?:ed| exceeded|_error)', re.I),
    re.compile(r'\b(?:402|429)\b[^\n]{0,40}(?:payment|too many requests|rate)', re.I),
    re.compile(r'余额不足|额度(?:不足|用完|已用尽)'),
]


def run(paths):
    hits, nfiles = [], 0
    for root in paths:
        files = [root] if os.path.isfile(root) else [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
        for fp in sorted(files):
            nfiles += 1
            try:
                with open(fp, encoding='utf-8', errors='replace') as fh:
                    for i, line in enumerate(fh, 1):
                        for pat in PATTERNS:
                            m = pat.search(line)
                            if m:
                                s = max(0, m.start() - 60)
                                hits.append({'file': fp, 'line': i, 'text': line[s:m.end() + 60].strip()})
                                break
            except OSError:
                continue
    if hits:
        return False, f'会话日志里有 {len(hits)} 处额度类的报错（AI 服务的余额或额度可能不够了）', {'hits': hits, 'files': nfiles}
    return True, f'会话日志里没有额度类的报错（看了 {nfiles} 个文件）', {'hits': [], 'files': nfiles}


if __name__ == '__main__':
    sys.exit(lib.cli(run))
