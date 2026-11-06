"""Regression tests for the 3.6.7 fixes. Each one fails on 3.6.6 unless its comment says it guards a fix."""
import json
import os
import subprocess
import sys
import unittest

from support import ENV, TOOLS, Workspace
from wslib import core, rows, tables
from wslib.schema import LIB_MODULES, TABLES

WRITER = ('import subprocess, sys\n'
          'tool, root, name = sys.argv[1:4]\n'
          'for i in range(5):\n'
          '    subprocess.run([sys.executable, tool, "--root", root, "add", "requirement", "--set",\n'
          '                    f"requirement=Writer {name} row {i}", "--set", "acceptance=listed"], check=True,\n'
          '                   stdout=subprocess.DEVNULL)\n')


class Imports(unittest.TestCase):
    def test_every_module_imports_alone(self):
        for name in LIB_MODULES:
            with self.subTest(module=name):
                run = subprocess.run([sys.executable, '-c', f'import wslib.{name}'], cwd=TOOLS, env=ENV,
                                     capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(run.returncode, 0, run.stderr[-600:])


class Locking(Workspace):
    def test_three_processes_add_without_losing_rows(self):
        # Guards the file lock until 3.9.0 replaces it with a system lock: concurrent writers lose and duplicate nothing.
        self.init(requirement=False)
        tool = str(self.root / '.agents/tools/ws.py')
        workers = [subprocess.Popen([sys.executable, '-c', WRITER, tool, str(self.root), str(n)], stderr=subprocess.PIPE,
                                    env={**ENV, 'WS_LOCK_WAIT': '120'}, text=True, encoding='utf-8') for n in range(3)]
        outcomes = [(worker.communicate()[1], worker.returncode) for worker in workers]
        self.assertEqual([code for _, code in outcomes], [0, 0, 0], outcomes)
        rows = tables.rows(self.root, TABLES['requirements'])
        self.assertEqual(sorted(r['Requirement'] for r in rows),
                         sorted(f'Writer {n} row {i}' for n in range(3) for i in range(5)))
        self.assertEqual(len({r['ID'] for r in rows}), 15)

    def test_l1_release_keeps_a_lock_that_is_not_ours(self):
        path = self.root / '.agents/cache/ws.lock'
        with core.lock(self.root):
            path.write_text(json.dumps({'pid': os.getpid(), 'created_at': 'x', 'nonce': 'another process'}), encoding='utf-8')
        self.assertTrue(path.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows process access rules')
    def test_access_denied_counts_as_alive(self):
        self.assertTrue(core.pid_alive(4))


class Pair(Workspace):
    """Window a holds T1 for R1. Window b holds T2, which builds on R2 and is listed by feature F1."""

    def env(self, name):
        return {**{n: '' for n in core.SESSION_VARS}, 'WS_SESSION_ID': name}

    def setUp(self):
        super().setUp()
        self.a, self.b = self.env('win-a'), self.env('win-b')
        self.write('a/one.py', 'ONE = 1\n')
        self.write('b/two.py', 'TWO = 2\n')
        self.ws('init', '--goal', 'Demo', env=self.a)
        for text in ('first', 'second'):
            self.ws('add', 'requirement', '--set', f'requirement={text}', '--set', 'acceptance=listed', env=self.a)
        for requirement, scope in (('R1', 'a/'), ('R2', 'b/')):
            self.ws('add', 'task', '--set', f'requirements={requirement}', '--set', f'scope={scope}', '--set',
                    f'action=Work on {scope}', '--set', 'acceptance=python -m unittest', env=self.a)
        self.ws('add', 'feature', '--set', 'behavior=Second', '--set', 'requirements=R2', '--set', 'tasks=T2', env=self.a)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                '--set', 'next_acceptance=a', env=self.a)
        self.ws('start', '--task', 'T1', env=self.a)
        self.ws('start', '--task', 'T2', env=self.b)


class Retire(Pair):
    def test_p1_retire_requirement_cited_by_claimed_task_is_refused(self):
        refused = self.ws('set', 'R2', '--set', 'status=removed', '--set', 'reason=x', env=self.a, expect=2).stderr
        self.assertIn('T2 builds on R2 and belongs to', refused)
        self.assertIn('must not retire R2. Ask the user', refused)

    def test_p1_retire_feature_whose_tasks_column_holds_claimed_task_is_refused(self):
        refused = self.ws('set', 'F1', '--set', 'status=removed', '--set', 'reason=x', env=self.a, expect=2).stderr
        self.assertIn('T2 builds on F1 and belongs to', refused)

    def test_retiring_what_only_your_own_task_builds_on_is_allowed(self):
        self.ws('set', 'R1', '--set', 'status=removed', '--set', 'reason=x', env=self.a)


class RetireMatching(unittest.TestCase):
    def test_r1_does_not_match_r10(self):
        tasks = {'T1': {'Requirements': 'R10'}, 'T2': {'Requirements': 'R1, R3'}}
        self.assertEqual(rows.builders('requirements', 'R1', {}, tasks), ['T2'])
        self.assertEqual(rows.builders('features', 'F1', {'F1': {'Tasks': 'T12, T2'}}, tasks), ['T12', 'T2'])


if __name__ == '__main__':
    unittest.main()
