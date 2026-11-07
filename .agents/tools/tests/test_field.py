"""Regressions from the Server2-us_ip field review: 162 sessions of Claude Code, Codex, Kiro and Gemini in one folder."""
import json
import unittest
from pathlib import Path

from support import Workspace
from wslib.core import SESSION_VARS


class FieldReview(Workspace):
    def test_set_reports_an_overwritten_cell_and_appends_with_plus_equals(self):
        # An agent erased a question's context with "ws set" and noticed only later.
        self.init()
        self.ws('add', 'question', '--set', 'question=Which key?', '--set', 'context=key at ~/.ssh/a; lockout after 3 tries')
        out = self.ws('set', 'Q1', '--set', 'context=asked the user').stdout
        self.assertIn('it was: key at ~/.ssh/a; lockout after 3 tries', out)
        self.ws('set', 'Q1', '--set', 'context+=user is checking')
        self.assertIn('asked the user; user is checking', self.read('docs/state/REQUIREMENTS.md'))

    def test_brief_says_when_no_hook_saves_chats(self):
        self.init()
        self.assertIn('Hooks: none enabled', self.ws('brief').stdout)
        self.ws('hooks', 'enable', 'claude')
        self.assertNotIn('Hooks: none enabled', self.ws('brief').stdout)

    def test_project_files_under_agents_are_flagged_and_scanned(self):
        # Reports for another repository piled up in .agents/tasks/, which an upgrade may replace.
        self.init()
        self.write('.agents/tasks/report.md', '# Report\n\napi_key = "sk-live-0123456789abcdefghij0123"\n')
        out = self.ws('check', expect=1).stdout
        self.assertIn('project files are under .agents/', out)
        self.assertIn('.agents/tasks/report.md', out)
        self.assertIn('looks like a credential', out)

    def test_budget_warning_for_architecture_names_a_way_out(self):
        self.init()
        self.write('docs/state/ARCHITECTURE.md', self.read('docs/state/ARCHITECTURE.md') + '\n' + 'Component detail.\n' * 1500)
        line = next(l for l in self.ws('check', expect=1).stdout.splitlines() if 'ARCHITECTURE.md is' in l)
        self.assertIn('docs/guides/', line)
        self.assertNotIn('compact', line)

    def test_hook_brief_matches_the_start_steps(self):
        self.init()
        text = json.loads(self.ws('brief', '--hook', 'claude', stdin='{}').stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn('continue with step 2', text)

    def test_zero_test_detection_reads_runner_summaries_only(self):
        from wslib.evidence import EMPTY_RUN
        self.assertTrue(EMPTY_RUN.search('Ran 0 tests in 0.000s'))
        self.assertTrue(EMPTY_RUN.search('============ no tests ran in 0.01s ============'))
        self.assertFalse(EMPTY_RUN.search('step 3: no tests ran for module x\nall checks OK'))

    def test_scratch_folders_are_skipped_only_at_the_root(self):
        self.init()
        for rel in ('.tmp/a.sh', 'tmp/b.py', 'src/tmp/keep.py', 'cache.db-wal', 'run.out'):
            self.write(rel, 'x')
        status = self.ws('status').stdout
        self.assertIn('src/tmp/keep.py', status)
        for rel in ('.tmp/a.sh', 'tmp/b.py', 'cache.db-wal', 'run.out'):
            self.assertNotIn(rel, status)

    def test_windows_separators_in_exclude_are_accepted(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"exclude": []', '"exclude": ["data\\\\raw\\\\**"]')
        self.write('docs/state/ARCHITECTURE.md', text)
        self.write('data/raw/a.csv', 'x')
        self.assertNotIn('data/raw/a.csv', self.ws('status').stdout)


class Writing(Workspace):
    """State rows stay readable for a new session, and nothing the user or the work recorded is lost."""
    LONG = ('Adopt the gateway after audit T56: tree byte-identical (sha a9ffcfe516220ada), 34 of 34 tests in 3.27 s, '
            'live matrix green (arXiv 211,707 B, Range 206 and 416, closed DOI 403, fake DOI 404, malformed 400), '
            'blue-team claims verified in code (rescue grid, ranking engine, OA state machine, HEAD fix, SIGTERM), '
            'one P1 open: no SSRF guard on candidate fetches, with loopback reflection into the attempts reason.')

    def test_a_long_value_is_saved_in_full_and_only_noted(self):
        self.init()
        out = self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56').stdout
        self.assertIn('saved in full', out)
        self.assertIn(self.LONG, self.read('docs/state/DESIGN.md'))

    def test_shortening_a_long_cell_keeps_the_previous_row(self):
        self.init()
        self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56')
        self.write('docs/reports/gateway-t56.md', '# Gateway audit T56\n\nDetail.\n')
        out = self.ws('set', 'D1', '--set', 'decision=Adopt the gateway; one P1 open (T57). Detail: docs/reports/gateway-t56.md').stdout
        self.assertIn('docs/archive/rows/D1.md', out)
        self.assertIn('211,707 B', self.read('docs/archive/rows/D1.md'))

    def test_lint_reports_state_rows_a_new_session_cannot_read(self):
        self.init()
        self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=Gateway',
                '--set', 'acceptance=python -m unittest')
        self.ws('add', 'feature', '--set', 'behavior=Gateway v3.2 auth, v3.3 HTML recovery, v3.4 impersonation',
                '--set', 'requirements=R1', '--set', 'tasks=T1')
        self.ws('add', 'question', '--set', 'question=Promote BLUE5 after ME-02 is fixed?',
                '--set', 'context=see docs/reports/missing.md')
        out = self.ws('lint').stdout
        self.assertIn('Keep the conclusion here and move the detail', out)
        self.assertIn('version history', out)
        self.assertIn('codes a new session cannot look up: BLUE5, ME-02', out)
        self.assertIn('docs/reports/missing.md, which does not exist', out)

    def test_terms_table_defines_codes(self):
        self.init()
        self.ws('add', 'question', '--set', 'question=Promote BLUE5 after ME-02 is fixed?')
        text = self.read('docs/state/ARCHITECTURE.md').replace(
            '| Term | Meaning | Detail |\n| --- | --- | --- |',
            '| Term | Meaning | Detail |\n| --- | --- | --- |\n| BLUE5 | Fifth blue-team build | none |\n'
            '| ME-02 | QC memory finding | none |')
        self.write('docs/state/ARCHITECTURE.md', text)
        self.assertNotIn('codes a new session cannot look up', self.ws('lint').stdout)

    def test_next_step_with_alternatives_points_to_a_question(self):
        self.init()
        self.ws('checkpoint', '--keep', '--stop', 'gateway audited', '--next', 'Fix T57, or adopt libgen, or start Nexus QC',
                '--set', 'phase=build', '--set', 'risks=none confirmed', '--set', 'next_acceptance=T57 passes')
        self.assertIn('next_step offers several options', self.ws('lint').stdout)
        self.ws('add', 'question', '--set', 'question=Which channel next: T57, libgen or Nexus QC?')
        self.ws('card', '--set', 'next_step=Ask the user Q1, then do that task')
        self.assertNotIn('next_step offers several options', self.ws('lint').stdout)

    def test_checkpoint_counts_findings_only_in_files_changed_this_session(self):
        self.init()
        self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56')
        out = self.ws('checkpoint', '--keep', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                      '--set', 'next_acceptance=a').stdout
        self.assertIn('findings in the state files changed this session', out)
        self.assertIn('delete nothing', out)
        out = self.ws('checkpoint', '--keep', '--stop', 's2', '--next', 'n2').stdout
        self.assertNotIn('findings in the state files changed this session', out)


VARS_TO_CLEAR = (*SESSION_VARS, 'CLAUDE_SESSION_ID', 'WS_ROLE', 'WS_HOST_PID')

# A stand-in agent window: a long-lived process that runs each ws command written to its inbox file.
HOST_LOOP = '''
import json, os, subprocess, sys, time
inbox = sys.argv[1]
open(inbox, 'w').close()
end = time.time() + 120
while time.time() < end:
    text = open(inbox, encoding='utf-8').read().strip()
    if text:
        open(inbox, 'w').close()
        req = json.loads(text)
        r = subprocess.run(req['cmd'], cwd=req['cwd'], capture_output=True, text=True, encoding='utf-8',
                           env={**os.environ, **req['env']})
        with open(inbox + '.out', 'w', encoding='utf-8') as f:
            json.dump({'code': r.returncode, 'out': r.stdout, 'err': r.stderr}, f)
    time.sleep(0.05)
'''


class Windows(Workspace):
    """Two agent windows on a host with no session variable. Each window is its own long-lived process."""

    def window(self, name):
        import os
        import shutil
        import subprocess
        import sys
        import time
        exe = self.parent / (name + Path(sys.executable).suffix)
        shutil.copy(sys.executable, exe)
        # A copied python.exe finds its DLLs next to itself or on PATH, and a standalone build such as uv's is not there.
        for dll in Path(sys.executable).parent.glob('*.dll'):
            if not (self.parent / dll.name).exists():
                shutil.copy(dll, self.parent / dll.name)
        loop = self.parent / 'host_loop.py'
        loop.write_text(HOST_LOOP, encoding='utf-8')
        inbox = self.parent / (name + '.inbox')
        env = {k: v for k, v in os.environ.items() if k not in VARS_TO_CLEAR}
        env['PYTHONHOME'] = sys.base_prefix
        proc = subprocess.Popen([str(exe), str(loop), str(inbox)], env=env)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        for _ in range(200):
            if inbox.exists():
                break
            time.sleep(0.05)
        return proc, inbox

    def run_in(self, inbox, *args, expect=0):
        import sys
        import time
        out = Path(str(inbox) + '.out')
        out.unlink(missing_ok=True)
        env = {'PYTHONUTF8': '1', 'WS_IMPORT': '0', **{n: '' for n in VARS_TO_CLEAR}}
        inbox.write_text(json.dumps({'cmd': [sys.executable, str(self.root / '.agents/tools/ws.py'), '--root',
                                             str(self.root), *args], 'cwd': str(self.root), 'env': env}), encoding='utf-8')
        for _ in range(1200):
            if out.exists() and out.read_text(encoding='utf-8'):
                data = json.loads(out.read_text(encoding='utf-8'))
                self.assertEqual(data['code'], expect, f'{args}\n{data["out"]}\n{data["err"]}')
                return data['out'] + data['err']
            time.sleep(0.05)
        self.fail('window did not answer')

    def test_a_live_window_is_not_taken_over_and_an_exited_one_is(self):
        _, inbox_a = self.window('hosta')
        b, inbox_b = self.window('hostb')
        self.run_in(inbox_a, 'init', '--goal', 'Demo')
        self.assertIn('other sessions are working', self.run_in(inbox_b, 'brief'))
        self.assertIn('collides with work in progress', self.run_in(inbox_b, 'start', expect=2))
        self.assertIn('from another window that is still running',
                      self.run_in(inbox_b, 'add', 'question', '--set', 'question=x', expect=2))
        self.run_in(inbox_a, 'add', 'question', '--set', 'question=owner writes')
        self.run_in(inbox_b, 'start', '--force', '--reason', 'user closed window A')
        self.assertIn('must not write', self.run_in(inbox_a, 'add', 'question', '--set', 'question=late', expect=2))
        self.assertIn('its window was still running (--force)', self.read('docs/logs/MAINTENANCE_LOG.md'))
        b.kill()
        b.wait()
        self.assertIn('has exited, so this takeover is safe', self.run_in(inbox_a, 'start'))

    def test_a_window_without_a_session_variable_cannot_claim_twice(self):
        # Two chats in one window look the same to the tool, so a second start is refused, never merged into the first.
        _, inbox = self.window('hosta')
        self.run_in(inbox, 'init', '--goal', 'Demo')
        self.assertIn('collides with work in progress', self.run_in(inbox, 'start', expect=2))
        self.run_in(inbox, 'add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y')
        self.run_in(inbox, 'checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                    '--set', 'next_acceptance=a')
        self.run_in(inbox, 'start')


class SmallFixes(Workspace):
    def test_check_with_expect_fails_when_the_output_is_wrong(self):
        self.init()
        self.write('probe.py', 'print("HTTP 404")\n')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=probe.py', '--set', 'action=Probe',
                '--set', 'acceptance=check: python probe.py expect "HTTP 200"')
        out = self.ws('verify', 'T1', '--done', '--', 'python', 'probe.py', expect=1).stdout
        self.assertIn('lacks what the acceptance expects: "HTTP 200"', out)
        self.write('probe.py', 'print("HTTP 200")\n')
        self.ws('verify', 'T1', '--done', '--', 'python', 'probe.py')
        self.assertIn('1 expected outputs found', self.read('docs/state/HANDOFF.md'))
        self.save()
        self.ready()

    def test_check_without_expect_is_named_exit_only(self):
        self.init()
        self.write('build.py', 'print("built")\n')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=build.py', '--set', 'action=Build',
                '--set', 'acceptance=check: python build.py')
        out = self.ws('verify', 'T1', '--done', '--', 'python', 'build.py').stdout
        self.assertIn('proves only that the command exited 0', out)
        self.assertIn('no expected output', self.read('docs/state/HANDOFF.md'))

    def test_expect_as_regular_expression(self):
        self.init()
        self.write('probe.py', 'print("size 211707 bytes")\n')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=probe.py', '--set', 'action=Probe',
                '--set', 'acceptance=check: python probe.py expect /size \\d{6} bytes/')
        self.ws('verify', 'T1', '--done', '--', 'python', 'probe.py')

    def test_source_works_the_same_on_every_table(self):
        self.init()
        self.ws('add', 'decision', '--set', 'decision=Use SQLite', '--set', 'reason=one file', '--source', 'user 2026-11-05')
        self.assertIn('| user 2026-11-05 |', self.read('docs/state/DESIGN.md'))
        self.ws('add', 'preference', '--set', 'preference=Reply in Chinese', '--source', 'user 2026-11-05')
        self.ws('add', 'requirement', '--set', 'requirement=Export', '--set', 'acceptance=x', '--set', 'source=user 2026-11-05')
        self.assertIn('user 2026-11-05', self.read('docs/logs/REQUIREMENT_LOG.md').split('| R2 |')[1].split('\n')[0])
        self.ws('add', 'decision', '--set', 'decision=Both forms', '--set', 'reason=y', '--set', 'source=user note', '--source', 'user')
        self.assertIn('| Both forms | y | user note |', self.read('docs/state/DESIGN.md'))

    def test_card_names_several_current_tasks(self):
        self.planned()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=b.py', '--set', 'action=Second',
                '--set', 'acceptance=python -m unittest test_demo')
        self.ws('card', '--set', 'current_task=T1, T2')
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo')
        self.assertIn('| current_task | T2 |', self.read('docs/state/HANDOFF.md'))
        self.assertIn('invalid ID list', self.ws('card', '--set', 'current_task=T1 and T2', expect=2).stderr)

    def test_read_only_commands_write_no_cache(self):
        self.init()
        self.save()
        cache = self.root / '.agents/cache/fingerprint.json'
        cache.unlink(missing_ok=True)
        self.write('new.py', 'x = 1\n')
        for command in ('brief', 'status', 'lint'):
            self.ws(command)
        self.ws('check', expect=1)
        self.assertFalse(cache.exists())
        self.ws('start')
        self.assertTrue(cache.exists())

    def test_a_count_in_the_stop_point_must_come_from_evidence(self):
        self.done()
        out = self.ws('checkpoint', '--stop', 'T1 done, live acceptance 18/18', '--next', 'next').stdout
        self.assertIn('states 18/18, which no evidence file reports', out)
        self.ws('start')
        out = self.ws('checkpoint', '--stop', 'T1 done, 1/1 passed', '--next', 'next').stdout
        self.assertNotIn('which no evidence file reports', out)


class Handoff(Workspace):
    """What a new session meets at the moment it needs it, and the shortcut that keeps every fact."""

    LONG = Writing.LONG

    def test_deferred_question_needs_a_default_and_is_not_asked_again(self):
        self.init()
        self.ws('add', 'question', '--set', 'question=Cache size limit?')
        self.assertIn('needs the default', self.ws('set', 'Q1', '--set', 'status=deferred', expect=2).stderr)
        self.ws('set', 'Q1', '--set', 'status=deferred', '--set', 'answer=default: 500 MB until the user decides')
        brief = self.ws('brief').stdout
        self.assertIn('Proceeding on defaults', brief)
        self.assertIn('500 MB', brief)
        self.assertNotIn('- Q1: Cache size limit?\n', brief.split('## Open questions')[1].split('Proceeding')[0])
        self.ws('add', 'question', '--set', 'question=Show the export button to guests?')
        self.assertIn('block work until the user answers: Q2', self.ws('turn').stdout)

    def test_move_detail_keeps_the_full_row_and_requires_a_link(self):
        self.init()
        self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56')
        refused = self.ws('set', 'D1', '--move-detail', 'docs/reports/gateway.md', '--set', 'decision=Adopt the gateway',
                          expect=2).stderr
        self.assertIn('must name docs/reports/gateway.md', refused)
        self.assertIn('under docs/specs/ or docs/reports/', self.ws('set', 'D1', '--move-detail', 'notes.md', '--set',
                                                                    'decision=x notes.md', expect=2).stderr)
        self.ws('set', 'D1', '--move-detail', 'docs/reports/gateway.md',
                '--set', 'decision=Adopt the gateway; one P1 open (T57). Detail: docs/reports/gateway.md')
        self.assertIn('211,707 B', self.read('docs/reports/gateway.md'))
        self.assertNotIn('211,707 B', self.read('docs/state/DESIGN.md'))
        self.assertNotIn('D1 decision is', self.ws('lint').stdout)

    def test_checkpoint_names_rows_with_a_fix(self):
        self.init()
        self.ws('add', 'decision', '--set', f'decision={self.LONG}', '--set', 'reason=audit T56', '--set', 'source=T56')
        out = self.ws('checkpoint', '--keep', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                      '--set', 'next_acceptance=a').stdout
        self.assertIn('fix: ws set D1 --move-detail', out)
        self.assertIn('hard for a new session to read', self.ws('brief').stdout)

    def test_start_names_the_resume_section(self):
        self.init()
        self.save()
        self.write('half.py', 'x = 1\n')
        self.assertIn('"Resume"', self.ws('start').stdout)

    def test_one_conversation_keeps_one_writer_label_across_checkpoints(self):
        # Drill: a session that checkpointed and ran ws start again showed up as three sessions in the brief.
        a = {'CLAUDE_CODE_SESSION_ID': '', 'CODEX_SESSION_ID': '', 'ZCODE_SESSION_ID': '', 'KIRO_SESSION_ID': '',
             'WS_SESSION_ID': 'conversation-a'}
        first = json.loads(self.ws('init', '--goal', 'Demo', env=a).stdout.splitlines()[0])['writer']
        self.ws('add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y', env=a)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                '--set', 'next_acceptance=a', env=a)
        self.assertEqual(json.loads(self.ws('start', env=a).stdout.splitlines()[0])['writer'], first)
        other = {**a, 'WS_SESSION_ID': 'conversation-b'}
        self.ws('checkpoint', '--stop', 's', '--next', 'n', env=a)
        self.assertNotEqual(json.loads(self.ws('start', env=other).stdout.splitlines()[0])['writer'], first)

    def test_goal_changes_in_place_and_logs_the_old_text(self):
        self.init()
        self.ws('goal', 'Build a small tested demo that also deletes', '--source', 'user 2026-11-05')
        self.assertIn('also deletes', self.read('docs/state/REQUIREMENTS.md'))
        log = self.read('docs/logs/REQUIREMENT_LOG.md')
        self.assertIn('was: Build a small tested demo', log)
        self.assertIn('user 2026-11-05', log)

    def test_contract_lists_sections_to_read_before_acting(self):
        text = self.read('AGENTS.md')
        for section in ('"Resume"', '"Ownership"', '"Evidence"', '"Recover"', 'Short rows, complete records'):
            self.assertIn(section, text.split('## Read before you act')[1])
        self.assertLess(len(text.encode('utf-8')), 14000)
        self.assertLessEqual(text.count('\n'), 200)


class Credentials(Workspace):
    """Credentials are kept the way the user decided; until then the agent asks before writing one."""

    FAKE = 'Hunter2Fake9x'

    def rule(self, value):
        text = self.read('docs/state/ARCHITECTURE.md').replace('"credentials": "ask"', f'"credentials": "{value}"')
        self.write('docs/state/ARCHITECTURE.md', text)

    def test_ask_rule_redacts_and_tells_the_agent_to_ask(self):
        self.init()
        out = self.ws('add', 'question', '--set', f'question=Server login? password: {self.FAKE}')
        self.assertNotIn(self.FAKE, self.read('docs/state/REQUIREMENTS.md'))
        self.assertIn('ask the user how credentials are kept', out.stderr)
        hook = json.loads(self.ws('turn', '--hook', 'claude', stdin=json.dumps({'prompt': f'password: {self.FAKE}'})).stdout)
        self.assertIn('ask the user once', hook['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('rotat', json.dumps(hook).lower())

    def test_plain_credentials_are_kept_as_written(self):
        self.init()
        self.rule('plain')
        self.ws('add', 'preference', '--set', 'preference=Server passwords go in docs/guides/server.md as written',
                '--source', 'user 2026-11-05')
        self.ws('add', 'question', '--set', f'question=Server login? password: {self.FAKE}')
        self.assertIn(self.FAKE, self.read('docs/state/REQUIREMENTS.md'))
        self.write('docs/guides/server.md', f'# Server\n\nLogin password: {self.FAKE}\n')
        self.assertNotIn('looks like a credential', self.ws('check', expect=1).stdout)
        hook = json.loads(self.ws('turn', '--hook', 'claude', stdin=json.dumps({'prompt': f'password: {self.FAKE}'})).stdout)
        self.assertNotIn('systemMessage', hook)

    def test_redact_rule_keeps_values_out_without_asking_again(self):
        self.init()
        self.rule('redact')
        out = self.ws('add', 'question', '--set', f'question=Server login? password: {self.FAKE}')
        self.assertNotIn(self.FAKE, self.read('docs/state/REQUIREMENTS.md'))
        self.assertIn('keeps credentials out of files', out.stderr)

    def test_an_unknown_rule_is_refused(self):
        self.init()
        self.rule('maybe')
        self.assertIn('WORKSPACE credentials must be', self.ws('check', expect=1).stdout + self.ws('check', expect=1).stderr)

    def test_contract_no_longer_tells_the_agent_to_push_rotation(self):
        text = self.read('AGENTS.md').lower()
        self.assertNotIn('rotate', text)
        self.assertIn('credentials are kept the way the user decided', text)


class Parallel(Workspace):
    """Sessions that claim tasks with separate paths and resources work at once; overlapping claims are refused."""

    def env(self, name):
        return {'CLAUDE_CODE_SESSION_ID': '', 'CODEX_SESSION_ID': '', 'ZCODE_SESSION_ID': '', 'KIRO_SESSION_ID': '',
                'QWEN_CODE_SESSION_ID': '', 'WS_SESSION_ID': name}

    def setUp(self):
        super().setUp()
        self.a, self.b, self.c = self.env('win-a'), self.env('win-b'), self.env('win-c')
        test = 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n'
        self.write('a/test_a.py', test)
        self.write('b/test_b.py', test)
        self.ws('init', '--goal', 'Demo', env=self.a)
        self.ws('add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y', env=self.a)
        for scope, src in (('a/', 'a'), ('b/ resource:vps/svc', 'b'), ('a/test_a.py', 'a'), ('new:docs/x resource:vps/svc', 'a')):
            self.ws('add', 'task', '--set', 'requirements=R1', '--set', f'scope={scope}', '--set', f'action=Work {src}',
                    '--set', f'acceptance=python -m unittest discover -s {src}', env=self.a)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', '--set', 'phase=p', '--set', 'risks=r',
                '--set', 'next_acceptance=a', env=self.a)
        self.ws('start', '--task', 'T1', env=self.a)

    def test_separate_tasks_run_in_parallel_and_both_save(self):
        self.assertIn('Claimed T2', self.ws('start', '--task', 'T2', env=self.b).stdout)
        self.ws('verify', 'T2', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'b', env=self.b)
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'a', env=self.a)
        self.ws('checkpoint', '--keep', '--stop', 'T2 verified', '--next', 'deploy b', env=self.b)
        self.assertIn('T2 verified', self.read('docs/state/HANDOFF.md').split('Parallel sessions')[1])
        self.assertIn('Parallel:', self.ws('brief', env=self.c).stdout)
        self.ws('checkpoint', '--stop', 'T2 done', '--next', 'nothing left', env=self.b)
        self.assertIn('READY', self.ws('checkpoint', '--stop', 'T1 done', '--next', 'T3', env=self.a).stdout)
        self.assertIn('| parallel claim |', self.read('docs/logs/MAINTENANCE_LOG.md'))

    def test_overlapping_paths_or_a_shared_resource_are_refused(self):
        self.assertIn('holds paths a', self.ws('start', '--task', 'T3', env=self.c, expect=2).stderr)
        self.ws('start', '--task', 'T2', env=self.b)
        self.assertIn('holds resource vps/svc', self.ws('start', '--task', 'T4', env=self.c, expect=2).stderr)

    def test_force_with_a_reason_overrides_and_is_logged(self):
        self.ws('start', '--task', 'T3', '--force', '--reason', 'user: T1 window is idle', env=self.c)
        log = self.read('docs/logs/MAINTENANCE_LOG.md')
        self.assertIn('| parallel claim forced |', log)
        self.assertIn('user: T1 window is idle', log)

    def test_a_session_cannot_touch_another_sessions_task_or_the_whole_workspace(self):
        self.ws('start', '--task', 'T2', env=self.b)
        self.assertIn('T1 belongs to', self.ws('set', 'T1', '--set', 'status=blocked', '--set', 'reason=x', env=self.b, expect=2).stderr)
        self.assertIn('T1 belongs to', self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', 'discover', '-s', 'a',
                                               env=self.b, expect=2).stderr)
        self.assertIn('changes the whole workspace', self.ws('compact', env=self.b, expect=2).stderr)
        self.assertIn('card belongs to the main session', self.ws('card', '--set', 'risks=x', env=self.b, expect=2).stderr)
        self.ws('add', 'question', '--set', 'question=Anyone may add rows', env=self.b)
        self.ws('note', 'b is halfway', env=self.b)

    def test_main_release_while_another_works_is_not_ready(self):
        self.ws('start', '--task', 'T2', env=self.b)
        out = self.ws('checkpoint', '--stop', 'T1 paused', '--next', 'T3', env=self.a).stdout
        self.assertIn('NOT READY', out)
        self.assertIn('still working on T2', out)

    def test_the_last_session_to_leave_writes_the_card_and_seals(self):
        # Drill: B left last; HANDOFF.md showed as unsaved and the card kept A's stale next step.
        self.ws('start', '--task', 'T2', env=self.b)
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'a', env=self.a)
        self.ws('checkpoint', '--stop', 'T1 done', '--next', 'T2 and T3 remain', env=self.a)
        self.ws('verify', 'T2', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'b', env=self.b)
        out = self.ws('checkpoint', '--stop', 'T2 done', '--next', 'T3 remains', env=self.b).stdout
        self.assertIn('READY. You were the last session working', out)
        handoff = self.read('docs/state/HANDOFF.md')
        self.assertIn('| next_step | T3 remains |', handoff)
        self.assertNotIn('Parallel sessions', handoff)
        self.assertIn('- none', self.ws('brief', env=self.c).stdout.split('## Unsaved changes')[1].split('##')[0])
        self.ready()

    def test_a_released_parallel_session_starts_afresh(self):
        self.ws('start', '--task', 'T2', env=self.b)
        self.ws('checkpoint', '--stop', 'T2 paused', '--next', 'resume T2', env=self.b)
        self.ws('checkpoint', '--stop', 'T1 paused', '--next', 'resume T1', env=self.a)
        data = json.loads(self.ws('start', env=self.b).stdout.splitlines()[0])
        self.assertFalse(data.get('parallel'))
        self.assertFalse(data.get('resumed'))

    def test_a_requirement_with_an_open_task_is_not_counted_verified(self):
        # Drill: R1 needs subtract and multiply; T1 (subtract) done and T3 (multiply) open showed "2/2".
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'a', env=self.a)
        self.assertIn('not yet: R1', self.ws('brief', env=self.a).stdout)

    def test_edits_inside_a_verified_task_scope_are_not_unregistered_work(self):
        # Drill: B verified T2 in b/ while claiming in parallel; the brief still said b/ edits were unregistered.
        self.ws('start', '--task', 'T2', env=self.b)
        self.write('b/test_b.py', self.read('b/test_b.py') + '\n# edited for T2\n')
        self.ws('verify', 'T2', '--done', '--', 'python', '-m', 'unittest', 'discover', '-s', 'b', env=self.b)
        self.ws('checkpoint', '--stop', 'T2 done', '--next', 'n', env=self.b)
        self.ws('checkpoint', '--stop', 'T1 paused', '--next', 'T1', env=self.a)
        self.assertNotIn('changed since the work was last registered', self.ws('brief', env=self.c).stdout)
        self.write('elsewhere.py', 'x = 1\n')
        self.ws('start', env=self.c)
        self.ws('checkpoint', '--stop', 's', '--next', 'n', env=self.c)
        self.assertIn('elsewhere.py', self.ws('brief', env=self.c).stdout)

    def test_a_task_with_no_path_holds_the_whole_tree(self):
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=Login',
                '--set', 'acceptance=check: python -c "print(1)" expect "1"', env=self.a)
        self.assertIn('the whole tree', self.ws('start', '--task', 'T5', env=self.b, expect=2).stderr)


if __name__ == '__main__':
    unittest.main()
