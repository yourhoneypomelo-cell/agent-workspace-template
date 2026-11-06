"""ws upgrade and the rebaseline it ends with (3.7.0). Maintainer tests: projects never receive them."""
import unittest

from support import Workspace
from wslib import core, upgrade


class Rebaseline(Workspace):
    def released(self):
        self.init()
        self.write('notes.py', 'NOTES = []\n')
        self.save()

    def test_rebaseline_keeps_other_drift(self):
        self.released()
        guide = '.agents/guides/HOSTS.md'
        self.write(guide, self.read(guide) + '\nA line from a newer template.\n')
        self.write('notes.py', 'NOTES = [1]\n')
        upgrade.rebaseline(self.root, [guide], 'test: newer guide')
        out = self.ws('check', expect=1).stdout
        self.assertIn('notes.py', out)
        self.assertNotIn(guide, out)

    def test_rebaseline_takes_only_template_files(self):
        self.released()
        with self.assertRaisesRegex(core.WorkspaceError, 'not notes.py'):
            upgrade.rebaseline(self.root, ['notes.py'], 'test')

    def test_rebaseline_needs_a_released_workspace(self):
        self.init()
        self.save(keep=True)
        with self.assertRaisesRegex(core.WorkspaceError, 'not released'):
            upgrade.rebaseline(self.root, ['.agents/guides/HOSTS.md'], 'test')

    def test_hooks_enable_on_a_released_workspace_keeps_it_ready(self):
        self.released()
        self.assertIn('its checkpoint now holds it', self.ws('hooks', 'enable', 'gemini').stdout)
        self.ready()


if __name__ == '__main__':
    unittest.main()
