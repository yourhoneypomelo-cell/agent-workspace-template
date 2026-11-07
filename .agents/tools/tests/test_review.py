"""Regression tests for the 3.5.0 red-team and blue-team findings."""
import json
import time
import unittest

from support import Workspace


class Review(Workspace):
    def task(self, acceptance):
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=y',
                '--set', f'acceptance={acceptance}')

    def test_evidence_of_another_run_cannot_mark_a_task_done(self):
        self.planned()
        self.write('test_easy.py', 'import unittest\n\n\nclass E(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
        proof = self.json('verify', '--', 'python', '-m', 'unittest', 'test_easy')['evidence']
        text = self.read('docs/state/TASKS.md').replace('| T1 | todo |', '| T1 | done |').replace('| none | none | none |', f'| none | {proof} | none |')
        self.write('docs/state/TASKS.md', text)
        self.assertIn('verified other tasks', self.save(expect=2).stderr)

    def test_empty_or_piped_acceptance_is_refused(self):
        self.init()
        self.passing_test()
        self.task('check:')
        self.assertIn('no acceptance command', self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo', expect=2).stderr)
        self.task('check: python a.py && python b.py')
        self.assertIn('shell pipeline', self.ws('verify', 'T2', '--done', '--kind', 'check', '--', 'python', 'a.py', '&&', 'python', 'b.py', expect=2).stderr)

    def test_windows_paths_in_acceptance_match(self):
        self.init()
        self.write('tests/__init__.py', '')
        self.write('tests/test_a.py', 'import unittest\n\n\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n')
        self.task(r'python -m unittest tests\test_a.py')
        run = self.ws('verify', 'T1', '--', 'python', '-m', 'unittest', r'tests\test_a.py', expect=None)
        self.assertNotIn('names the acceptance', run.stderr)

    def test_secrets_in_verify_arguments_and_because_are_redacted(self):
        self.planned()
        self.ws('verify', 'T1', '--because', 'token Bearer eyJhbGciOiJIUzI1NiJ9abcdefgh', '--', 'python', '-c', 'print(1)',
                '--password', 'Hunter2xyz9', expect=None)
        text = ''.join(p.read_text(encoding='utf-8') for p in (self.root / 'docs').rglob('*') if p.is_file())
        self.assertNotIn('Hunter2xyz9', text)
        self.assertNotIn('eyJhbGciOiJIUzI1NiJ9abcdefgh', text)

    def test_reconcile_answers_the_nudge_and_bad_payloads_never_fail(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"credentials": "ask"', '"credentials": "ask", "stop_nudge": true')
        self.assertIn('"stop_nudge": true', text)
        self.write('docs/state/ARCHITECTURE.md', text)
        self.capture_and_turn('s1', 'use SQLite')
        mid = [l.split()[0] for l in self.ws('reconcile').stdout.splitlines() if l.startswith('m')][0]
        self.ws('reconcile', mid, '--reason', 'chat: already recorded elsewhere')
        self.assertEqual(self.stop('s1'), '')
        self.capture_and_turn('s1', 'and PDF')
        self.assertEqual(self.stop('s2'), '', 'a stop from another session is not nudged')
        self.capture_and_turn('s1', 'and CSV')
        self.assertEqual(self.stop('s1', loop_count='1'), '')
        self.capture_and_turn('s1', 'and XML')
        self.assertEqual(self.stop('s1', status='aborted'), '')

    def capture_and_turn(self, session, prompt):
        self.ws('turn', '--hook', 'kiro', stdin=json.dumps({'session_id': session, 'prompt': prompt}))

    def stop(self, session, **extra):
        return self.ws('capture', '--host', 'claude', '--event', 'Stop',
                       stdin=json.dumps({'session_id': session, **extra})).stdout

    def test_rebrief_after_compaction_stays_under_the_limit(self):
        self.init()
        for n in range(40):
            self.ws('add', 'question', '--set', f'question=Question {n} ' + 'x' * 200)
        self.ws('capture', '--host', 'gemini', '--event', 'PreCompress', stdin='{}')
        text = json.loads(self.ws('turn', '--hook', 'gemini', stdin='{}').stdout)['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(text), 9000)
        self.assertIn('Brief cut', text)

    def test_spaces_cannot_stall_redaction(self):
        from wslib.coverage import redact_pasted
        started = time.monotonic()
        for text in ('admin' + ' ' * 3000 + 'x', 'ssh' + ' ' * 3000, 'a@b.c' + ' ' * 3000 + 'x'):
            redact_pasted(text)
        self.assertLess(time.monotonic() - started, 2)

    def test_redaction_keeps_developer_text_and_catches_env_secrets(self):
        from wslib.coverage import redact_pasted
        for text in ('key: value2', 'api_key: config.apiKey2', 'feature/Login2FA-Flow', 'admin dashboard2',
                     'pass test_parse_v2', 'primary_key: user_id12', 'csrf_token: abc123XYZ789',
                     'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='):
            self.assertEqual(redact_pasted(text), text)
        for text, secret in (('PGPASSWORD=Hunter2x9', 'Hunter2x9'), ('my key AbCdEfGh1234IjKlMnOp5678QrSt', 'AbCdEfGh1234'),
                             ('ssh root@1.2.3.4 password hunter2x9', 'hunter2x9')):
            self.assertNotIn(secret, redact_pasted(text))

    def test_short_keys_and_login_lines(self):
        # Synthetic values only. Short unlabeled keys in user text, and login lines.
        from wslib.coverage import redact, redact_pasted
        for text, secret in (('here Qz8mN2kL7pXwR4tY6vB1cD', 'Qz8mN2kL7pXwR4tY6vB1cD'),
                             ('Xk7pQ2mLw9RtZb4N 写进环境变量', 'Xk7pQ2mLw9RtZb4N'),
                             ('ssh admin@host Xk7pQ2mLw9', 'Xk7pQ2mLw9'), ('server 192.168.1.20 密码 Xk7pQ2mLw9', 'Xk7pQ2mLw9'),
                             ('run it with --password Hunter2xyz9', 'Hunter2xyz9')):
            self.assertNotIn(secret, redact_pasted(text), text)
        for text in ('Reset the password, then run session kiro-20261101 again', 'password policy: build v2 with Python311',
                     'Formula C6H12O6Na2Cl2K3 in buffer', 'see https://example.com/a/Qz8mN2kL7pXwR4tY6vB1cD',
                     'ref #Qz8mN2kL7pXwR4tY6vB1cD', 'useEffectCallback2Handler', 'mail me at a@b.com, thanks',
                     'user@example.com:8080', 'git@github.com:owner/repo.git', 'call_Qz8mN2kL7pXwR4tY6vB',
                     'version Win11Pro23H2x64', 'sha256 3f2a9c1b7d4e5f60', 'fake@example.com\tFakeName42',
                     'see (Qz8mN2kL7pXwR4tY6vB) and [Xk7pQ2mLw9RtZb4N]', 'id:Xk7pQ2mLw9RtZb4N'):
            self.assertEqual(redact_pasted(text), text, text)
        # Short keys apply to user messages only; state rows go through redact(), which keeps them.
        self.assertEqual(redact('Use Qz8mN2kL7pXwR4tY6vB1cD as the fixture name'), 'Use Qz8mN2kL7pXwR4tY6vB1cD as the fixture name')

    def test_prompt_hook_names_a_pasted_credential_without_the_value(self):
        self.init()
        fake = 'Hunter2Fake9x'
        for host in ('claude', 'codex', 'cursor'):
            run = self.ws('turn', '--hook', host, stdin=json.dumps({'prompt': f'the db password: {fake}', 'session_id': 's'}))
            self.assertNotIn(fake, run.stdout + run.stderr)
            data = json.loads(run.stdout)
            shown = data.get('systemMessage') or data.get('user_message')
            context = data.get('additional_context') or data['hookSpecificOutput']['additionalContext']
            self.assertIn('credential (password)', shown, host)
            self.assertIn('ask the user once how this project keeps credentials', context, host)
            self.assertNotIn('rotate', context.lower(), host)
        quiet = json.loads(self.ws('turn', '--hook', 'claude', stdin=json.dumps({'prompt': 'reset the password flow'})).stdout)
        self.assertNotIn('systemMessage', quiet)
        cache = self.root / '.agents/cache'
        self.assertNotIn(fake, ''.join(p.read_text(encoding='utf-8', errors='replace') for p in cache.rglob('*') if p.is_file()))

    def test_raw_transcript_copy_drops_pasted_tokens(self):
        self.init()
        transcript = self.parent / 's.jsonl'
        transcript.write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'key AbCdEfGh1234IjKlMnOp5678QrSt'}}) + '\n', encoding='utf-8')
        self.ws('capture', '--host', 'claude', '--event', 'Stop', stdin=json.dumps({'session_id': 'r', 'transcript_path': str(transcript)}))
        self.assertNotIn('AbCdEfGh1234IjKlMnOp5678QrSt', self.read('docs/chats/claude/raw/r.jsonl'))

    def test_only_retired_requirements_is_not_ready(self):
        self.init()
        self.ws('set', 'R1', '--set', 'status=removed', '--set', 'reason=user dropped it')
        self.assertIn('NOT READY', self.save().stdout)

    def test_credential_in_a_state_file_blocks_ready(self):
        self.init()
        self.write('docs/specs/demo/requirements.md', '# Requirement detail: demo\n\npassword: Hunter2Hunter2\n')
        self.assertIn('NOT READY', self.save().stdout)

    def test_coverage_survives_compact(self):
        self.done()
        self.save()
        self.ws('start')
        self.ws('compact')
        self.assertIn('Requirements verified: 1/1', self.ws('brief').stdout)

    def test_lint_leaves_ordinary_technical_prose_alone(self):
        from wslib import lint
        for text in ('The proxy serves as a cache.', 'Requests time out, reflecting the upstream limit.',
                     'In summary mode the CLI prints totals.', 'The schema has been updated to v3.', 'Ports: 8080; 8443; 9000.'):
            self.assertEqual(lint.check('# T\n\n' + text + '\n', 'x.md'), [], text)
        self.assertTrue(lint.check('# T\n\nThis serves as a testament to care.\n', 'x.md'))

    def test_rule_file_checks(self):
        self.init()
        self.write('CODEBUDDY.md', '# Rules\n\nUse tabs.\n')
        run = self.ws('check', expect=None)
        self.assertIn('CODEBUDDY.md exists', run.stdout + run.stderr)

    def test_codex_override_and_long_nested_chain_are_reported(self):
        self.init()
        self.assertNotIn('AGENTS.override.md', self.ws('check', expect=None).stdout)
        self.write('src/AGENTS.override.md', '# Override\n')
        self.write('src/deep/AGENTS.md', '# Deep rules\n\n' + 'Keep this rule short.\n' * 1200)
        out = self.ws('check', expect=None).stdout
        self.assertIn('src/AGENTS.override.md exists; Codex reads it instead', out)
        self.assertIn('down to src/deep/AGENTS.md total', out)

    def test_invisible_characters_do_not_hide_credentials(self):
        from wslib.coverage import credential_kinds, find_secrets, redact
        key = 'sk-proj-abcdefghij\u200bklmnopqrstuvwxyz0123456789'
        self.assertEqual(redact('key ' + key), 'key [REDACTED]')
        self.assertEqual(redact('pass\u00adword: Hunter2Hunter2!'), 'pass\u00adword: [REDACTED]')
        self.assertEqual(find_secrets('ghp_abcdefghijklmnop\u200dqrstuvwxyz0123456789'), [(1, 'GitHub token')])
        self.assertIn('API key (sk-)', credential_kinds(key))
        family = 'family \U0001F468\u200d\U0001F469\u200d\U0001F467 photo'
        self.assertEqual(redact(family), family)

    def test_raw_copy_drops_encrypted_host_blobs_even_when_plain(self):
        from wslib import coverage
        from wslib.core import CREDENTIALS
        blob = 'gAAAAAB' + 'x9Y' * 200
        lines = json.dumps({'type': 'response_item', 'payload': {'type': 'compaction', 'encrypted_content': blob}})
        lines += '\n' + json.dumps({'type': 'note', 'text': 'password: Hunter2Hunter2!'})
        for setting in ('ask', 'plain'):
            token = CREDENTIALS.set(setting)
            try:
                out = coverage.redact_json_lines(lines)
            finally:
                CREDENTIALS.reset(token)
            self.assertNotIn(blob, out, setting)
            self.assertIn('[removed: encrypted host data]', out)
            self.assertNotIn('Hunter2Hunter2!', out, setting)  # D2: "plain" keeps credentials only in named files
        plain = json.dumps({'a': 1})
        token = CREDENTIALS.set('plain')
        try:
            self.assertEqual(coverage.redact_json_lines(plain), plain)
        finally:
            CREDENTIALS.reset(token)

    def test_letters_only_passwords_are_removed_and_prose_is_kept(self):
        from wslib.coverage import redact
        for text in ('password = hunterhunter', 'the password is hunterhunter', 'pwd=bluesky', 'PASSWORD: Sunflower',
                     '密码：hunterhunter', '密码是hunterhunter', 'my password hunterhunter',
                     '密码 hunterhunter', 'passphrase correcthorse', 'password: abcdef'):
            self.assertIn('[REDACTED]', redact(text), text)
        for text in ('password reset flow', 'password manager', 'password policy', 'Password: Required',
                     'password: <your password>', 'password: changeme', 'password = PASSWORD', 'password: ${DB_PASS}',
                     'the password is stored hashed', 'The password is correct', 'password hashing uses bcrypt',
                     'password = os.environ', 'password is required', 'A pasted password stayed out of every file',
                     '[1Password: Sunflower]', 'password field validation'):
            self.assertEqual(redact(text), text, text)


if __name__ == '__main__':
    unittest.main()
