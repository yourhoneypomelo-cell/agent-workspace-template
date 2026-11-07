"""Regression tests for the 3.6 survey items: task logs, blocked reasons, test-surface notes, rejected runs, feature
shipping, card history, jobs, known command problems, snapshots, takeover warning and DeepSeek Harness import."""
import json
import os
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path

from support import Workspace


class Tasks(Workspace):
    def test_acceptance_edit_and_block_are_logged_and_block_needs_a_reason(self):
        self.planned()
        self.ws('set', 'T1', '--set', 'acceptance=python -m unittest test_demo.Demo.test_value')
        log = self.read('docs/logs/CHANGE_LOG.md')
        self.assertIn('acceptance edited', log)
        self.assertIn('was: python -m unittest test_demo', log)
        self.assertIn('give a reason', self.ws('set', 'T1', '--set', 'status=blocked', expect=2).stderr)
        self.ws('set', 'T1', '--set', 'status=blocked', '--set', 'reason=needs the API key from the user')
        self.assertIn('todo -> blocked', self.read('docs/logs/CHANGE_LOG.md'))
        self.assertIn('(blocked: needs the API key from the user)', self.ws('brief').stdout)

    def test_an_acceptance_edited_by_hand_is_logged_at_the_next_checkpoint(self):
        self.planned()
        self.save(keep=True)
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace(
            'python -m unittest test_demo |', 'python -m unittest test_demo.Demo.test_value |'))
        self.assertIn('changed outside "ws set": T1 acceptance', self.ws('brief').stdout)
        self.save(keep=True)
        self.assertIn('acceptance edited outside ws | was: python -m unittest test_demo', self.read('docs/logs/CHANGE_LOG.md'))
        self.assertNotIn('outside "ws set"', self.ws('brief').stdout)
        self.ws('set', 'T1', '--set', 'acceptance=python -m unittest test_demo')
        self.save(keep=True)
        self.assertEqual(self.read('docs/logs/CHANGE_LOG.md').count('outside ws'), 1)

    def test_a_reworded_retired_row_is_listed_for_the_agent(self):
        self.init()
        for text in ('导出笔记为 CSV 文件，供表格软件打开', '用户登录使用邮箱和密码'):
            self.ws('add', 'requirement', '--set', f'requirement={text}', '--set', 'acceptance=x')
        for rid in ('R2', 'R3'):
            self.ws('set', rid, '--set', 'status=removed', '--set', 'reason=user dropped it')
        out = self.ws('add', 'requirement', '--set', 'requirement=支持把所有笔记导出成 CSV 表格', '--set', 'acceptance=x').stdout
        self.assertIn('Closest retired requirements', out)
        self.assertIn('R2 removed', out.split('Closest retired requirements')[1].split('\n')[1])
        self.assertNotIn('Closest retired', self.ws('add', 'requirement', '--set', 'requirement=Add a dark theme',
                                                    '--set', 'acceptance=x').stdout)

    def test_feature_ships_when_its_last_task_is_verified(self):
        self.done()
        self.assertIn('| F1 | shipped |', self.read('docs/state/FEATURES.md'))
        self.assertIn('building -> shipped', self.read('docs/logs/CHANGE_LOG.md').replace('planned -> shipped', 'building -> shipped'))
        self.save()

    def test_rejected_runs_are_counted_in_the_brief(self):
        self.planned()
        self.write('test_demo.py', 'import unittest\n\n\nclass Demo(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(2 + 2, 5)\n')
        for _ in range(3):
            self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo', expect=1)
        brief = self.ws('brief').stdout
        self.assertIn('3 rejected verify runs in a row', brief)
        self.assertIn('ask the user before running it again', brief)
        self.passing_test()
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertNotIn('rejected verify runs', self.ws('brief').stdout)


class Surface(Workspace):
    def test_skips_are_shown_and_a_shrinking_run_is_noted(self):
        self.init()
        body = ('import unittest\n\n\nclass Demo(unittest.TestCase):\n    def test_a(self):\n        pass\n\n'
                '    def test_b(self):\n        pass\n')
        self.write('test_demo.py', body)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Demo',
                '--set', 'acceptance=python -m unittest test_demo')
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.write('test_demo.py', body.replace('    def test_b', '    @unittest.skip("later")\n    def test_b'))
        run = self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertIn('1 skipped', self.read('docs/state/HANDOFF.md'))
        self.assertIn('tests less than the previous accepted run', run.stdout)
        self.assertIn('never narrow them just to get a pass', run.stdout)

    def test_evidence_written_before_the_surface_key_still_loads(self):
        self.done()
        task = next(line for line in self.read('docs/state/TASKS.md').splitlines() if line.startswith('| T1 |'))
        rel = next(part.strip() for part in task.split('|') if part.strip().startswith('docs/archive/checks/'))
        data = json.loads(self.read(rel))
        data.pop('surface')
        self.write(rel, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        self.save(keep=True)


class Card(Workspace):
    def test_replaced_risks_are_kept_in_the_log(self):
        self.init()
        self.ws('card', '--set', 'risks=the migration script failed on empty rows')
        self.ws('card', '--set', 'risks=none confirmed')
        self.assertIn('was: the migration script failed on empty rows', self.read('docs/logs/MAINTENANCE_LOG.md'))

    def test_a_recorded_job_is_checked_by_the_brief(self):
        self.init()
        job = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(job.kill)
        self.write('build/job.log', 'step 1\nstep 2 of 9\n')
        self.ws('card', '--set', f'recovery_notes=training run pid={job.pid} log=build/job.log')
        self.assertIn('started=', self.read('docs/state/HANDOFF.md'))
        brief = self.ws('brief').stdout
        self.assertIn(f'job pid {job.pid}: running', brief)
        self.assertIn('last: step 2 of 9', brief)
        job.kill()
        job.wait()
        self.assertIn(f'job pid {job.pid}: exited', self.ws('brief').stdout)
        self.assertIn('is not running', self.ws('card', '--set', f'recovery_notes=pid={job.pid}', expect=2).stderr)

    def test_known_command_problems_reach_the_brief(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace(
            '| Command | Symptom | Working form |\n| --- | --- | --- |\n',
            '| Command | Symptom | Working form |\n| --- | --- | --- |\n| pnpm test | pnpm not on PATH | D:/npm-global/pnpm.cmd test |\n')
        self.write('docs/state/ARCHITECTURE.md', text)
        self.assertIn('- pnpm test: pnpm not on PATH -> D:/npm-global/pnpm.cmd test', self.ws('brief').stdout)

    def test_preferences_are_listed_in_the_brief(self):
        self.init()
        self.ws('add', 'preference', '--set', 'preference=Reply in Chinese', '--set', 'source=user 2026-11-04')
        self.assertIn('Preferences: P1 Reply in Chinese', self.ws('brief').stdout)


class Snapshot(Workspace):
    def test_snapshot_zips_the_documents_and_sets_the_baseline(self):
        self.init()
        self.write('src/app.py', 'print(1)\n')
        self.write('.env', 'TOKEN=x\n')
        result = json.loads(self.ws('snapshot', '--label', 'before-merge', 'src').stdout.splitlines()[0])
        with zipfile.ZipFile(self.root / result['snapshot']) as bundle:
            names = bundle.namelist()
            manifest = json.loads(bundle.read('SNAPSHOT.json'))
        self.assertIn('docs/state/REQUIREMENTS.md', names)
        self.assertIn('src/app.py', names)
        self.assertNotIn('.env', names)
        self.assertEqual(set(manifest['files']), set(names) - {'SNAPSHOT.json'})
        self.assertIn(result['snapshot'], self.read('docs/state/HANDOFF.md'))
        self.assertIn('lowercase words', self.ws('snapshot', '--label', 'Bad Label', expect=2).stderr)
        self.assertIn('cannot hold other snapshots', self.ws('snapshot', '--label', 'x', 'docs/archive/snapshots', expect=2).stderr)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=src', '--set', 'action=App', '--set', 'acceptance=check: python src/app.py')
        self.save(keep=True)


class Specs(Workspace):
    def spec(self, slug, text):
        self.write(f'docs/specs/{slug}/requirements.md', text)
        for name in ('design', 'tasks'):
            self.write(f'docs/specs/{slug}/{name}.md', f'# {name}\n')

    def test_spec_folders_are_checked_against_their_rows(self):
        self.init()
        self.spec('export', '# Requirement detail: Export\n\n## Context\n\nRequirement IDs: R9.\n')
        self.ws('add', 'requirement', '--set', 'requirement=Export notes', '--set', 'acceptance=python -m unittest test_x',
                '--set', 'detail=docs/specs/export/requirements.md')
        self.spec('orphan', '# Requirement detail: Orphan\n\nRequirement IDs: R1.\n')
        warnings = self.ws('check', expect=None).stdout
        self.assertIn('docs/specs/orphan/ is linked by no requirement', warnings)
        self.assertIn('names R9, which no row has', warnings)
        self.assertIn('R2 links this spec but its "Requirement IDs:" line does not name it', warnings)
        template = (Path(__file__).resolve().parents[2] / 'template/spec/requirements.md').read_text(encoding='utf-8')
        self.spec('export', template)
        warnings = self.ws('check', expect=None).stdout
        self.assertIn('still holds the template text', warnings)
        self.assertNotIn('does not name it', warnings)  # the R<n> placeholder is skipped

    def test_a_filled_spec_and_a_compacted_link_are_quiet(self):
        self.init()
        self.spec('export', '# Requirement detail: Export\n\n## Context\n\nRequirement IDs: R2.\n')
        self.ws('add', 'requirement', '--set', 'requirement=Export notes', '--set', 'acceptance=python -m unittest test_x',
                '--set', 'detail=docs/specs/export/requirements.md')
        self.assertFalse([l for l in self.ws('check', expect=None).stdout.splitlines() if l.startswith('WARNING: docs/specs/')])
        self.ws('set', 'R2', '--set', 'status=removed', '--set', 'reason=user dropped export')
        self.ws('compact')
        self.assertNotIn('linked by no requirement', self.ws('check', expect=None).stdout)


class Ownership(Workspace):
    def test_a_takeover_of_a_recent_writer_warns(self):
        self.init()
        refused = self.ws('start', expect=2).stderr
        self.assertIn('collides with work in progress', refused)
        self.assertIn('--force --reason', refused)


class DeepSeek(unittest.TestCase):
    def test_project_key_matches_the_store_folder_format(self):
        from wslib import dsh
        key = dsh.project_key(Path('E:/AI项目/T8'))
        self.assertEqual(key, '--E-AI~9879~76EE-T8--') if os.name == 'nt' else self.assertTrue(key.startswith('--'))

    def test_messages_keep_typed_turns_and_apply_replacements(self):
        from wslib import dsh
        lines = [
            {'type': 'session', 'version': 4, 'id': 's', 'cwd': 'x', 'delegationDepth': 0},
            {'type': 'user/message', 'seq': 1, 'time': 1793779617000, 'data': {'source': {'kind': 'agent-instructions'}, 'content': [{'type': 'text', 'text': 'rules'}]}},
            {'type': 'user/message', 'seq': 2, 'time': 1793779617000, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': 'old ask'}]}},
            {'type': 'user/message', 'seq': 3, 'time': 1793779618000, 'surfaceOp': {'op': 'replace', 'startSeq': 2, 'endSeq': 2},
             'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': 'edited ask'}]}},
            {'type': 'assistant/message', 'seq': 4, 'time': 1793779619000,
             'data': {'message': {'content': [{'type': 'reasoning', 'text': 'hidden'}, {'type': 'text', 'text': 'answer'}]}}},
        ]
        found = dsh.messages('\n'.join(json.dumps(r) for r in lines))
        self.assertEqual([(r, t) for r, t, _ in found], [('user', 'edited ask'), ('assistant', 'answer')])
        self.assertTrue(found[0][2].endswith('Z'))
        child = [{'type': 'session', 'delegationDepth': 1, 'parentSession': 'p'}] + lines[1:]
        self.assertEqual(dsh.messages('\n'.join(json.dumps(r) for r in child)), [])


class ReviewFixes(Workspace):
    """Findings of the 3.6.0 red team on verify, jobs and snapshots."""

    def test_a_malformed_feature_row_does_not_stop_verify(self):
        self.planned()
        self.ws('add', 'feature', '--set', 'behavior=Other', '--set', 'requirements=R1', '--set', 'tasks=T1')
        self.write('docs/state/FEATURES.md', self.read('docs/state/FEATURES.md').replace('| F2 | planned | Other | R1 | T1 |', '| F2 | planned | Other | R1 | T3 and T4 |'))
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertIn('| T1 | done |', self.read('docs/state/TASKS.md'))

    def test_the_shrink_note_is_logged_and_compares_with_the_largest_run(self):
        self.init()
        body = 'import unittest\n\n\nclass Demo(unittest.TestCase):\n' + ''.join(f'    def test_{n}(self):\n        pass\n\n' for n in 'abcd')
        self.write('test_demo.py', body)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Demo',
                '--set', 'acceptance=python -m unittest test_demo')
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.write('test_demo.py', body.replace('    def test_d(self):\n        pass\n\n', ''))
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertIn('tests less than before', self.read('docs/logs/MAINTENANCE_LOG.md'))
        third = self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertIn('4 tests before, 3 now', third.stdout)

    def test_a_task_edit_restarts_the_rejected_count(self):
        self.planned()
        self.write('test_demo.py', 'import unittest\n\n\nclass Demo(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(1, 2)\n')
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo', expect=1)
        self.ws('set', 'T1', '--set', 'scope=test_demo.py and docs')
        for _ in range(2):
            self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'test_demo', expect=1)
        self.assertIn('2 rejected verify runs in a row', self.ws('brief').stdout)

    def test_a_finished_job_can_be_recorded_and_secret_logs_are_not_shown(self):
        self.init()
        self.ws('card', '--set', 'recovery_notes=build job pid 70523 finished OK; pid=70523 exited')
        self.write('.env', 'X=1\n')
        job = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(job.kill)
        self.ws('card', '--set', f'recovery_notes=pid={job.pid} log=.env')
        self.assertIn('not shown', self.ws('brief').stdout)

    def test_snapshot_skips_keys_links_and_old_snapshots(self):
        self.init()
        self.write('ops/id_rsa', 'fake key\n')
        self.write('ops/creds.json', '{}\n')
        self.write('ops/run.py', 'print(1)\n')
        first = json.loads(self.ws('snapshot', '--label', 'one').stdout.splitlines()[0])['snapshot']
        second = json.loads(self.ws('snapshot', '--label', 'two', 'docs').stdout.splitlines()[0])['snapshot']
        with zipfile.ZipFile(self.root / second) as bundle:
            names = bundle.namelist()
        self.assertIn('ops/run.py', names)
        self.assertFalse([n for n in names if n.endswith(('id_rsa', 'creds.json', '.zip'))], names)
        self.assertTrue((self.root / first).is_file())
        self.assertIn('up to 60 characters', self.ws('snapshot', '--label', 'x' * 61, expect=2).stderr)


class CaptureFixes(Workspace):
    """Findings of the 3.6.0 red team on capture, DeepSeek Harness, compact and the hook brief."""

    def test_typed_text_after_a_reminder_part_is_kept(self):
        from wslib import capture
        record = {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': [
            {'type': 'text', 'text': '<system-reminder>be careful</system-reminder>'}, {'type': 'text', 'text': '把导出改成 JSON'}]}}
        self.assertEqual(capture._message(record), ('user', '把导出改成 JSON'))
        only = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '<system-reminder>x</system-reminder>'}]}}
        self.assertIsNone(capture._message(only))

    def test_codex_tags_and_ide_headings(self):
        from wslib import capture
        for tag in ('<heartbeat>tick</heartbeat>', '<subagent_notification>done</subagent_notification>'):
            self.assertIsNone(capture._message({'type': 'user', 'message': {'role': 'user', 'content': tag}}))
        wrapped = '# Context from my IDE setup:\n\n## Open tabs:\n- a.py\n\n## My request:\nfix the export'
        self.assertEqual(capture._message({'type': 'user', 'message': {'role': 'user', 'content': wrapped}})[1], 'fix the export')
        quoted = 'Our docs say "## My request for Codex:" starts the text; keep this sentence'
        self.assertEqual(capture._message({'type': 'user', 'message': {'role': 'user', 'content': quoted}})[1], quoted)

    def test_dsh_compaction_does_not_delete_history(self):
        from wslib import dsh
        lines = [{'type': 'session', 'delegationDepth': 0},
                 {'type': 'user/message', 'seq': 1, 'time': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': 'first ask'}]}},
                 {'type': 'user/message', 'seq': 2, 'time': 2, 'surfaceOp': {'op': 'replace', 'startSeq': 1, 'endSeq': 1},
                  'data': {'source': {'kind': 'compact-checkpoint'}, 'content': [{'type': 'text', 'text': 'summary'}]}}]
        self.assertEqual([t for _, t, _ in dsh.messages('\n'.join(json.dumps(r) for r in lines))], ['first ask'])

    def test_dsh_refuses_a_decompression_bomb(self):
        try:
            from backports import zstd
        except ImportError:
            try:
                from compression import zstd
            except ImportError:
                self.skipTest('no zstd module')
        from wslib import dsh
        decode, _ = dsh.decoder(in_process=True)
        with self.assertRaises(ValueError):
            decode(zstd.compress(b'a' * (dsh.MAX_TEXT + 1)))
        self.assertEqual(decode(zstd.compress(b'x') + zstd.compress(b'y')), 'xy')

    def test_legacy_closed_rows_with_odd_endings_upgrade(self):
        from wslib import tables
        legacy = ('# C\n\n| ID | Status | Summary | Reason | Replacement | Evidence | Closed |\n'
                  '| --- | --- | --- | --- | --- | --- | --- |\n| R1 | removed | a \\| b | why | none | none ||\n')
        up = tables.upgrade_closed(legacy)
        self.assertEqual(tables.parse(up, tables.CLOSED_HEADERS, 'x')[0]['Summary'], 'a | b')
        pasted = up + '| R2 | removed | c | d | none | none | 2026-01-01 |\n'
        self.assertEqual(tables.parse(tables.upgrade_closed(pasted), tables.CLOSED_HEADERS, 'x')[-1]['Row'], 'none')

    def test_a_cut_hook_brief_keeps_the_next_section(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('wscli', self.root / '.agents/tools/ws.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = '# B\n\n## Handoff\n\n' + '- line\n' * 3000 + '\n## Next\n\n2. Run: start --session k-abc\n'
        cut = module.cut_brief(text, 8800)
        self.assertLessEqual(len(cut), 8800)
        self.assertTrue(cut.endswith('start --session k-abc\n'))

    def test_weak_passwords_long_keys_and_code_after_a_label(self):
        import random
        import string
        from wslib.coverage import redact, redact_pasted
        for text, secret in (('password: admin123', 'admin123'), ('密码：abc123', 'abc123'), ('password: 1234567', '1234567')):
            self.assertNotIn(secret, redact(text), text)
        for text in ('pwd = os.environ["X"]', 'password = getenv("DB_PASS")', 'password = settings.DB["pw"]', 'password: v2.3.3'):
            self.assertEqual(redact(text), text)
        rnd = random.Random(7)
        keys = [''.join(rnd.choice(string.ascii_letters + string.digits) for _ in range(26)) for _ in range(200)]
        missed = sum(1 for key in keys if key in redact_pasted('here ' + key))
        self.assertLess(missed, 10)

    def test_compact_of_the_last_requirement_is_not_ready(self):
        self.init()
        self.ws('set', 'R1', '--set', 'status=removed', '--set', 'reason=user dropped it')
        self.ws('compact')
        self.save(expect=None)
        self.ready(expect=1)


if __name__ == '__main__':
    unittest.main()
