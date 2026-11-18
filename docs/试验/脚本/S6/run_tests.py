#!/usr/bin/env python3
"""试验 S6 的全部测试。每项事先写明期望，打印「符合 / 不符」。"""
import json, os, shutil, subprocess, sys, time, tomllib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as J

R = '/tmp/sop-spike-s6'; W = R + '/work'
flow = tomllib.load(open(R + '/flow.toml', 'rb'))
results = []


def check(desc, ok, extra=''):
    results.append(ok); print(('符合  | ' if ok else '不符  | ') + desc + (f'  [{extra}]' if extra and not ok else ''), flush=True)


def sh(*a, cwd=None, check_=True):
    p = subprocess.run(a, cwd=cwd, capture_output=True, text=True,
                       env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'})
    if check_ and p.returncode:
        raise RuntimeError(f'{a}: {p.stderr}')
    return p.stdout.strip()


def ev(gitdir, scope, step, typ, **kw):
    return J.append(gitdir, {'scope': scope, 'step': step, 'type': typ, **kw})


def clone_bare(name):
    """模拟一台电脑：裸仓库加工作目录的结构（设计书 5.1）。"""
    root = f'{W}/{name}'; os.makedirs(root)
    sh('git', 'clone', '-q', '--bare', f'{W}/remote.git', root + '/.git')
    sh('git', '--git-dir', root + '/.git', 'config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*')
    sh('git', '--git-dir', root + '/.git', 'fetch', '-q', 'origin')
    return root + '/.git'


# ---------- 准备：一个充当 GitHub 的远程仓库，里面有代码分支和一条空的日志分支 ----------
shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
sh('git', 'init', '-q', '--bare', '-b', 'main', W + '/remote.git')
sh('git', 'clone', '-q', W + '/remote.git', W + '/seed')
open(W + '/seed/README.md', 'w').write('代码\n')
sh('git', 'add', '.', cwd=W + '/seed'); sh('git', 'commit', '-q', '-m', '初始代码', cwd=W + '/seed'); sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=W + '/seed')
for b in ('feat/a', 'ticket/a/1', 'ticket/a/2'):
    sh('git', 'push', '-q', 'origin', f'HEAD:refs/heads/{b}', cwd=W + '/seed')
# 日志分支：一条和代码没有共同历史的分支，第一个提交是空的
empty_tree = sh('git', 'hash-object', '-t', 'tree', '/dev/null', cwd=W + '/seed')
c0 = sh('git', 'commit-tree', empty_tree, '-m', '建立日志分支', cwd=W + '/seed')
sh('git', 'push', '-q', 'origin', f'{c0}:refs/heads/sop/journal', cwd=W + '/seed')
A = clone_bare('pc-A')
code_tips_before = sh('git', '--git-dir', W + '/remote.git', 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/main', 'refs/heads/feat', 'refs/heads/ticket')

print('## 一、单独的分支')
ev(A, 'feature/a', 'F8', 'done', cost=0.4)
tree = sh('git', '--git-dir', W + '/remote.git', 'ls-tree', '-r', '--name-only', 'refs/heads/sop/journal')
check('日志分支上只有事件文件，没有代码', all(l.startswith('events/') for l in tree.splitlines()) and 'README.md' not in tree)
check('日志分支和代码分支没有共同的历史', subprocess.run(['git', '--git-dir', W + '/remote.git', 'merge-base', 'refs/heads/main', 'refs/heads/sop/journal'], capture_output=True).returncode != 0)
check('写日志不需要把日志分支检出成一个目录', not os.path.exists(W + '/pc-A/journal') and sh('git', '--git-dir', A, 'worktree', 'list').count('\n') == 0)

print('## 二、回放：顺利的路、回头路、条件步骤、中断、重新确认、放弃')
T = 'ticket/a/1'
for s in ('T1', 'T2', 'T3'):
    ev(A, T, s, 'start'); ev(A, T, s, 'done', cost=0.5)
pos = J.positions(A, flow)[T]
check('顺利做完 T1 到 T3 后，位置在 T4', pos['pos'] == 'T4' and pos['status'] == 'ready', str(pos))
# 回头路：T4 通过，T5 门禁不通过 -> T6 修复 -> 回 T4
ev(A, T, 'T4', 'start'); ev(A, T, 'T4', 'done')
ev(A, T, 'T5', 'start'); ev(A, T, 'T5', 'failed', attempt=1, reason='测试不通过', cost=0.1)
check('T5 失败后，位置在 T6（修复）', J.positions(A, flow)[T]['pos'] == 'T6')
ev(A, T, 'T6', 'start'); ev(A, T, 'T6', 'done', cost=0.8)
check('T6 修完后，位置回到 T4（回头路）', J.positions(A, flow)[T]['pos'] == 'T4')
for i in (2, 3):
    ev(A, T, 'T4', 'start'); ev(A, T, 'T4', 'done'); ev(A, T, 'T5', 'start'); ev(A, T, 'T5', 'failed', attempt=i, reason='仍不通过')
    ev(A, T, 'T6', 'start'); ev(A, T, 'T6', 'done', cost=0.8)
pos = J.positions(A, flow)[T]
check('三轮修复之后，记录显示 T6 做了 3 次、T5 失败 3 次', pos['attempts'].get('T6') == 3 and pos['fails'].get('T5') == 3, str(pos))
ev(A, T, 'T4', 'start'); ev(A, T, 'T4', 'done'); ev(A, T, 'T5', 'start'); ev(A, T, 'T5', 'failed', attempt=4, reason='仍不通过')
check('第 4 次失败时修复次数已用完，位置转到 T7（深入诊断）', J.positions(A, flow)[T]['pos'] == 'T7')
ev(A, T, 'T7', 'start'); ev(A, T, 'T7', 'done', cost=1.2)
ev(A, T, 'T4', 'start'); ev(A, T, 'T4', 'done'); ev(A, T, 'T5', 'start'); ev(A, T, 'T5', 'failed', attempt=5, reason='仍不通过')
pos = J.positions(A, flow)[T]
check('深入诊断之后仍失败，位置转到 T8（技术决策）并停下', pos['pos'] == 'T8' and pos['status'] == 'stopped', str(pos))
check('花费由事件累加得出（3×0.5 + 0.1 + 3×0.8 + 1.2 = 5.2）', pos['cost'] == 5.2, str(pos['cost']))
# 条件步骤
T2 = 'ticket/a/2'
for s in ('T1', 'T2', 'T3', 'T4', 'T5', 'T9', 'T10'):
    ev(A, T2, s, 'start'); ev(A, T2, s, 'done')
ev(A, T2, 'T11', 'skipped', reason='本功能选的是整份统一验收')
pos = J.positions(A, flow)[T2]
check('T11 按条件跳过后，位置在 T12，且记下了跳过', pos['pos'] == 'T12' and pos['skipped'] == ['T11'], str(pos))
# 合并冲突的回头路：T13 失败 -> T14 -> 回 T5
ev(A, T2, 'T12', 'start'); ev(A, T2, 'T12', 'done'); ev(A, T2, 'T13', 'start'); ev(A, T2, 'T13', 'failed', reason='有冲突')
check('T13 有冲突时，位置在 T14', J.positions(A, flow)[T2]['pos'] == 'T14')
ev(A, T2, 'T14', 'start'); ev(A, T2, 'T14', 'done')
check('T14 解决冲突后，位置回到 T5', J.positions(A, flow)[T2]['pos'] == 'T5')
# 中断：有开始没有结束
ev(A, T2, 'T5', 'start')
pos = J.positions(A, flow)[T2]
check('只有「开始」没有结束（断电、崩溃），回放显示这一步被中断、要重做', pos['pos'] == 'T5' and pos['status'] == 'interrupted', str(pos))
# 人的确认与重新打开
F = 'feature/a'
ev(A, F, 'F9', 'done'); ev(A, F, 'F10', 'confirm', commit='abc1234')
pos = J.positions(A, flow)[F]
check('小白确认后，位置在 F11，确认记录带着当时的提交编号', pos['pos'] == 'F11' and pos['confirms'].get('F10') == 'abc1234', str(pos))
ev(A, F, 'F11', 'done')
check('之后文件内容再怎么变，只要没有「重新打开」事件，确认仍然有效', 'F10' in J.positions(A, flow)[F]['confirms'])
ev(A, F, 'F14', 'reopen', target='F10', reason='验收卡的可见内容改了')
pos = J.positions(A, flow)[F]
check('出现「重新打开」事件后，确认失效，位置回到 F10', pos['pos'] == 'F10' and 'F10' not in pos['confirms'], str(pos))
ev(A, 'feature/b', 'F8', 'done'); ev(A, 'feature/b', 'F8', 'drop', reason='小白放弃这个功能')
check('「放弃」事件之后，这个功能的状态是已放弃', J.positions(A, flow)['feature/b']['status'] == 'dropped')

print('## 三、并行写入')
n_before = len(J.read_events(A))
t0 = time.time()
procs = [subprocess.Popen([sys.executable, R + '/journal.py', 'burst', A, f'ticket/p/{i}', '25'], stdout=subprocess.PIPE, text=True) for i in range(4)]
retries = sum(int(p.communicate()[0].strip() or 0) for p in procs); secs = time.time() - t0
evs = J.read_events(A)
check(f'同一台电脑上 4 个进程同时各写 25 个事件，100 个一个不少（用时 {secs:.1f} 秒，被抢先后重来 {retries} 次）', len(evs) - n_before == 100 and all(p.returncode == 0 for p in procs), f'{len(evs) - n_before}')
per = {}
for e in evs:
    if e['scope'].startswith('ticket/p/'):
        per.setdefault(e['scope'], []).append(int(e['step'][1:]))
check('每张工单自己的事件，顺序没有乱', all(v == sorted(v) and len(v) == 25 for v in per.values()))
log = sh('git', '--git-dir', W + '/remote.git', 'log', '--format=%P', 'refs/heads/sop/journal')
check('日志分支的历史是一条直线，没有合并提交，也没有用过强制推送', all(len(l.split()) <= 1 for l in log.splitlines()))
one_file = sh('git', '--git-dir', W + '/remote.git', 'log', '--format=format:@@', '--name-only', 'refs/heads/sop/journal')
counts = [len([x for x in blk.strip().splitlines() if x]) for blk in one_file.split('@@')[1:]]
check('每个提交只加一个事件文件', all(c <= 1 for c in counts), str(sorted(set(counts))))

print('## 四、另一台电脑同时写；换目录重建')
B = clone_bare('pc-B')
pa = subprocess.Popen([sys.executable, R + '/journal.py', 'burst', A, 'ticket/x/1', '15'], stdout=subprocess.PIPE, text=True)
pb = subprocess.Popen([sys.executable, R + '/journal.py', 'burst', B, 'ticket/x/2', '15'], stdout=subprocess.PIPE, text=True)
pa.communicate(); pb.communicate()
pa_, pb_ = J.positions(A, flow), J.positions(B, flow)
check('两台电脑同时写，各 15 个事件都在，互不覆盖', len([e for e in J.read_events(A) if e['scope'].startswith('ticket/x/')]) == 30)
check('两台电脑各自回放，得出的每一处位置完全相同', json.dumps(pa_, sort_keys=True) == json.dumps(pb_, sort_keys=True))
C = clone_bare('pc-C')
pc_ = J.positions(C, flow)
check('第三台全新的电脑克隆后回放，位置与前两台完全相同', json.dumps(pc_, sort_keys=True) == json.dumps(pa_, sort_keys=True))
# 按远程分支和事件日志重建进行中的工作目录
ev(A, 'ticket/a/2', 'T1', 'worktree', branch='ticket/a/2', base='feat/a', dir='ticket-a-2')
ev(A, 'feature/a', 'F1', 'worktree', branch='feat/a', base='main', dir='feat-a')
rebuilt = []
for e in J.read_events(C):
    if e['type'] == 'worktree':
        d = f"{W}/pc-C/{e['dir']}"
        sh('git', '--git-dir', C, 'worktree', 'add', '-q', '-B', e['branch'], d, f"origin/{e['branch']}")
        rebuilt.append((e['dir'], e['base'], os.path.exists(d + '/README.md')))
check('新电脑按事件日志里记的分支、目录名、基准分支，把进行中的工作目录建了回来', len(rebuilt) == 2 and all(r[2] for r in rebuilt) and dict((r[0], r[1]) for r in rebuilt) == {'ticket-a-2': 'feat/a', 'feat-a': 'main'}, str(rebuilt))
check('回放不受这类「登记」事件影响（位置不变）', J.positions(C, flow)['ticket/a/2']['pos'] == pc_['ticket/a/2']['pos'])

check('流程定义里没有的步骤编号，回放时不猜、不崩溃，只记下有多少个', pa_['ticket/x/1']['unknown'] == 15 and pa_['ticket/x/1']['pos'] == 'T1', str(pa_['ticket/x/1']))

print('## 五、不影响代码分支')
code_tips_after = sh('git', '--git-dir', W + '/remote.git', 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/main', 'refs/heads/feat', 'refs/heads/ticket')
check('写了这么多事件之后，所有代码分支的指针一个都没变', code_tips_before == code_tips_after)
total = len(J.read_events(A)); t0 = time.time(); J.positions(A, flow, do_fetch=False); rt = time.time() - t0
print(f'（共 {total} 个事件；全部回放一遍用时 {rt:.2f} 秒）')
print(f'\n合计 {len(results)} 项，符合 {sum(results)} 项，不符 {len(results) - sum(results)} 项')
