"""Session identity: resume after compaction (A2/U36) and a stopped old window (A1/U35)."""
import json
import unittest

from support import Workspace

VARS = ('WS_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'QWEN_CODE_SESSION_ID',
        'ZCODE_SESSION_ID', 'KIRO_SESSION_ID')


def host(**names):
    """Environment of a command run by a host session: only the given session variables are set."""
    return {**{n: '' for n in VARS}, **names}


class SessionIdentity(Workspace):
    def started(self, env=None, *start, fresh=True):
        if fresh:
            self.init()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Implement demo',
                '--set', 'acceptance=python -m unittest test_demo', env=env)
        self.passing_test()
        self.ws('checkpoint', '--stop', 'planned', '--next', 'verify T1', '--set', 'phase=build', '--set', 'risks=demo only',
                '--set', 'next_acceptance=T1 passes', env=env)
        return json.loads(self.ws('start', *start, env=env).stdout.splitlines()[0])

    def finish(self, env=None):
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo', env=env)

    def test_same_session_start_after_compaction_keeps_its_evidence(self):
        a = host(CLAUDE_CODE_SESSION_ID='claude-a')
        first = self.started(a)
        self.finish(a)
        again = json.loads(self.ws('start', env=a).stdout.splitlines()[0])
        self.assertTrue(again.get('resumed'))
        self.assertEqual(again['writer'], first['writer'])
        self.assertNotIn('| takeover |', self.read('docs/logs/MAINTENANCE_LOG.md'))
        self.ws('checkpoint', '--stop', 'T1 done', '--next', 'next task', env=a)
        self.ready()

    def test_old_window_is_stopped_without_writer_flag(self):
        a, b = host(CLAUDE_CODE_SESSION_ID='claude-a'), host(CLAUDE_CODE_SESSION_ID='claude-b')
        self.started(a)
        self.ws('start', '--force', '--reason', 'user: test', env=b)
        result = self.ws('add', 'question', '--set', 'question=from the old window', env=a, expect=2)
        self.assertIn('took over the workspace', result.stderr)
        self.ws('add', 'question', '--set', 'question=from the new owner', env=b)

    def test_codex_subagent_thread_is_the_same_session(self):
        root = host(CODEX_SESSION_ID='root', CODEX_THREAD_ID='root')
        self.started(root)
        sub = host(CODEX_SESSION_ID='root', CODEX_THREAD_ID='child')
        self.assertTrue(json.loads(self.ws('start', env=sub).stdout.splitlines()[0]).get('resumed'))
        self.ws('add', 'question', '--set', 'question=from the parent', env=root)

    def test_nested_hosts_and_missing_ids_never_refuse(self):
        self.started(host(CLAUDE_CODE_SESSION_ID='claude-a'))
        self.ws('add', 'question', '--set', 'question=no id', env=host())
        self.ws('add', 'question', '--set', 'question=nested', env=host(CLAUDE_CODE_SESSION_ID='x', CODEX_SESSION_ID='y'))
        zcode_subagent = host(CLAUDE_CODE_SESSION_ID='sub', ZCODE_SESSION_ID='sub')
        self.ws('add', 'question', '--set', 'question=zcode subagent', env=zcode_subagent)
        self.assertNotIn('k-', self.read('docs/state/HANDOFF.md').split('<!-- CONTINUITY ')[1].split('"session"')[0])

    def test_old_window_cannot_borrow_the_new_owner_label(self):
        a, b = host(CLAUDE_CODE_SESSION_ID='sessA'), host(CLAUDE_CODE_SESSION_ID='sessB')
        self.started(a)
        owner = json.loads(self.ws('start', '--force', '--reason', 'user: test', env=b).stdout.splitlines()[0])['writer']
        self.assertIn('must stop writing', self.ws('add', 'question', '--set', 'question=x', '--writer', owner, env=a, expect=2).stderr)
        self.assertIn('collides with work in progress', self.ws('start', '--writer', owner, env=a, expect=2).stderr)

    def test_a_copied_key_cannot_claim_a_session_named_by_a_variable(self):
        from wslib.core import session_key
        a = host(CLAUDE_CODE_SESSION_ID='sessA')
        self.started(a)
        stolen = json.loads(self.ws('start', '--session', session_key('sessA'), '--force', '--reason', 'user: test', env=host()).stdout.splitlines()[0])
        self.assertFalse(stolen.get('resumed'))

    def test_note_snapshot_and_reconcile_refuse_an_old_window(self):
        a, b = host(CLAUDE_CODE_SESSION_ID='sessA'), host(CLAUDE_CODE_SESSION_ID='sessB')
        self.started(a)
        self.ws('start', '--force', '--reason', 'user: test', env=b)
        for args in (('note', 'x'), ('snapshot', '--label', 'x'), ('reconcile', 'all', '--reason', 'chat: x')):
            self.assertIn('must stop writing', self.ws(*args, env=a, expect=2).stderr, args)

    def test_kiro_conversations_are_told_apart(self):
        a, b = host(KIRO_SESSION_ID='conv-a'), host(KIRO_SESSION_ID='conv-b')
        self.started(a)
        self.finish(a)
        self.assertTrue(json.loads(self.ws('start', env=a).stdout.splitlines()[0]).get('resumed'))
        self.ws('start', '--force', '--reason', 'user: test', env=b)
        self.assertIn('must stop writing', self.ws('add', 'question', '--set', 'question=x', env=a, expect=2).stderr)

    def test_cursor_old_conversation_is_told_by_the_turn_hook(self):
        from wslib.core import session_key
        self.started(host())
        self.ws('start', '--session', session_key('conv-b'), '--force', '--reason', 'user: test', env=host())
        old = json.loads(self.ws('turn', '--hook', 'cursor', stdin=json.dumps({'conversation_id': 'conv-a', 'prompt': 'go on'}),
                                 env=host()).stdout)['additional_context']
        self.assertIn('took over this workspace in another conversation', old)
        new = json.loads(self.ws('turn', '--hook', 'cursor', stdin=json.dumps({'conversation_id': 'conv-b', 'prompt': 'go on'}),
                                 env=host()).stdout)['additional_context']
        self.assertNotIn('took over', new)

    def test_zcode_restart_resumes_and_its_subagents_may_write(self):
        zcode = host(CLAUDE_CODE_SESSION_ID='main', ZCODE_SESSION_ID='main')
        self.started(zcode)
        self.finish(zcode)
        self.assertTrue(json.loads(self.ws('start', env=zcode).stdout.splitlines()[0]).get('resumed'))
        self.ws('add', 'question', '--set', 'question=from a subagent', env=host(CLAUDE_CODE_SESSION_ID='sub', ZCODE_SESSION_ID='sub'))
        self.ws('checkpoint', '--stop', 'T1 done', '--next', 'next task', env=zcode)

    def test_brief_hook_key_resumes_on_hosts_without_a_variable(self):
        self.init()
        hook = self.ws('brief', '--hook', 'kiro', stdin=json.dumps({'sessionId': 'chat-1'}), env=host()).stdout
        key = hook.split('start --session ')[1].split()[0]
        self.started(host(), '--session', key, fresh=False)
        self.finish(host())
        again = json.loads(self.ws('start', '--session', key, env=host()).stdout.splitlines()[0])
        self.assertTrue(again.get('resumed'))
        self.ws('checkpoint', '--stop', 'T1 done', '--next', 'next task', env=host())
        self.ready()

    def test_another_chat_of_the_same_app_takes_over(self):
        # Two chats in one IDE process: each brief carries its own key, so the last prompt never decides.
        first = self.started(host(), '--session', 'k-chat1')
        other = json.loads(self.ws('start', '--session', 'k-chat2', '--force', '--reason', 'user: test', env=host()).stdout.splitlines()[0])
        self.assertEqual(other.get('took_over_from'), first['writer'])
        plain = json.loads(self.ws('start', '--force', '--reason', 'user: test', env=host()).stdout.splitlines()[0])
        self.assertEqual(plain.get('took_over_from'), other['writer'])

    def test_claude_hook_key_matches_its_variable(self):
        self.init()
        hook = self.ws('brief', '--hook', 'claude', stdin=json.dumps({'session_id': 'abc'}), env=host()).stdout
        key = hook.split('start --session ')[1].split()[0]
        a = host(CLAUDE_CODE_SESSION_ID='abc')
        self.started(a, '--session', key, fresh=False)
        self.assertNotIn(key, self.read('docs/state/HANDOFF.md'))
        self.ws('start', '--force', '--reason', 'user: test', env=host(CLAUDE_CODE_SESSION_ID='other'))
        self.ws('card', '--set', 'risks=late write', env=a, expect=2)

    def test_checkpoint_release_clears_the_session(self):
        a = host(CLAUDE_CODE_SESSION_ID='claude-a')
        self.started(a)
        self.ws('checkpoint', '--stop', 'released', '--next', 'next', env=a)
        self.assertIsNone(json.loads(self.read('docs/state/HANDOFF.md').split('<!-- CONTINUITY ')[1].split(' -->')[0]).get('session'))

    def test_same_session_writes_again_after_its_checkpoint(self):
        # Field data: agents checkpointed every turn, then prefixed each write with "ws start >/dev/null".
        a = host(CLAUDE_CODE_SESSION_ID='claude-a')
        self.started(a)
        self.ws('checkpoint', '--stop', 'released', '--next', 'next', env=a)
        self.ws('add', 'question', '--set', 'question=next turn', env=a)
        self.assertIn('| resume |', self.read('docs/logs/MAINTENANCE_LOG.md'))
        self.ws('checkpoint', '--stop', 'released', '--next', 'next', env=a)
        self.ws('add', 'question', '--set', 'question=other window', env=host(CLAUDE_CODE_SESSION_ID='claude-b'), expect=2)
        self.ws('add', 'question', '--set', 'question=no id', env=host(), expect=2)

    def test_worker_role_never_claims_or_writes(self):
        a = host(CLAUDE_CODE_SESSION_ID='parent')
        self.started(a)
        worker = {**host(CLAUDE_CODE_SESSION_ID='parent'), 'WS_ROLE': 'worker'}
        self.assertIn('WS_ROLE', self.ws('start', env=worker, expect=2).stderr)
        self.assertIn('WS_ROLE', self.ws('add', 'question', '--set', 'question=x', env=worker, expect=2).stderr)
        self.assertIn('Read only what your task needs', self.ws('brief', env=worker).stdout)
        self.ws('add', 'question', '--set', 'question=parent still owns it', env=a)

    def test_brief_does_not_send_a_new_window_to_take_over_a_live_owner(self):
        self.started(host(CLAUDE_CODE_SESSION_ID='claude-a'))
        out = self.ws('brief', env=host(CLAUDE_CODE_SESSION_ID='claude-b')).stdout
        self.assertIn('other sessions are working', out)
        self.assertIn('start --task <ID>', out)
        self.assertNotIn('takes over from', out)

    def test_sync_pending_saves_a_refused_checkpoint(self):
        a = host(CLAUDE_CODE_SESSION_ID='claude-a')
        self.started(a)
        self.write('docs/state/TASKS.md', self.read('docs/state/TASKS.md').replace('| T1 | todo |', '| T1 | done |'))
        self.ws('checkpoint', '--keep', '--stop', 'stuck', '--next', 'fix T1', env=a, expect=2)
        handoff = self.read('docs/state/HANDOFF.md').replace('## Unfinished work\n', '## Unfinished work\n\n<!-- SYNC-PENDING -->\nT1 has no evidence\n', 1)
        self.write('docs/state/HANDOFF.md', handoff)
        out = self.ws('checkpoint', '--keep', '--stop', 'stuck', '--next', 'fix T1', env=a).stdout
        self.assertIn('SAVED WITHOUT SEAL', out)
        self.assertIn('| stuck |', self.read('docs/state/HANDOFF.md'))
        self.assertIn('sync-pending', self.read('docs/logs/SESSION_LOG.md'))
        self.ready(expect=1)

    def test_empty_lock_left_by_a_crash_is_removed(self):
        import os
        import time
        self.started(host(CLAUDE_CODE_SESSION_ID='claude-a'))
        lock = self.root / '.agents/cache/ws.lock'
        lock.write_bytes(b'\x00' * 32)
        old = time.time() - 120
        os.utime(lock, (old, old))
        self.ws('add', 'question', '--set', 'question=after crash', env=host(CLAUDE_CODE_SESSION_ID='claude-a'))

    def test_live_lock_is_not_reclaimed_even_with_an_older_generation(self):
        """A live holder keeps its lock, whatever generation an older version wrote into it."""
        import os
        self.started(host(CLAUDE_CODE_SESSION_ID='claude-a'))
        lock = self.root / '.agents/cache/ws.lock'
        lock.write_text(json.dumps({'pid': os.getpid(), 'created_at': '2026-01-01T00:00:00', 'generation': 0}))
        result = self.ws('add', 'question', '--set', 'question=blocked', expect=2,
                         env={**host(CLAUDE_CODE_SESSION_ID='claude-a'), 'WS_LOCK_WAIT': '1'})
        self.assertIn('another ws.py command is running', result.stderr)
        self.assertIn('"generation": 0', lock.read_text())


class MergeAndCard(Workspace):
    def test_conflict_markers_block_writes_and_ready(self):
        self.init()
        self.save()
        self.ws('start')
        text = self.read('docs/state/REQUIREMENTS.md')
        row = next(line for line in text.split('\n') if line.startswith('| R1 '))
        conflict = ('<<<<<<< HEAD\n| R7 | active | Ours | csv | inline | none |\n=======\n'
                    '| R9 | active | Theirs | json | inline | none |\n>>>>>>> b')
        self.write('docs/state/REQUIREMENTS.md', text.replace(row, row + '\n' + conflict))
        result = self.ws('add', 'requirement', '--set', 'requirement=Third', '--set', 'acceptance=x', expect=2)
        self.assertIn('merge conflict', result.stderr)
        self.assertIn('merge conflict', self.ws('brief').stdout)
        self.ws('check', '--ready', expect=1)
        self.save(expect=2)

    def test_setext_heading_is_not_a_conflict(self):
        self.init()
        self.write('docs/state/DESIGN.md', self.read('docs/state/DESIGN.md') + '\nApproach\n========\n')
        self.ws('card', '--set', 'risks=demo only')

    def test_seven_equals_heading_and_fenced_example_are_not_conflicts(self):
        from wslib import validate
        self.assertIsNone(validate._conflict_line('# T\n\nMerge procedure\n=======\n'))
        self.assertIsNone(validate._conflict_line('```text\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n```\n'))
        self.assertEqual(validate._conflict_line('# T\n\n<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n'), 3)

    def test_citations_in_chinese_lowercase_and_other_clauses_are_caught(self):
        from wslib import validate
        ids, live = {'T1': 'done', 'T2': 'dropped', 'Q1': 'dropped'}, {'T1'}
        for text in ('继续实现T2的CSV导出', 'Implement T2 CSV export now; do not touch T1', 'Implement t2 CSV export'):
            self.assertTrue(validate.card_citations(ids, live, {'next_step': text}), text)
        for text in ('Ship the release planned for Q1 2027 after T1', 'T2 dropped, do not rebuild'):
            self.assertFalse(validate.card_citations(ids, live, {'next_step': text}), text)

    def test_next_step_citing_a_dropped_task_is_refused(self):
        self.planned()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=x', '--set', 'action=CSV export',
                '--set', 'acceptance=python -m unittest test_demo')
        self.ws('set', 'T2', '--set', 'status=dropped', '--set', 'reason=user dropped CSV')
        args = ('--set', 'phase=build', '--set', 'risks=demo only', '--set', 'next_acceptance=T1 passes')
        result = self.ws('checkpoint', '--stop', 'dropped T2', '--next', 'Implement T2 CSV export', *args)
        self.assertIn('NOT READY', result.stdout)
        self.assertIn('T2 (dropped)', result.stdout)
        self.ws('start')
        result = self.ws('checkpoint', '--stop', 'dropped T2', '--next', 'Implement T1; T2 dropped, do not rebuild', *args)
        self.assertIn('READY. State is saved', result.stdout)

if __name__ == '__main__':
    unittest.main()
