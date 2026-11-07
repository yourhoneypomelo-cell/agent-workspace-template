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
from wslib import core, locks, tables, validate
from wslib.schema import TABLES

HOLD = ('import sys, time\nsys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\nfrom wslib import locks\n'
        'with locks.lock(Path(sys.argv[2])):\n    print("held", flush=True)\n    time.sleep(60)\n')
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
        with locks.lock(self.root):
            errors = validate.semantics(self.root, ready=True)
        self.assertEqual([e for e in errors if 'lock' in e or 'command is running' in e], [])

    def test_22_a_drive_that_cannot_lock_names_the_way_out(self):
        self.init()
        target = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with mock.patch(target, side_effect=OSError(errno.ENOLCK, 'No locks available')), \
                self.assertRaisesRegex(core.WorkspaceError, 'WS_LOCK=legacy'):
            with locks.lock(self.root):
                pass

    def test_22_ws_lock_legacy_uses_the_older_lock_file(self):
        # Guards the way back for this version: the lock file of 3.8.
        self.init()
        with mock.patch.dict(os.environ, {'WS_LOCK': 'legacy'}), locks.lock(self.root):
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


def window(name):
    """A host session named by WS_SESSION_ID; every other session variable is cleared."""
    return {**{n: '' for n in core.SESSION_VARS}, 'WS_SESSION_ID': name}


class Permits(Workspace):
    """Window a is the main session and holds T1 (a/); window b holds T2 (b/), which builds on R2. Each cell runs
    one write command as one identity and checks whether it is allowed, by exit code and message."""

    CELLS = (
        # (actor, command, exit code, part of the message)
        ('b', ('add', 'question', '--set', 'question=From b?'), 0, ''),
        ('a', ('add', 'question', '--set', 'question=From a?'), 0, ''),
        ('b', ('idea', 'An idea from b'), 0, ''),
        ('b', ('set', 'T2', '--set', 'action=Work on b/ more'), 0, ''),
        ('b', ('set', 'T1', '--set', 'action=Take over a/'), 2, 'belongs to'),
        ('a', ('set', 'T2', '--set', 'action=Take over b/'), 2, 'belongs to'),
        ('a', ('set', 'R2', '--set', 'status=removed', '--set', 'reason=x'), 2, 'must not retire R2'),
        ('b', ('card', '--set', 'risks=from b'), 2, 'card belongs to the main session'),
        ('a', ('card', '--set', 'risks=from a'), 0, ''),
        ('a', ('goal', 'Another goal'), 2, 'changes the whole workspace'),
        ('a', ('compact',), 2, 'changes the whole workspace'),
        ('a', ('snapshot', '--label', 'before-split'), 2, 'changes the whole workspace'),
        ('b', ('note', 'b is halfway'), 0, ''),
        ('b', ('verify', 'T1', '--', 'python', '-m', 'unittest'), 2, 'belongs to'),
        ('b', ('checkpoint', '--keep', '--stop', 'b saved', '--next', 'b goes on'), 0, ''),
        ('c', ('add', 'question', '--set', 'question=From c?'), 2, ''),
        ('worker', ('add', 'question', '--set', 'question=From a worker?'), 2, 'WS_ROLE'),
    )

    def setUp(self):
        super().setUp()
        self.env = {'a': window('win-a'), 'b': window('win-b'), 'c': window('win-c'),
                    'worker': {**window('win-a'), 'WS_ROLE': 'worker'}}
        self.write('a/one.py', 'ONE = 1\n')
        self.write('b/two.py', 'TWO = 2\n')
        a = self.env['a']
        self.ws('init', '--goal', 'Demo', env=a)
        for text in ('first', 'second'):
            self.ws('add', 'requirement', '--set', f'requirement={text}', '--set', 'acceptance=listed', env=a)
        for requirement, scope in (('R1', 'a/'), ('R2', 'b/')):
            self.ws('add', 'task', '--set', f'requirements={requirement}', '--set', f'scope={scope}', '--set',
                    f'action=Work on {scope}', '--set', 'acceptance=python -m unittest', env=a)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                '--set', 'next_acceptance=a', env=a)
        self.ws('start', '--task', 'T1', env=a)
        self.ws('start', '--task', 'T2', env=self.env['b'])

    def test_23_p8_a_parallel_session_touches_only_tasks_in_its_claim(self):
        # T3 was claimed by nobody: b verified it, its release did not include it, and a's checkpoint stuck on it.
        self.ws('add', 'task', '--set', 'requirements=R2', '--set', 'scope=b/', '--set', 'action=More b',
                '--set', 'acceptance=python -m unittest', env=self.env['b'])
        refused = self.ws('set', 'T3', '--set', 'action=Even more b', env=self.env['b'], expect=2).stderr
        self.assertIn('T3 is not in the claim of this session', refused)
        self.assertIn('ws start --task T3', refused)
        self.ws('start', '--task', 'T3', env=self.env['b'])
        self.ws('set', 'T3', '--set', 'action=Even more b', env=self.env['b'])

    def test_23_p8_a_dropped_task_leaves_the_card(self):
        # b could not drop T2 while the card named it: the status was refused, and so was the card.
        self.ws('card', '--set', 'current_task=T1, T2', env=self.env['a'])
        self.ws('set', 'T2', '--set', 'status=dropped', '--set', 'reason=user changed plans', env=self.env['b'])
        self.assertIn('| current_task | T1 |', self.read('docs/state/HANDOFF.md'))

    def test_23_p7_verify_ignores_edits_inside_another_sessions_claim(self):
        self.write('a/test_one.py', 'import unittest\nfrom pathlib import Path\n\n\nclass One(unittest.TestCase):\n'
                   '    def test_one(self):\n        Path("b/two.py").write_text("TWO = 3\\n")  # b edits its own file\n'
                   '        self.assertTrue(True)\n')
        self.ws('set', 'T1', '--set', 'acceptance=python -m unittest a.test_one', env=self.env['a'])
        self.write('a/__init__.py', '')
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'a.test_one', env=self.env['a'])

    def test_23_p6_a_session_key_tells_two_conversations_in_one_window_apart(self):
        # No session variable: both conversations run in this test's process tree, so only the brief keys differ.
        bare = {n: '' for n in core.SESSION_VARS}
        self.ws('checkpoint', '--keep', '--stop', 'b saved', '--next', 'b goes on', env=self.env['b'])
        self.ws('checkpoint', '--stop', 'a done', '--next', 'n', env=self.env['a'])
        self.ws('checkpoint', '--stop', 'b done', '--next', 'n', env=self.env['b'])
        self.ws('start', '--task', 'T1', '--session', 'k-aaaa', env=bare)
        self.ws('start', '--task', 'T2', '--session', 'k-bbbb', env=bare)
        self.ws('set', 'T2', '--set', 'action=Work on b/ again', '--session', 'k-bbbb', env=bare)
        refused = self.ws('set', 'T1', '--set', 'action=x', '--session', 'k-bbbb', env=bare, expect=2).stderr
        self.assertIn('belongs to', refused)

    def test_23_each_identity_may_run_what_the_table_says(self):
        for actor, command, code, part in self.CELLS:
            with self.subTest(actor=actor, command=' '.join(command[:2])):
                done = self.ws(*command, env=self.env[actor], expect=None)
                self.assertEqual(done.returncode, code, done.stdout[-300:] + done.stderr[-300:])
                self.assertIn(part, done.stderr)


if __name__ == '__main__':
    unittest.main()
