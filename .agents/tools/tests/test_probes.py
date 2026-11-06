"""Cold-start probes: each recorded fact reaches the files a fresh agent reads, before and after compact.

This checks that facts are available to a new session, not that a model uses them.
One fixture is built in-process for the whole class, so the module stays near a few seconds."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from support import TEMPLATE, TOOLS  # noqa: F401  (support puts the tools folder on sys.path)

from wslib import distribution, ops  # noqa: E402

T0_STATE = ('docs/state/HANDOFF.md', 'docs/state/REQUIREMENTS.md', 'docs/state/PREFERENCES.md')
T1_STATE = T0_STATE + ('docs/state/FEATURES.md', 'docs/state/TASKS.md', 'docs/state/ARCHITECTURE.md',
                       'docs/state/DESIGN.md')

# (probe, tier where AGENTS.md says the agent finds it, expected substrings, must stay findable after compact)
PROBES = (
    ('goal', 'brief', ['Notes CLI that adds and lists notes'], True),
    ('next step', 'brief', ['Implement T3 list newest first'], True),
    ('ready task', 'brief', ['ready next: T3'], True),
    ('open question', 'brief', ['--limit'], True),
    ('risk', 'brief', ['notes.json is not locked'], True),
    ('verified work', 'brief', ['Requirements verified: 1/2'], True),
    ('constraint', 't0', ['standard library only'], True),
    ('late correction', 't0', ['newest first'], True),
    ('rejected option', 't1', ['SQLite'], True),
    ('removed feature', 't1', ['F1', 'CSV export'], True),
    ('why it was removed', 't1', ['no CSV, too much scope'], True),
)
# Superseded values: present only next to a retired status, never as live work.
STALE = (('oldest first', ('replaced',)), ('Implement CSV export', ('dropped', 'removed')))
# Facts never recorded: nothing in the read set may claim them.
ABSENT = ('PostgreSQL', 'Rust')


def run(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class ColdStartProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ws-probe-', dir=distribution.scratch_dir())
        root = cls.root = Path(cls.temp.name) / 'project'
        distribution.install(TEMPLATE, root, allow_modified=True)
        add = lambda table, *sets, source='user': run(ops.add, root, table, list(sets), source)
        run(ops.init, root, 'Notes CLI that adds and lists notes', None)
        add('requirements', 'requirement=notes add TEXT stores a note in notes.json', 'acceptance=python -m unittest test_notes')
        add('requirements', 'requirement=notes list prints notes oldest first', 'acceptance=python -m unittest test_notes')
        add('requirements', 'requirement=Export notes to CSV', 'acceptance=python -m unittest test_notes')
        add('preferences', 'preference=No third-party dependencies; standard library only', 'source=user 2026-11-01')
        add('decisions', 'decision=Store notes as JSON, not SQLite', 'reason=user wants a file they can read', 'source=user')
        add('questions', 'question=Should list support a --limit flag?')
        for req, action in (('R1', 'Implement add'), ('R3', 'Implement CSV export'), ('R2', 'Implement list order')):
            add('tasks', f'requirements={req}', 'scope=notes.py', f'action={action}', 'acceptance=python -m unittest test_notes')
        add('features', 'behavior=CSV export', 'requirements=R3', 'tasks=T2')
        (root / 'notes.py').write_text('def add(t):\n    return t\n', encoding='utf-8')
        (root / 'test_notes.py').write_text('import unittest\nfrom notes import add\n\n\nclass N(unittest.TestCase):\n'
                                            '    def test_add(self):\n        self.assertEqual(add("x"), "x")\n', encoding='utf-8')
        run(ops.verify, root, ['T1'], [sys.executable, '-m', 'unittest', 'test_notes'], True, None, None, None, 120,
            because='the fixture runs the same test with the current interpreter')
        # Late correction: the user reverses the list order, then drops CSV export.
        add('requirements', 'requirement=notes list prints notes newest first', 'acceptance=python -m unittest test_notes')
        run(ops.set_row, root, 'R2', ['status=replaced', 'reason=user: newest first, see R4'], 'user')
        run(ops.set_row, root, 'T3', ['requirements=R4', 'action=Implement list newest first'], None)
        run(ops.set_row, root, 'R3', ['status=removed', 'reason=user: no CSV, too much scope'], 'user')
        run(ops.set_row, root, 'T2', ['status=dropped', 'reason=superseded: R3 removed'], None)
        run(ops.set_row, root, 'F1', ['status=removed', 'reason=user: no CSV, too much scope'], 'user')
        run(ops.set_card, root, ['risks=notes.json is not locked against two writers'])
        run(ops.checkpoint, root, 'T1 add verified', 'Implement T3 list newest first', [], True)
        cls.before = cls.read_sets()
        run(ops.compact, root, False, False)
        run(ops.checkpoint, root, 'compacted', 'Implement T3 list newest first', [], False)
        cls.after = cls.read_sets()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def read_sets(cls) -> dict:
        text = lambda rels: ''.join((cls.root / rel).read_text(encoding='utf-8') for rel in rels)
        brief = ops.brief(cls.root)
        return {'brief': brief, 't0': brief + text(T0_STATE), 't1': brief + text(T1_STATE)}

    def test_each_probe_is_found_in_its_tier(self):
        for label, sets in (('before compact', self.before), ('after compact', self.after)):
            for probe, tier, expected, survives in PROBES:
                if label == 'after compact' and not survives:
                    continue
                for needle in expected:
                    with self.subTest(probe=probe, when=label, needle=needle):
                        self.assertIn(needle, sets[tier], f'{probe}: "{needle}" missing from the {tier} read set {label}')

    def test_superseded_values_appear_only_as_retired(self):
        for label, sets in (('before compact', self.before), ('after compact', self.after)):
            for line in sets['t1'].splitlines():
                for needle, statuses in STALE:
                    if needle in line:
                        with self.subTest(when=label, needle=needle):
                            self.assertTrue(any(s in line for s in statuses), f'{label}: live line keeps "{needle}"')

    def test_unrecorded_facts_are_absent(self):
        for needle in ABSENT:
            self.assertNotIn(needle, self.after['t1'])

    def test_read_set_stays_small(self):
        self.assertLess(len(self.after['brief']), 9000)
        self.assertLess(len(self.after['t1']), 12000)


class LosslessCompact(unittest.TestCase):
    """A9: compact keeps every column of every row and survives a crash between its writes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ws-compact-', dir=distribution.scratch_dir())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        distribution.install(TEMPLATE, self.root, allow_modified=True)
        run(ops.init, self.root, 'Long requirement text', None)
        self.long = 'notes export ' + 'keeps every field of every note ' * 9  # about 300 characters
        run(ops.add, self.root, 'requirements', [f'requirement={self.long.strip()}', 'acceptance=python -m unittest t_long'], 'user')
        run(ops.add, self.root, 'requirements', ['requirement=keep one live row here', 'acceptance=python -m unittest t'], 'user')
        run(ops.set_row, self.root, 'R1', ['status=removed', 'reason=user dropped export ' + 'because of scope ' * 12], 'user')

    def test_full_row_survives(self):
        run(ops.compact, self.root, False, False)
        body = (self.root / 'docs/archive/closed/R1.md').read_text(encoding='utf-8')
        self.assertIn(self.long.strip(), body)
        self.assertIn('python -m unittest t_long', body)
        self.assertIn('docs/archive/closed/R1.md', (self.root / 'docs/logs/CLOSED_ITEMS.md').read_text(encoding='utf-8'))

    def test_crash_after_archive_loses_nothing(self):
        real = ops.write

        def die_on_state(root, rel, text):
            if rel.startswith('docs/state/'):
                raise OSError('simulated crash')
            real(root, rel, text)
        ops.write = die_on_state
        try:
            with self.assertRaises(OSError):
                run(ops.compact, self.root, False, False)
        finally:
            ops.write = real
        self.assertIn('| R1 |', (self.root / 'docs/state/REQUIREMENTS.md').read_text(encoding='utf-8'))
        run(ops.compact, self.root, False, False)  # the rerun finishes the move without a second index row
        closed = (self.root / 'docs/logs/CLOSED_ITEMS.md').read_text(encoding='utf-8')
        self.assertEqual(closed.count('| R1 |'), 1)
        self.assertNotIn('| R1 |', (self.root / 'docs/state/REQUIREMENTS.md').read_text(encoding='utf-8'))

    def test_legacy_closed_items_are_read_and_upgraded(self):
        rel = self.root / 'docs/logs/CLOSED_ITEMS.md'
        legacy = rel.read_text(encoding='utf-8').replace(' | Row |', ' |').replace(' | --- |\n', ' |\n', 1)
        legacy = legacy.replace('| --- | --- | --- | --- | --- | --- | --- | --- |', '| --- | --- | --- | --- | --- | --- | --- |')
        legacy = legacy.rstrip('\n') + '\n| T9 | done | R1: old task | none | none | none | 2026-01-01 |\n'
        rel.write_text(legacy, encoding='utf-8')
        from wslib import tables
        self.assertEqual([r['Row'] for r in tables.closed_rows(self.root)], ['none'])
        run(ops.compact, self.root, False, False)
        rows = tables.parse(rel.read_text(encoding='utf-8'), tables.CLOSED_HEADERS, 'closed')
        self.assertEqual([r['ID'] for r in rows], ['T9', 'R1'])


if __name__ == '__main__':
    unittest.main()
