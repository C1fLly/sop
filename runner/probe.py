#!/usr/bin/env python3
"""隔离自检的探针：在受限环境里逐项试，报告做得到还是做不到。只用标准库。
试写一个已有的文件时只「以追加方式打开、什么都不写」，不改它；试写一个目录时建一个临时文件再删掉。"""
import json
import os
import subprocess
import sys
import uuid


def do(a):
    op, p = a['op'], a.get('path')
    try:
        if op == 'exists':
            return os.path.lexists(p)
        if op == 'write_file':
            with open(p, 'ab'):
                pass
            return True
        if op == 'write_dir':
            f = os.path.join(p, f'.sop-probe-{uuid.uuid4().hex[:8]}')
            with open(f, 'w') as fh:
                fh.write('x')
            os.unlink(f)
            return True
        if op == 'mkfile':          # 真的建一个文件（只用在测试自己的目录里）
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as fh:
                fh.write(a.get('text', 'x'))
            return True
        if op == 'env':
            return sorted(os.environ)
        if op == 'run':
            r = subprocess.run(a['argv'], cwd=a.get('cwd'), capture_output=True, text=True, timeout=60)
            return {'rc': r.returncode, 'out': (r.stdout + r.stderr)[-300:]}
    except OSError as e:
        return False if op != 'run' else {'rc': -1, 'out': str(e)}
    return None


if __name__ == '__main__':
    actions = json.load(open(sys.argv[1]))
    print(json.dumps([do(a) for a in actions], ensure_ascii=False))
