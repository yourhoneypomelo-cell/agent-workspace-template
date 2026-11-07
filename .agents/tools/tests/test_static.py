"""Source hygiene and maintainer process: damage a writing tool can do to the source without breaking any other
test, the grammar of the oldest Python the tool supports, and the records MAINTAINING.md keeps."""
import ast
import importlib
import json
import re
import subprocess
import sys
import unittest
import warnings
from pathlib import Path

from support import TEMPLATE
from wslib import distribution
from wslib.core import sha
from wslib.schema import MANIFEST, STATIC_FILES


def maintaining_section(title: str) -> str:
    text = (TEMPLATE / '.agents/guides/MAINTAINING.md').read_text(encoding='utf-8')
    return re.split(r'^##', text.split(f'### {title}\n', 1)[1], maxsplit=1, flags=re.M)[0]


class SourceBytes(unittest.TestCase):
    def test_no_control_characters(self):
        self.assertEqual(distribution.control_bytes(TEMPLATE), [])

    def test_no_collapsed_continuations(self):
        self.assertEqual(distribution.collapsed_continuations(TEMPLATE), [])

    def test_sources_parse_with_the_python_3_9_grammar(self):
        # Warnings are errors here: an invalid escape such as "\|" only warns today and fails in a later Python.
        for rel in (r for r in STATIC_FILES if r.endswith('.py')):
            with self.subTest(rel=rel), warnings.catch_warnings():
                warnings.simplefilter('error')
                ast.parse((TEMPLATE / rel).read_text(encoding='utf-8'), rel, feature_version=(3, 9))

    def test_no_call_needs_a_python_newer_than_3_9(self):
        # The grammar check cannot see keyword arguments added later, such as write_text(newline=) in 3.10.
        newer = {('write_text', 'newline'), ('read_text', 'newline'), ('zip', 'strict')}
        found = []
        for rel in (r for r in STATIC_FILES if r.endswith('.py')):
            for node in ast.walk(ast.parse((TEMPLATE / rel).read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
                    found += [f'{rel}:{node.lineno} {name}({k.arg}=)' for k in node.keywords if (name, k.arg) in newer]
        self.assertEqual(found, [])

    def test_ws_py_parses_with_the_python_3_7_grammar(self):
        # Its version gate can only print the message if an older Python parses the whole file.
        ast.parse((TEMPLATE / '.agents/tools/ws.py').read_text(encoding='utf-8'), 'ws.py', feature_version=(3, 7))

    def test_manifest_matches_the_checkout(self):
        recorded = json.loads((TEMPLATE / MANIFEST).read_text(encoding='utf-8'))['files']
        changed = [rel for rel in STATIC_FILES if recorded.get(rel) !=
                   sha((TEMPLATE / rel).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8'))]
        self.assertEqual(changed, [], 'run "python .agents/tools/ws.py stamp" after changing a template file')


class Process(unittest.TestCase):
    def test_fix_table_names_existing_tests(self):
        text = (TEMPLATE / '.agents/guides/FIXES.md').read_text(encoding='utf-8')
        rows = [line for line in text.splitlines() if re.match(r'^\| \d+\.\d+\.\d+ \|', line)]
        self.assertEqual([row for row in rows if not re.search(r'\| `test_\w+\.\w+\.test_\w+` \| (?:fails|guard) \|$', row)], [])
        names = re.findall(r'`(test_\w+\.\w+\.test_\w+)`', text)
        self.assertTrue(names)
        missing = []
        for name in names:
            module, case, method = name.split('.')
            if not callable(getattr(getattr(importlib.import_module(module), case, None), method, None)):
                missing.append(name)
        self.assertEqual(missing, [])

    def test_protocol_prints_the_permission_table_the_commands_enforce(self):
        from wslib.permits import table_markdown
        text = (TEMPLATE / '.agents/guides/PROTOCOL.md').read_text(encoding='utf-8')
        self.assertEqual(text.split('<!-- PERMITS:START -->\n', 1)[1].split('<!-- PERMITS:END -->', 1)[0], table_markdown())

    def test_test_environment_clears_every_session_variable(self):
        # Run inside a host conversation, the tests would otherwise give every test project that conversation.
        code = ('import os, sys; sys.path.insert(0, ".."); from wslib.core import SESSION_VARS; '
                'os.environ.update({n: "outer" for n in SESSION_VARS}); import support; '
                'print(",".join(n for n in SESSION_VARS if support.ENV.get(n)))')
        run = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parent, capture_output=True, text=True,
                             encoding='utf-8')
        self.assertEqual((run.returncode, run.stdout.strip()), (0, ''), run.stderr[-600:])


class OwnerRules(unittest.TestCase):
    def test_agents_md_keeps_owner_rule_anchors(self):
        anchors = re.findall(r'^- `(.+)`$', maintaining_section('Pinned rules'), re.M)
        self.assertGreaterEqual(len(anchors), 9)
        contract = (TEMPLATE / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual([anchor for anchor in anchors if anchor not in contract], [])


if __name__ == '__main__':
    unittest.main()
