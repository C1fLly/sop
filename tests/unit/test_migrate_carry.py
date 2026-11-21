"""3-31：环境迁移 Q2 到 Q5（设计书 4.8）。用假的 docker 命令（tests/fakes/docker/docker）测，从不连真的 Docker：
假 docker 的状态都在每个测试自己的临时目录（FAKEDOCKER_ROOT）里，旧的、新的两份按通道分开，数据卷就是目录。

清单（Q1 的结果）在这里直接造，和 tests/fakes/migrate/ 里虚拟机取的那份放的东西一样：
旧的 docker.io 里镜像 shop-web:dev、busybox:1.36，数据卷 shop_pgdata（编排文件的标签，容器 shop-db-1 正在用）、notes（停着的 old-tool 用过）。
"""
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from kernel import cli as kcli
from machine import catalog
from machine.migrate import carry as C, flow, inventory as inv, record
from machine.migrate.dockercli import Daemon
from tests.helpers import REPO, TempHome

FAKE = REPO / 'tests' / 'fakes' / 'docker'
DOCKER = str(FAKE / 'docker')
SUDO = str(FAKE / 'sudo')
OLD_HOST, NEW_HOST = 'unix:///fake/run/docker.sock', 'unix:///fake/run/user/1000/docker.sock'
NOW = inv.parse_time('2026-11-24T06:00:00Z')
PG_LABELS = {'com.docker.compose.project': 'shop', 'com.docker.compose.volume': 'pgdata'}


def key(host):
    import re
    return re.sub(r'[^A-Za-z0-9.-]', '_', host)


class Base(TempHome):
    def setUp(self):
        super().setUp()
        self.fd = self.tmp / 'fakedocker'
        self.fd.mkdir()
        self.tools = self.tmp / 'tools'
        (self.tools / 'docker' / 'bin').mkdir(parents=True)
        (self.tools / 'docker' / 'etc').mkdir()
        os.symlink(DOCKER, self.tools / 'docker' / 'bin' / 'docker')
        (self.tools / 'docker' / 'etc' / 'docker-host').write_text(NEW_HOST + '\n')
        # 这两样在 TempHome 收拾之前先放开（tearDown 里）：patch.dict 放开时会把环境恢复成它开始时的样子，
        # 要是晚于 TempHome，就把这个测试的 HOME、SOP_HOME 等又带回给后面的测试
        self.patches = [mock.patch.dict(os.environ, {'FAKEDOCKER_ROOT': str(self.fd), 'SOP_TOOLS_DIR': str(self.tools),
                                                     'TMPDIR': str(self.tmp)}),
                        mock.patch.object(tempfile, 'tempdir', str(self.tmp))]   # docker 的临时设置目录也放在这个测试自己的目录里
        for x in self.patches:
            x.start()
        self.seed_old()
        self.said = []

    def tearDown(self):
        for x in reversed(self.patches):
            x.stop()
        super().tearDown()

    # ---- 假 Docker 的状态 ----
    def state(self, host):
        f = self.fd / key(host) / 'state.json'
        return json.loads(f.read_text()) if f.exists() else {'images': {}, 'containers': {}, 'volumes': {}}

    def put_state(self, host, st):
        d = self.fd / key(host)
        (d / 'vols').mkdir(parents=True, exist_ok=True)
        (d / 'state.json').write_text(json.dumps(st))

    def vol(self, host, name):
        return self.fd / key(host) / 'vols' / name

    def seed_old(self, helper=False):
        import shutil
        shutil.rmtree(self.fd / key(OLD_HOST), ignore_errors=True)
        imgs = {'shop-web:dev': {'id': 'sha256:' + 'a' * 64, 'size': 5_000_000},
                'busybox:1.36': {'id': 'sha256:' + 'b' * 64, 'size': 4_000_000}}
        if helper:
            imgs[C.HELPER] = {'id': 'sha256:' + 'c' * 64, 'size': 8_000_000}
        self.put_state(OLD_HOST, {
            'images': imgs,
            'containers': {'shop-db-1': {'running': True, 'volumes': ['shop_pgdata']},
                           'old-tool': {'running': False, 'volumes': ['notes']}},
            'volumes': {'shop_pgdata': {'labels': PG_LABELS}, 'notes': {'labels': {}}}})
        pg = self.vol(OLD_HOST, 'shop_pgdata')
        (pg / 'base' / '1').mkdir(parents=True)
        (pg / 'base' / '1' / 'table').write_bytes(b'500 rows\n' * 100)
        (pg / 'PG_VERSION').write_text('17\n')
        (pg / 'empty').write_text('')
        os.chmod(pg / 'PG_VERSION', 0o600)
        os.symlink('base/1/table', pg / 'link')
        notes = self.vol(OLD_HOST, 'notes')
        notes.mkdir(parents=True)
        (notes / 'a b.txt').write_text('有空格的名字\n')

    def log(self):
        f = self.fd / 'log'
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def old_cmds(self):
        return [' '.join(x['args']) for x in self.log() if x['host'] == OLD_HOST]

    def new_cmds(self):
        return [' '.join(x['args']) for x in self.log() if x['host'] == NEW_HOST]

    # ---- 清单 ----
    def inventory(self, *, running=True, listed=True, needs_admin=False, kind='docker.io'):
        vols = [
            {'name': 'shop_pgdata', 'size_bytes': 2_000_000, 'project': 'shop', 'project_from': 'label', 'anonymous': False,
             'driver': 'local', 'used_by': ['shop-db-1'], 'in_use': True, 'last_used': NOW, 'created': NOW},
            {'name': 'notes', 'size_bytes': 1000, 'project': '', 'project_from': '', 'anonymous': False, 'driver': 'local',
             'used_by': ['old-tool'], 'in_use': False, 'last_used': NOW - 86400 * 3, 'created': NOW}]
        imgs = [
            {'id': 'aaaaaaaaaaaa', 'tags': ['shop-web:dev'], 'size_bytes': 5_000_000, 'project': 'shop', 'used_by': [],
             'in_use': False, 'last_used': None, 'created': None, 'tagged_at': None},
            {'id': 'bbbbbbbbbbbb', 'tags': ['busybox:1.36'], 'size_bytes': 4_000_000, 'project': '', 'used_by': ['old-tool'],
             'in_use': False, 'last_used': NOW - 86400 * 3, 'created': None, 'tagged_at': None},
            {'id': 'dddddddddddd', 'tags': [], 'size_bytes': 1000, 'project': '', 'used_by': [], 'in_use': False,
             'last_used': None, 'created': None, 'tagged_at': None}]
        ctrs = [{'name': 'shop-db-1', 'image': 'postgres:17-alpine', 'project': 'shop', 'running': True, 'size_rw': 100,
                 'volumes': ['shop_pgdata']},
                {'name': 'old-tool', 'image': 'busybox:1.36', 'project': '', 'running': False, 'size_rw': 3_200_000,
                 'volumes': ['notes']}]
        d = {'kind': kind, 'label': inv.LABELS[kind], 'auto': True, 'admin': True, 'version': '29.1.3',
             'dirs': [{'path': '/var/lib/docker', 'size_bytes': 4096, 'on_system_disk': True, 'size_partial': True}],
             'residue': [], 'size_bytes': 4096, 'size_partial': True, 'on_system_disk': True,
             'daemon': {'host': OLD_HOST, 'cli': DOCKER, 'running': running, 'needs_admin': needs_admin},
             'listed': listed, 'images': imgs if listed else [], 'volumes': vols if listed else [],
             'containers': ctrs if listed else []}
        if not listed:
            d['why'] = '它现在没在运行'
        self.full = {'images': imgs, 'volumes': vols, 'containers': ctrs}
        return {'made_at': '', 'docker': [d], 'tools': [], 'tool_users': None, 'admin_used': False}

    def probe(self, admin=None):
        return inv.Probe(root=str(self.tmp / 'root'), home=str(self.test_home), run=lambda a, t: (1, '', ''), admin=admin,
                         usage=lambda p: (0, False), sysdisk=lambda p: False, now=NOW, tools=self.tools)

    def run_flow(self, answers, inventory=None, **kw):
        kw.setdefault('q2_fn', lambda i, say: True)
        kw.setdefault('probe', self.probe())
        kw.setdefault('free', lambda p: 10 ** 12)
        kw.setdefault('sleep', lambda s: None)
        rc = flow.migrate(ask=flow.Ask(answers, say=self.said.append), say=self.said.append,
                          inv=inventory or self.inventory(), **kw)
        return rc, '\n'.join(self.said)

    def tree(self, root):
        """目录里每样东西：相对路径 -> (类型, 权限, 内容或链接指向)。"""
        out = {}
        for dp, dns, fns in os.walk(root):
            for n in dns + fns:
                p = os.path.join(dp, n)
                st = os.lstat(p)
                rel = os.path.relpath(p, root)
                if stat.S_ISLNK(st.st_mode):
                    out[rel] = ('link', os.readlink(p))
                elif stat.S_ISDIR(st.st_mode):
                    out[rel] = ('dir', oct(st.st_mode & 0o777))
                else:
                    out[rel] = ('file', oct(st.st_mode & 0o777), pathlib.Path(p).read_bytes())
        return out


class Q3Choices(Base):
    def test_default_keeps_everything_and_touches_nothing(self):
        rc, out = self.run_flow([])
        self.assertEqual(rc, 0, out)
        self.assertIn('留着', out)
        self.assertEqual(self.log(), [])                      # 一条 docker 命令都没跑
        self.assertFalse((self.tools / 'backup').exists())
        ch = json.loads((record.migrate_dir() / 'choices.json').read_text())
        self.assertEqual(ch['docker'][0]['choice'], flow.KEEP)
        self.assertEqual(self.state(OLD_HOST)['containers']['shop-db-1']['running'], True)

    def test_not_a_terminal_means_defaults(self):
        a = flow.Ask(say=self.said.append, tty=False)
        self.assertEqual(a.choose('留还是卸', [(flow.KEEP, '留着'), (flow.DROP, '卸掉')], flow.KEEP), flow.KEEP)
        self.assertFalse(a.yes('现在停一下吗'))
        self.assertIn('不是在终端里运行，按默认', '\n'.join(self.said))

    def test_leave_one_volume_and_one_image(self):
        # 卸；shop_pgdata 带走、notes 不要；shop-web 带走、busybox 不要；停容器：是
        rc, out = self.run_flow(['2', '', '2', '', '2', 'y'])
        self.assertEqual(rc, 0, out)
        new = self.state(NEW_HOST)
        self.assertIn('shop_pgdata', new['volumes'])
        self.assertNotIn('notes', new['volumes'])
        self.assertIn('shop-web:dev', new['images'])
        self.assertNotIn('busybox:1.36', new['images'])
        self.assertIn('没名字的镜像 dddddddddddd', out)
        self.assertIn('不要的数据卷 notes（卸载时随旧的一起删掉）', out)
        self.assertIn('容器 old-tool 里有 3.2 MB 没放进数据卷的改动', out)


class Q4Carry(Base):
    def test_carry_everything(self):
        os.environ['FAKEDOCKER_REQUIRE'] = str(record.record_path())     # 停容器的那一刻记录必须已经在
        before = {n: self.tree(self.vol(OLD_HOST, n)) for n in ('shop_pgdata', 'notes')}
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0, out)
        for n in ('shop_pgdata', 'notes'):
            self.assertEqual(self.tree(self.vol(NEW_HOST, n)), before[n], n)
            self.assertEqual(self.tree(self.vol(OLD_HOST, n)), before[n], n)     # 旧的一样没动
        new, old = self.state(NEW_HOST), self.state(OLD_HOST)
        self.assertEqual(new['volumes']['shop_pgdata']['labels'], PG_LABELS)      # 原来的标签带上了
        self.assertEqual(set(new['volumes']), {'shop_pgdata', 'notes'})          # 临时卷删了
        self.assertTrue({'shop-web:dev', 'busybox:1.36', C.HELPER} <= set(new['images']))
        self.assertTrue(old['containers']['shop-db-1']['running'])               # 停了又起回来了
        self.assertFalse(old['containers']['old-tool']['running'])               # 原来停着的没去起
        self.assertNotIn(C.HELPER, old['images'])                                # 临时放进旧的的小镜像删了
        self.assertFalse(record.record_path().exists())
        cmds = self.old_cmds()
        self.assertEqual([c for c in cmds if c.startswith(('stop', 'start'))], ['stop -t 30 shop-db-1', 'start shop-db-1'])
        stop_at, start_at = cmds.index('stop -t 30 shop-db-1'), cmds.index('start shop-db-1')
        packs = [i for i, c in enumerate(cmds) if c.startswith('run') and ' tar ' in c]
        self.assertTrue(all(stop_at < i < start_at for i in packs) and len(packs) == 2, cmds)
        self.assertFalse(any(c.startswith('run') and '-v /' in c for c in cmds))  # 没往旧 Docker 里挂宿主机目录
        st = C.load_state()
        self.assertEqual(st['ready_for_q6'], {'docker.io': True})
        self.assertTrue(all(it['status'] == 'verified' for it in st['items'].values()), st)
        backup = pathlib.Path(st['backup_dir'])
        self.assertTrue(str(backup).startswith(str(self.tools / 'backup' / 'migrate-')))
        for f in ('images.tar', 'vol-shop_pgdata.tar', 'vol-shop_pgdata.before', 'vol-notes.tar'):
            self.assertTrue((backup / f).exists(), f)
        self.assertEqual(stat.S_IMODE(os.stat(backup).st_mode), 0o700)
        self.assertIn('和搬之前一致', out)
        self.assertIn('卸载旧的（Q6）还没做好', out)
        # 清单里有路径、类型、归属、权限、校验值、链接指向，没有目录的大小
        text = (backup / 'vol-shop_pgdata.before').read_text()
        self.assertIn('./PG_VERSION|regular file|', text)
        self.assertIn('|600', text)
        self.assertIn('./link -> base/1/table', text)
        self.assertRegex(text, r'[0-9a-f]{64}  \./base/1/table')

    def test_helper_already_in_old_is_kept(self):
        self.seed_old(helper=True)
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0, out)
        self.assertIn(C.HELPER, self.state(OLD_HOST)['images'])
        self.assertFalse(any(c.startswith('load') for c in self.old_cmds()))

    def test_declining_to_stop_does_nothing(self):
        rc, out = self.run_flow(['2', '', '', '', ''])        # 最后「现在停一下吗」直接回车 = 否
        self.assertEqual(rc, 1, out)
        self.assertIn('你选了先不停容器', out)
        self.assertFalse(any(c.startswith(('stop', 'run')) for c in self.old_cmds()))
        self.assertTrue(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        self.assertNotIn(C.HELPER, self.state(OLD_HOST)['images'])
        self.assertFalse(record.record_path().exists())

    def test_failure_while_packing_starts_containers_again(self):
        os.environ['FAKEDOCKER_FAIL'] = r'^unix:///fake/run/docker\.sock run .*notes:/sop-from:ro .* tar '
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 1, out)
        self.assertIn('把数据卷 notes 打包没成', out)
        self.assertIn('旧的照常可用', out)
        self.assertTrue(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        self.assertFalse(record.record_path().exists())
        self.assertNotIn(C.HELPER, self.state(OLD_HOST)['images'])
        self.assertNotIn('shop_pgdata', self.state(NEW_HOST)['volumes'])        # 打包没全成，一个卷都还没往新的里放
        # 去掉故障再执行一次：接着做完（镜像已经带过去了，跳过）
        del os.environ['FAKEDOCKER_FAIL']
        self.said.clear()
        n_load = sum(c.startswith('load') for c in self.new_cmds())
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0, out)
        self.assertEqual(sum(c.startswith('load') for c in self.new_cmds()), n_load)
        self.assertEqual(set(self.state(NEW_HOST)['volumes']), {'shop_pgdata', 'notes'})

    def test_trial_restore_mismatch_stops(self):
        os.environ['FAKEDOCKER_CORRUPT'] = r'^sop-migrate-try-shop_pgdata$'
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 1, out)
        self.assertIn('数据卷 shop_pgdata：备份试着还原到临时卷以后，文件清单和打包时的对不上', out)
        self.assertIn('多了或变了', out)
        new = self.state(NEW_HOST)
        self.assertNotIn('shop_pgdata', new['volumes'])
        self.assertNotIn('sop-migrate-try-shop_pgdata', new['volumes'])
        self.assertTrue(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        self.assertFalse(C.load_state().get('ready_for_q6'))

    def test_same_name_volume_in_new_is_not_overwritten(self):
        self.put_state(NEW_HOST, {'images': {}, 'containers': {}, 'volumes': {'notes': {'labels': {}}}})
        mine = self.vol(NEW_HOST, 'notes')
        mine.mkdir(parents=True)
        (mine / 'keep.txt').write_text('别人的\n')
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 1, out)
        self.assertIn('新 Docker 里已经有同名的数据卷 notes，不是这次迁移建的，不覆盖', out)
        self.assertEqual(os.listdir(mine), ['keep.txt'])
        self.assertFalse(any(c.startswith(('stop', 'run', 'save')) for c in self.old_cmds()))

    def test_not_enough_space_does_not_start(self):
        rc, out = self.run_flow(['2', '', '', '', '', 'y'], free=lambda p: 500 * 1024 ** 2)
        self.assertEqual(rc, 1, out)
        self.assertIn('还差', out)
        self.assertIn('备份位置和新 Docker 在同一个分区上', out)
        self.assertEqual(self.old_cmds(), [])
        self.assertFalse((self.tools / 'backup').exists())

    def test_space_plan_on_two_partitions(self):
        vols = [{'name': 'v', 'size_bytes': 3 * 1024 ** 3}]
        imgs = [{'tags': ['x:1'], 'size_bytes': 1024 ** 3}]
        devs = {str(self.tmp / 'b'): 1, str(self.tmp / 'n'): 2}
        (self.tmp / 'b').mkdir()
        (self.tmp / 'n').mkdir()
        with mock.patch.object(C, '_dev', lambda p: devs[p]):
            ok, text = C.space_plan(vols, imgs, self.tmp / 'b', self.tmp / 'n',
                                    free=lambda p: {str(self.tmp / 'b'): 100 * 1024 ** 3, str(self.tmp / 'n'): 5 * 1024 ** 3}[p])
        self.assertFalse(ok)
        self.assertIn('新 Docker 那边还差 3.2 GB', text)          # 要 4 + 3（临时卷）+ 1 = 8 GiB，剩 5 GiB（显示按 1000 进位）
        self.assertNotIn('备份位置还差', text)
        ok, text = C.space_plan([{'name': 'v', 'size_bytes': None}], [], self.tmp / 'b', self.tmp / 'n')
        self.assertFalse(ok)
        self.assertIn('量不出 数据卷 v 的大小', text)

    def test_rerun_after_done_skips(self):
        rc, _ = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0)
        n = len(self.log())
        self.said.clear()
        rc, out = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0, out)
        self.assertIn('选了带走的都已经带过去了，跳过', out)
        new_log = [' '.join(x['args']) for x in self.log()[n:]]
        self.assertFalse(any(c.startswith(('stop', 'save', 'load', 'volume create')) for c in new_log), new_log)

    def test_q5_catches_a_changed_volume(self):
        rc, _ = self.run_flow(['2', '', '', '', '', 'y'])
        self.assertEqual(rc, 0)
        (self.vol(NEW_HOST, 'notes') / 'a b.txt').write_text('被改了\n')
        new = Daemon(DOCKER, NEW_HOST)
        good, bad = C.verify(new, self.full['volumes'], [], scope='docker.io', say=self.said.append)
        new.close()
        self.assertFalse(good)
        self.assertIn('数据卷 notes 在新 Docker 里的文件清单和搬之前的对不上', '\n'.join(bad))
        self.assertEqual(C.load_state()['ready_for_q6'], {'docker.io': False})


class StoppedRecord(Base):
    def test_killed_midway_then_any_sop_starts_them_again(self):
        """sop 被强制结束（kill -9，退出时的保险来不及跑）：记录留着；下一次执行任何 sop 命令先把容器起回来。"""
        f = self.tmp / 'inv.json'
        f.write_text(json.dumps(self.inventory()))
        code = (
            'import json, sys\n'
            'from machine.migrate import flow, inventory as inv\n'
            'p = inv.Probe(root="/nonexistent", run=lambda a, t: (1, "", ""), usage=lambda p: (0, False), sysdisk=lambda p: False)\n'
            'flow.migrate(ask=flow.Ask(["2", "", "", "", "", "y"]), inv=json.load(open(sys.argv[1])), probe=p,\n'
            '             q2_fn=lambda i, say: True, free=lambda p: 10 ** 12)\n')
        env = {**os.environ, 'PYTHONPATH': str(REPO), 'FAKEDOCKER_KILL': r'^unix:///fake/run/docker\.sock run .*notes:/sop-from:ro .* tar '}
        p = subprocess.run([sys.executable, '-c', code, str(f)], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, -signal.SIGKILL, p.stdout + p.stderr)
        rec = record.load()
        self.assertEqual(rec['containers'], ['shop-db-1'])
        self.assertEqual(rec['helper_added'], C.HELPER)
        self.assertFalse(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        # 下一次执行 sop（这里是 sop machine tools）：先起回来，再做它本来的事
        with mock.patch('builtins.print') as pr:
            rc = kcli.main(['machine', 'tools'])
        printed = '\n'.join(' '.join(map(str, c.args)) for c in pr.call_args_list)
        self.assertEqual(rc, 0)
        self.assertIn('现在先把它们起回来', printed)
        self.assertIn('工具包要装的基础工具', printed)
        self.assertTrue(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        self.assertNotIn(C.HELPER, self.state(OLD_HOST)['images'])
        self.assertFalse(record.record_path().exists())

    def test_no_record_means_nothing_happens(self):
        self.assertTrue(record.recover(say=self.said.append))
        self.assertEqual(self.said, [])
        self.assertEqual(self.log(), [])
        self.assertFalse(record.migrate_dir().exists())

    def test_migration_in_progress_elsewhere_is_left_alone(self):
        old = Daemon(DOCKER, OLD_HOST)
        st = self.state(OLD_HOST)
        st['containers']['shop-db-1']['running'] = False
        self.put_state(OLD_HOST, st)
        with record.Running():
            record.add_stopped(old, ['shop-db-1'])
            self.assertTrue(record.recover(say=self.said.append))
            self.assertFalse(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
            with self.assertRaises(record.Busy):
                with record.Running():
                    pass
        self.assertTrue(record.recover(say=self.said.append))
        self.assertTrue(self.state(OLD_HOST)['containers']['shop-db-1']['running'])
        old.close()

    def test_start_failure_keeps_record_and_says_so(self):
        old = Daemon(DOCKER, OLD_HOST, [SUDO])
        record.add_stopped(old, ['shop-db-1'])
        os.environ['FAKEDOCKER_FAIL'] = r' start '
        self.assertFalse(record.recover(say=self.said.append))
        out = '\n'.join(self.said)
        self.assertIn('系统会问一次这台电脑的登录密码', out)
        self.assertIn('没起回来', out)
        self.assertIn(f'sudo {DOCKER} --host {OLD_HOST} start shop-db-1', out)
        self.assertEqual(record.load()['containers'], ['shop-db-1'])
        self.assertIn('start shop-db-1', (self.fd / 'sudo.log').read_text())
        old.close()

    def test_garbled_record_is_reported_not_guessed(self):
        record.migrate_dir().mkdir(parents=True)
        record.record_path().write_text('{坏的')
        self.assertFalse(record.recover(say=self.said.append))
        self.assertIn('读不懂', '\n'.join(self.said))
        self.assertTrue(record.record_path().exists())


class StoppedDaemonAndAdmin(Base):
    """替用户定的两条：旧 Docker 停着时、要管理员才连得上时，先说一句再问，默认不做、改回「留」。"""

    def fake_system(self):
        calls = []

        def system(argv):
            calls.append(argv)
            return 0, '', ''
        return calls, system

    def relist(self, probe, d):
        return {'listed': True, **self.full}

    def test_stopped_daemon_default_not_started(self):
        calls, system = self.fake_system()
        rc, out = self.run_flow(['2', ''], self.inventory(running=False, listed=False), system=system, relist=self.relist)
        self.assertEqual(rc, 0, out)
        self.assertIn('现在停着', out)
        self.assertIn('这一份 Docker 先留着', out)
        self.assertEqual(calls, [])
        self.assertEqual(self.log(), [])
        ch = json.loads((record.migrate_dir() / 'choices.json').read_text())
        self.assertEqual(ch['docker'][0]['choice'], flow.KEEP)

    def test_stopped_daemon_started_then_stopped_back(self):
        calls, system = self.fake_system()
        probe = self.probe()
        with mock.patch.object(flow, 'ADMIN', [SUDO]):
            rc, out = self.run_flow(['2', 'y', '', '', '', '', 'y'], self.inventory(running=False, listed=False),
                                    system=system, relist=self.relist, probe=probe)
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, [[SUDO, 'systemctl', 'start', 'docker.service'], [SUDO, 'systemctl', 'stop', 'docker.service']])
        self.assertIn('起它要管理员权限', out)
        self.assertIn('已经停回去了', out)
        self.assertEqual(set(self.state(NEW_HOST)['volumes']), {'shop_pgdata', 'notes'})

    def test_stopped_back_even_when_carry_fails(self):
        calls, system = self.fake_system()
        os.environ['FAKEDOCKER_FAIL'] = r'^unix:///fake/run/docker\.sock save '
        with mock.patch.object(flow, 'ADMIN', [SUDO]):
            rc, out = self.run_flow(['2', 'y', '', '', '', '', 'y'], self.inventory(running=False, listed=False),
                                    system=system, relist=self.relist)
        self.assertEqual(rc, 1, out)
        self.assertEqual(calls[-1], [SUDO, 'systemctl', 'stop', 'docker.service'])

    def test_admin_needed_default_not_used(self):
        rc, out = self.run_flow(['2', ''], self.inventory(listed=False, needs_admin=True))
        self.assertEqual(rc, 0, out)
        self.assertIn('只有管理员才连得上', out)
        self.assertIn('这一份 Docker 先留着', out)
        self.assertEqual(self.log(), [])
        self.assertFalse((self.fd / 'sudo.log').exists())

    def test_admin_used_for_old_docker_only(self):
        with mock.patch.object(flow, 'ADMIN', [SUDO]):
            rc, out = self.run_flow(['2', 'y', '', '', '', '', 'y'], self.inventory(listed=False, needs_admin=True),
                                    relist=self.relist)
        self.assertEqual(rc, 0, out)
        sudo = [x for x in (self.fd / 'sudo.log').read_text().splitlines() if ' --host ' in x]   # 算清单的脚本有好几行
        self.assertTrue(sudo and all(OLD_HOST in x for x in sudo), sudo)       # 只有旧的那份用了管理员
        self.assertTrue(any(' save ' in x for x in sudo))
        self.assertTrue(record.record_path().exists() is False)


class Q2(Base):
    def tool(self, name, step):
        return catalog.Tool(name=name, what=name, version='', location=f'~/tools/{name}', check='true',
                            install=f'script:install/{name}.sh', admin=False, step=step)

    def test_installs_missing_m2_tools_with_docker_deps(self):
        got = []
        tools = [self.tool('uv', 'M2'), self.tool('docker', 'M2'), self.tool('gh', 'M2')]
        ok = flow.q2({'docker': [{}], 'tools': [{'name': 'uv'}]}, self.said.append,
                     check=lambda t: mock.Mock(ok=t.name == 'uv'), install=lambda n: (got.append(n), (True, []))[1],
                     tools=tools)
        self.assertTrue(ok)
        self.assertEqual(got, [('uidmap', 'dbus-user-session', 'docker')])

    def test_all_installed_skips(self):
        ok = flow.q2({'docker': [{}], 'tools': []}, self.said.append, check=lambda t: mock.Mock(ok=True),
                     install=lambda n: self.fail('不该装'), tools=[self.tool('docker', 'M2')])
        self.assertTrue(ok)
        self.assertIn('都已经装好了，跳过', '\n'.join(self.said))

    def test_wt_missing_asks_for_setup(self):
        ok = flow.q2({'docker': [], 'tools': [{'name': 'wt'}]}, self.said.append, check=lambda t: mock.Mock(ok=False),
                     install=lambda n: self.fail('不该装'), tools=[self.tool('wt', 'M5')])
        self.assertFalse(ok)
        self.assertIn('先执行 sop machine setup', '\n'.join(self.said))

    def test_q2_failure_stops_before_choices(self):
        rc, out = self.run_flow(['2'], q2_fn=lambda i, say: False)
        self.assertEqual(rc, 1)
        self.assertNotIn('Q3', out)
        self.assertEqual(self.log(), [])


class FakeDockerItself(Base):
    def test_refuses_without_root(self):
        env = {k: v for k, v in os.environ.items() if k != 'FAKEDOCKER_ROOT'}
        p = subprocess.run([DOCKER, 'version'], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 99)

    def test_fake_sudo_runs_only_fake_docker(self):
        p = subprocess.run([SUDO, '-p', 'x', 'true'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn('只执行假的 docker', p.stderr)


if __name__ == '__main__':
    unittest.main()
