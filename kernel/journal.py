"""事件日志（设计书 8.2；放行事件 6.4；归属名不重复 6.4）。

放在单独的分支 sop/journal 上，只有事件文件，不含代码。写法照 S6、第一段 W21/W17：
- 不把日志分支检出成目录：直接造一个提交接在远程最新的提交后面，再推送；不强制推送，被抢先了就取回重来。
- 一个 sop 进程里只有一个写入线程。每个事件都等推上去了，发出它的那一步才往下走；
  同一时刻排着的几个事件合成一个提交、一次推送（v0.9 定）。
- 断网时写不了，流程停下，不在本地攒着（Y4）。

文件的放法：
  events/project/<纳秒时间>-<随机>.json          项目级的事件
  events/feature/<功能>/<纳秒时间>-<随机>.json    一个功能的事件，含它的工单（scope 写 ticket/<功能>/<编号>）
  releases/<归属>/<路径的散列>/<序号>.json        放行事件，守门检查只读这个目录
  names/<名字>.json                               登记过的归属名（分支名）；文件已经在了，就是用过了
"""
import hashlib
import json
import os
import queue
import socket
import tempfile
import threading
import time
import uuid

from .errors import SopError
from .gitx import Git, GitError

BRANCH = 'sop/journal'
REF = f'refs/heads/{BRANCH}'
TRACK = f'refs/remotes/origin/{BRANCH}'
WHO = {'GIT_AUTHOR_NAME': 'sop', 'GIT_AUTHOR_EMAIL': 'sop@localhost', 'GIT_COMMITTER_NAME': 'sop',
       'GIT_COMMITTER_EMAIL': 'sop@localhost'}

STEP_TYPES = ('start', 'done', 'failed', 'skipped', 'confirm', 'reopen', 'drop')
# register：登记（分支、目录、基准，换电脑时重建用）；release：放行；
# note：记录，不影响位置（指标、额度报错、花费提醒、绕开说明等，开工时用户同意加的一种）
OTHER_TYPES = ('register', 'release', 'note')


class NameTaken(SopError):
    pass


class Offline(SopError):
    pass


def scope_dir(scope):
    """事件放在哪个目录：项目级一个，每个功能一个（工单算在它的功能里）。"""
    if scope == 'project':
        return 'project'
    parts = scope.split('/')
    if parts[0] in ('feature', 'ticket') and len(parts) >= 2:
        return f'feature/{parts[1]}'
    raise ValueError(f'不认识的范围：{scope}')


def owner_key(owner):
    return owner.replace('/', '__')


def path_key(path):
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def name_file(name):
    return f'names/{name.replace("/", "__")}.json'


def event(scope, step, type, **payload):
    if type not in STEP_TYPES + OTHER_TYPES:
        raise ValueError(f'不认识的事件种类：{type}')
    return {'_item': 'event', 'scope': scope, 'step': step, 'type': type, **payload}


def release(owner, path, blob, case, **payload):
    """放行事件：放行「某个归属名下、某个路径上的某一份内容」。blob 写 'deleted' 表示放行删除。序号由写入线程按日志里现有的定。"""
    return {'_item': 'release', 'owner': owner, 'path': path, 'blob': blob, 'case': case, **payload}


def register_name(name, **payload):
    """登记一个归属名。这个名字以前用过，就加不进去（抛 NameTaken）。"""
    return {'_item': 'name', 'name': name, **payload}


class Journal:
    """一个项目的事件日志。gitdir 是项目的裸仓库；远程叫 origin。"""

    def __init__(self, gitdir, test_die_before_push=None):
        self.git = Git(gitdir)
        self._writer = None
        self._lock = threading.Lock()
        self.host = socket.gethostname()
        n = test_die_before_push if test_die_before_push is not None else os.environ.get('SOP_TEST_DIE_BEFORE_PUSH')
        self._die_at = int(n) if n else None
        self.pushes = 0          # 推送了几次（测试和统计用）
        self.retries = 0         # 被抢先重来了几次

    # ---------- 建立 ----------
    def init_branch(self):
        """在远程建一条空的日志分支（项目初始化 I6 用；和代码没有共同的历史）。已有就不动。"""
        if self.git.ok('ls-remote', '--exit-code', 'origin', REF):
            self.fetch()
            return
        empty = self.git('hash-object', '-t', 'tree', '-w', '--stdin', input='')
        c = self.git('commit-tree', empty, '-m', '建立日志分支', env=WHO)
        self.git('push', '-q', 'origin', f'{c}:{REF}')
        self.git('update-ref', TRACK, c)

    # ---------- 读 ----------
    def fetch(self):
        for i in range(20):
            p = self.git.run('fetch', '-q', '--no-write-fetch-head', 'origin', f'+{REF}:{TRACK}', check=False)
            if p.returncode == 0:
                return
            if any(m in p.stderr for m in ('cannot lock ref', 'unable to update local ref', 'incorrect old value')):
                time.sleep(0.05 * (i + 1))   # 本机另一个线程正好在更新同一个指针
                continue
            raise Offline(f'取不到远程的事件日志，流程停下（不在本地攒着）。检查网络后重新执行 sop。原始报错：{p.stderr.strip()[:300]}')
        raise Offline('取回事件日志一直失败')

    def tip(self):
        return self.git.rev(TRACK)

    def _cat(self, specs):
        """一次读出很多个文件（按字节切，中文不会错位）。"""
        if not specs:
            return []
        out = self.git.run('cat-file', '--batch', input=''.join(s + '\n' for s in specs).encode(), binary=True).stdout
        res, i = [], 0
        while i < len(out):
            j = out.index(b'\n', i)
            hdr = out[i:j].split()
            if len(hdr) < 3 or hdr[1] != b'blob':
                raise RuntimeError(f'读事件文件失败：{out[i:j]!r}')
            size = int(hdr[2])
            res.append(out[j + 1:j + 1 + size])
            i = j + 2 + size
        return res

    def read(self, dirs, fetch=True):
        """按提交的先后读出这几个目录下的全部事件（同一个提交里按文件名，也就是写入的先后）。"""
        if fetch:
            self.fetch()
        tip = self.tip()
        if not tip:
            return []
        out = self.git('log', '--reverse', '--format=%x01%H', '--name-only', '--diff-filter=A', tip, '--',
                       *[f'events/{d}/' for d in dirs])
        order = []
        for chunk in out.split('\x01'):
            lines = [l for l in chunk.splitlines() if l.strip()]
            if not lines:
                continue
            commit, files = lines[0], sorted(lines[1:])
            order += [(commit, f) for f in files]
        bodies = self._cat([f'{c}:{f}' for c, f in order])
        evs = []
        for (c, f), b in zip(order, bodies):
            e = json.loads(b.decode('utf-8'))
            e['_commit'], e['_file'] = c, f
            evs.append(e)
        return evs

    def releases(self, owner, fetch=True):
        """某个归属名下，每个路径序号最大的那条放行（守门检查用的是同一种比法）。"""
        if fetch:
            self.fetch()
        tip = self.tip()
        if not tip:
            return {}
        files = [f for f in self.git('ls-tree', '-r', '--name-only', tip, f'releases/{owner_key(owner)}/').splitlines()
                 if f.endswith('.json')]
        best = {}
        for b in self._cat([f'{tip}:{f}' for f in files]):
            r = json.loads(b.decode('utf-8'))
            if r.get('owner') == owner and (r['path'] not in best or r['seq'] > best[r['path']]['seq']):
                best[r['path']] = r
        return best

    def name_used(self, name, fetch=True):
        if fetch:
            self.fetch()
        tip = self.tip()
        return bool(tip) and self.git.blob_of(tip, name_file(name)) is not None

    # ---------- 写 ----------
    def append(self, *items):
        """写入并等它们推上去。返回每一项写成的文件名；登记的名字用过了抛 NameTaken。"""
        with self._lock:
            if self._writer is None or not self._writer.is_alive():
                self._writer = _Writer(self)
                self._writer.start()
        done = threading.Event()
        box = {}
        self._writer.q.put((list(items), done, box))
        done.wait()
        if 'error' in box:
            raise box['error']
        return box['files']

    def close(self):
        if self._writer and self._writer.is_alive():
            self._writer.q.put(None)
            self._writer.join()


class _Writer(threading.Thread):
    """唯一的写入线程：把同一时刻排着的几批合成一个提交、一次推送。"""

    def __init__(self, journal):
        super().__init__(daemon=True, name='sop-journal-writer')
        self.j = journal
        self.q = queue.Queue()

    def run(self):
        while True:
            first = self.q.get()
            if first is None:
                return
            batch = [first]
            while True:
                try:
                    nxt = self.q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    self.q.put(None)
                    break
                batch.append(nxt)
            try:
                self._commit(batch)
            except BaseException as e:   # 写入线程不能死：把错误交给等着的那几步
                for _, done, box in batch:
                    if 'files' not in box and 'error' not in box:
                        box['error'] = e if isinstance(e, SopError) else SopError(f'写事件日志出错：{e}')
                        done.set()

    def _commit(self, batch):
        g = self.j.git
        for attempt in range(100):
            self.j.fetch()
            tip = self.j.tip()
            if not tip:
                raise SopError('远程没有日志分支 sop/journal（项目初始化的 I6 没做？）')
            plan = []        # (box, done, [(文件名, 内容)]) 或 (box, done, 错误)
            taken, seqs = set(), {}
            for items, done, box in batch:
                files, err = [], None
                for it in items:
                    if it['_item'] == 'name':
                        nf = name_file(it['name'])
                        if nf in taken or g.blob_of(tip, nf):
                            err = NameTaken(f'名字 {it["name"]} 以前用过，不能再用（放行事件按归属名记，旧的放行会被重新利用，6.4）')
                            break
                        taken.add(nf)
                        body = {k: v for k, v in it.items() if k != '_item'}
                        files.append((nf, {'type': 'name', **body, **self._stamp()}))
                    elif it['_item'] == 'release':
                        d = f'releases/{owner_key(it["owner"])}/{path_key(it["path"])}'
                        if d not in seqs:
                            names = g('ls-tree', '--name-only', tip, d + '/').splitlines()
                            seqs[d] = max([int(n.rsplit('/', 1)[-1][:-5]) for n in names] or [0])
                        seqs[d] += 1
                        body = {k: v for k, v in it.items() if k != '_item'}
                        files.append((f'{d}/{seqs[d]:06d}.json', {'type': 'release', **body, 'seq': seqs[d], **self._stamp()}))
                    else:
                        st = self._stamp()
                        body = {k: v for k, v in it.items() if k != '_item'}
                        name = f'events/{scope_dir(it["scope"])}/{time.time_ns():020d}-{st["id"][:8]}.json'
                        files.append((name, {**body, **st}))
                plan.append((box, done, err if err else files))
            writes = [f for _, _, fs in plan if isinstance(fs, list) for f in fs]
            if not writes:
                break
            commit = self._make_commit(tip, writes)
            self.j.pushes += 1
            if self.j._die_at is not None and self.j.pushes >= self.j._die_at:
                os._exit(137)    # 测试用：模拟 sop 在推送之前被强制结束
            p = g.run('push', '-q', '--porcelain', 'origin', f'{commit}:{REF}', check=False)
            if p.returncode == 0:
                g.run('update-ref', TRACK, commit, check=False)   # 本机另一个进程同时在更新也没关系，下次取回会补上
                break
            # 推送失败：不猜原因。下一轮先取回——取不回就是断网（fetch 会报 Offline），取回了就是被别人抢先，重来。
            self.j.retries += 1
            time.sleep(min(0.05 * (attempt + 1), 1))
        else:
            raise SopError('推送事件一直被别人抢先，重来 100 次仍不成')
        for box, done, fs in plan:
            if isinstance(fs, list):
                box['files'] = [n for n, _ in fs]
            else:
                box['error'] = fs
            done.set()

    def _stamp(self):
        return {'id': uuid.uuid4().hex, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'host': self.j.host, 'pid': os.getpid()}

    def _make_commit(self, tip, writes):
        g = self.j.git
        with tempfile.TemporaryDirectory(prefix='sop-ev-') as td:
            names = []
            for i, (_, body) in enumerate(writes):
                fn = os.path.join(td, f'{i}.json')
                with open(fn, 'w', encoding='utf-8') as f:
                    json.dump(body, f, ensure_ascii=False, indent=1)
                names.append(fn)
            blobs = g('hash-object', '-w', '--no-filters', '--stdin-paths', input='\n'.join(names) + '\n').split()
            ix = {'GIT_INDEX_FILE': os.path.join(td, 'index')}
            g('read-tree', tip, env=ix)
            g('update-index', '--add', '--index-info', input=''.join(f'100644 {b}\t{n}\n' for b, (n, _) in zip(blobs, writes)), env=ix)
            tree = g('write-tree', env=ix)
        msg = f'{len(writes)} 条：' + '；'.join(
            f'{b.get("scope", b.get("owner", b.get("name", "")))} {b.get("step", "")} {b["type"]}'.strip() for _, b in writes[:5]
        ) + ('…' if len(writes) > 5 else '')
        return g('commit-tree', tree, '-p', tip, '-m', msg, env=WHO)
