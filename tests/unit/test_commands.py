"""3-62：命令表 kernel/commands.py 和代码里真分派的命令一致（文档检查 checks/doc_refs 按这张表认 `sop …`）。

把各命令的处理函数换成「到了」（抛 Reached），再调 kernel.cli.main：
- DONE、INTERNAL 里的每一条都要分派到处理函数（或像 `sop machine` 那样直接打出用法、退出码 0）；
- PLANNED 里的每一条现在都还分派不到（不认识、或说排在以后，退出码不是 0）。哪天做好了，这项不过，提醒把它挪到 DONE。
什么都不真做：不进项目、不写文件、不起子进程。
"""
import contextlib
import io
import re
import types
import unittest
from unittest import mock

from kernel import commands
from tests.helpers import REPO


class Reached(Exception):
    pass


def example_argv(usage):
    """用法 -> 一条能分派的命令行：<…> 填一个字，[…] 不填。"""
    out = []
    for w in usage.split():
        if w.startswith('['):
            continue
        out.append('x1' if w.startswith('<') else w)
    return out


def probe(argv):
    """返回 (到了哪个处理函数或 None, 退出码, 打出来的字)。"""
    def hit(name):
        def f(*a, **k):
            raise Reached(name)
        return f
    targets = {
        'kernel.cli.run_engine': 'run_engine', 'kernel.cli.status': 'status', 'kernel.cli.show_cost': 'cost',
        'kernel.cli.feature_new': 'feature_new', 'kernel.cli.feature_drop': 'feature_drop',
        'kernel.cli.init_project': 'init_project',
        'kernel.projectnew.cli': 'project new', 'kernel.projectclone.cli': 'project clone',
        'kernel.version.install': 'version.install', 'kernel.version.upgrade': 'version.upgrade',
        'machine.cli.show_tools': 'machine tools', 'machine.doctor.main': 'machine doctor',
        'machine.setup.main': 'machine setup', 'machine.migrate.flow.main': 'machine migrate',
    }
    out = io.StringIO()
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch('machine.migrate.record.recover', lambda: None))
        st.enter_context(mock.patch('kernel.cli.find_root', lambda cwd: '/nonexistent'))
        st.enter_context(mock.patch('kernel.cli.Project', lambda root: types.SimpleNamespace(name='demo')))
        st.enter_context(mock.patch('kernel.locks.ProjectLock', lambda name: contextlib.nullcontext()))
        for t, name in targets.items():
            st.enter_context(mock.patch(t, hit(name)))
        st.enter_context(contextlib.redirect_stdout(out))
        from kernel import cli
        try:
            rc = cli.main(argv)
        except Reached as r:
            return str(r), None, out.getvalue()
    return None, rc, out.getvalue()


class CommandTable(unittest.TestCase):
    def test_done_and_internal_are_dispatched(self):
        for usage in [*commands.DONE, *commands.INTERNAL]:
            argv = example_argv(usage)
            with self.subTest(sop=usage):
                where, rc, text = probe(argv)
                self.assertTrue(where or (rc == 0 and '不认识' not in text),
                                f'sop {" ".join(argv)} 没分派到任何处理函数（退出码 {rc}）：{text[-200:]}')

    def test_planned_not_dispatched_yet(self):
        for usage, when in commands.PLANNED.items():
            argv = example_argv(usage)
            with self.subTest(sop=usage):
                self.assertTrue(when.strip())
                where, rc, text = probe(argv)
                self.assertIsNone(where, f'sop {" ".join(argv)} 已经做好了（分派到 {where}），把它从 PLANNED 挪到 DONE')
                self.assertNotEqual(rc, 0, text[-200:])

    def test_probe_catches_unknown(self):
        # 反着试：表里没有的命令分派不到；machine 下不认识的也分派不到
        for argv in (['nope'], ['machine', 'nope'], ['self', 'nope'], ['feature', 'new']):
            where, rc, _ = probe(argv)
            self.assertIsNone(where, argv)
            self.assertNotEqual(rc, 0, argv)

    def test_no_duplicates(self):
        seen = {}
        for kind in ('DONE', 'INTERNAL', 'PLANNED'):
            for usage in getattr(commands, kind):
                w = commands.words(usage)
                self.assertNotIn(w, seen, f'sop {" ".join(w)} 在 {seen.get(w)} 和 {kind} 里各有一条')
                seen[w] = kind

    def test_planned_are_in_design(self):
        """PLANNED 不是随便往里放的地方：每一条都要是设计书里写着的命令。"""
        design = (REPO / 'docs' / '设计书.md').read_text(encoding='utf-8')
        written = {commands.words(m) for m in re.findall(r'`sop ([^`]*)`', design)}
        for usage in commands.PLANNED:
            self.assertIn(commands.words(usage), written, f'设计书里没有 sop {usage}')

    def test_words(self):
        self.assertEqual(commands.words('feature new <功能名>'), ('feature', 'new'))
        self.assertEqual(commands.words('check [步骤]'), ('check',))
        self.assertEqual(commands.words(''), ())
        self.assertTrue(commands.takes_args('self fix <问题单>'))
        self.assertFalse(commands.takes_args('machine doctor'))
