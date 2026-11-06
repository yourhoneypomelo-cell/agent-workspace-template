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


def host(**names):
    """Environment of a command run by a host session: only the given session variables are set."""
    return {**{n: '' for n in core.SESSION_VARS}, **names}


def window(name):
    """Environment of a command run by host conversation `name`."""
    return host(WS_SESSION_ID=name)


def turn_context(test, conversation):
    """What the Cursor per-turn hook adds for a prompt of this conversation. Hooks get no session variable."""
    payload = json.dumps({'conversation_id': conversation, 'prompt': 'go on'})
    return json.loads(test.ws('turn', '--hook', 'cursor', stdin=payload, env=host()).stdout)['additional_context']


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

    def setUp(self):
        super().setUp()
        self.a, self.b = window('win-a'), window('win-b')
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


class ClaimedTurnHook(Pair):
    def test_turn_hook_spares_a_conversation_with_a_parallel_claim(self):
        self.assertNotIn('took over', turn_context(self, 'win-b'))
        self.assertIn('took over this workspace in another conversation', turn_context(self, 'win-c'))


PASSING = 'import unittest\n\n\nclass Two(unittest.TestCase):\n    def test_two(self):\n        self.assertTrue(True)\n'


class Parallel(Pair):
    def leave(self, env, *flags):
        return self.ws('checkpoint', '--stop', 'stopped at the parser', '--next', 'finish the parser', *flags, env=env)

    def test_p2_last_leaver_with_global_errors_releases_without_seal(self):
        self.leave(self.a)
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace('| T1 | todo | R1 |', '| T1 | todo | R9 |'))
        sealed = core.state_of(self.root)['checkpoint']
        out = self.leave(self.b).stdout
        self.assertEqual(core.state_of(self.root)['checkpoint'], sealed)
        self.assertIn('released without a seal', out)
        self.assertIn('T1 names unknown requirement R9', out)

    def test_n1_primary_checkpoint_keeps_parallel_tasks_unsealed(self):
        self.write('test_two.py', PASSING)
        self.ws('verify', 'T2', '--done', '--', 'python', '-m', 'unittest', env=self.b)
        self.write('b/two.py', 'TWO = 3\n')
        self.leave(self.a)
        self.assertIn('T2: files in its scope changed after', self.ws('check', expect=None).stdout)

    def test_p3_takeover_keeps_released_parallel_rows(self):
        self.leave(self.b)
        self.ws('start', '--force', '--reason', 'user: window a is closed', env=window('win-c'))
        self.assertIn('stopped at the parser', self.read('docs/state/HANDOFF.md'))

    def test_p4_parallel_session_reconciles_after_primary_released(self):
        self.leave(self.a)
        self.ws('reconcile', 'all', '--reason', 'chat: greeting', env=self.b)

    def test_p4_parallel_session_cannot_snapshot(self):
        refused = self.ws('snapshot', '--label', 'before-change', env=self.b, expect=2).stderr
        self.assertIn('ws snapshot changes the whole workspace', refused)
        self.leave(self.a)
        self.ws('snapshot', '--label', 'before-change', env=self.b)

    def test_p5_repeated_start_task_checks_clashes(self):
        self.assertIn('collides with work in progress', self.ws('start', '--task', 'T2', env=self.a, expect=2).stderr)
        self.assertIn('collides with work in progress', self.ws('start', '--task', 'T1', env=self.b, expect=2).stderr)

    def test_p5_resumed_start_drops_done_tasks_without_refusing(self):
        self.ws('set', 'T1', '--set', 'status=dropped', '--set', 'reason=user dropped it', env=self.a)
        out = self.ws('start', '--task', 'T1', env=self.a).stdout
        self.assertTrue(json.loads(out.splitlines()[0]).get('resumed'))
        self.assertIn('T1 is dropped', out)

    def test_parallel_checkpoint_logs_hand_edits(self):
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace('Work on b/', 'Work on b/ by hand'))
        self.leave(self.b, '--keep')
        self.assertIn('| T2 | action edited outside ws |', self.read('docs/logs/CHANGE_LOG.md'))
        self.leave(self.a)
        self.assertEqual(self.read('docs/logs/CHANGE_LOG.md').count('| T2 | action edited outside ws |'), 1)

    def test_parallel_claim_cannot_be_impersonated_with_writer_flag(self):
        label = next(iter(core.state_of(self.root)['claims']))
        refused = self.ws('set', 'T2', '--set', 'status=dropped', '--set', 'reason=x', '--writer', label, env=self.a,
                          expect=2).stderr
        self.assertIn(f'{label} is the claim of another session', refused)
        self.ws('add', 'question', '--set', 'question=Which port?', '--writer', label, env=self.b)


class RetireMatching(unittest.TestCase):
    def test_r1_does_not_match_r10(self):
        tasks = {'T1': {'Requirements': 'R10'}, 'T2': {'Requirements': 'R1, R3'}}
        self.assertEqual(rows.builders('requirements', 'R1', {}, tasks), ['T2'])
        self.assertEqual(rows.builders('features', 'F1', {'F1': {'Tasks': 'T12, T2'}}, tasks), ['T12', 'T2'])


class Resume(Workspace):
    """Window a planned T1 for R1 and released the workspace with a checkpoint. Its next write takes it back."""

    def setUp(self):
        super().setUp()
        self.a = window('win-a')
        self.ws('init', '--goal', 'Build a small tested demo', env=self.a)
        self.ws('add', 'requirement', '--set', 'requirement=Demo returns 4', '--set',
                'acceptance=python -m unittest test_demo', env=self.a)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Implement demo',
                '--set', 'acceptance=python -m unittest test_demo', env=self.a)
        self.passing_test()
        self.release()

    def release(self, *flags):
        self.ws('checkpoint', '--stop', 'planned', '--next', 'verify T1', '--set', 'phase=build', '--set', 'risks=demo only',
                '--set', 'next_acceptance=T1 passes', *flags, env=self.a)

    def resumes(self):
        return self.read('docs/logs/MAINTENANCE_LOG.md').count('| resume |')

    def test_l5_verify_done_after_release_attaches(self):
        result = self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo', env=self.a, expect=None)
        self.assertTrue(json.loads(result.stdout.splitlines()[0])['marked_done'], result.stdout)
        self.assertEqual(self.resumes(), 1)
        self.release()
        self.ready()

    def test_l5_one_resume_row(self):
        self.release('--keep')
        self.assertEqual(self.resumes(), 1)

    def test_l5_note_reconcile_snapshot_resume(self):
        self.ws('note', 'T1 under way', env=self.a)
        self.release()
        self.ws('snapshot', '--label', 'before-change', env=self.a)
        self.release()
        self.ws('reconcile', 'all', '--reason', 'chat: greeting', env=self.a)
        self.assertEqual(self.resumes(), 3)

    def test_missing_checkpoint_manifest_does_not_disable_guarded(self):
        self.ws('start', env=self.a)
        (self.root / core.state_of(self.root)['checkpoint']['manifest']).unlink()
        refused = self.ws('set', 'T1', '--set', 'requirements=R99', env=self.a, expect=2).stderr
        self.assertIn('unknown requirement R99', refused)

    def test_l5_first_write_after_release_is_validated(self):
        # Guards the resume: the claim it saves must leave a state line that validates, or every write would pass.
        refused = self.ws('set', 'T1', '--set', 'requirements=R99', env=self.a, expect=2).stderr
        self.assertIn('unknown requirement R99', refused)

    def test_l5_rev_matches_the_revision_before_resume(self):
        # Guards the resume: it takes a revision of its own, yet --rev names the revision the session read.
        text = self.read('docs/state/ARCHITECTURE.md').replace('"ownership": "solo"', '"ownership": "shared"')
        self.write('docs/state/ARCHITECTURE.md', text)
        state = core.state_of(self.root)
        writer = state['released']['writer']
        self.ws('add', 'question', '--set', 'question=Which port?', '--writer', writer, '--rev', str(state['revision']),
                env=self.a)
        self.release('--writer', writer, '--rev', str(core.state_of(self.root)['revision']))
        self.release('--keep', '--writer', writer, '--rev', str(core.state_of(self.root)['revision']))


class Identity(Workspace):
    def test_l3_cursor_conversation_resumes_and_another_is_refused(self):
        a, b = host(CURSOR_CONVERSATION_ID='conv-a'), host(CURSOR_CONVERSATION_ID='conv-b')
        self.ws('init', '--goal', 'Demo', env=a)
        self.assertTrue(json.loads(self.ws('start', env=a).stdout.splitlines()[0]).get('resumed'))
        self.assertIn('collides with work in progress', self.ws('start', env=b, expect=2).stderr)

    def test_cursor_subagent_conversation_cannot_write(self):
        parent, subagent = host(CURSOR_CONVERSATION_ID='conv-parent'), host(CURSOR_CONVERSATION_ID='conv-subagent')
        self.ws('init', '--goal', 'Demo', env=parent)
        refused = self.ws('add', 'question', '--set', 'question=from the subagent', env=subagent, expect=2).stderr
        self.assertIn('A subagent reports its result to the conversation that started it', refused)
        self.ws('add', 'question', '--set', 'question=from the parent', env=parent)

    def test_l3_refusal_names_the_same_window_case(self):
        self.init()
        refused = self.ws('start', expect=2).stderr
        self.assertIn('This window already holds the workspace', refused)
        self.assertIn('go on without a new start', refused)

    def test_cursor_turn_hook_names_another_conversation(self):
        self.ws('init', '--goal', 'Demo', env=host(CURSOR_CONVERSATION_ID='conv-a'))
        self.assertIn('took over this workspace in another conversation', turn_context(self, 'conv-b'))
        self.assertNotIn('took over', turn_context(self, 'conv-a'))

    def test_a_host_started_from_a_cursor_shell_is_the_session(self):
        inner = host(CURSOR_CONVERSATION_ID='conv-a', CLAUDE_CODE_SESSION_ID='claude-a')
        self.ws('init', '--goal', 'Demo', env=inner)
        self.ws('add', 'question', '--set', 'question=from the inner host', env=host(CLAUDE_CODE_SESSION_ID='claude-a'))
        self.ws('add', 'question', '--set', 'question=from the outer chat', env=host(CURSOR_CONVERSATION_ID='conv-a'),
                expect=2)


class Guarded(Workspace):
    def test_invalid_state_line_refuses_every_write(self):
        self.init()
        state = core.state_of(self.root)
        state['writer_revision'] = state['revision'] + 5
        core.save_state(self.root, state)
        refused = self.ws('add', 'question', '--set', 'question=Which port?', expect=2).stderr
        self.assertIn('invalid writer_revision', refused)
        self.assertNotIn('Which port?', self.read('docs/state/REQUIREMENTS.md'))

    def test_check_that_stops_early_refuses_every_write(self):
        self.init()
        rel, rule = 'docs/state/PREFERENCES.md', '| --- | --- | --- | --- | --- |'
        self.write(rel, self.read(rel).replace(rule, rule + '\n| P1 | active |'))
        refused = self.ws('add', 'question', '--set', 'question=Which port?', expect=2).stderr
        self.assertIn('row has 2 cells', refused)
        self.assertNotIn('Which port?', self.read('docs/state/REQUIREMENTS.md'))


if __name__ == '__main__':
    unittest.main()
