"""3.9.0: the system file lock, the permission table, message timing and IDs, redaction, chat import and credentials
as the owner decided, and hook paths. Each test fails on 3.8.0 unless its comment says it guards a behavior."""
import errno
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from support import ENV, TOOLS, Workspace
from wslib import core, tables, validate
from wslib.schema import TABLES

HOLD = ('import sys, time\nsys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\nfrom wslib import core\n'
        'with core.lock(Path(sys.argv[2])):\n    print("held", flush=True)\n    time.sleep(60)\n')
WRITER = ('import subprocess, sys\n'
          'tool, root, name = sys.argv[1:4]\n'
          'for i in range(10):\n'
          '    subprocess.run([sys.executable, tool, "--root", root, "add", "question", "--set",\n'
          '                    f"question=Writer {name} question {i}?"], check=True, stdout=subprocess.DEVNULL)\n')


class Lock(Workspace):
    def holder(self):
        proc = subprocess.Popen([sys.executable, '-c', HOLD, str(TOOLS), str(self.root)], stdout=subprocess.PIPE,
                                text=True, env=ENV)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), 'held')
        return proc

    def test_22_a_killed_holder_frees_the_lock_at_once(self):
        # Guards: 3.8 reclaimed a lock whose pid had ended; the system lock ends with the process itself.
        self.init()
        holder = self.holder()
        self.assertIn('another ws.py command is running (pid', self.ws('note', 'x', expect=2, env={'WS_LOCK_WAIT': '1'}).stderr)
        holder.kill()
        holder.wait()
        started = time.monotonic()
        self.ws('add', 'question', '--set', 'question=After the kill?', env={'WS_LOCK_WAIT': '2'})
        self.assertLess(time.monotonic() - started, 10)

    def test_22_an_empty_lock_file_from_a_crash_does_not_block(self):
        # A command killed between creating ws.lock and writing its pid left an empty file, which 3.8 waited out for
        # 60 seconds before removing it.
        self.init()
        self.write('.agents/cache/ws.lock', '')
        self.ws('add', 'question', '--set', 'question=After a crash?', env={'WS_LOCK_WAIT': '2'})

    def test_22_the_ready_check_does_not_count_its_own_lock(self):
        self.done()
        self.save()
        with core.lock(self.root):
            errors = validate.semantics(self.root, ready=True)
        self.assertEqual([e for e in errors if 'lock' in e or 'command is running' in e], [])

    def test_22_a_drive_that_cannot_lock_names_the_way_out(self):
        self.init()
        target = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with mock.patch(target, side_effect=OSError(errno.ENOLCK, 'No locks available')), \
                self.assertRaisesRegex(core.WorkspaceError, 'WS_LOCK=legacy'):
            with core.lock(self.root):
                pass

    def test_22_ws_lock_legacy_uses_the_older_lock_file(self):
        # Guards the way back for this version: the lock file of 3.8.
        self.init()
        with mock.patch.dict(os.environ, {'WS_LOCK': 'legacy'}), core.lock(self.root):
            self.assertTrue((self.root / '.agents/cache/ws.lock').is_file())
        self.assertFalse((self.root / '.agents/cache/ws.lock').exists())

    def test_22_eight_writers_get_unique_ids_and_lose_no_row(self):
        self.init(requirement=False)
        tool = str(self.root / '.agents/tools/ws.py')
        workers = [subprocess.Popen([sys.executable, '-c', WRITER, tool, str(self.root), str(n)], stderr=subprocess.PIPE,
                                    env={**ENV, 'WS_LOCK_WAIT': '300'}, text=True, encoding='utf-8') for n in range(8)]
        outcomes = [(worker.communicate()[1][-400:], worker.returncode) for worker in workers]
        self.assertEqual([code for _, code in outcomes], [0] * 8, outcomes)
        rows = tables.rows(self.root, TABLES['questions'])
        self.assertEqual(sorted(r['Question'] for r in rows),
                         sorted(f'Writer {n} question {i}?' for n in range(8) for i in range(10)))
        self.assertEqual(len({r['ID'] for r in rows}), 80)


if __name__ == '__main__':
    unittest.main()
