"""Links between requirements, tasks and features stay current when requirements change."""
import unittest

from support import Workspace


class Tracking(Workspace):
    def test_retiring_a_requirement_names_the_open_work_that_cites_it(self):
        self.planned()
        out = self.ws('set', 'R1', '--set', 'status=replaced', '--set', 'reason=user wants SQLite').stdout
        self.assertIn('T1', out)
        self.assertIn('F1', out)
        self.assertIn('cites only retired requirements', self.ws('brief').stdout)
        self.ws('add', 'requirement', '--set', 'requirement=Demo uses SQLite', '--set', 'acceptance=python -m unittest test_demo')
        self.ws('set', 'T1', '--set', 'requirements=R2')
        self.ws('set', 'F1', '--set', 'requirements=R2')
        self.assertNotIn('cites only retired', self.ws('brief').stdout)

    def test_rewording_a_requirement_names_dependents_and_status_only_edits_do_not(self):
        self.planned()
        self.assertIn('T1', self.ws('set', 'R1', '--set', 'requirement=Demo returns 4 quickly').stdout)
        self.assertNotIn('cite it', self.ws('set', 'T1', '--set', 'status=doing').stdout)

    def test_brief_shows_requirement_coverage_and_the_ready_task(self):
        self.planned()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=b', '--set', 'action=Second step',
                '--set', 'acceptance=python -m unittest test_demo', '--set', 'depends=T1')
        brief = self.ws('brief').stdout
        self.assertIn('Requirements verified: 0/1 (not yet: R1)', brief)
        self.assertIn('ready next: T1 Implement demo', brief)
        self.assertIn('cites R1: Demo returns 4', brief)
        self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo')
        brief = self.ws('brief').stdout
        # T2 also cites R1 and is still open, so part of R1 is not built yet.
        self.assertIn('Requirements verified: 0/1 (not yet: R1)', brief)
        self.assertIn('ready next: T2 Second step', brief)
        self.ws('set', 'T2', '--set', 'status=dropped', '--set', 'reason=folded into T1')
        self.assertIn('Requirements verified: 1/1', self.ws('brief').stdout)

    def test_done_restates_cited_requirements_and_clears_the_card(self):
        self.planned()
        self.ws('card', '--set', 'current_task=T1')
        out = self.ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_demo').stdout
        self.assertIn('Check R1 is met in full: Demo returns 4', out)
        self.assertIn('| current_task | none |', self.read('docs/state/HANDOFF.md'))

    def test_card_pointing_at_a_finished_task_blocks_the_checkpoint(self):
        self.done()
        self.assertIn('current_task names T1, which is done', self.ws('card', '--set', 'current_task=T1', expect=2).stderr)


if __name__ == '__main__':
    unittest.main()
