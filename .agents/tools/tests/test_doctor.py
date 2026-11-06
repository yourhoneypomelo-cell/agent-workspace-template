"""ws doctor (3.7.0): each broken setup is reported with the command that fixes it, and nothing is written."""
import json
import unittest

from support import Workspace

FIX_CLAUDE = 'python .agents/tools/ws.py hooks enable claude'


class Doctor(Workspace):
    def doctor(self, expect=0, **env):
        return json.loads(self.ws('doctor', '--json', expect=expect, env=env).stdout)

    def problems(self, report, area):
        return [p for p in report['problems'] if p['area'] == area]

    def test_a_healthy_project_has_no_problems_and_nothing_is_written(self):
        self.init()
        self.ws('hooks', 'enable', 'claude')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = self.doctor(CLAUDE_CODE_SESSION_ID='chat-1')
        self.assertEqual(report['problems'], [])
        self.assertIn('claude: 5 hook commands in .claude/settings.json', json.dumps(report['facts']))
        self.assertIn('named by CLAUDE_CODE_SESSION_ID', json.dumps(report['facts']))
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_missing_hooks_of_the_host_that_runs_it(self):
        self.init()
        (problem,) = self.problems(self.doctor(expect=1, CLAUDE_CODE_SESSION_ID='chat-1'), 'hooks')
        self.assertIn('starts without the brief', problem['text'])
        self.assertEqual(problem['fix'], FIX_CLAUDE)
        self.assertIn(f'fix: {FIX_CLAUDE}', self.ws('doctor', expect=1, env={'CLAUDE_CODE_SESSION_ID': 'chat-1'}).stdout)

    def test_hooks_that_run_another_projects_tool(self):
        # A project copied from another folder, with hooks someone had pointed at that folder's ws.py.
        self.init()
        self.ws('hooks', 'enable', 'claude')
        other = (self.parent / 'original/.agents/tools/ws.py').as_posix()
        self.write('.claude/settings.json', self.read('.claude/settings.json').replace('.agents/tools/ws.py', f'\\"{other}\\"'))
        (problem,) = self.problems(self.doctor(expect=1), 'hooks')
        self.assertIn(f'runs {other}, the tool of another folder', problem['text'])
        self.assertEqual(problem['fix'], FIX_CLAUDE)

    def test_tool_files_that_differ_from_the_manifest(self):
        self.init()
        views = self.root / '.agents/tools/wslib/views.py'
        views.write_bytes(views.read_bytes() + b'\n# patched by hand\n')
        (problem,) = self.problems(self.doctor(expect=1), 'tool')
        self.assertIn('may mix two versions: .agents/tools/wslib/views.py', problem['text'])
        self.assertIn('--overwrite-modified-tools', problem['fix'])


if __name__ == '__main__':
    unittest.main()
