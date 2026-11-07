"""End-to-end behavior through the command line, one process per command."""
import json
import subprocess
import sys

from support import ENV, Workspace
from wslib import core, logs, tables
from wslib.schema import CLOSED, TABLES


class Lifecycle(Workspace):
    def test_goal_without_requirements_is_never_ready(self):
        self.init(requirement=False)
        self.assertIn('## Attention', self.ws('brief').stdout)
        out = self.save().stdout
        self.assertIn('NOT READY', out)
        self.assertIn('no requirement rows', out)
        self.assertIn('added no requirement', out)
        self.assertIn('no requirement rows', self.ready(expect=1).stdout)
        self.ws('start')
        self.ws('add', 'question', '--set', 'question=What should the first version do?')
        self.save()
        self.ready()
        self.ws('start')
        self.ws('add', 'requirement', '--set', 'requirement=Gateway checks the API key', '--set', 'acceptance=pytest -k key')
        out = self.save().stdout
        self.assertIn('added 1 requirements', out)
        self.assertIn('READY. State is saved', out)
        self.ready()

    def test_code_change_without_task_is_flagged(self):
        self.init()
        self.save()
        self.ws('start')
        self.write('src/gateway.py', 'print("gateway")\n')
        self.write('docs/guides/NOTES.md', '# Notes\n')
        out = self.save(keep=True).stdout
        self.assertIn('src/gateway.py', out)
        self.assertNotIn('NOTES.md, ', out)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=src/gateway.py', '--set', 'action=Gateway',
                '--set', 'acceptance=python -m unittest')
        self.write('src/gateway.py', 'print("gateway v2")\n')
        self.assertNotIn('no requirement or task row changed', self.save(keep=True).stdout)

    def test_note_and_interrupted_session_report(self):
        self.init()
        self.save()
        self.ws('start')
        self.ws('note', 'halfway', 'through', 'auth')
        self.assertIn('halfway through auth', self.ws('brief').stdout)
        out = self.ws('start', '--force', '--reason', 'user: the old window crashed').stdout
        self.assertIn('did not release the workspace', out)
        self.assertIn('its note: halfway through auth', out)
        self.assertNotIn('SESSION_LOG.md', out.split('its note')[1])

    def test_turn_reminder_formats(self):
        self.init()
        self.ws('add', 'question', '--set', 'question=Edge or Chrome?')
        text = self.ws('turn').stdout
        self.assertIn('are recorded with', text)
        self.assertIn('block work until the user answers: Q1', text)
        claude = json.loads(self.ws('turn', '--hook', 'claude', stdin='{"prompt": "hi"}').stdout)
        self.assertEqual(claude['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        gemini = json.loads(self.ws('turn', '--hook', 'gemini', stdin='{}').stdout)
        self.assertEqual(gemini['hookSpecificOutput']['hookEventName'], 'BeforeAgent')
        first = json.loads(self.ws('turn', '--hook', 'antigravity', stdin='{"invocationNum": 0}').stdout)
        self.assertIn('ephemeralMessage', first['injectSteps'][0])
        self.assertEqual(json.loads(self.ws('turn', '--hook', 'antigravity', stdin='{"invocationNum": 3}').stdout), {})
        self.assertIn('are recorded with', self.ws('turn', '--hook', 'kiro', stdin='not json').stdout)

    def test_autosave_on_stop_hook(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"ownership": "solo"', '"ownership": "solo", "autosave": true')
        self.write('docs/state/ARCHITECTURE.md', text)
        before = len(list((self.root / 'docs/archive/checkpoints').glob('*.json')))
        result = self.ws('capture', '--host', 'gemini', '--event', 'AfterAgent', stdin='{}')
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(list((self.root / 'docs/archive/checkpoints').glob('*.json'))), before + 1)
        self.assertTrue(core.state_of(self.root)['writer'])

    def test_autosave_never_waits_for_a_busy_lock(self):
        import time
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"ownership": "solo"', '"ownership": "solo", "autosave": true')
        self.write('docs/state/ARCHITECTURE.md', text)
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(holder.kill)
        self.write('.agents/cache/ws.lock', json.dumps({'pid': holder.pid}))
        start = time.time()
        result = self.ws('capture', '--host', 'claude', '--event', 'Stop', stdin='{}')
        self.assertLess(time.time() - start, 10)
        self.assertIn('autosave skipped', result.stderr)
        self.assertTrue((self.root / '.agents/cache/ws.lock').exists())

    def test_note_needs_an_owner(self):
        self.init()
        self.save()
        self.assertIn('Run "ws start" first', self.ws('note', 'x', expect=2).stderr)
        self.ready()

    def test_untracked_code_warning_survives_questions_and_checkpoints(self):
        self.init()
        self.save(keep=True)
        self.write('app.py', 'print(1)\n')
        self.ws('add', 'question', '--set', 'question=Which port?')
        self.assertIn('app.py', self.save(keep=True).stdout)
        self.assertIn('app.py', self.save(keep=True).stdout)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=app.py', '--set', 'action=App',
                '--set', 'acceptance=python -m unittest')
        self.assertNotIn('app.py', self.save(keep=True).stdout)

    def test_bootstrap_passes_structure_but_not_ready(self):
        self.ws('check', '--strict')
        result = self.ready(expect=1)
        self.assertIn('bootstrap', result.stdout)

    def test_session_that_dies_before_first_checkpoint_leaves_a_baseline(self):
        self.init()
        self.write('notes.py', 'print("half done")\n')
        brief = self.ws('brief').stdout
        self.assertIn('notes.py', brief)
        self.assertIn('notes.py', json.loads(self.ws('start', '--force', '--reason', 'user: crashed').stdout.splitlines()[0])['unsaved_changes']['added'])

    def test_init_once_then_checkpoint_is_ready(self):
        self.init()
        self.ws('init', '--goal', 'other', expect=2)
        self.assertEqual(core.goal(self.root), 'Build a small tested demo')
        self.ready(expect=1)
        out = self.save().stdout
        self.assertIn('READY', out)
        self.ready()

    def test_add_assigns_ids_and_writes_log(self):
        self.init(requirement=False)
        first = self.json('add', 'requirement', '--set', 'requirement=Export JSON', '--set', 'acceptance=pytest -k export',
                          '--source', 'user 2026-10-31')
        second = self.json('add', 'requirement', '--set', 'requirement=Import JSON', '--set', 'acceptance=pytest -k import')
        self.assertEqual((first['id'], second['id']), ('R1', 'R2'))
        rows = logs.live_rows(self.root, 'REQUIREMENT_LOG')
        self.assertEqual([(r['ID'], r['Event']) for r in rows[-2:]], [('R1', 'added'), ('R2', 'added')])
        self.assertEqual(rows[-2]['Source'], 'user 2026-10-31')

    def test_status_and_text_changes_are_logged(self):
        self.init(requirement=False)
        self.ws('add', 'requirement', '--set', 'requirement=CSV export', '--set', 'acceptance=pytest -k csv')
        self.ws('set', 'R1', '--set', 'requirement=CSV and TSV export')
        self.ws('set', 'R1', '--set', 'status=removed', expect=2)
        self.ws('set', 'R1', '--set', 'status=removed', '--set', 'reason=User dropped CSV')
        events = [(r['Event'], r['Detail']) for r in logs.live_rows(self.root, 'REQUIREMENT_LOG') if r['ID'] == 'R1']
        self.assertIn(('edited', 'was: CSV export'), events)
        self.assertIn(('active -> removed', 'User dropped CSV'), events)

    def test_invalid_reference_is_rejected_without_writing(self):
        self.init()
        before = self.read('docs/state/TASKS.md')
        result = self.ws('add', 'task', '--set', 'requirements=R9', '--set', 'scope=tree:', '--set', 'action=b',
                         '--set', 'acceptance=c', expect=2)
        self.assertIn('unknown requirement R9', result.stderr)
        self.assertEqual(self.read('docs/state/TASKS.md'), before)

    def test_question_lifecycle_shows_in_brief(self):
        self.init()
        self.ws('add', 'question', '--set', 'question=Integer or UUID ids?')
        self.assertIn('Q1: Integer or UUID ids?', self.ws('brief').stdout)
        self.ws('set', 'Q1', '--set', 'status=answered', '--set', 'answer=Integers')
        self.assertNotIn('Q1:', self.ws('brief').stdout)
        self.assertTrue(any(r['Detail'] == 'answer: Integers' for r in logs.live_rows(self.root, 'REQUIREMENT_LOG')))


class Verification(Workspace):
    def test_verify_done_marks_task_and_seals(self):
        self.done()
        row = tables.rows(self.root, TABLES['tasks'])[0]
        self.assertEqual(row['Status'], 'done')
        self.assertTrue(row['Evidence'].startswith('docs/archive/checks/'))
        self.ws('set', 'F1', '--set', 'status=shipped')
        self.save()
        self.ready()
        self.assertIn('1 passed', core.card(self.root)['last_verification'])

    def test_failed_zero_and_skipped_runs_are_rejected(self):
        self.planned()
        self.write('test_demo.py', 'import unittest\n\n\nclass Demo(unittest.TestCase):\n    def test_value(self):\n        self.fail("no")\n')
        result = self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo', expect=1)
        self.assertIn('REJECTED', result.stdout)
        self.write('empty.py', '')
        self.ws('verify', '--', 'python', '-m', 'unittest', 'empty', expect=1)
        self.write('test_skip.py', 'import unittest\n\n\n@unittest.skip("x")\nclass S(unittest.TestCase):\n    def test_a(self):\n        pass\n')
        self.ws('verify', '--', 'python', '-m', 'unittest', 'test_skip', expect=1)
        self.assertEqual(tables.rows(self.root, TABLES['tasks'])[0]['Status'], 'todo')

    def test_evidence_must_come_from_the_recorded_acceptance(self):
        self.planned()
        self.write('test_easy.py', 'import unittest\n\n\nclass E(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
        result = self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_easy', expect=2)
        self.assertIn('names the acceptance', result.stderr)
        self.assertNotIn('| done |', self.read('docs/state/TASKS.md'))
        self.ws('verify', 'T1', '--done', '--because', 'acceptance file renamed', '--', 'python', '-m', 'unittest', 'test_easy')
        self.assertIn('verify override', self.read('docs/logs/MAINTENANCE_LOG.md'))
        self.assertIn('acceptance file renamed', self.read('docs/logs/MAINTENANCE_LOG.md'))

    def test_acceptance_in_backticks_or_with_check_prefix_matches(self):
        self.init()
        self.passing_test()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=y',
                '--set', 'acceptance=`python -m unittest test_demo`')
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo')

    def test_command_that_writes_source_is_rejected_with_file_names(self):
        self.planned()
        code = 'from pathlib import Path; Path("generated.txt").write_text("x"); print("Ran 1 test in 0.1s"); print(); print("OK")'
        result = self.ws('verify', 'T1', '--because', 'probe', '--', 'python', '-c', code, expect=1)
        self.assertIn('generated.txt', result.stdout)

    def test_output_into_excluded_folder_is_allowed(self):
        self.planned()
        code = ('from pathlib import Path; Path("build").mkdir(exist_ok=True); Path("build/r.txt").write_text("x"); '
                'print("Ran 1 test in 0.1s"); print(); print("OK")')
        self.ws('verify', 'T1', '--because', 'probe', '--', 'python', '-c', code)

    def test_done_task_needs_current_session_evidence(self):
        self.planned()
        proof = self.json('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')['evidence']
        self.save()
        self.ws('start')
        text = self.read('docs/state/TASKS.md').replace('| T1 | todo |', '| T1 | done |').replace('| none | none | none |', f'| none | {proof} | none |')
        self.write('docs/state/TASKS.md', text)
        result = self.save(expect=2)
        self.assertIn('current session', result.stderr)

    def test_source_change_after_evidence_requires_reverify(self):
        self.planned()
        proof = self.json('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')['evidence']
        self.write('test_demo.py', self.read('test_demo.py') + '\n# edited\n')
        text = self.read('docs/state/TASKS.md').replace('| T1 | todo |', '| T1 | done |').replace('| none | none | none |', f'| none | {proof} | none |')
        self.write('docs/state/TASKS.md', text)
        self.assertIn('files in its scope changed after', self.save(expect=2).stderr)
        self.assertIn('test_demo.py', self.save(expect=2).stderr)

    def test_change_outside_the_task_scope_keeps_its_evidence(self):
        # Field data: deploy scripts and another window's probes kept voiding unrelated test evidence.
        self.done()
        self.write('ops/deploy.sh', 'echo deploy\n')
        self.write('services/other.py', '# another task\n')
        self.save()
        self.ready()

    def test_task_without_a_path_in_scope_watches_the_whole_tree(self):
        self.init()
        self.passing_test()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=y',
                '--set', 'acceptance=python -m unittest discover')
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'discover')
        self.write('extra.py', '# new source')
        self.assertIn('extra.py', self.save(expect=2).stderr)

    def test_check_that_ran_zero_tests_is_rejected(self):
        self.init()
        self.write('empty_check.py', 'print("Ran 0 tests in 0.000s")\n')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=y',
                '--set', 'acceptance=check: python empty_check.py')
        result = self.ws('verify', 'T1', '--done', '--', 'python', 'empty_check.py', expect=1)
        self.assertIn('zero tests', result.stdout)

    def test_scratch_and_database_files_never_void_a_run(self):
        self.planned()
        code = ('from pathlib import Path; Path("cache.db-wal").write_text("x"); Path(".tmp").mkdir(exist_ok=True); '
                'Path(".tmp/probe.sh").write_text("x"); print("Ran 1 test in 0.1s"); print(); print("OK")')
        self.ws('verify', 'T1', '--because', 'probe', '--', 'python', '-c', code)

    def test_editing_docs_does_not_make_evidence_stale(self):
        self.done()
        self.write('docs/specs/demo/requirements.md', '# Requirement detail: demo\n')
        self.ws('card', '--set', 'risks=none confirmed')
        self.save()
        self.ready()

    def test_tampered_evidence_is_detected(self):
        self.done()
        self.save()
        rel = tables.rows(self.root, TABLES['tasks'])[0]['Evidence']
        data = json.loads(self.read(rel))
        data['output'] += 'x'
        self.write(rel, json.dumps(data))
        self.ready(expect=1)

    def test_recorded_command_has_no_local_paths(self):
        self.planned()
        proof = self.json('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')['evidence']
        data = json.loads(self.read(proof))
        self.assertEqual(data['command'][0], 'python')
        self.assertNotIn(str(self.root), data['output'])

    def test_structured_json_report(self):
        self.planned()
        script = ("import os, json; open(os.environ['CONTINUITY_REPORT'], 'w').write(json.dumps("
                  "{'schema': 'test-summary.v1', 'total': 1, 'passed': 1, 'failed': 0, 'errors': 0, 'skipped': 0}))")
        self.ws('verify', 'T1', '--done', '--report', 'json', '--because', 'report test', '--', 'python', '-c', script)
        self.save()
        self.ready()


class Takeover(Workspace):
    def test_solo_takeover_after_abrupt_stop_lists_unsaved_files(self):
        self.init()
        self.save()
        old = self.json('start')['writer']
        self.write('src/half.py', 'def half():\n    pass\n')
        self.assertIn('src/half.py', self.ws('brief').stdout)
        refused = self.ws('start', expect=2).stderr
        self.assertIn('collides with work in progress', refused)
        data = json.loads(self.ws('start', '--force', '--reason', 'user: the old window crashed').stdout.splitlines()[0])
        self.assertEqual(data['took_over_from'], old)
        self.assertIn('src/half.py', data['unsaved_changes']['added'])
        self.assertIn('takeover', self.read('docs/logs/MAINTENANCE_LOG.md'))
        self.save()
        self.ready()

    def test_old_session_is_stopped_after_takeover(self):
        self.init()
        old = core.state_of(self.root)['writer']
        self.ws('start', '--force', '--reason', 'user: took over')
        result = self.ws('card', '--writer', old, '--set', 'risks=x', expect=2)
        self.assertIn('took over the workspace', result.stderr)

    def test_manual_edit_between_sessions(self):
        self.init()
        self.save()
        self.write('app.py', 'print("edited in the IDE")\n')
        self.ready(expect=1)
        self.ws('start')
        self.save()
        self.ready()

    def test_shared_mode_requires_writer_revision_and_force(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"ownership": "solo"', '"ownership": "shared"')
        self.write('docs/state/ARCHITECTURE.md', text)
        state = core.state_of(self.root)
        self.ws('card', '--set', 'risks=x', expect=2)
        self.ws('card', '--writer', state['writer'], '--rev', str(state['revision'] - 1), '--set', 'risks=x', expect=2)
        self.ws('card', '--writer', state['writer'], '--rev', str(state['revision']), '--set', 'risks=x')
        self.ws('start', expect=2)
        self.ws('start', '--force', '--reason', 'owner confirmed stopped')

    def test_parallel_writes_never_corrupt(self):
        self.init()
        self.save(keep=True)
        script = str(self.root / '.agents/tools/ws.py')
        jobs = [subprocess.Popen([sys.executable, script, '--root', str(self.root), 'add', 'question', '--set', f'question=q{n}'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV) for n in range(4)]
        for job in jobs:
            job.communicate(timeout=60)
        ids = [r['ID'] for r in tables.rows(self.root, TABLES['questions'])]
        self.assertEqual(sorted(ids), ['Q1', 'Q2', 'Q3', 'Q4'])
        self.save()
        self.ready()


class Growth(Workspace):
    def test_compact_moves_closed_rows_and_keeps_ids_reserved(self):
        self.done()
        self.ws('set', 'F1', '--set', 'status=removed', '--set', 'reason=No longer needed')
        self.ws('set', 'R1', '--set', 'status=deprecated', '--set', 'reason=Replaced by nothing')
        self.ws('card', '--set', 'current_task=none')
        self.save(keep=True)
        report = json.loads(self.ws('compact').stdout)
        self.assertEqual(sorted(report['moved_to_closed']), ['F1', 'R1', 'T1'])
        self.assertEqual(tables.rows(self.root, TABLES['tasks']), [])
        closed = {r['ID'] for r in tables.closed_rows(self.root)}
        self.assertEqual(closed, {'R1', 'T1', 'F1'})
        new = self.json('add', 'requirement', '--set', 'requirement=New', '--set', 'acceptance=x')
        self.assertEqual(new['id'], 'R2')
        self.save()
        self.ready()

    def test_deleting_an_id_is_rejected(self):
        self.planned()
        self.save(keep=True)
        text = self.read('docs/state/FEATURES.md')
        self.write('docs/state/FEATURES.md', '\n'.join(l for l in text.split('\n') if not l.startswith('| F1 ')))
        self.assertIn('F1 was removed', self.save(expect=2).stderr)

    def test_retired_id_cannot_return(self):
        self.planned()
        self.ws('set', 'F1', '--set', 'status=removed', '--set', 'reason=x')
        self.save(keep=True)
        text = self.read('docs/state/FEATURES.md').replace('| F1 | removed |', '| F1 | building |')
        self.write('docs/state/FEATURES.md', text)
        self.assertIn('cannot return', self.save(expect=2).stderr)

    def test_reopening_a_closed_row_is_refused(self):
        self.done()
        self.ws('card', '--set', 'current_task=none')
        self.save(keep=True)
        self.ws('compact')
        self.assertIn('closed', self.ws('set', 'T1', '--set', 'status=doing', expect=2).stderr)

    def test_large_log_rolls_into_archive_with_hash(self):
        self.init()
        rel = 'docs/logs/CHANGE_LOG.md'
        text = self.read(rel)
        for n in range(700):
            text = logs.add(text, 'CHANGE_LOG', {'ID': 'D1', 'Event': 'note', 'Detail': 'x' * 80, 'Source': 'test'})
        self.write(rel, text)
        self.save(keep=True)
        live = logs.live_rows(self.root, 'CHANGE_LOG')
        self.assertEqual(len(live), logs.KEEP_AFTER_ARCHIVE)
        self.assertEqual(len(logs.all_rows(self.root, 'CHANGE_LOG')), 700)
        archive = logs.archives(self.root, 'CHANGE_LOG')[0]['Path']
        self.write(archive, self.read(archive) + 'tampered\n')
        self.ws('check', expect=1)

    def test_checkpoint_retention(self):
        self.init()
        for _ in range(13):
            self.save(keep=True)
        self.assertEqual(len(list((self.root / 'docs/archive/checkpoints').glob('*.json'))), 10)
        self.ws('check')

    def test_size_warning(self):
        self.init()
        text = self.read('docs/state/REQUIREMENTS.md').replace('- None.', '- ' + 'long idea ' * 2500)
        self.write('docs/state/REQUIREMENTS.md', text)
        self.assertIn('WARNING', self.ws('check', expect=1).stdout)


class Hooks(Workspace):
    def test_enable_rejects_bad_shapes_and_replaces_stale_entries(self):
        for text in ('[1, 2]', '{"hooks": "x"}', '{"hooks": {"Stop": {"a": 1}}}', '{"hooks": {"Stop": [1]}}',
                     '{"hooks": {"Stop": [{"hooks": "x"}]}}'):
            self.write('.claude/settings.json', text)
            self.assertIn('ERROR', self.ws('hooks', 'enable', 'claude', expect=2).stderr)
            self.assertEqual(self.read('.claude/settings.json'), text)
        self.write('.claude/settings.json', json.dumps({'hooks': {'UserPromptSubmit': [
            {'hooks': [{'type': 'command', 'command': 'python scripts/ws.py-lint.py'}]},
            {'hooks': [{'type': 'command', 'command': 'python old/.agents/tools/ws.py turn --hook claude'}]}]}}))
        self.ws('hooks', 'enable', 'claude')
        commands = [h['hooks'][0]['command'] for h in json.loads(self.read('.claude/settings.json'))['hooks']['UserPromptSubmit']]
        self.assertEqual(commands, ['python scripts/ws.py-lint.py', 'python .agents/tools/ws.py turn --hook claude'])
        self.write('.agents/hooks.json', json.dumps({
            'workspace-brief': {'SessionStart': [{'type': 'command', 'command': 'python .agents/tools/ws.py brief --hook antigravity'}]},
            'mine': {'Stop': [{'type': 'command', 'command': 'echo hi'}]}}))
        self.ws('hooks', 'enable', 'antigravity')
        data = json.loads(self.read('.agents/hooks.json'))
        self.assertIn('mine', data)
        self.assertEqual(data['workspace-brief']['SessionStart'][0]['command'], 'python tools/ws.py brief --hook antigravity')
        self.write('.kiro/hooks/workspace-brief.json', '{"version": "v1", "hooks": [{"name": "workspace-brief", '
                   '"trigger": "SessionStart", "action": {"type": "command", "command": "python .agents/tools/ws.py brief --hook kiro"}}]}')
        self.ws('hooks', 'enable', 'kiro')
        self.assertFalse((self.root / '.kiro/hooks/workspace-brief.json').exists())

    def test_enable_writes_settings_and_merges(self):
        self.write('.claude/settings.json', json.dumps({'permissions': {'allow': ['Bash(ls)']}}))
        self.ws('hooks', 'enable', 'claude')
        self.ws('hooks', 'enable', 'claude')
        data = json.loads(self.read('.claude/settings.json'))
        self.assertEqual(data['permissions'], {'allow': ['Bash(ls)']})
        self.assertEqual(len(data['hooks']['SessionStart']), 1)
        for host in ('codex', 'cursor', 'gemini', 'copilot', 'kiro', 'antigravity'):
            self.ws('hooks', 'enable', host)
            self.ws('hooks', 'enable', host)
        kiro = json.loads(self.read('.kiro/hooks/workspace.json'))
        self.assertEqual(kiro['version'], 'v1')
        self.assertEqual([h['trigger'] for h in kiro['hooks']], ['SessionStart', 'UserPromptSubmit', 'Stop'])
        claude = json.loads(self.read('.claude/settings.json'))
        self.assertIn('ws.py turn --hook claude', json.dumps(claude['hooks']['UserPromptSubmit']))
        self.assertIn('PreInvocation', json.loads(self.read('.agents/hooks.json'))['workspace-turn'])
        self.assertEqual(json.loads(self.read('.cursor/hooks.json'))['version'], 1)
        codex = json.loads(self.read('.codex/hooks.json'))
        hook = codex['hooks']['UserPromptSubmit'][0]['hooks'][0]
        self.assertEqual(hook['commandWindows'], hook['command'])
        antigravity = json.loads(self.read('.agents/hooks.json'))
        self.assertIn('SessionStart', antigravity['workspace-brief'])
        self.ws('hooks', 'enable', 'grok')
        self.assertIn('Stop', json.loads(self.read('.grok/hooks/workspace.json'))['hooks'])
        gemini = json.loads(self.read('.gemini/settings.json'))
        self.assertIn('AGENTS.md', gemini['context']['fileName'])
        self.assertIn('SessionStart', gemini['hooks'])
        self.ws('check', '--strict')

    def test_brief_hook_formats(self):
        self.init()
        for host, path in (('claude', ('hookSpecificOutput', 'additionalContext')), ('cursor', ('additional_context',)),
                           ('copilot', ('additionalContext',)), ('antigravity', ('injectSteps',))):
            data = json.loads(self.ws('brief', '--hook', host, stdin='{}').stdout)
            for key in path:
                data = data[key]
            self.assertIn('Build a small tested demo', json.dumps(data, ensure_ascii=False))
        self.assertIn('Do not run ws brief again', self.ws('brief', '--hook', 'kiro', stdin='{}').stdout)

    def test_capture_copies_transcript_and_never_fails(self):
        self.init()
        self.save()
        transcript = self.parent / 'session.jsonl'
        transcript.write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'hello'}}) + '\n', encoding='utf-8')
        payload = json.dumps({'session_id': 'abc', 'transcript_path': str(transcript)})
        self.ws('capture', '--host', 'claude', '--event', 'Stop', stdin=payload)
        self.assertIn('hello', self.read('docs/chats/claude/abc.md'))
        self.assertIn('| claude | abc | 1 |', self.read('docs/chats/INDEX.md'))
        # The copied chat is not an unsaved change; only the open message blocks READY.
        errors = [l for l in self.ready(expect=1).stdout.splitlines() if l.startswith('ERROR')]
        self.assertEqual(len(errors), 1, errors)
        self.assertIn('not reconciled', errors[0])
        self.ws('capture', '--host', 'claude', stdin='not json')
        self.ws('capture', '--host', 'claude', stdin=json.dumps({'transcript_path': 'missing.jsonl'}))

    def test_capture_reads_utf8_payload_bytes_regardless_of_console_encoding(self):
        self.init()
        folder = self.parent / '项目 记录'
        folder.mkdir()
        transcript = folder / 'rollout.jsonl'
        line = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '开始。项目目标是记事本'}]}}
        transcript.write_text(json.dumps(line, ensure_ascii=False) + '\n', encoding='utf-8')
        payload = json.dumps({'session_id': 'u8', 'transcript_path': str(transcript)}, ensure_ascii=False).encode('utf-8')
        env = dict(ENV, PYTHONIOENCODING='cp437', PYTHONUTF8='0')
        run = subprocess.run([sys.executable, str(self.root / '.agents/tools/ws.py'), 'capture', '--host', 'codex'],
                             input=payload, capture_output=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('开始。项目目标是记事本', self.read('docs/chats/codex/u8.md'))

    def test_stop_payload_adds_final_reply_missing_from_transcript(self):
        self.init()
        transcript = self.parent / 's.jsonl'
        transcript.write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'question'}}) + '\n', encoding='utf-8')
        payload = {'session_id': 's2', 'transcript_path': str(transcript), 'last_assistant_message': 'final answer'}
        self.ws('capture', '--host', 'codex', '--event', 'Stop', stdin=json.dumps(payload))
        text = self.read('docs/chats/codex/s2.md')
        self.assertLess(text.index('question'), text.index('final answer'))

    def test_hook_commands_work_from_any_folder(self):
        self.init()
        script = self.root / '.agents/tools/ws.py'
        for cwd in (self.root / '.agents', self.root / 'docs/state', self.parent):
            run = subprocess.run([sys.executable, str(script), 'brief', '--hook', 'antigravity'], cwd=cwd, input='{}',
                                 capture_output=True, text=True, encoding='utf-8', env=ENV)
            self.assertIn('Build a small tested demo', run.stdout, cwd)
        self.ws('hooks', 'enable', 'antigravity')
        command = json.loads(self.read('.agents/hooks.json'))['workspace-brief']['SessionStart'][0]['command']
        run = subprocess.run(command.split(), cwd=self.root / '.agents', input='{}', capture_output=True, text=True,
                             encoding='utf-8', env=ENV)
        self.assertIn('injectSteps', run.stdout)

    def test_session_start_hook_injects_brief(self):
        self.init()
        out = self.ws('brief', '--hook', 'claude', stdin='{}').stdout
        data = json.loads(out)
        self.assertIn('Build a small tested demo', data['hookSpecificOutput']['additionalContext'])
