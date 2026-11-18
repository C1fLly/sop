"""受保护路径的比对（设计书 6.4）。本机的「受保护路径」检查和 GitHub 上的守门检查用的是这同一份。

一条放行事件放行的是「某个归属名下、某个路径上的某一份内容」。比法：列出这个改动相对目标分支最终多出来的改动里
动到的每一个受保护路径，看它现在的内容指纹（删掉了就是 deleted）是不是本归属下这个路径序号最大的那条放行。
"""
import os

from checks import lib

HERE = os.path.dirname(os.path.abspath(__file__))


def load_list(path):
    if not os.path.exists(path):
        return []
    return [l.strip() for l in open(path, encoding='utf-8') if l.strip() and not l.lstrip().startswith('#')]


def patterns_for(toolkit_dir, sop):
    """工具包基础清单 + sop.json 声明的各档案的清单（都从工具包那个版本里取）。"""
    pats = load_list(os.path.join(toolkit_dir, 'checks', 'protected', 'base.txt'))
    prof = (sop or {}).get('profiles', {})
    for kind in ('stack', 'end'):
        for name in prof.get(kind, []):
            pats += load_list(os.path.join(toolkit_dir, 'profiles', kind, name, 'protected.txt'))
    return pats


def changes(gitdir, base, head):
    """head 相对 base 最终多出来的改动：[(状态, 路径)]。"""
    mb = lib.git(gitdir, 'merge-base', base, head).strip()
    out = lib.nul(lib.git(gitdir, 'diff', '--name-status', '-z', '--no-renames', mb, head))
    return [(out[i], out[i + 1]) for i in range(0, len(out), 2)]


def blob_of(gitdir, rev, path):
    return lib.git(gitdir, 'rev-parse', f'{rev}:{path}').strip()


def evaluate(gitdir, base, head, patterns, releases, chg=None):
    """返回 (违规列表, 放行了的列表)。releases：{路径: {blob, seq}}（本归属每个路径序号最大的那条）。"""
    bad, ok = [], []
    for st, path in (chg if chg is not None else changes(gitdir, base, head)):
        if not lib.match(path, patterns):
            continue
        blob = 'deleted' if st == 'D' else blob_of(gitdir, head, path)
        r = releases.get(path)
        if r is not None and r['blob'] == blob:
            ok.append({'path': path, 'blob': blob, 'seq': r['seq']})
        elif r is None:
            bad.append({'path': path, 'blob': blob, 'why': '没有放行'})
        else:
            bad.append({'path': path, 'blob': blob, 'why': f'内容和最后一条放行对不上（最后一条序号 {r["seq"]}）'})
    return bad, ok
