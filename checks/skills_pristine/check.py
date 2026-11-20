#!/usr/bin/env python3
"""检查「技能副本和固定的那个上游提交逐字一致」（设计书 3.2、7.11、10.2 第 4 条；W12）。在哪运行：工具包自己的自测（本机，以后也在工具包仓库的 GitHub 检查里跑）。
参数：dir（工具包的 skills/ 目录）。
副本放在 <dir>/mattpocock/ 下，路径和上游仓库里一样（LICENSE、skills/<分类>/<技能>/...）；版本记录是 <dir>/source.json。
逐个文件按 Git 的算法算指纹（内容一个字节、换行、执行权限都算在内），和版本记录比：改了的、多了的、少了的、权限变了的都报。
另外把整个 skills/ 按 Git 的算法算出目录指纹，和记录里的比；这个指纹和上游 `git rev-parse <提交>:skills` 是同一个数，任何人都能拿上游仓库核对。"""
import hashlib
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from checks import lib  # noqa: E402

COPY = 'mattpocock'


def blob_id(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def tree_id(files, prefix):
    """files：{相对路径: (权限, 指纹)}；算 prefix 这一层目录的 Git 树编号（只有普通文件，权限 100644 / 100755）。"""
    root = {}
    for path, (mode, oid) in files.items():
        if not path.startswith(prefix + '/'):
            continue
        node, parts = root, path[len(prefix) + 1:].split('/')
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = (mode, oid)

    def build(node):
        ents = []
        for name, v in node.items():
            if isinstance(v, dict):
                ents.append((name.encode() + b'/', b'40000', name.encode(), bytes.fromhex(build(v))))
            else:
                ents.append((name.encode(), v[0].encode(), name.encode(), bytes.fromhex(v[1])))
        body = b''.join(m + b' ' + n + b'\0' + h for _, m, n, h in sorted(ents))
        return hashlib.sha1(b'tree %d\0' % len(body) + body).hexdigest()
    return build(root)


def scan(top):
    """副本里实际有什么：{相对路径: (权限, 指纹)}，另外列出不是普通文件的东西和空目录。"""
    files, odd = {}, []
    for d, dirs, names in os.walk(top):
        rel_d = os.path.relpath(d, top)
        for n in list(dirs):
            if os.path.islink(os.path.join(d, n)):
                dirs.remove(n); names.append(n)
        if not dirs and not names and rel_d != '.':
            odd.append(rel_d + '/（空目录）')
        for n in names:
            p = os.path.join(d, n)
            rel = os.path.normpath(os.path.join(rel_d, n))
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                odd.append(rel + '（不是普通文件）'); continue
            with open(p, 'rb') as f:
                files[rel] = ('100755' if st.st_mode & 0o100 else '100644', blob_id(f.read()))
    return files, odd


def run(dir):
    rec_path = os.path.join(dir, 'source.json')
    try:
        rec = json.load(open(rec_path, encoding='utf-8'))
    except FileNotFoundError:
        return False, '技能副本没有版本记录 source.json', {'path': rec_path}
    want = {k: tuple(v) for k, v in rec['files'].items()}
    top = os.path.join(dir, COPY)
    if not os.path.isdir(top):
        return False, f'没有技能副本目录 {COPY}/', {'path': top}
    have, odd = scan(top)
    changed = sorted(k for k in want if k in have and have[k][1] != want[k][1])
    mode = sorted(k for k in want if k in have and have[k][1] == want[k][1] and have[k][0] != want[k][0])
    missing = sorted(k for k in want if k not in have)
    extra = sorted([k for k in have if k not in want] + odd)
    trees = {p: tree_id(have, p) for p in rec['trees']}
    rec_trees_ok = all(tree_id(want, p) == t for p, t in rec['trees'].items())
    report = {'commit': rec['commit'], 'changed': changed, 'mode_changed': mode, 'missing': missing, 'extra': extra,
              'trees_recorded': rec['trees'], 'trees_actual': trees, 'record_consistent': rec_trees_ok}
    short = rec['commit'][:7]
    if changed or mode or missing or extra:
        parts = [f'{t} {len(x)} 个（{"、".join(x[:3])}{"等" if len(x) > 3 else ""}）'
                 for t, x in (('内容改了', changed), ('权限变了', mode), ('少了', missing), ('多了', extra)) if x]
        return False, f'技能副本和上游提交 {short} 不一致：' + '；'.join(parts), report
    if not rec_trees_ok or trees != rec['trees']:
        return False, f'技能副本的版本记录前后对不上（逐个文件的指纹和目录指纹不符），不能证明和提交 {short} 一致', report
    return True, f'技能副本和上游提交 {short} 逐字一致（{len(have)} 个文件）', report


if __name__ == '__main__':
    sys.exit(lib.cli(run))
