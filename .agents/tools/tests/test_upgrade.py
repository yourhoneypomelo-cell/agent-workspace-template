"""ws upgrade and the rebaseline it ends with (3.7.0). Maintainer tests: projects never receive them."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import ENV, TEMPLATE, TOOLS, Workspace
from test_distribution import v2_workspace
from wslib import core, evidence, upgrade
from wslib.schema import MANIFEST

OLD_TOOL = '.agents/tools/wslib/legacy.py'


class Killed(BaseException):
    """A stop no code can catch, like a killed process or a power cut."""


def snapshot(root: Path) -> dict:
    """Every file's bytes, except the folders an upgrade adds to on purpose."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()
            and not p.relative_to(root).as_posix().startswith(('docs/archive/', '.agents/cache/'))}


class Upgrade(Workspace):
    def aged(self, root=None, older=('.agents/guides/HOSTS.md', '.agents/tools/wslib/views.py'), maintainer=False):
        """A released project that looks installed from an older release: the files in older hold older text, the
        manifest records it, and a tool module exists only in that release."""
        root = root or self.root
        if root != self.root:
            from wslib import distribution
            distribution.install(TEMPLATE, root, allow_modified=True)
        manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
        for rel in older:
            text = (root / rel).read_bytes().replace(b'\r\n', b'\n') + b'\n# from the older release\n'
            (root / rel).write_bytes(text)
            manifest['files'][rel] = core.sha(text)
        (root / OLD_TOOL).write_bytes(b'"""Only in the older release."""\n')
        manifest['files'][OLD_TOOL] = core.sha(b'"""Only in the older release."""\n')
        if maintainer:  # 3.6.x manifests listed the template's maintainer files too
            manifest['files']['.agents/guides/MAINTAINING.md'] = 'f' * 64
        (root / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        self.run_ws(root, 'init', '--goal', 'Notes app')
        self.run_ws(root, 'add', 'requirement', '--set', 'requirement=Notes are listed', '--set', 'acceptance=listed')
        self.run_ws(root, 'checkpoint', '--stop', 'set up', '--next', 'upgrade', '--set', 'phase=build',
                    '--set', 'risks=none confirmed', '--set', 'next_acceptance=check passes')
        return root

    def run_ws(self, root, *args, expect=0):
        done = subprocess.run([sys.executable, str(root / '.agents/tools/ws.py'), '--root', str(root), *args], env=ENV,
                              capture_output=True, text=True, encoding='utf-8')
        if expect is not None:
            self.assertEqual(done.returncode, expect, f'{args}\n{done.stdout}\n{done.stderr}')
        return done

    def upgrade(self, root, *args, expect=0):
        done = subprocess.run([sys.executable, str(TOOLS / 'ws.py'), 'upgrade', '--target', str(root), *args], env=ENV,
                              capture_output=True, text=True, encoding='utf-8')
        if expect is not None:
            self.assertEqual(done.returncode, expect, f'{args}\n{done.stdout}\n{done.stderr}')
        return done

    def test_dry_run_writes_nothing(self):
        self.aged()
        before = {p: b for p, b in snapshot(self.root).items()}
        cache = sorted(p.as_posix() for p in (self.root / '.agents/cache').rglob('*'))
        report = json.loads(self.upgrade(self.root, '--dry-run').stdout)
        self.assertEqual(report['counts'].get('replace'), 2)
        self.assertEqual(report['counts'].get('delete'), 1)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(sorted(p.as_posix() for p in (self.root / '.agents/cache').rglob('*')), cache)
        self.assertFalse((self.root / upgrade.UPGRADES).exists())

    def test_replaces_unmodified_and_keeps_modified_guides(self):
        self.aged()
        quick = self.root / '.agents/guides/QUICKSTART.md'
        quick.write_bytes(quick.read_bytes() + b'\nOur own note.\n')
        self.run_ws(self.root, 'start')
        self.run_ws(self.root, 'checkpoint', '--stop', 'own note added', '--next', 'upgrade')
        self.upgrade(self.root, expect=1)
        self.assertEqual((self.root / '.agents/guides/HOSTS.md').read_bytes(), (TEMPLATE / '.agents/guides/HOSTS.md').read_bytes().replace(b'\r\n', b'\n'))
        self.assertFalse((self.root / OLD_TOOL).exists())
        self.assertIn(b'Our own note.', quick.read_bytes())
        self.assertEqual(len(list((self.root / upgrade.UPGRADES).glob('*/new/.agents/guides/QUICKSTART.md'))), 1)
        self.run_ws(self.root, 'check')

    def test_keeps_hooks_json_and_docs(self):
        self.aged()
        self.run_ws(self.root, 'hooks', 'enable', 'antigravity')
        docs = {k: v for k, v in snapshot(self.root).items() if k.startswith('docs/') and k not in
                ('docs/state/HANDOFF.md', 'docs/logs/MAINTENANCE_LOG.md')}
        self.upgrade(self.root)
        self.assertTrue((self.root / '.agents/hooks.json').is_file())
        self.assertEqual({k: v for k, v in snapshot(self.root).items() if k in docs}, docs)
        self.run_ws(self.root, 'check', '--ready')

    def test_merges_the_project_rules_section(self):
        self.aged(older=())
        agents = self.root / 'AGENTS.md'
        older = agents.read_bytes().replace(b'\r\n', b'\n').replace(b'## Rules', b'## Rules\n\nAn older rule.', 1)
        agents.write_bytes(older + b'\n## Project rules\n\nRules kept from the AGENTS.md that existed before installation.\n\nUse tabs.\n')
        manifest = json.loads(self.read(MANIFEST))
        manifest['files']['AGENTS.md'] = core.sha(older)
        self.write(MANIFEST, json.dumps(manifest, indent=1, sort_keys=True) + '\n')
        self.run_ws(self.root, 'start')
        self.run_ws(self.root, 'checkpoint', '--stop', 'project rules added', '--next', 'upgrade')
        self.upgrade(self.root)
        text = agents.read_text(encoding='utf-8')
        self.assertTrue(text.startswith((TEMPLATE / 'AGENTS.md').read_text(encoding='utf-8').rstrip('\n')))
        self.assertNotIn('An older rule.', text)
        self.assertTrue(text.endswith('\n## Project rules\n\nRules kept from the AGENTS.md that existed before installation.\n\nUse tabs.\n'))

    def test_refuses_modified_tool_code(self):
        self.aged()
        views = self.root / '.agents/tools/wslib/core.py'
        views.write_bytes(views.read_bytes() + b'\n# a local patch\n')
        before = snapshot(self.root)
        refused = self.upgrade(self.root, expect=2).stderr
        self.assertIn('.agents/tools/wslib/core.py', refused)
        self.assertEqual(snapshot(self.root), before)

    def test_refuses_an_owned_workspace(self):
        self.aged()
        self.run_ws(self.root, 'start')
        self.assertIn('is working in this workspace', self.upgrade(self.root, expect=2).stderr)

    def test_refuses_v2_and_names_migrate(self):
        v2 = self.parent / 'v2'
        v2_workspace(v2)
        self.assertIn('migrate --target', self.upgrade(v2, expect=2).stderr)

    def test_regenerates_only_our_hook_entries(self):
        self.aged()
        user = {'hooks': [{'type': 'command', 'command': 'echo user hook'}]}
        old = {'hooks': [{'type': 'command', 'command': 'python3 .agents/tools/ws.py turn --hook claude --old'}]}
        self.write('.claude/settings.json', json.dumps({'permissions': {'allow': ['Bash(ls)']},
                                                         'hooks': {'UserPromptSubmit': [old], 'Stop': [user]}}))
        self.upgrade(self.root)
        data = json.loads(self.read('.claude/settings.json'))
        commands = [h['command'] for entries in data['hooks'].values() for e in entries for h in e['hooks']]
        self.assertIn('echo user hook', commands)
        self.assertIn('python3 .agents/tools/ws.py turn --hook claude', commands)
        self.assertNotIn('python3 .agents/tools/ws.py turn --hook claude --old', commands)
        self.assertEqual(data['permissions'], {'allow': ['Bash(ls)']})

    def test_is_idempotent(self):
        self.aged()
        first = json.loads(self.upgrade(self.root).stdout)
        self.assertEqual((first['rebaselined'], first['new_errors']), (True, []))
        folders = sorted((self.root / upgrade.UPGRADES).iterdir())
        again = json.loads(self.upgrade(self.root).stdout)
        self.assertFalse(again['changed'])
        self.assertEqual(sorted((self.root / upgrade.UPGRADES).iterdir()), folders)

    def stop_at(self, error, nth=3):
        """os.replace that raises error on the nth file moved from staging into the project."""
        real, moved, staging = os.replace, [], str(self.root / upgrade.STAGING)

        def replace(source, path):
            if str(source).startswith(staging) and not str(path).startswith(staging):
                moved.append(path)
                if len(moved) == nth:
                    raise error
            real(source, path)
        return mock.patch.object(upgrade.os, 'replace', replace)

    def applying(self):
        return [p.name for p in (self.root / upgrade.UPGRADES).iterdir() if upgrade._journal_state(p) == 'applying']

    def test_interrupted_then_rollback_restores_bytes(self):
        self.aged()
        before = snapshot(self.root)
        with self.stop_at(OSError(28, 'No space left on device')), \
                self.assertRaisesRegex(core.WorkspaceError, 'every file was put back'):
            upgrade.run(TEMPLATE, self.root)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.applying(), [])
        with self.stop_at(Killed()), self.assertRaises(Killed):
            upgrade.run(TEMPLATE, self.root)
        (name,) = self.applying()
        self.assertIn('was interrupted', self.upgrade(self.root, expect=2).stderr)
        self.upgrade(self.root, '--rollback', name)
        self.assertEqual(snapshot(self.root), before)
        self.run_ws(self.root, 'check', '--ready')
        self.assertIn('rolled back already', self.upgrade(self.root, '--rollback', name, expect=2).stderr)

    def test_rollback_after_new_work_needs_force_and_keeps_the_state(self):
        self.aged()
        name = Path(json.loads(self.upgrade(self.root).stdout)['folder']).name
        self.run_ws(self.root, 'start')
        self.run_ws(self.root, 'checkpoint', '--stop', 'worked after the upgrade', '--next', 'more')
        self.assertIn('sessions have written', self.upgrade(self.root, '--rollback', name, expect=2).stderr)
        handoff = self.read('docs/state/HANDOFF.md')
        # Going back to a tool that knows only summary rules 1 lists the evidence it would refuse.
        with mock.patch.object(upgrade, '_rules_of', return_value=1), \
                mock.patch.object(evidence, 'refused_by_rules_1', return_value=['T1: docs/archive/checks/x.json']):
            done = upgrade.rollback(self.root, name, force=True)
        self.assertIn('next "ws checkpoint"', done['note'])
        self.assertEqual(done['verify_again'], ['T1: docs/archive/checks/x.json'])
        self.assertTrue((self.root / OLD_TOOL).exists())
        self.assertEqual(self.read('docs/state/HANDOFF.md'), handoff)

    def test_a_new_tool_that_fails_on_the_project_is_rolled_back(self):
        self.aged()
        before = snapshot(self.root)
        with mock.patch.object(upgrade, '_check', side_effect=[(0, []), (99, ['KeyError: card'])]), \
                self.assertRaisesRegex(core.WorkspaceError, 'rolled back'):
            upgrade.run(TEMPLATE, self.root)
        self.assertEqual(snapshot(self.root), before)
        # When the old tool failed too, going back would not help, so the upgrade stays.
        with mock.patch.object(upgrade, '_check', side_effect=[(99, ['old']), (99, ['new'])]):
            self.assertTrue(upgrade.run(TEMPLATE, self.root)['changed'])
        self.assertFalse((self.root / OLD_TOOL).exists())

    def test_a_failed_restore_exits_3_and_names_the_rollback(self):
        self.aged()
        before = snapshot(self.root)
        with self.stop_at(OSError(28, 'No space left on device')), \
                mock.patch.object(upgrade.shutil, 'copyfile', side_effect=PermissionError('held by an editor')), \
                self.assertRaises(upgrade.RestoreFailed) as caught:
            upgrade.run(TEMPLATE, self.root)
        (name,) = self.applying()
        self.assertIn(f'--rollback {name}', str(caught.exception))
        spec = importlib.util.spec_from_file_location('wscli', TOOLS / 'ws.py')
        ws = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ws)
        with mock.patch.object(upgrade.shutil, 'copyfile', side_effect=PermissionError('held by an editor')), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ws.main(['upgrade', '--target', str(self.root), '--rollback', name]), 3)
        self.assertIn('run the rollback again', err.getvalue())
        self.upgrade(self.root, '--rollback', name)
        self.assertEqual(snapshot(self.root), before)

    def test_bases_from_zip_and_head_manifests(self):
        for shape in ('package', 'checkout'):
            with self.subTest(shape=shape):
                root = self.aged(self.parent / shape, maintainer=shape == 'checkout')
                self.upgrade(root)
                self.run_ws(root, 'check', '--ready')
        root = self.aged(self.parent / 'no-manifest')
        package = self.parent / 'old-release.zip'
        with zipfile.ZipFile(package, 'w') as bundle:
            for rel in (OLD_TOOL, '.agents/guides/HOSTS.md', '.agents/tools/wslib/views.py'):
                bundle.write(root / rel, f'agent-workspace-old/{rel}')
        (root / MANIFEST).unlink()
        self.run_ws(root, 'start')
        self.run_ws(root, 'checkpoint', '--stop', 'manifest gone', '--next', 'upgrade')
        report = json.loads(self.upgrade(root, '--assume-base', str(package)).stdout)
        self.assertEqual(report['counts'].get('delete'), 1)
        self.assertFalse((root / OLD_TOOL).exists())

    def test_scan_lists_versions_and_writes_nothing(self):
        folder = self.parent / 'projects'
        self.aged(folder / 'notes')
        v2_workspace(folder / 'legacy')
        before = {p: snapshot(folder / p) for p in ('notes', 'legacy')}
        out = subprocess.run([sys.executable, str(TOOLS / 'ws.py'), 'upgrade', '--scan', str(folder)], env=ENV,
                             capture_output=True, text=True, encoding='utf-8')
        lines = {Path(l['path']).name: l for l in map(json.loads, out.stdout.splitlines())}
        self.assertEqual(lines['legacy']['schema'], 'continuity.v2')
        self.assertEqual(lines['notes']['schema'], 'continuity.v3')
        self.assertEqual(lines['notes']['plan'].get('replace'), 2)
        self.assertEqual({p: snapshot(folder / p) for p in before}, before)

    def test_linked_agents_folder_is_refused(self):
        self.aged()
        other = self.parent / 'linked'
        shutil.copytree(self.root, other, ignore=shutil.ignore_patterns('.agents'))
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(self.root / '.agents'), str(other / '.agents'))
        else:
            os.symlink(self.root / '.agents', other / '.agents')
        self.addCleanup(os.rmdir if os.name == 'nt' else os.unlink, other / '.agents')
        self.assertIn('is a link', self.upgrade(other, expect=2).stderr)


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

    def test_removed_entries_are_template_files_that_are_gone(self):
        self.released()
        with self.assertRaisesRegex(core.WorkspaceError, 'not .agents/guides/HOSTS.md'):
            upgrade.rebaseline(self.root, [], 'test', removed=['.agents/guides/HOSTS.md'])
        (self.root / 'notes.py').unlink()
        with self.assertRaisesRegex(core.WorkspaceError, 'not notes.py'):
            upgrade.rebaseline(self.root, [], 'test', removed=['notes.py'])
        self.assertIn('notes.py', self.ws('check', expect=1).stdout)

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
