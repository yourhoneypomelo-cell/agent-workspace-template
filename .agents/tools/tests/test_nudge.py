"""The optional Stop nudge asks once when a turn recorded nothing, and never loops."""
import json
import unittest

from support import Workspace


class Nudge(Workspace):
    def enable(self):
        text = self.read('docs/state/ARCHITECTURE.md').replace('"credentials": "ask"}',
                                                               '"credentials": "ask", "stop_nudge": true}')
        self.assertIn('"stop_nudge": true', text)
        self.write('docs/state/ARCHITECTURE.md', text)

    def turn(self, host='claude', prompt='Use SQLite instead'):
        self.ws('turn', '--hook', host, stdin=json.dumps({'session_id': 's1', 'prompt': prompt}))

    def stop(self, host='claude', **payload):
        return self.ws('capture', '--host', host, '--event', 'Stop', stdin=json.dumps({'session_id': 's1', **payload})).stdout

    def test_turn_with_no_record_is_nudged_once(self):
        self.init()
        self.enable()
        self.turn()
        out = json.loads(self.stop())
        self.assertEqual(out['decision'], 'block')
        self.assertIn('not recorded', out['reason'])
        self.assertEqual(self.stop(), '')

    def test_recorded_turn_is_not_nudged(self):
        self.init()
        self.enable()
        self.turn()
        self.ws('add', 'requirement', '--set', 'requirement=Use SQLite', '--set', 'acceptance=y')
        self.assertEqual(self.stop(), '')
        self.turn(prompt='thanks')
        self.ws('note', 'no record: thanks')
        self.assertEqual(self.stop(), '')

    def test_loop_guards_and_host_formats(self):
        self.init()
        self.enable()
        self.turn()
        self.assertEqual(self.stop(stop_hook_active=True), '')
        self.turn(host='cursor')
        self.assertIn('followup_message', self.stop(host='cursor'))
        self.turn(host='cursor')
        self.assertEqual(self.stop(host='cursor', loop_count=1), '')
        self.turn()
        self.assertEqual(self.stop(reason='session_end'), '')

    def test_off_by_default(self):
        self.init()
        self.turn()
        self.assertEqual(self.stop(), '')


if __name__ == '__main__':
    unittest.main()
