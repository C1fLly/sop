"""流程沙箱测试共用的底子。"""
import json
import os

from tests.helpers import TempHome
from tests.sandbox import plans
from tests.sandbox.world import World

F = 'jz-1'
FS = f'feature/{F}'
FB = f'feat/{F}'


class SandboxCase(TempHome):
    visibility = 'public'
    tweak = None

    def setUp(self):
        super().setUp()
        self.w = World(self.tmp, self.visibility, tweak=type(self).tweak)

    def start(self, tickets, new_pages=False):
        r = self.w.sop('feature', 'new', 'jz')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ai, human = plans.happy(F, tickets, new_pages)
        self.w.script.update(ai); self.w.human.update(human)

    def go(self, *args, ok=True):
        self.w.save_scripts()
        r = self.w.sop(*args)
        if os.environ.get('SOP_SHOW'):
            print(r.stdout[-6000:], r.stderr[-3000:])
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout[-5000:] + r.stderr[-3000:])
        return r

    def evs(self, scope=None):
        e = self.w.events(f'feature/{F}')
        return [x for x in e if scope is None or x.get('scope') == scope]

    def steps(self, scope, type_=None):
        return [(x['step'], x['type']) for x in self.evs(scope) if type_ is None or x['type'] == type_]

    def main_file(self, path):
        return self.w.rgit('show', f'main:{path}', check=False)

    def blob_main(self, path):
        return self.w.rgit('rev-parse', f'main:{path}')

    def prs(self):
        return {p['head']: p for p in self.w.db()['prs'].values()}

    def assertFeatureDone(self, r):
        self.assertIn('不需要你做什么', r.stdout, r.stdout[-3000:])
        self.assertIn(('F23', 'done'), self.steps(FS))
        self.assertEqual(self.prs()[FB]['state'], 'MERGED')
