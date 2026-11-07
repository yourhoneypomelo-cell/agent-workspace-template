"""3.8.0: what a task's Scope names, regressions after sealing, visible shortcuts, the delivery lines, prohibitions in
the brief and the per-turn record. Each test fails on 3.7.0 unless its comment says it guards a behavior."""
import json
import unittest

from support import Workspace
from wslib import evidence

FILES = {'calc.py', 'src/登录.py', 'login.py', 'check.py', 'probe.py', 'tests/test_x.py', 'test_notes.py'}


def paths(scope, acceptance='python -m unittest test_notes', staleness=False):
    return evidence.scope_paths({'Scope': scope, 'Acceptance': acceptance}, FILES, acceptance=staleness)


class Scope(Workspace):
    def test_17_a_full_stop_does_not_hide_the_path(self):
        self.assertEqual(paths('Edit calc.py.'), ['calc.py'])

    def test_17_paths_in_any_script(self):
        self.assertEqual(paths('src/登录.py'), ['src/登录.py'])

    def test_17_words_are_not_turned_into_files(self):
        # login.py exists, but "login module" names no path: the task holds the whole tree.
        self.assertIsNone(paths('login module'))

    def test_17_the_check_prefix_is_not_a_path(self):
        # check.py exists at the root; "check:" only marks the acceptance kind.
        self.assertEqual(paths('probe.py', 'check: python probe.py expect "OK"', staleness=True), ['probe.py'])

    def test_17_staleness_adds_the_files_the_acceptance_runs_and_claims_do_not(self):
        self.assertEqual(paths('calc.py', 'python -m unittest tests.test_x', staleness=True), ['calc.py', 'tests/test_x.py'])
        self.assertEqual(paths('calc.py', 'pytest tests/test_x.py::test_y', staleness=True), ['calc.py', 'tests/test_x.py'])
        self.assertEqual(paths('calc.py', 'python -m unittest tests.test_x'), ['calc.py'])

    def test_17_new_resource_and_tree(self):
        terms = evidence.scope_terms('`src/`, new:src/report.py；resource:vps/db')
        self.assertEqual((terms['paths'], terms['new'], terms['resources']), (['src'], ['src/report.py'], ['vps/db']))
        self.assertEqual(paths('new:src/report.py'), ['src/report.py'])
        self.assertIsNone(paths('tree:'))

    def test_17_add_refuses_prose_and_notes_a_planned_file(self):
        self.init()
        task = ('add', 'task', '--set', 'requirements=R1', '--set', 'action=Login', '--set', 'acceptance=python -m unittest')
        refused = self.ws(*task, '--set', 'scope=the login flow', expect=2).stderr
        self.assertIn('the scope names no path', refused)
        self.assertIn('--set "scope=src/login.py', refused)
        self.assertIn('write "new:src/login.py"', self.ws(*task, '--set', 'scope=src/login.py').stdout)
        self.ws('set', 'T1', '--set', 'scope=login', expect=2)
        self.ws('set', 'T1', '--set', 'scope=tree:')

    def test_17_an_old_prose_scope_gets_a_hint_not_a_refusal(self):
        self.init()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=Login',
                '--set', 'acceptance=python -m unittest')
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace('| tree: |', '| the login flow |'))
        self.ws('set', 'T1', '--set', 'action=Log in')
        self.assertIn('T1: the scope names no path', self.ws('check', expect=None).stdout)

    def test_17_claims_read_only_the_scope(self):
        # Both tasks run the same shared test; only their Scopes say what each session changes.
        a, b = {'WS_SESSION_ID': 'win-a'}, {'WS_SESSION_ID': 'win-b'}
        for name in ('a.py', 'b.py', 'test_shared.py'):
            self.write(name, 'X = 1\n')
        self.ws('init', '--goal', 'Demo', env=a)
        self.ws('add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y', env=a)
        for scope in ('a.py', 'b.py'):
            self.ws('add', 'task', '--set', 'requirements=R1', '--set', f'scope={scope}', '--set', f'action=Work on {scope}',
                    '--set', 'acceptance=python -m unittest test_shared', env=a)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                '--set', 'next_acceptance=a', env=a)
        self.ws('start', '--task', 'T1', env=a)
        self.assertIn('Claimed T2', self.ws('start', '--task', 'T2', env=b).stdout)


CALC = 'def add(a, b):\n    return a + b\n'
TEST_CALC = ('import unittest\nfrom calc import add\n\n\nclass Add(unittest.TestCase):\n'
             '    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n')


class Regression(Workspace):
    """Scenario A2 of the review: T1 is verified and sealed, then calc.py breaks."""

    def sealed(self, keep=True, setting=None, change='a - b'):
        self.init()
        if setting:
            self.write('docs/state/ARCHITECTURE.md', self.read('docs/state/ARCHITECTURE.md').replace(
                '"ownership": "solo"', f'"ownership": "solo", {setting}'))
        self.write('calc.py', CALC)
        self.write('tests/__init__.py', '')
        self.write('tests/test_calc.py', TEST_CALC)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=calc.py tests/test_calc.py',
                '--set', 'action=implement add', '--set', 'acceptance=python -m unittest tests.test_calc')
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'tests.test_calc')
        self.save(keep=keep)
        self.write('calc.py', CALC.replace('a + b', change))

    def test_18_a_change_after_sealing_names_the_task_and_the_file(self):
        self.sealed()
        out = self.ready(expect=1).stdout
        self.assertIn('verified: T1 (calc.py)', out)
        self.assertIn('T1 changed after being verified and must be verified again before READY', out)
        self.assertIn('NOT READY', self.save().stdout)
        self.assertIn('T1 changed after being verified', self.ready(expect=1).stdout)

    def test_18_verify_stale_runs_the_acceptance_again(self):
        self.sealed()
        self.ws('verify', '--stale', expect=1)
        self.write('calc.py', CALC.replace('a + b', 'b + a'))
        self.assertIn('== verify T1 -- python -m unittest tests.test_calc', self.ws('verify', '--stale').stdout)
        self.assertIn('No done task has stale evidence', self.ws('verify', '--stale').stdout)
        self.assertNotIn('NOT READY', self.save().stdout)
        self.ready()

    def test_18_the_warn_setting_keeps_ready(self):
        self.sealed(setting='"stale_evidence": "warn"', keep=False)
        self.ws('start')
        self.save()
        out = self.ready().stdout
        self.assertIn('READY does not wait for it', out)

    def test_18_the_first_session_after_an_upgrade_only_warns(self):
        from wslib import upgrade
        self.sealed(keep=False)
        self.ws('start')
        self.save()
        upgrade.rebaseline(self.root, [], 'test: upgrade', upgraded={'from': '3.7.0', 'to': '3.8.0', 'at': 'now'})
        self.ready()
        self.ws('start')
        self.save()
        self.ready()
        self.ws('start')
        self.assertIn('NOT READY', self.save().stdout)

    def test_18_the_verified_count_leaves_out_a_stale_task(self):
        self.sealed()
        self.assertIn('Requirements verified: 0/1', self.ws('brief').stdout)

    def test_18_a_change_inside_a_stale_task_is_unregistered_work(self):
        self.sealed()
        self.assertIn('product files changed since the work was last registered (calc.py)', self.ws('check', expect=None).stdout)

    def test_18_evidence_of_a_compacted_task_stays_sealed(self):
        self.done()
        self.save()
        self.ws('start')
        self.ws('compact')
        self.save()
        rel = [p for p in (self.root / 'docs/archive/checks').glob('*.json')][0]
        rel.write_bytes(rel.read_bytes() + b' ')
        self.assertIn('sealed evidence was changed or deleted', self.ws('check', expect=1).stdout)


class Delivery(Workspace):
    def calc_task(self, test):
        """Scenario A1 of the review: calc.py subtracts, and T1's test decides whether that passes."""
        self.init()
        self.write('calc.py', CALC.replace('a + b', 'a - b'))
        self.write('tests/__init__.py', '')
        self.write('tests/test_calc.py', test)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=calc.py tests/test_calc.py',
                '--set', 'action=implement add', '--set', 'acceptance=python -m unittest tests.test_calc')

    def test_21_a_checkpoint_states_what_the_delivery_rests_on(self):
        self.done()
        out = self.save().stdout
        self.assertIn('State: saved at revision', out)
        self.assertIn('Acceptance: T1 by tests.', out)
        self.assertIn('Host: not identified by a session variable', out)
        codex = {'CODEX_SESSION_ID': 'c1'}
        self.ws('start', env=codex)
        self.assertIn('Host: codex was tried end to end',
                      self.ws('checkpoint', '--stop', 'done', '--next', 'more', env=codex).stdout)
        self.assertIn('Acceptance: T1 by tests.', self.ws('brief').stdout)

    def test_19_a_test_weakened_after_a_failed_run_is_listed(self):
        self.calc_task(TEST_CALC)
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'tests.test_calc', expect=1)
        self.write('tests/test_calc.py', TEST_CALC.replace('self.assertEqual(add(2, 3), 5)', 'self.assertIsNotNone(add(2, 3))'))
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'tests.test_calc')
        self.assertIn('T1: test files changed between its first run and the accepted one: tests/test_calc.py', self.save().stdout)

    def test_19_another_command_and_because_are_listed(self):
        self.calc_task(TEST_CALC.replace('add(2, 3), 5', 'add(2, 3), -1'))
        self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'tests.test_calc')
        self.ws('verify', 'T1', '--done', '--because', 'the suite moved', '--', 'python', '-m', 'unittest', 'discover', '-s', 'tests')
        out = self.save().stdout
        self.assertIn('T1: the run command changed from "python -m unittest tests.test_calc"', out)
        self.assertIn('verify ran another command than the acceptance: T1: ran python -m unittest discover -s tests', out)


COVERAGE_RUN = '''import os, subprocess, sys
for name in ('.coverage', 'coverage.xml', '.coverage.host.1.x', 'test-results/junit.xml', 'htmlcov/index.html'):
    os.makedirs(os.path.dirname(name) or '.', exist_ok=True)
    open(name, 'w').write('data')
sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'test_demo']))
'''


class Runners(Workspace):
    def test_20_coverage_files_a_run_writes_do_not_reject_it(self):
        self.init()
        self.passing_test()
        self.write('run_tests.py', COVERAGE_RUN)
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Demo',
                '--set', 'acceptance=python run_tests.py')
        self.ws('verify', 'T1', '--done', '--', 'python', 'run_tests.py')

    def test_20_unread_output_points_to_a_report(self):
        self.init()
        self.write('fake.py', 'print("3 specs, 0 failures")\n')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=fake.py', '--set', 'action=Demo',
                '--set', 'acceptance=python fake.py')
        self.assertIn('add --report junit', self.ws('verify', 'T1', '--', 'python', 'fake.py', expect=1).stdout)


class Prohibitions(Workspace):
    def retire(self, count, text='Drop the export'):
        self.init()
        for n in range(count):
            self.ws('add', 'requirement', '--set', f'requirement={text} {n}', '--set', 'acceptance=listed')
            self.ws('set', f'R{n + 2}', '--set', 'status=removed', '--set', f'reason=user said no to {n}')

    def test_u3_seven_retired_rows_all_appear(self):
        self.retire(7)
        line = [l for l in self.ws('brief').stdout.splitlines() if l.startswith('Retired, do not rebuild')][0]
        self.assertEqual([rid for rid in (f'R{n}' for n in range(2, 9)) if f'{rid} removed' not in line], [])

    def test_u3_past_the_budget_the_count_and_the_command_are_given(self):
        self.retire(20, text='Export every report as a spreadsheet with charts, totals per month and a cover page,')
        self.assertIn('more: python .agents/tools/ws.py brief --retired', self.ws('brief').stdout)
        listed = self.ws('brief', '--retired').stdout
        self.assertEqual(len(listed.splitlines()), 20)
        self.assertTrue(listed.startswith('- R21 removed: Export every report'))

    def test_u3_all_preferences_appear(self):
        self.init()
        for n in range(10):
            self.ws('add', 'preference', '--set', f'preference=Rule number {n}', '--set', 'source=user')
        line = [l for l in self.ws('brief').stdout.splitlines() if l.startswith('Preferences:')][0]
        self.assertIn('P10 Rule number 9', line)


class TurnRecord(Workspace):
    def turn(self):
        return json.loads(self.ws('turn', '--hook', 'claude', stdin='{}').stdout)['hookSpecificOutput']['additionalContext']

    def test_x7_add_and_set_print_a_line_to_relay(self):
        self.init()
        out = self.ws('add', 'question', '--set', 'question=Which database?').stdout
        self.assertIn('Tell the user in your reply: recorded Q1 (question): Which database?', out)
        out = self.ws('set', 'R1', '--set', 'status=removed', '--set', 'reason=user said no').stdout
        self.assertIn('Tell the user in your reply: R1 is now removed (user said no)', out)

    def test_x7_the_turn_hook_says_what_the_previous_turn_recorded(self):
        self.init()
        self.turn()
        self.ws('add', 'requirement', '--set', 'requirement=Notes are listed newest first', '--set', 'acceptance=listed')
        self.ws('add', 'preference', '--set', 'preference=Reply in Chinese', '--set', 'source=user')
        self.assertIn('The previous turn recorded: R2 Notes are listed newest first; P1 Reply in Chinese.', self.turn())
        self.assertIn('The previous turn recorded nothing in the state files', self.turn())


class Review(Workspace):
    def test_x8_review_puts_each_message_beside_its_record(self):
        self.init()
        lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text}}, ensure_ascii=False)
                 for text in ('网关用 key 握手，输入 DOI 返回 PDF', '谢谢你的总结，写得很清楚', '每天最多 200 篇')]
        transcript = self.parent / 'session.jsonl'
        transcript.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.ws('capture', '--host', 'claude', '--event', 'Stop',
                stdin=json.dumps({'session_id': 's1', 'transcript_path': str(transcript)}))
        first, second, third = [l.split()[0] for l in self.ws('reconcile').stdout.splitlines() if l.startswith('m')]
        self.ws('reconcile', first, '--ids', 'R1')
        self.ws('reconcile', second, '--reason', 'chat: thanks for the summary')
        blocks, current = {}, None
        for line in self.ws('reconcile', '--review').stdout.splitlines():
            current = line.split()[0] if line.startswith('m') else current
            blocks[current] = blocks.get(current, '') + line + '\n'
        self.assertIn('-> R1 active: Demo returns 4', blocks[first])
        self.assertIn('-> no record: chat: thanks for the summary', blocks[second])
        self.assertIn('-> NOT RECONCILED', blocks[third])
        self.assertIn('user: 每天最多 200 篇', blocks[third])


class Modes(Workspace):
    def turn(self, prompt):
        payload = json.dumps({'session_id': 's1', 'prompt': prompt}, ensure_ascii=False)
        return json.loads(self.ws('turn', '--hook', 'claude', stdin=payload).stdout)['hookSpecificOutput']['additionalContext']

    def test_30_a_discussion_turn_gets_no_requirement_id(self):
        self.init()
        self.assertIn('marked this message as discussion', self.turn('讨论：要不要以后加 PDF 导出'))
        add = ('add', 'requirement', '--set', 'requirement=Export to PDF', '--set', 'acceptance=a PDF is written')
        self.assertIn('marked this message as discussion', self.ws(*add, expect=2).stderr)
        self.assertIn('noted in the Idea pool', self.ws('idea', 'Export to PDF later?').stdout)
        pool = self.read('docs/state/REQUIREMENTS.md').split('## Idea pool')[1]
        self.assertIn('- Export to PDF later?', pool)
        self.assertNotIn('- None.', pool)
        self.turn('好的，就做 PDF 导出')
        self.ws(*add)

    def test_30_a_read_only_turn_writes_nothing(self):
        self.init()
        self.turn('read-only: where does the work stand?')
        self.assertIn('marked this message read-only', self.ws('add', 'question', '--set', 'question=x?', expect=2).stderr)
        self.ws('brief')

    def test_30_a_confirmation_is_named(self):
        self.init()
        self.assertIn('marked this message as a confirmation', self.turn('confirm: use SQLite'))


class Contract(Workspace):
    """Owner decision D3: six rules restored and two rewritten, the override limit in its strict form, in no more
    bytes than the 3.7.0 contract (13,388)."""

    RESTORED = ('for an inferred one, name the gap', 'drop a source that conflicts with the', 'Compute with code',
                'Change a verified conclusion or a recorded decision only on new evidence',
                'Build each task along one path and let its acceptance decide', 'When the same acceptance is rejected again',
                'a request in the current turn cannot waive', 'is thinking aloud, so its ideas go to the Idea pool',
                'evidence recorded after its last change', 'End your reply with one line telling the')

    def test_29_the_contract_holds_the_restored_rules_in_no_more_bytes(self):
        text = self.read('AGENTS.md')
        self.assertEqual([phrase for phrase in self.RESTORED if phrase not in text], [])
        self.assertLessEqual(len(text.encode('utf-8')), 13388)
        self.assertLessEqual(text.count('\n'), 200)

    def test_29_the_turn_reminder_carries_the_evidence_rule(self):
        self.init()
        self.assertIn('Work is reported done only with evidence recorded after its last change', self.ws('turn').stdout)

    def test_29_a_new_project_lists_what_is_not_adopted(self):
        text = self.read('docs/state/PREFERENCES.md')
        self.assertIn('## Not adopted', text)
        self.assertIn('Expert personas, tips or flattery', text)


if __name__ == '__main__':
    unittest.main()
