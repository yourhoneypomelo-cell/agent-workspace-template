"""Regression tests for the 3.6.7 fixes. Each one fails on 3.6.6 unless its comment says it guards a fix."""
import subprocess
import sys
import unittest

from support import ENV, Workspace
from wslib import tables
from wslib.schema import TABLES

WRITER = ('import subprocess, sys\n'
          'tool, root, name = sys.argv[1:4]\n'
          'for i in range(5):\n'
          '    subprocess.run([sys.executable, tool, "--root", root, "add", "requirement", "--set",\n'
          '                    f"requirement=Writer {name} row {i}", "--set", "acceptance=listed"], check=True,\n'
          '                   stdout=subprocess.DEVNULL)\n')


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


if __name__ == '__main__':
    unittest.main()
