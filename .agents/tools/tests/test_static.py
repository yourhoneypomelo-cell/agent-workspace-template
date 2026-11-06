"""Source hygiene: damage a writing tool can do to the source without breaking any other test, and the grammar of
the oldest Python the tool supports."""
import ast
import json
import unittest
import warnings

from support import TEMPLATE
from wslib import distribution
from wslib.core import sha
from wslib.schema import MANIFEST, STATIC_FILES


class SourceBytes(unittest.TestCase):
    def test_no_control_characters(self):
        self.assertEqual(distribution.control_bytes(TEMPLATE), [])

    def test_no_collapsed_continuations(self):
        self.assertEqual(distribution.collapsed_continuations(TEMPLATE), [])

    def test_sources_parse_with_the_python_3_10_grammar(self):
        # Warnings are errors here: an invalid escape such as "\|" only warns today and fails in a later Python.
        for rel in (r for r in STATIC_FILES if r.endswith('.py')):
            with self.subTest(rel=rel), warnings.catch_warnings():
                warnings.simplefilter('error')
                ast.parse((TEMPLATE / rel).read_text(encoding='utf-8'), rel, feature_version=(3, 10))

    def test_manifest_matches_the_checkout(self):
        recorded = json.loads((TEMPLATE / MANIFEST).read_text(encoding='utf-8'))['files']
        changed = [rel for rel in STATIC_FILES if recorded.get(rel) !=
                   sha((TEMPLATE / rel).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8'))]
        self.assertEqual(changed, [], 'run "python .agents/tools/ws.py stamp" after changing a template file')


if __name__ == '__main__':
    unittest.main()
