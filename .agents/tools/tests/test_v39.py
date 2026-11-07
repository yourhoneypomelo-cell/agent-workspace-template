"""3.9.0: the system file lock, the permission table, message timing and IDs, redaction, chat import and credentials
as the owner decided, and hook paths. Each test fails on 3.8.0 unless its comment says it guards a behavior."""
import errno
import json
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


def claude_lines(*messages):
    """A Claude Code transcript from (role, text, time) triples."""
    return ''.join(json.dumps({'type': role, 'message': {'role': role, 'content': text}, 'timestamp': stamp},
                              ensure_ascii=False) + '\n' for role, text, stamp in messages)


OLD_TRANSCRIPT = ('# Transcript claude s1\n\n## 1. user 2026-11-01T01:00:00Z\n\nKeep the CSV export\n\n'
                  '## 2. assistant 2026-11-01T01:00:05Z\n\nok\n\n## 3. user 2026-11-01T01:01:00Z\n\n可以\n')


class Messages(Workspace):
    def prompt(self, text, session='s1', host='claude'):
        payload = {'session_id': session, 'prompt': text}
        return self.ws('turn', '--hook', host, stdin=json.dumps(payload, ensure_ascii=False)).stdout

    def stop(self, *messages, session='s1'):
        transcript = self.parent / f'{session}.jsonl'
        transcript.write_text(claude_lines(*messages), encoding='utf-8')
        self.ws('capture', '--host', 'claude', '--event', 'Stop',
                stdin=json.dumps({'session_id': session, 'transcript_path': str(transcript)}))

    def open_ids(self):
        return [line.split()[0] for line in self.ws('reconcile').stdout.splitlines() if line.startswith('m')]

    def old_transcript(self):
        self.write('docs/chats/claude/s1.md', OLD_TRANSCRIPT)
        index = self.read('docs/chats/INDEX.md').rstrip('\n')
        self.write('docs/chats/INDEX.md', index + '\n| 2026-11-01 | claude | s1 | 3 | docs/chats/claude/s1.md | none |\n')

    def test_24_ready_survives_the_stop_hook_that_copies_the_turn(self):
        # Claude Code saved a turn only in its Stop hook, after the checkpoint had released the workspace.
        self.done()
        self.save()
        self.ws('start')
        said = self.prompt('Add a dark mode toggle')
        mid, = self.open_ids()
        self.assertIn(f'saved as {mid}', said)
        self.ws('reconcile', mid, '--ids', 'R1')
        self.save()
        self.ready()
        self.stop(('user', 'Add a dark mode toggle', '2026-11-07T01:00:00Z'),
                  ('assistant', 'Recorded as R1.', '2026-11-07T01:00:05Z'))
        self.ready()
        self.assertIn(f'## 1. user 2026-11-07T01:00:00Z [{mid}]', self.read('docs/chats/claude/s1.md'))
        self.prompt('thanks')
        self.assertIn('| docs/chats/claude/s1.md | docs/chats/claude/raw/s1.jsonl |', self.read('docs/chats/INDEX.md'))

    def test_24_a_message_saved_after_the_seal_waits_for_the_next_session(self):
        self.done()
        self.save()
        self.prompt('Also add a footer with the version', host='kiro')
        self.ready()
        self.assertIn('saved after the last checkpoint', self.ws('check').stdout)
        self.assertIn('not reconciled', self.ws('brief').stdout)
        self.ws('start')
        mid, = self.open_ids()
        self.ws('add', 'requirement', '--set', 'requirement=Footer shows the version', '--set', 'acceptance=seen')
        self.ws('reconcile', mid, '--ids', 'R2')
        self.save()
        self.ready()

    def test_24_an_upgrade_lists_the_open_messages_as_a_seal_does(self):
        # A seal of 3.8 lists none, so after an upgrade every new message blocked READY until the next checkpoint.
        from wslib import ops, upgrade
        self.done()
        self.save()
        state = core.state_of(self.root)
        old = {k: v for k, v in core.checkpoint_of(self.root, state).items() if k != 'messages_open'}
        state['checkpoint'] = ops.write_checkpoint(self.root, old)
        core.save_state(self.root, state)
        upgrade.rebaseline(self.root, [], 'test: upgrade', upgraded={'from': '3.8.0', 'to': '3.9.0', 'at': 'now'})
        self.prompt('Also add a footer with the version', host='kiro')
        self.ready()

    def test_24_the_same_sentence_in_two_sessions_is_reconciled_in_each(self):
        self.init()
        for session in ('s1', 's2'):
            self.prompt('Use PostgreSQL for storage', session=session, host='kiro')
        first, second = self.open_ids()
        self.ws('reconcile', first, '--ids', 'R1')
        self.assertEqual(self.open_ids(), [second])

    def test_24_marks_of_3_8_stay_valid_when_the_transcript_is_written_again(self):
        # Guards the upgrade: a transcript of 3.8 has no IDs in its headings, and its marks name the hash of the text.
        self.init()
        self.old_transcript()
        mid, = self.open_ids()
        self.ws('reconcile', mid, '--ids', 'R1')
        self.stop(('user', 'Keep the CSV export', '2026-11-01T01:00:00Z'), ('assistant', 'ok', '2026-11-01T01:00:05Z'),
                  ('user', '可以', '2026-11-01T01:01:00Z'), ('user', 'Export to JSON too', '2026-11-01T01:02:00Z'))
        later, = self.open_ids()
        self.assertNotEqual(later, mid)

    def test_24_yes_and_no_are_reconciled_like_other_messages(self):
        # Before 3.9 a lone "no", the answer to a question, was skipped as small talk; messages saved then keep the rule.
        self.init()
        self.old_transcript()
        self.ws('reconcile', self.open_ids()[0], '--ids', 'R1')
        for text in ('no', '可以', '行'):
            self.prompt(text, host='kiro')
        self.assertEqual(len(self.open_ids()), 3)

    def test_24_the_stop_hook_keeps_the_id_when_the_host_copy_adds_to_the_typed_text(self):
        self.init()
        self.prompt('Rename calc to compute')
        mid, = self.open_ids()
        self.stop(('user', 'Rename calc to compute\n[Image #1]', '2026-11-07T01:00:00Z'))
        self.assertEqual(self.open_ids(), [mid])

    def test_24_a_transcript_missing_from_the_index_is_reported(self):
        self.init()
        self.write('docs/chats/claude/lost.md', '# Transcript claude lost\n\n## 1. user\n\nAdd an export button\n')
        out = self.ws('reconcile').stdout
        self.assertNotIn('All user messages in docs/chats/ are reconciled', out)
        self.assertIn('docs/chats/claude/lost.md', out)
        self.assertIn('not listed in docs/chats/INDEX.md', self.ws('check', expect=None).stdout)

    def test_24_reconcile_all_names_how_many_it_marks(self):
        self.init()
        for text in ('What is the build status?', 'And the tests?', 'Any open bugs?'):
            self.prompt(text, host='kiro')
        all_of = ('reconcile', 'all', '--reason', 'question: status only')
        self.assertIn('--confirm 3', self.ws(*all_of, expect=2).stderr)
        self.ws(*all_of, '--confirm', '2', expect=2)
        self.ws(*all_of, '--confirm', '3')
        self.assertEqual(self.open_ids(), [])
        self.assertIn('(reconcile all, 3 messages)', self.read('docs/logs/RECONCILE_LOG.md'))

    def test_24_the_stop_nudge_lets_a_pure_question_pass(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md')
        self.write('docs/state/ARCHITECTURE.md', text.replace('"credentials": "ask"', '"credentials": "ask", "stop_nudge": true'))
        stop = {'stdin': json.dumps({'session_id': 's1'})}
        self.prompt('What does the demo return?')
        self.assertEqual(self.ws('capture', '--host', 'claude', '--event', 'Stop', **stop).stdout, '')
        self.prompt('Make the demo return 5')
        self.assertIn('not recorded', self.ws('capture', '--host', 'claude', '--event', 'Stop', **stop).stdout)


FAKE_KEY = ('-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1234567890abcdefghijFAKEFAKE\n'
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ012345==\n-----END RSA PRIVATE KEY-----')


class Redaction(Workspace):
    def test_27_a_private_key_goes_as_one_block(self):
        # Only the BEGIN line was removed; the key lines below it stayed.
        from wslib.coverage import redact, redact_json_lines
        self.assertEqual(redact(f'key:\n{FAKE_KEY}\nend'), 'key:\n[REDACTED]\nend')
        self.assertEqual(redact(FAKE_KEY.rsplit('\n', 1)[0] + '\n\nnext line'), '[REDACTED]\n\nnext line')
        escaped = json.dumps({'type': 'note', 'text': 'here: ' + FAKE_KEY})
        self.assertNotIn('ABCDEFGHIJKLMNOP', redact_json_lines(escaped))
        self.assertNotIn('ABCDEFGHIJKLMNOP', redact(escaped))

    def test_27_invisible_characters_are_removed_before_matching_and_kept_elsewhere(self):
        # Appendix A6: the second password, hidden by a soft hyphen, was kept.
        from wslib.coverage import redact, redact_pasted
        self.assertEqual(redact('password: A1b2c3d4! and pass\u00adword: Second2!'),
                         'password: [REDACTED] and pass\u00adword: [REDACTED]')
        self.assertNotIn('defghij', redact_pasted('sk-abc\u200bdefghijklmnopqrstuvwxyz0123'))
        family = 'with the \U0001F468\u200d\U0001F469\u200d\U0001F467 family, password: Hunter2Hunter2!'
        self.assertEqual(redact(family), 'with the \U0001F468\u200d\U0001F469\u200d\U0001F467 family, password: [REDACTED]')

    def test_27_a_json_key_says_its_string_is_the_secret(self):
        # Appendix A6: both values stayed in the raw copy.
        from wslib.coverage import redact, redact_json_lines
        raw = redact_json_lines('{"password": " hunterhunter ", "secret_key": "MySuperSecret", "public_key": "ssh-rsa AAAA"}')
        self.assertEqual(json.loads(raw), {'password': '[REDACTED]', 'secret_key': '[REDACTED]', 'public_key': 'ssh-rsa AAAA'})
        self.assertEqual(redact('{"secret_key": "MySuperSecret", "token": "${TOKEN}"}'),
                         '{"secret_key": "[REDACTED]", "token": "${TOKEN}"}')

    def test_27_chinese_labels_sentences_and_command_lines(self):
        from wslib.coverage import redact
        for text, kept in (('账号admin 密码admin123', '账号admin 密码'), ('密码：123456', '密码：'),
                           ('The password for the staging server is Xk9#mPq2vL.', 'The password for the staging server is '),
                           ("sshpass -p 'S3cr3tPass!' ssh root@10.0.0.5", 'sshpass -p'),
                           ('mysql -u shop_admin -pS3cretPass1 shop', 'mysql -u shop_admin -p'),
                           ('api key 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08', 'api key ')):
            with self.subTest(text=text):
                self.assertIn('[REDACTED]', redact(text))
                self.assertTrue(redact(text).startswith(kept), redact(text))
        for text in ('密码至少8位', '密码是什么？', '账号和密码在 docs/guides/server.md', 'mysql -u root -p shop'):
            self.assertEqual(redact(text), text)

    def test_27_explanatory_text_is_left_alone(self):
        # These were replaced with [REDACTED] for good, with the original text lost.
        from wslib.coverage import redact
        for text in ('Password: minimum 8 characters', 'Release key: v2.3.1-beta', 'S3 key: exports/2026/data.csv',
                     '“Release key: v2.3.1-beta”', 'Password: at least 12 characters long'):
            self.assertEqual(redact(text), text)
        self.assertIn('[REDACTED]', redact('aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'))

    def test_27_ws_check_scans_the_saved_transcripts(self):
        self.init()
        self.write('docs/chats/claude/old.md', '# Transcript claude old\n\n## 1. user\n\nthe db password: Hunter2Fake9x\n')
        out = self.ws('check', expect=None).stdout
        self.assertIn('docs/chats/claude/old.md:5: looks like a credential (password)', out)
        self.assertNotIn('Hunter2Fake9x', out)

    def test_27_d2_plain_keeps_credentials_only_in_the_files_the_owner_names(self):
        self.init()
        text = self.read('docs/state/ARCHITECTURE.md').replace('"credentials": "ask"', '"credentials": "plain"')
        self.write('docs/state/ARCHITECTURE.md', text)
        self.assertIn('"credential_files" names no file', self.ws('check', expect=None).stdout)
        named = text.replace('"credentials": "plain"', '"credentials": "plain", "credential_files": '
                                                       '["docs/guides/*.md", "docs/state/DESIGN.md"]')
        self.write('docs/state/ARCHITECTURE.md', named)
        self.write('docs/guides/server.md', '# Server\n\nLogin password: Hunter2Fake9x\n')
        self.write('docs/specs/login/notes.md', '# Notes\n\nLogin password: Hunter2Fake9x\n')
        out = self.ws('check', expect=None).stdout
        self.assertNotIn('docs/guides/server.md:3: looks like a credential', out)
        self.assertIn('docs/specs/login/notes.md:3: looks like a credential', out)
        self.ws('add', 'question', '--set', 'question=Server login? password: Hunter2Fake9x')
        self.assertNotIn('Hunter2Fake9x', self.read('docs/state/REQUIREMENTS.md'))
        self.ws('add', 'decision', '--set', 'decision=Staging login password: Hunter2Fake9x', '--set', 'reason=user',
                '--set', 'source=user 2026-11-07')
        self.assertIn('Hunter2Fake9x', self.read('docs/state/DESIGN.md'))
        self.ws('turn', '--hook', 'kiro', stdin=json.dumps({'session_id': 'k1', 'prompt': 'password: Hunter2Fake9x'}))
        self.assertNotIn('Hunter2Fake9x', self.read('docs/chats/kiro/k1.md'))

    def test_27_ask_mode_refuses_no_write(self):
        # Guards owner decision D2: a credential in ask mode is redacted and the write goes through.
        self.init()
        done = self.ws('add', 'question', '--set', 'question=Server login? password: Hunter2Fake9x')
        self.assertIn('ask the user how credentials are kept', done.stderr)
        self.assertIn('password: [REDACTED]', self.read('docs/state/REQUIREMENTS.md'))


class ChatImport(Workspace):
    def home(self, *sessions):
        """A home folder holding Codex sessions of this project, given as (name, text, days old)."""
        home = self.parent / 'home'
        for name, text, days in sessions:
            path = home / '.codex/sessions/2026/11/07' / f'rollout-{name}.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            records = [{'type': 'session_meta', 'payload': {'id': name, 'cwd': str(self.root)}},
                       {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                             'content': [{'type': 'input_text', 'text': text}]}}]
            path.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
        if days:
            # A session written in the same second as init is older than the install: a filesystem that rounds
            # timestamps to whole seconds, as the CI runners do, cannot tell the two moments apart.
            then = time.time() - (2 if days < 0 else days * 86400)
            os.utime(path, (then, then))
        return {'HOME': str(home), 'USERPROFILE': str(home), 'WS_IMPORT': ''}

    def imported(self, env):
        return json.loads(self.ws('start', env=env).stdout.splitlines()[0])['imported_sessions']

    def set_up(self, *options, env):
        out = self.ws('init', '--goal', 'Demo', *options, env=env).stdout
        self.ws('add', 'requirement', '--set', 'requirement=Demo returns 4', '--set', 'acceptance=listed')
        self.save()
        return out

    def test_26_start_imports_nothing_until_the_user_decides(self):
        # ws start copied every chat of the folder from nine host stores, chats from before the setup included.
        env = self.home(('new', 'Use SQLite for storage', -1))
        self.assertIn('may ws start copy', self.set_up(env=env))
        self.assertIn('"chat_import": "ask"', self.read('docs/state/ARCHITECTURE.md'))
        started = self.ws('start', env=env).stdout
        self.assertEqual(json.loads(started.splitlines()[0])['imported_sessions'], {})
        self.assertIn('Chat import is not decided', started)

    def test_26_an_answer_at_init_imports_only_chats_from_after_the_setup(self):
        env = self.home(('old', 'An old chat about pricing', 30))
        self.assertNotIn('may ws start copy', self.set_up('--chat-import', 'on', env=env))
        self.home(('new', 'Use SQLite for storage', -1))
        self.assertEqual(self.imported(env), {'codex': 1})
        self.assertIn('Use SQLite', self.read('docs/chats/codex/rollout-new.md'))
        self.assertFalse((self.root / 'docs/chats/codex/rollout-old.md').exists())
        self.assertNotIn('Chat import is not decided', self.ws('check', env=env, expect=None).stdout)

    def test_26_a_git_project_is_asked_whether_git_ignores_the_chats(self):
        (self.root / '.git').mkdir()
        out = self.ws('init', '--goal', 'Demo', '--chat-import', 'off').stdout
        self.assertIn('should git ignore docs/chats/', out)
        self.assertNotIn('may ws start copy', out)

    def test_26_ignore_adds_docs_chats_to_the_project_gitignore(self):
        (self.root / '.git').mkdir()
        self.write('.gitignore', 'node_modules/')
        out = self.ws('init', '--goal', 'Demo', '--chat-import', 'off', '--chats-git', 'ignore').stdout
        self.assertNotIn('should git ignore', out)
        self.assertEqual(self.read('.gitignore'), 'node_modules/\n/docs/chats/\n')

    def test_26_ws_import_in_the_environment_decides_for_every_project(self):
        # Guards the user-level override: WS_IMPORT=0 never imports, WS_IMPORT=1 imports without asking.
        self.init()
        self.save()
        env = self.home(('new', 'Use SQLite for storage', -1))
        self.assertEqual(self.imported({**env, 'WS_IMPORT': '0'}), {})
        self.save()
        self.assertEqual(self.imported({**env, 'WS_IMPORT': '1'}), {'codex': 1})


class HookPaths(Workspace):
    def hook(self, rel, *keys):
        value = json.loads(self.read(rel))
        for key in keys:
            value = value[key]
        return value

    def run_from(self, command, folder):
        return subprocess.run(command, shell=True, cwd=folder, input=json.dumps({'session_id': 's1', 'prompt': 'hi'}),
                              capture_output=True, text=True, encoding='utf-8', env=ENV)

    def test_25_absolute_hooks_run_from_a_subfolder_of_a_path_with_spaces(self):
        from wslib import distribution
        from support import TEMPLATE
        self.root = self.parent / 'my project'
        distribution.install(TEMPLATE, self.root, allow_modified=True)
        self.init()
        self.ws('hooks', 'enable', 'claude', '--absolute')
        command = self.hook('.claude/settings.json', 'hooks', 'UserPromptSubmit', 0, 'hooks', 0, 'command')
        self.assertIn('/my project/.agents/tools/ws.py" turn --hook claude', command)
        folder = self.root / 'src' / 'deep'
        folder.mkdir(parents=True)
        done = self.run_from(command, folder)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('hookSpecificOutput', done.stdout)
        self.ws('hooks', 'enable', 'claude', '--absolute')
        self.assertEqual(len(self.hook('.claude/settings.json', 'hooks', 'UserPromptSubmit')), 1)

    def test_25_powershell_commands_get_the_call_operator(self):
        self.init()
        self.ws('hooks', 'enable', 'copilot', '--absolute')
        entry = self.hook('.github/hooks/workspace.json', 'hooks', 'sessionStart', 0)
        self.assertTrue(entry['powershell'].startswith('& '), entry)
        self.assertFalse(entry['bash'].startswith('& '), entry)
        self.assertTrue(entry['bash'].endswith('/.agents/tools/ws.py" brief --hook copilot'), entry)

    def test_25_the_default_stays_relative(self):
        # Guards the default until the host trials decide it (owner decision D5).
        self.init()
        self.ws('hooks', 'enable', 'claude')
        command = self.hook('.claude/settings.json', 'hooks', 'UserPromptSubmit', 0, 'hooks', 0, 'command')
        self.assertTrue(command.endswith(' .agents/tools/ws.py turn --hook claude'), command)


if __name__ == '__main__':
    unittest.main()
