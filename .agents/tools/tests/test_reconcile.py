"""Saved user messages are listed until a row or a reason accounts for each one."""
import json
import unittest

from support import Workspace


class Reconcile(Workspace):
    def capture(self, *messages):
        lines = []
        for role, text in messages:
            lines.append(json.dumps({'type': role, 'message': {'role': role, 'content': text}}, ensure_ascii=False))
        transcript = self.parent / 'session.jsonl'
        transcript.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        payload = json.dumps({'session_id': 's1', 'transcript_path': str(transcript)}, ensure_ascii=False)
        self.ws('capture', '--host', 'claude', '--event', 'Stop', stdin=payload)

    def pending(self):
        return [line.split()[0] for line in self.ws('reconcile').stdout.splitlines() if line.startswith('m')]

    def test_lists_messages_until_each_is_marked(self):
        self.init()
        self.capture(('user', '网关用 key 握手，输入 DOI 返回 PDF'), ('assistant', '好的'),
                     ('user', '只给我自己用，每天最多 200 篇'), ('user', '继续'))
        first, second = self.pending()
        self.assertIn('not reconciled', self.ws('brief').stdout)
        self.assertIn('not reconciled', self.ws('turn').stdout)

        self.ws('reconcile', first, '--ids', 'R1')
        self.ws('reconcile', first, '--ids', 'R1', expect=2)
        self.assertIn('unknown IDs: R9', self.ws('reconcile', second, '--ids', 'R9', expect=2).stderr)
        self.assertIn('reason must start', self.ws('reconcile', second, '--reason', 'nothing', expect=2).stderr)
        self.ws('reconcile', second, '--ids', 'R1', '--reason', 'chat: x', expect=2)

        self.ws('add', 'requirement', '--set', 'requirement=Single user, 200 papers a day', '--set', 'acceptance=y')
        self.ws('reconcile', second, '--ids', 'R2')
        self.assertEqual(self.pending(), [])
        self.assertIn('are reconciled', self.ws('reconcile').stdout)
        self.assertNotIn('not reconciled', self.ws('brief').stdout)
        log = self.read('docs/logs/RECONCILE_LOG.md')
        self.assertIn(f'| {first} | R1 |', log)
        self.assertIn(f'| {second} | R2 |', log)

    def test_all_needs_a_reason_and_open_messages_block_ready(self):
        self.init()
        self.capture(('user', 'what is the status of the build?'), ('user', 'and the tests?'))
        self.assertIn('not reconciled', self.save().stdout)
        self.assertIn('are not reconciled', self.ready(expect=1).stdout)
        self.ws('start')
        self.ws('reconcile', 'all', '--ids', 'R1', expect=2)
        self.ws('reconcile', 'all', '--reason', 'question: status only')
        self.assertEqual(self.pending(), [])
        self.assertNotIn('not reconciled', self.save().stdout)
        self.ready()

    def test_cache_follows_transcript_changes(self):
        self.init()
        self.capture(('user', 'add CSV export'), ('user', '继续，好的'))
        self.assertEqual(len(self.pending()), 1)
        self.assertTrue((self.root / '.agents/cache/messages.json').is_file())
        self.capture(('user', 'add CSV export'), ('user', 'also JSON export'))
        self.assertEqual(len(self.pending()), 2)
        (self.root / '.agents/cache/messages.json').write_text('not json', encoding='utf-8')
        self.assertEqual(len(self.pending()), 2)

    def test_needs_an_owner(self):
        self.init()
        self.capture(('user', 'add CSV export'))
        self.save()
        message = self.pending()[0]
        self.assertIn('ws start', self.ws('reconcile', message, '--reason', 'chat: x', expect=2).stderr)

    def test_older_project_without_the_log_reads_and_writes(self):
        self.init()
        self.capture(('user', 'add CSV export'))
        (self.root / 'docs/logs/RECONCILE_LOG.md').unlink()
        self.save()
        self.ws('brief')
        self.ws('check', '--strict')
        self.assertIn('not reconciled', self.ready(expect=1).stdout)
        self.assertFalse((self.root / 'docs/logs/RECONCILE_LOG.md').exists(), 'read-only commands must not write')
        self.ws('start')
        self.ws('reconcile', self.pending()[0], '--ids', 'R1')
        self.assertIn('| Date | Message | Outcome |', self.read('docs/logs/RECONCILE_LOG.md'))
        self.save()
        self.ready()

    def test_bad_cache_index_and_paths_are_handled(self):
        self.init()
        self.capture(('user', 'add CSV export'))
        self.pending()
        cache = self.root / '.agents/cache/messages.json'
        data = json.loads(cache.read_text(encoding='utf-8'))
        for entry in data.values():
            entry['messages'] = [5]
        cache.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(len(self.pending()), 1)
        outside = self.parent / 'outside.md'
        outside.write_text('## 1. user' + chr(10) + chr(10) + 'secret outside text' + chr(10), encoding='utf-8')
        index = self.root / 'docs/chats/INDEX.md'
        index.write_text(index.read_text(encoding='utf-8') + '| 2026-11-01 | x | y | 1 | docs/chats/../../outside.md | none |' + chr(10), encoding='utf-8')
        self.assertNotIn('secret outside text', self.ws('reconcile').stdout)
        index.write_text(index.read_text(encoding='utf-8') + '| a | b | c | d | e | f | g |' + chr(10), encoding='utf-8')
        self.assertIn('cannot be reconciled', self.ws('brief').stdout)
        self.ws('reconcile', expect=2)

    def test_empty_ids_and_secrets_in_reasons_are_refused_or_redacted(self):
        self.init()
        self.capture(('user', 'add CSV export'), ('user', 'and PDF'))
        first, second = self.pending()
        self.ws('reconcile', first, '--ids', ' , ;', expect=2)
        self.ws('reconcile', first, '--ids', 'r1')
        self.ws('reconcile', second, '--reason', 'chat: password: Hunter2Hunter2!')
        self.assertNotIn('Hunter2Hunter2', self.read('docs/logs/RECONCILE_LOG.md'))


if __name__ == '__main__':
    unittest.main()
