"""Shared fixtures: each test gets a fresh project installed from this template."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
TEMPLATE = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True

from wslib import core, distribution  # noqa: E402

# A command blocked by a held lock gives up after 5 s instead of 30 s, which keeps the lock tests short.
ENV = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', WS_IMPORT='0', WS_LOCK_WAIT='5')
ENV.pop('WS_ROLE', None)
# Host store locations from this machine must not leak into tests that build a fake home.
for _name in ('QWEN_HOME', 'QODER_HOME', 'WORKBUDDY_HOME', 'CODEBUDDY_CONFIG_DIR', 'GEMINI_HOME', 'KIRO_HOME',
              'CODEX_HOME', 'KIMI_CODE_HOME'):
    ENV.pop(_name, None)
# The host session running the tests must not become the session of every test project.
for _name in core.SESSION_VARS:
    ENV.pop(_name, None)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ws-test-', dir=distribution.scratch_dir())
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / 'project'
        distribution.install(TEMPLATE, self.root, allow_modified=True)

    def ws(self, *args, expect=0, stdin=None, env=None):
        result = subprocess.run([sys.executable, str(self.root / '.agents/tools/ws.py'), '--root', str(self.root), *args],
                                capture_output=True, text=True, encoding='utf-8', env={**ENV, **(env or {})}, input=stdin)
        if expect is not None:
            self.assertEqual(result.returncode, expect, f'ws {" ".join(args)}\n{result.stdout}\n{result.stderr}')
        return result

    def json(self, *args, expect=0):
        return json.loads(self.ws(*args, expect=expect).stdout.splitlines()[0])

    def read(self, rel):
        return (self.root / rel).read_text(encoding='utf-8')

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def init(self, requirement=True):
        """Initialize. By default also record one requirement, as a real first session must."""
        self.ws('init', '--goal', 'Build a small tested demo')
        if requirement:
            self.ws('add', 'requirement', '--set', 'requirement=Demo returns 4', '--set', 'acceptance=python -m unittest test_demo')

    def passing_test(self, name='test_demo.py'):
        self.write(name, 'import unittest\n\n\nclass Demo(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(2 + 2, 4)\n')

    def planned(self):
        """Initialized workspace with R1, T1 and F1 and a passing product test."""
        self.init()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=test_demo.py', '--set', 'action=Implement demo',
                '--set', 'acceptance=python -m unittest test_demo')
        self.ws('add', 'feature', '--set', 'behavior=Demo', '--set', 'requirements=R1', '--set', 'tasks=T1')
        self.passing_test()

    def done(self):
        self.planned()
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo')

    def ready(self, expect=0):
        return self.ws('check', '--ready', expect=expect)

    def save(self, keep=False, expect=0):
        return self.ws('checkpoint', '--stop', 'saved at a test boundary', '--next', 'continue with the next task',
                       *(['--keep'] if keep else []), expect=expect)
