"""Regression tests for the 3.6.7 fixes. Each one fails on 3.6.6 unless its comment says it guards a fix."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from support import ENV, TEMPLATE, TOOLS, Workspace
from wslib import core, evidence, logs, rows, schema, tables
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


def busy_once(real):
    """A file call that fails once, as on Windows while another process has the file open."""
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise PermissionError(13, 'The process cannot access the file because it is being used by another process')
        return real(*args, **kwargs)
    return call


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

    def test_a_stale_lock_that_a_reader_holds_open_is_retried(self):
        path = self.root / '.agents/cache/ws.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'pid': 999999999, 'created_at': 'x', 'nonce': 'gone'}), encoding='utf-8')
        with mock.patch.object(Path, 'unlink', busy_once(Path.unlink)), core.lock(self.root):
            pass
        self.assertFalse(path.exists())

    def test_release_is_retried_while_a_reader_holds_the_lock(self):
        with mock.patch.object(Path, 'unlink', busy_once(Path.unlink)), core.lock(self.root):
            pass
        self.assertFalse((self.root / '.agents/cache/ws.lock').exists())

    def test_a_lock_create_refused_during_a_delete_is_retried(self):
        with mock.patch.object(core.os, 'open', busy_once(os.open)), core.lock(self.root):
            pass


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


class Hooks(Workspace):
    def test_h3_every_host_settings_file_is_in_hook_files(self):
        import ws
        self.assertEqual({h: ws.hook_settings(h)[0] for h in ws.HOSTS}, schema.HOOK_FILES)
        self.assertEqual(core.rewatch(self.root, {rel: '' for rel in schema.HOOK_FILES.values() if rel not in schema.ADAPTERS}), {})
        self.assertEqual([r for r in (*schema.ADAPTERS, *schema.SEARCH_IGNORE) if not r.startswith(schema.NON_SOURCE)], [])

    def test_h3_hooks_keep_ready_for_watched_hosts(self):
        import ws
        self.init()
        self.save()
        for host in (h for h in ws.HOSTS if h != 'gemini'):
            with self.subTest(host=host):
                self.ws('hooks', 'enable', host)
                self.ready()

    def test_n2_gemini_hooks_print_the_checkpoint_note(self):
        self.init()
        self.save()
        self.assertIn('until "ws checkpoint" saves it', self.ws('hooks', 'enable', 'gemini').stdout)
        self.ws('start')
        self.save()
        self.ready()
        settings = json.loads(self.read('.gemini/settings.json'))
        settings['hooks']['Notification'] = [{'hooks': [{'type': 'command', 'command': 'echo ' + 'x' * 3000}]}]
        self.write('.gemini/settings.json', json.dumps(settings))
        self.assertNotIn('short pointer', self.ws('check', expect=None).stdout)

    def test_rewatch_ignores_files_the_new_rules_exclude(self):
        self.init()
        self.save()
        recorded = {'src/a.py': '1', '.qwen/settings.json': '2', 'node_modules/x.js': '3', 'AGENTS.md': '4'}
        self.assertEqual(core.rewatch(self.root, recorded), {'src/a.py': '1', 'AGENTS.md': '4'})
        self.assertEqual(core.rewatch(self.root, {'.ignore': '5', 'src/a.py': '1'}, source_only=True), {'src/a.py': '1'})
        # A checkpoint from a version that still watched .qwen/ must not report its file as removed.
        state = core.state_of(self.root)
        rel = state['checkpoint']['manifest']
        manifest = json.loads(self.read(rel))
        manifest['files']['.qwen/settings.json'] = 'x'
        raw = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
        (self.root / rel).write_bytes(raw.encode('utf-8'))
        state['checkpoint']['sha256'] = core.sha(raw.encode('utf-8'))
        core.save_state(self.root, state)
        self.ready()


class Evidence(Workspace):
    PROBE = ('add', 'task', '--set', 'requirements=R1', '--set', 'scope=probe.py', '--set', 'action=Probe')

    def test_v3_invalid_expect_regex_is_a_clean_error(self):
        self.init()
        refused = self.ws(*self.PROBE, '--set', 'acceptance=check: python probe.py expect /[unclosed/', expect=2).stderr
        self.assertIn('invalid expect pattern', refused)
        self.ws(*self.PROBE, '--set', 'acceptance=check: python probe.py expect "OK"')
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace('expect "OK"', 'expect /[unclosed/'))
        self.write('probe.py', 'print("OK")\n')
        failed = self.ws('verify', 'T1', '--', 'python', 'probe.py', expect=2).stderr
        self.assertIn('invalid expect pattern', failed)
        self.assertNotIn('Traceback', failed)

    def test_v3_backticked_check_is_a_check(self):
        self.init()
        self.write('probe.py', 'print("OK")\n')
        self.ws(*self.PROBE, '--set', 'acceptance=`check: python probe.py expect "OK"`')
        out = self.ws('verify', 'T1', '--done', '--', 'python', 'probe.py').stdout
        self.assertTrue(json.loads(out.splitlines()[0])['marked_done'])

    def test_n8_old_test_evidence_satisfies_a_check_acceptance(self):
        self.done()
        tested = tables.rows(self.root, TABLES['tasks'])[0]['Evidence']
        self.assertEqual(evidence.load(self.root, tested, 'check')['kind'], 'test')
        self.write('probe.py', 'print("OK")\n')
        self.ws(*self.PROBE, '--set', 'acceptance=check: python probe.py expect "OK"')
        self.ws('verify', 'T2', '--', 'python', 'probe.py')
        checked = tables.rows(self.root, TABLES['tasks'])[1]['Evidence']
        with self.assertRaises(core.WorkspaceError):
            evidence.load(self.root, checked, 'test')

    def test_v4_py_launcher_version_switch_is_kept(self):
        run, recorded = evidence._resolve(['py', '-3', '-c', 'print(1)'])
        self.assertNotEqual(run[0], sys.executable)
        self.assertEqual(recorded, ['py', '-3', '-c', 'print(1)'])


class Misc(Workspace):
    def test_u5_brief_with_a_transcript_writes_no_cache(self):
        self.init()
        self.save()
        payload = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'please add export'}})
        transcript = self.parent / 'session.jsonl'
        transcript.write_text(payload + '\n', encoding='utf-8')
        self.ws('capture', '--host', 'claude', '--event', 'Stop', stdin=json.dumps({'session_id': 'abc', 'transcript_path': str(transcript)}))
        cache = self.root / '.agents/cache/messages.json'
        cache.unlink(missing_ok=True)
        self.ws('brief')
        self.ws('check', expect=None)
        self.assertFalse(cache.exists())

    def test_u7_dropped_dependency_has_one_meaning(self):
        self.init()
        for action, depends in (('First step', 'none'), ('Second step', 'T1')):
            self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=demo.py', '--set', f'action={action}',
                    '--set', 'acceptance=python -m unittest', '--set', f'depends={depends}')
        self.ws('set', 'T1', '--set', 'status=dropped', '--set', 'reason=user dropped it')
        brief = self.ws('brief').stdout
        self.assertNotIn('ready next: T2', brief)
        self.assertIn('ws set T2 --set depends=none', brief)

    def test_u7_cycle_names_only_members(self):
        from wslib import validate
        rows = {'T1': {'Depends': 'T2'}, 'T2': {'Depends': 'T1'}, 'T3': {'Depends': 'T1'}, 'T4': {'Depends': 'T4'}}
        self.assertEqual(validate._cycle(rows), ['TASKS.md: dependency cycle among T1, T2, T4'])

    def test_u7_snapshot_restores_to_a_checkable_workspace(self):
        self.done()
        self.save()
        self.ws('start')
        snapshot = json.loads(self.ws('snapshot', '--label', 'before-change', 'test_demo.py').stdout.splitlines()[0])['snapshot']
        other = self.parent / 'restored'
        from wslib import distribution
        distribution.install(TEMPLATE, other, allow_modified=True)
        import zipfile
        with zipfile.ZipFile(self.root / snapshot) as bundle:
            bundle.extractall(other)
        (other / 'SNAPSHOT.json').unlink()
        run = subprocess.run([sys.executable, str(other / '.agents/tools/ws.py'), '--root', str(other), 'check'], env=ENV,
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_u2_first_checkpoint_has_no_lint_warning(self):
        # Guards the order in checkpoint: the card is written before the state files are linted.
        self.init()
        out = self.ws('checkpoint', '--stop', 'requirements recorded', '--next', 'plan the first task', '--set', 'phase=plan',
                      '--set', 'risks=none known yet', '--set', 'next_acceptance=T1 has an acceptance command').stdout
        self.assertNotIn('findings in the state files changed this session', out)

    def test_u63_turn_reminder_follows_the_credential_rule(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"credentials": "ask"', '"credentials": "plain"')
        self.write('docs/state/ARCHITECTURE.md', text)
        out = json.loads(self.ws('turn', '--hook', 'claude', stdin=json.dumps({'prompt': 'go on'})).stdout)
        context = out['hookSpecificOutput']['additionalContext']
        self.assertNotIn('never repeated or written to a file', context)
        self.assertIn('kept as written', context)

    def test_h4_codex_session_end_has_a_timeout(self):
        import ws
        self.assertEqual(ws.hook_settings('codex')[1]['hooks']['SessionEnd'][0]['hooks'][0]['timeout'], 3)

    def test_hand_edits_use_the_local_date(self):
        # A "ws set" in the evening west of Greenwich is logged on the local date, while UTC is already a day later.
        self.init()
        logs.append(self.root, 'CHANGE_LOG', {'Date': '2026-11-06', 'ID': 'T1', 'Event': 'acceptance edited',
                                              'Detail': 'was: old', 'Source': 'assistant'})
        code = ('import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from wslib import coverage; '
                'cp = {"created_at": "2026-11-07T03:00:00+00:00", "task_texts": {"T1": {"Acceptance": "old"}}}; '
                'print(json.dumps(coverage.hand_edits(Path(sys.argv[2]), {"tasks": [{"ID": "T1", "Acceptance": "new"}]}, cp)))')
        run = subprocess.run([sys.executable, '-c', code, str(TOOLS), str(self.root)], env={**ENV, 'TZ': 'XXX12'},
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.stdout.strip(), '[]', run.stderr[-600:])

    def test_linked_agents_folder_is_refused(self):
        other = self.parent / 'other'
        other.mkdir()
        link = other / '.agents'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(self.root / '.agents'), str(link))
        else:
            os.symlink(self.root / '.agents', link)
        self.addCleanup(os.rmdir if os.name == 'nt' else os.unlink, link)
        run = subprocess.run([sys.executable, str(link / 'tools/ws.py'), 'status'], cwd=other, env=ENV,
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('is a link', run.stderr)

    def test_move_detail_into_a_new_spec_folder(self):
        self.init()
        self.ws('set', 'R1', '--set', 'requirement=Demo returns 4; the spec holds the rest', '--set',
                'detail=docs/specs/demo/requirements.md', '--move-detail', 'docs/specs/demo/requirements.md')
        for name in ('requirements', 'design', 'tasks'):
            self.assertTrue((self.root / f'docs/specs/demo/{name}.md').is_file(), name)

    def test_dsh_helper_stops_at_the_size_limit(self):
        from wslib import dsh
        stub = self.parent / 'stub' / 'compression'
        stub.mkdir(parents=True)
        (stub / '__init__.py').write_text('', encoding='utf-8')
        (stub / 'zstd.py').write_text('class ZstdDecompressor:\n    eof, needs_input, unused_data = False, False, b""\n\n'
                                      '    def decompress(self, data, max_length=-1):\n        return b"x" * max_length\n',
                                      encoding='utf-8')
        run = subprocess.run([sys.executable, '-c', dsh.HELPER, str(4 << 20)], input=b'frame', capture_output=True,
                             env={**ENV, 'PYTHONPATH': str(stub.parent)})
        self.assertEqual(run.returncode, 3, run.stderr[-600:])
        self.assertLessEqual(len(run.stdout), 4 << 20)


class Capture(Workspace):
    def transcripts(self, *texts):
        paths = []
        for n, text in enumerate(texts):
            path = self.parent / f'session-{n}.jsonl'
            path.write_text(json.dumps({'cwd': text}) + '\n', encoding='utf-8')
            paths.append(path)
        return paths

    def test_c4_mentions_boundary_and_drive_case(self):
        from wslib import capture
        root = str(self.root.resolve())
        exact, longer, lower = self.transcripts(root + os.sep + 'src', root + '2' + os.sep + 'src', root[0].swapcase() + root[1:])
        self.assertEqual(capture._mentions(self.root, [exact, longer]), [exact])
        if os.name == 'nt':
            self.assertEqual(capture._mentions(self.root, [lower]), [lower])

    def test_c4_scan_cache_from_older_rules_is_recomputed(self):
        from wslib import capture
        (other,) = self.transcripts(str(self.parent / 'elsewhere'))
        info = other.stat()
        cache = self.root / capture.SCAN_CACHE
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({str(other): [f'{info.st_size}:{info.st_mtime_ns}', True]}), encoding='utf-8')
        self.assertEqual(capture._mentions(self.root, [other]), [])


class Entry(Workspace):
    def test_is_ours_recognizes_quoted_absolute_and_variable_commands(self):
        import ws
        for command in ('"C:\\Python311\\python.exe" "E:\\proj\\.agents\\tools\\ws.py" turn --hook claude',
                        'python "$CLAUDE_PROJECT_DIR/.agents/tools/ws.py" brief --hook claude',
                        'py -3 %CLAUDE_PROJECT_DIR%\\.agents\\tools\\ws.py capture --host claude --event Stop',
                        'python tools/ws.py brief --hook antigravity'):
            with self.subTest(command=command):
                self.assertTrue(ws._is_ours({'hooks': [{'type': 'command', 'command': command}]}))
        self.assertTrue(ws._is_ours({'action': {'type': 'command', 'command': 'python3 .agents/tools/ws.py turn --hook kiro'}}))
        self.assertFalse(ws._is_ours({'hooks': [{'type': 'command', 'command': 'python lint/ws.py brief'}]}))
        self.assertFalse(ws._is_ours({'hooks': [{'type': 'command', 'command': 'echo hello'}],
                                      'note': 'python .agents/tools/ws.py turn'}))

    def test_x1_hook_command_uses_an_interpreter_that_exists(self):
        import shutil
        import ws
        self.ws('hooks', 'enable', 'claude', '--python', 'py -3')
        commands = ws._commands(json.loads(self.read('.claude/settings.json')))
        self.assertTrue(commands and all(c.startswith('py -3 .agents/tools/ws.py ') for c in commands), commands)
        self.assertTrue(shutil.which(ws.interpreter().split()[0]))

    def test_x1_python_version_message(self):
        tool = str(self.root / '.agents/tools/ws.py')
        code = ('import runpy, sys; sys.version_info = (3, 9, 6, "final", 0); sys.argv = sys.argv[1:]; '
                'runpy.run_path(sys.argv[0], run_name="__main__")')

        def run(*args):
            return subprocess.run([sys.executable, '-c', code, tool, *args], env=ENV, capture_output=True, text=True,
                                  encoding='utf-8')
        plain = run('status')
        self.assertEqual(plain.returncode, 2, plain.stdout + plain.stderr)
        self.assertIn('needs Python 3.10 or newer', plain.stderr)
        self.assertIn('macOS', plain.stderr)
        self.assertEqual(run('turn', '--hook', 'cursor').returncode, 0)


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
