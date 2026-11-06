"""Which host records count as user messages, and how saved transcripts keep their message IDs (3.6, G2)."""
import json
import os
import unittest
from pathlib import Path

from support import Workspace
from wslib import capture, reconcile


def write_lines(path: Path, records: list) -> Path:
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n', encoding='utf-8')
    return path


def user(text, **extra):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}, **extra}


class HostText(Workspace):
    def test_claude_keeps_typed_text_and_drops_host_turns(self):
        summary = 'This session is being continued from a previous conversation that ran out of context.'
        path = write_lines(self.parent / 'claude.jsonl', [
            user('typed with origin', origin={'kind': 'human'}),
            user('typed without origin'),
            user('pasted: ' + summary + ' Keep the CSV export.'),  # a real paste of an old summary
            user(summary + ' (resumed by hand)', origin={'kind': 'human'}),
            user('unknown kind is kept', origin={'kind': 'composer'}),
            user(summary + ' Summary...', isCompactSummary=True, isVisibleInTranscriptOnly=True),
            user('<task-notification>subtask done</task-notification>', origin={'kind': 'task-notification'}),
            user('cloud agent continued', origin={'kind': 'auto-continuation'}),
            user([{'type': 'text', 'text': '[Request interrupted by user]'}]),
            user([{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]),
            user('<local-command-stdout>ok</local-command-stdout>'),
            {'type': 'api-request-blob', 'message': {'role': 'user', 'content': 'typed without origin'}},
            user('peer says hi', isMeta=True, origin={'kind': 'channel'}),
        ])
        self.assertEqual([t for _, t in capture.extract(path)], [
            'typed with origin', 'typed without origin', 'pasted: ' + summary + ' Keep the CSV export.',
            summary + ' (resumed by hand)', 'unknown kind is kept'])

    def test_codex_subagent_and_guardian_threads_are_not_imported(self):
        home = self.parent / 'codex'
        day = home / 'sessions' / '2026' / '11' / '02'
        day.mkdir(parents=True)
        root = str(self.root.resolve())
        cases = {'user': ('vscode', 'user'), 'vscode-sub': ('vscode', 'subagent'),
                 'guardian': ({'subagent': 'other'}, 'guardian_review'), 'old-sub': ({'subagent': 'thread_spawn'}, None),
                 'old-user': ('vscode', None), 'empty-cwd': ('cli', 'user')}
        for name, (source, thread) in cases.items():
            meta = {'id': name, 'cwd': '' if name == 'empty-cwd' else root, 'source': source}
            if thread:
                meta['thread_source'] = thread
            write_lines(day / f'rollout-{name}.jsonl', [{'type': 'session_meta', 'payload': meta}])
        os.environ['CODEX_HOME'] = str(home)
        self.addCleanup(os.environ.pop, 'CODEX_HOME')
        found = sorted(sid for sid, _ in capture.local_sessions(self.root, 'codex'))
        self.assertEqual(found, ['rollout-old-user', 'rollout-user'])

    def test_codex_ide_wrapper_is_unwrapped_unless_the_request_is_empty(self):
        def item(text):
            return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                         'content': [{'type': 'input_text', 'text': text}]}}
        path = write_lines(self.parent / 'rollout.jsonl', [
            item('# Files mentioned by the user:\n\n## a.md: E:/p/a.md\n\n## My request for Codex:\nadd CSV export\n'),
            item('# In app browser:\nhttp://x\n\n## My request for Codex:\n'),
        ])
        texts = [t for _, t in capture.extract(path)]
        self.assertEqual(texts[0], 'add CSV export')
        self.assertIn('In app browser', texts[1])

    def test_qwen_thoughts_and_workbuddy_stubs_and_edited_resends_are_dropped(self):
        qwen = write_lines(self.parent / 'qwen.jsonl', [
            {'type': 'assistant', 'message': {'role': 'model', 'parts': [{'text': 'hidden plan', 'thought': True},
                                                                       {'text': 'visible reply'}]}}])
        self.assertEqual(capture.extract(qwen), [('assistant', 'visible reply')])
        def msg(role, mid, text, **extra):
            kind = 'input_text' if role == 'user' else 'output_text'
            return {'type': 'message', 'role': role, 'id': mid, 'content': [{'type': kind, 'text': text}], **extra}
        wb = write_lines(self.parent / 'wb.jsonl', [
            msg('user', 'u1', 'make a todo app'),
            msg('assistant', 'a1', '502 Bad Gateway', status='incomplete', providerData={'error': {'code': 502}, 'skipRun': True}),
            msg('assistant', 'a0', 'partial', providerData={'error': {'code': 'aborted'}}),
            {'type': 'resend-fork-notice', 'id': 'n1', 'editedUserItemId': 'u1'},
            msg('user', 'u2', 'make a todo app with tags'),
            msg('assistant', 'a2', 'done'),
            {'type': 'resend-fork-notice', 'id': 'n2', 'editedUserItemId': 'later'},  # unknown or later id: no cut
        ])
        self.assertEqual(capture.extract(wb), [('user', 'make a todo app with tags'), ('assistant', 'done')])

    def test_store_files_without_a_cwd_belong_to_no_project(self):
        self.assertFalse(capture._same_dir('', self.root))
        self.assertFalse(capture._same_dir('.', self.root))
        self.assertTrue(capture._same_dir(str(self.root.resolve()), self.root))


class Transcript(Workspace):
    def capture(self, records):
        path = write_lines(self.parent / 'session.jsonl', records)
        self.ws('capture', '--host', 'claude', '--event', 'Stop',
                stdin=json.dumps({'session_id': 's1', 'transcript_path': str(path)}))
        return self.read('docs/chats/claude/s1.md')

    def test_times_and_compaction_marks_go_in_headings_and_ids_do_not_change(self):
        self.init()
        old = '# Transcript claude s1\n\n## 1. user\n\nkeep the CSV export\n\n## 2. assistant\n\nok\n'
        new = self.capture([
            user('keep the CSV export', timestamp='2026-11-02T01:02:03.456Z'),
            {'type': 'assistant', 'message': {'role': 'assistant', 'content': 'ok'}, 'timestamp': 1793581323456},
            user('summary', isCompactSummary=True, timestamp='2026-11-02T02:00:00Z'),
            user('now add tags', timestamp='2026-11-02T03:00:00+08:00'),
        ])
        self.assertIn('## 1. user 2026-11-02T01:02:03Z\n', new)
        self.assertIn('## 3. user 2026-11-01T19:00:00Z (after compaction)\n', new)
        self.assertNotIn('summary', new.split('## 1.', 1)[1])
        old_path, new_path = self.parent / 'old.md', self.parent / 'new.md'
        old_path.write_text(old, encoding='utf-8')
        new_path.write_text(new, encoding='utf-8')
        self.assertEqual(list(reconcile.texts(old_path)), list(reconcile.texts(new_path))[:1])
        self.assertEqual(len(reconcile.texts(new_path)), 2)

    def test_body_lines_that_look_like_headings_stay_in_the_body(self):
        self.init()
        text = 'quoted:\n## 2. user 2026-11-02T01:02:03Z\n## 3. assistant (after compaction)\n## 4. user anything'
        saved = self.capture([user(text, timestamp='2026-11-02T01:00:00Z')])
        path = self.root / 'docs/chats/claude/s1.md'
        self.assertEqual(len(reconcile.texts(path)), 1)
        self.assertIn('## 4. user anything', saved)

    def test_hook_journal_stamps_each_message_and_still_skips_repeats(self):
        self.init()
        payload = json.dumps({'session_id': 'k1', 'hook_event_name': 'UserPromptSubmit', 'prompt': 'use port 8080'})
        for _ in range(2):
            self.ws('turn', '--hook', 'kiro', stdin=payload)
        text = self.read('docs/chats/kiro/k1.md')
        self.assertEqual(text.count('use port 8080'), 1)
        self.assertRegex(text, r'## 1\. user \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n')


class Signals(Workspace):
    def test_code_warning_is_quiet_while_a_task_is_doing(self):
        self.init()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=app.py', '--set', 'action=App',
                '--set', 'acceptance=python -m unittest')
        self.ws('set', 'T1', '--set', 'status=doing')
        self.ws('checkpoint', '--keep', '--stop', 's', '--next', 'n')
        self.write('app.py', 'print(1)\n')
        self.ws('note', 'progress')
        self.assertNotIn('product files changed', self.ws('brief').stdout)
        self.assertNotIn('product files changed', self.ws('turn').stdout)
        self.ws('set', 'T1', '--set', 'status=todo')
        self.ws('checkpoint', '--keep', '--stop', 's', '--next', 'n')
        self.write('app.py', 'print(2)\n')
        self.assertIn('product files changed', self.ws('brief').stdout)
        self.assertIn('no task is doing', self.ws('turn').stdout)

    def test_brief_lists_requirements_the_user_did_not_state(self):
        self.init()  # R1 is added without --source, so its log Source is "assistant"
        self.ws('add', 'requirement', '--set', 'requirement=Port 8080', '--set', 'acceptance=x', '--source', 'user 2026-11-02')
        brief = self.ws('brief').stdout
        self.assertIn('Not stated by the user: R1.', brief)
        self.ws('set', 'R1', '--set', 'status=active', '--source', 'user 2026-11-02')
        self.assertNotIn('Not stated by the user', self.ws('brief').stdout)
        self.assertIn('| R1 | confirmed |', self.read('docs/logs/REQUIREMENT_LOG.md'))


if __name__ == '__main__':
    unittest.main()
