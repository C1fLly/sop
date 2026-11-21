#!/usr/bin/env python3
"""3-33：在模拟终端里跑一条要人回答的命令（sop machine migrate），像小白一样看着屏幕回答；只用标准库，虚拟机里用。

用法：python3 migrate-drive.py <规则文件.json> <记录文件> -- <命令...>

规则文件：
  {"answers": [{"q": "正则", "a": "回答"}, ...],      屏幕上出了一个问题（停在「输入数字…：」或「…」）：」）时，
                                                     拿这个问题的文字（上一次回答之后出来的全部）逐条比，第一条比得上且没用过的就答它；
                                                     都比不上就直接回车（按默认），记一行「（驱动：按默认）」
   "events":  [{"on": "正则", "do": "kill" | "pause", "run": "shell 命令"}, ...],
                                                     屏幕上出了这样一行就：kill = 强制结束整个命令（kill -9 整组）；
                                                     pause = 先暂停整组（SIGSTOP），跑 run，再接着跑（SIGCONT）
   "timeout": 秒数}
退出码：命令自己的退出码；被 kill 的是 137；超时 124（也强制结束）。
"""
import codecs
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import time

PROMPTS = ('输入数字，直接回车就是默认：', '」）：')


def main():
    rules_file, log_file, sep, *cmd = sys.argv[1:]
    assert sep == '--' and cmd, __doc__
    rules = json.load(open(rules_file, encoding='utf-8'))
    answers = [dict(r, used=False) for r in rules.get('answers', [])]
    events = [dict(e, done=False) for e in rules.get('events', [])]
    deadline = time.time() + rules.get('timeout', 1800)
    master, slave = pty.openpty()
    p = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True)
    os.close(slave)
    log = open(log_file, 'w', encoding='utf-8')
    dec = codecs.getincrementaldecoder('utf-8')('replace')
    text, asked_from, line_from = '', 0, 0

    def note(s):
        log.write(s + '\n'); log.flush()
        sys.stdout.write(s + '\n'); sys.stdout.flush()

    def group(sig):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    rc = None
    while True:
        if time.time() > deadline:
            note('（驱动：超时，强制结束）')
            group(signal.SIGKILL); p.wait(); rc = 124
            break
        r, _, _ = select.select([master], [], [], 0.5)
        if not r:
            if p.poll() is not None:
                break
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:          # 另一头都关了
            break
        if not chunk:
            break
        s = dec.decode(chunk)
        text += s
        log.write(s); log.flush()
        sys.stdout.write(s); sys.stdout.flush()
        # 整行出来的事件
        cut = text.rfind('\n')
        if cut >= line_from:
            lines = text[line_from:cut + 1]
            line_from = cut + 1
            for e in events:
                if not e['done'] and re.search(e['on'], lines):
                    e['done'] = True
                    if e['do'] == 'kill':
                        note(f'\n（驱动：看到「{e["on"]}」，强制结束整个命令：kill -9 整组）')
                        group(signal.SIGKILL); p.wait(); rc = 137
                        break
                    if e['do'] == 'pause':
                        group(signal.SIGSTOP)
                        note(f'\n（驱动：看到「{e["on"]}」，先暂停整个命令，执行：{e["run"]}）')
                        out = subprocess.run(['bash', '-c', e['run']], stdin=subprocess.DEVNULL, capture_output=True, text=True)
                        note(out.stdout + out.stderr + '（驱动：接着跑）')
                        group(signal.SIGCONT)
            if rc is not None:
                break
        # 停在一个问题上
        tail = text.rstrip(' ')
        if tail.endswith(PROMPTS) and len(text) > asked_from:
            q = text[asked_from:]
            a = next((x for x in answers if not x['used'] and re.search(x['q'], q, re.S)), None)
            if a is None:
                note('（驱动：按默认）')
                reply = ''
            else:
                a['used'] = True
                reply = a['a']
            os.write(master, (reply + '\n').encode())
            asked_from = len(text)
    if rc is None:
        rc = p.wait()
        try:
            while True:
                r, _, _ = select.select([master], [], [], 0.2)
                if not r:
                    break
                chunk = os.read(master, 65536)
                if not chunk:
                    break
                s = dec.decode(chunk); log.write(s); sys.stdout.write(s)
        except OSError:
            pass
    unused = [x['q'] for x in answers if not x['used']]
    if unused:
        note(f'（驱动：这些问题没出现：{unused}）')
    note(f'（驱动：退出码 {rc}）')
    sys.exit(rc)


if __name__ == '__main__':
    main()
