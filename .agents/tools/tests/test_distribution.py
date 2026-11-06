"""Install, export, release package and continuity.v2 migration."""
import json
import os
import re
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from support import TEMPLATE, Workspace
from wslib import defaults, distribution, migrate, tables
from wslib.core import WorkspaceError, state_of
from wslib.schema import MAINTAINER_FILES, MANIFEST, SEARCH_IGNORE, SELFTEST, STATIC_FILES, TABLES, VERSION

V2_BACKUP = Path(os.environ.get('WS_V2_FIXTURE', TEMPLATE.parent / 'agent-workspace-template-v2.3.3.backup-20261031'))


class Install(Workspace):
    def test_generated_files_match_defaults(self):
        for rel, text in defaults.documents().items():
            if rel != 'README.md':
                self.assertEqual(self.read(rel), text, rel)

    def test_template_checkout_matches_defaults(self):
        # The checkout's README.md is the repository front page; projects receive the generated one.
        for rel, text in defaults.documents().items():
            if rel != 'README.md':
                self.assertEqual((TEMPLATE / rel).read_text(encoding='utf-8'), text, rel)

    def test_facade_readme_stays_in_template(self):
        self.assertEqual(self.read('README.md'), defaults.documents()['README.md'])
        for rel in ('README.zh-CN.md', 'DESIGN.md', 'DESIGN.zh-CN.md'):
            self.assertFalse((self.root / rel).exists(), rel)

    def test_i2_install_failure_leaves_the_target_unchanged(self):
        target = self.parent / 'product'
        (target / 'src').mkdir(parents=True)
        (target / 'src/app.py').write_text('print(1)\n', encoding='utf-8')
        (target / 'AGENTS.md').write_bytes(b'# Old rules\r\n\r\nUse tabs.\r\n')
        before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        real, calls = distribution.atomic_write, []

        def fail_late(path, text):
            calls.append(path)
            if len(calls) == 20:
                raise OSError('disk full')
            real(path, text)
        with mock.patch.object(distribution, 'atomic_write', fail_late), self.assertRaises(OSError):
            distribution.install(TEMPLATE, target, merge=True, allow_modified=True)
        after = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ['AGENTS.md', 'src'])

    def test_project_readme_links_are_not_checked(self):
        self.init()
        self.write('README.md', '# My product\n\nSee [the guide](docs/guide.md).\n')
        self.save()

    def test_install_keeps_existing_files_and_reports_conflicts(self):
        target = self.parent / 'product'
        (target / 'src').mkdir(parents=True)
        (target / 'README.md').write_text('# My product\n', encoding='utf-8')
        (target / 'AGENTS.md').write_text('# Old rules\n\nUse tabs.\n', encoding='utf-8')
        plan = distribution.install(TEMPLATE, target, dry_run=True, allow_modified=True)
        self.assertIn('AGENTS.md', plan['conflicts'])
        with self.assertRaises(WorkspaceError):
            distribution.install(TEMPLATE, target, allow_modified=True)
        self.assertFalse((target / 'docs').exists())
        distribution.install(TEMPLATE, target, merge=True, allow_modified=True)
        self.assertEqual((target / 'README.md').read_text(encoding='utf-8'), '# My product\n')
        agents = (target / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('## Project rules', agents)
        self.assertIn('Use tabs.', agents)

    def test_installed_project_validates(self):
        self.ws('check', '--strict')

    def test_modified_system_file_blocks_install(self):
        source = self.parent / 'template-copy'
        shutil.copytree(TEMPLATE, source, ignore=shutil.ignore_patterns('cache', 'archive'))
        distribution.stamp(source)
        path = source / '.agents/guides/PROTOCOL.md'
        path.write_text(path.read_text(encoding='utf-8') + '\nPRIVATE RULE\n', encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, 'differ from the release manifest'):
            distribution.install(source, self.parent / 'x')

    def test_export_writes_clean_zip(self):
        self.planned()
        out = self.parent / 'release'
        distribution.export(self.root, out, allow_modified=True)
        self.assertEqual(state_of(out)['mode'], 'bootstrap')
        with zipfile.ZipFile(str(out) + '.zip') as bundle:
            names = bundle.namelist()
            text = '\n'.join(bundle.read(n).decode('utf-8') for n in names if '/docs/' in n)
        self.assertFalse(any(n.endswith('test_demo.py') for n in names))
        self.assertNotIn('Build a small tested demo', text)
        self.assertNotIn('Demo returns 4', text)

    def test_release_builds_one_verified_clean_package(self):
        source = self.parent / 'template-copy'
        shutil.copytree(TEMPLATE, source, ignore=shutil.ignore_patterns('cache', 'archive', 'dist'))
        (source / 'dist').mkdir()
        (source / 'dist/agent-workspace-0.9.0.zip').write_bytes(b'old')
        first = distribution.release(source, gated=False)
        self.assertEqual(first['removed'], ['agent-workspace-0.9.0.zip'])
        packages = sorted(p.name for p in (source / 'dist').glob('*.zip'))
        self.assertEqual(packages, [Path(first['package']).name])
        with zipfile.ZipFile(source / first['package']) as bundle:
            names = bundle.namelist()
        self.assertIn('AGENTS.md', names)
        self.assertIn('.agents/tools/ws.py', names)
        self.assertFalse([n for n in names if n.startswith(('dist/', 'docs/archive/', '.agents/cache/')) or n.endswith('.pyc')])
        unpacked = self.parent / 'fresh'
        with zipfile.ZipFile(source / first['package']) as bundle:
            bundle.extractall(unpacked)
        self.assertEqual(state_of(unpacked)['mode'], 'bootstrap')
        self.assertIn(first['sha256'], (source / 'dist/README.md').read_text(encoding='utf-8'))
        second = distribution.release(source, gated=False)
        self.assertEqual(sorted(p.name for p in (source / 'dist').glob('*.zip')), [Path(second['package']).name])

    def test_project_folder_cannot_release(self):
        self.init()
        result = self.ws('release', expect=2)
        self.assertIn('template folder', result.stderr)

    def test_projects_get_no_maintainer_files_and_searches_skip_the_tool(self):
        for rel in MAINTAINER_FILES:
            self.assertTrue((TEMPLATE / rel).is_file(), rel)
            self.assertFalse((self.root / rel).exists(), rel)
        self.assertFalse((self.root / '.agents/tools/tests').exists())
        for rel in SEARCH_IGNORE:
            self.assertIn('.agents/tools/', self.read(rel))
        self.init()
        self.assertNotIn('maintainer files', self.ws('check', expect=None).stdout)

    def test_tidy_removes_unedited_leftovers_and_keeps_edited_ones(self):
        self.init()
        old, edited = '.agents/guides/MAINTAINING.md', '.agents/guides/DESIGN_REQUIREMENTS.md'
        for rel in (old, edited, '.agents/tools/tests/support.py'):
            self.write(rel, (TEMPLATE / rel).read_text(encoding='utf-8'))
        self.write(edited, self.read(edited) + '\nProject note.\n')
        (self.root / '.ignore').unlink()
        self.assertIn('maintainer files', self.ws('check', expect=None).stdout)
        self.assertTrue((self.root / old).is_file())
        dry = json.loads(self.ws('tidy', '--dry-run').stdout)
        self.assertTrue((self.root / old).is_file())
        result = json.loads(self.ws('tidy').stdout)
        self.assertEqual(dry['removed'], result['removed'])
        self.assertIn(old, result['removed'])
        self.assertEqual(result['kept_edited'], [edited])
        self.assertEqual(result['added'], ['.ignore'])
        self.assertFalse((self.root / old).exists())
        self.assertFalse((self.root / '.agents/tools/tests').exists())
        self.assertTrue((self.root / edited).is_file())
        self.assertIn('--force', result['note'])
        self.assertEqual(json.loads(self.ws('tidy', '--force').stdout)['removed'], [edited])
        self.assertFalse((self.root / edited).exists())

    def test_template_checkout_does_not_report_its_own_maintainer_files(self):
        self.assertEqual(distribution.maintainer_leftovers(TEMPLATE), [])
        with self.assertRaises(WorkspaceError):
            distribution.tidy(TEMPLATE, dry_run=True)

    def test_runtime_documents_may_not_link_maintainer_files(self):
        self.init()
        self.write('.agents/guides/HOSTS.md', self.read('.agents/guides/HOSTS.md') + '\nSee [m](MAINTAINING.md).\n')
        self.write('.agents/guides/MAINTAINING.md', 'x\n')
        self.assertIn('which projects do not receive', self.ws('check', '--strict', expect=None).stdout)

    def test_package_refuses_maintainer_files(self):
        archive = self.parent / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('AGENTS.md', 'x')
            bundle.writestr('.agents/guides/MAINTAINING.md', 'x')
        with self.assertRaises(WorkspaceError):
            distribution.check_package(archive)

    def test_payload_has_no_large_files(self):
        for rel in STATIC_FILES:
            self.assertLess((TEMPLATE / rel).stat().st_size, 40000, rel)


class Release(Workspace):
    def copy(self):
        source = self.parent / 'template-copy'
        shutil.copytree(TEMPLATE, source, ignore=shutil.ignore_patterns('cache', 'archive', 'dist'))
        return source

    def test_release_refuses_a_control_character(self):
        source = self.copy()
        path = source / '.agents/tools/wslib/tables.py'
        path.write_text(path.read_text(encoding='utf-8') + '# \x08\n', encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, r'tables\.py:\d+: control character'):
            distribution.gate(source)

    def test_release_requires_the_version_row(self):
        source = self.copy()
        path = source / '.agents/guides/MAINTAINING.md'
        head, sep, rest = path.read_text(encoding='utf-8').partition('\n## Versions\n')
        section, tail = rest.split('\n## ', 1)
        # Rows of the other tables that start with the version stay; they must not count as its row.
        section = re.sub(rf'^\| {re.escape(VERSION)} \|.*\n', '', section, flags=re.M)
        path.write_text(head + sep + section + '\n## ' + tail, encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, f'no row for {re.escape(VERSION)}'):
            distribution.gate(source)

    def test_release_requires_a_full_run_on_this_code(self):
        source = self.copy()
        with mock.patch.object(distribution, 'run_tier', return_value={'tests': 1, 'seconds': 0.1}):
            with self.assertRaisesRegex(WorkspaceError, 'no full self-test run is recorded'):
                distribution.gate(source)
            self.assertEqual(distribution.gate(source, 'hotfix')['full'], {'skipped': 'hotfix'})

    def test_release_restores_the_manifest_when_the_package_check_fails(self):
        source = self.copy()
        before = (source / MANIFEST).read_bytes()
        with mock.patch.object(distribution, 'check_package', side_effect=WorkspaceError('package check failed')):
            with self.assertRaisesRegex(WorkspaceError, 'package check failed'):
                distribution.release(source, gated=False)
        self.assertEqual((source / MANIFEST).read_bytes(), before)

    def test_release_records_the_gate_result(self):
        source = self.copy()
        record = {'passed': True, 'tree': distribution.tree_digest(source), 'tests': 290, 'seconds': 1100.0,
                  'python': '3.11.2', 'at': '2026-11-07T00:00:00+00:00'}
        (source / SELFTEST).parent.mkdir(parents=True, exist_ok=True)
        (source / SELFTEST).write_text(json.dumps(record), encoding='utf-8')
        with mock.patch.dict(os.environ), mock.patch.object(distribution, 'run_tier', return_value={'tests': 120, 'seconds': 200.0}):
            os.environ.pop('WS_IN_GATE', None)
            result = distribution.release(source)
        notes = (source / 'dist/README.md').read_text(encoding='utf-8')
        self.assertIn('fast tier 120 tests in 200.0 s', notes)
        self.assertIn('full tier 290 tests in 1100.0 s on Python 3.11.2', notes)
        self.assertEqual(result['self_tests']['full']['tests'], 290)


@unittest.skipUnless((V2_BACKUP / 'docs/state/TODO.md').is_file(), 'continuity.v2 backup not available')
class Migration(Workspace):
    def v2_project(self):
        target = self.parent / 'v2'
        shutil.copytree(V2_BACKUP, target)
        todo = target / 'docs/state/TODO.md'
        text = todo.read_text(encoding='utf-8').replace('"mode": "bootstrap"', '"mode": "active"').replace('"revision": 0', '"revision": 7')
        todo.write_text(text.replace('当前任务：无', '当前任务：T2'), encoding='utf-8')
        req = target / 'docs/state/REQUIREMENTS.md'
        req.write_text(req.read_text(encoding='utf-8').replace('<!-- GOAL:END -->', 'Ship a todo CLI\n<!-- GOAL:END -->')
                       .replace('| --- | --- | --- | --- | --- | --- |', '| --- | --- | --- | --- | --- | --- |\n'
                                '| R1 | 确认 | add and list | python -m unittest | inline | 无 |\n'
                                '| R2 | 废弃 | CSV export | n/a | inline | user dropped it |'), encoding='utf-8')
        tasks = target / 'docs/state/TASKS.md'
        tasks.write_text(tasks.read_text(encoding='utf-8').replace('| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
                         '| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n'
                         '| T1 | 完成 | R1 | todo.py | add | python -m unittest | 无 | docs/archive/checks/x.json | 无 |\n'
                         '| T2 | 进行中 | R1 | todo.py | list | python -m unittest | T1 | 无 | 无 |\n'
                         '| T3 | 完成 | R1 | todo.py | done | python -m unittest | 无 | docs/archive/checks/y.json | 无 |'), encoding='utf-8')
        todo.write_text(todo.read_text(encoding='utf-8').replace('当前任务：T2', '当前任务：T3'), encoding='utf-8')
        prefs = target / 'docs/state/PREFERENCES.md'
        prefs.write_text(prefs.read_text(encoding='utf-8') + '| P1 | 中文回复 | user | quote | high |\n', encoding='utf-8')
        (target / 'docs/chats/CURRENT.md').write_text('# Decisions\n\n- D1: JSON storage.\n', encoding='utf-8')
        return target

    def test_v2_workspace_converts(self):
        target = self.v2_project()
        report = migrate.migrate(TEMPLATE, target)
        self.assertEqual(sorted(report['closed_rows']), ['R2', 'T1'])
        self.assertEqual(state_of(target)['schema'], 'continuity.v3')
        tasks = {r['ID']: r for r in tables.rows(target, TABLES['tasks'])}
        self.assertEqual(tasks['T3']['Status'], 'unverified')
        self.assertEqual(tasks['T2']['Status'], 'doing')
        self.assertEqual(tables.rows(target, TABLES['preferences'])[0]['Preference'], '中文回复')
        self.assertTrue((target / 'docs/chats/legacy/CURRENT.md').is_file())
        self.assertTrue((target / 'docs/archive/v2-backup/docs/state/TODO.md').is_file())
        self.assertFalse((target / 'scripts').exists())
        self.assertFalse((target / 'docs/state/TODO.md').exists())
        from wslib.validate import validate
        self.assertEqual(validate(target, sealing=True), [])

    def test_migration_refuses_owned_workspace_unless_forced(self):
        target = self.v2_project()
        todo = target / 'docs/state/TODO.md'
        todo.write_text(todo.read_text(encoding='utf-8').replace('"writer": null', '"writer": "old"'), encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, 'still owns'):
            migrate.migrate(TEMPLATE, target)
        (target / 'scripts/capture_stage.py').write_text('# v2.3.5 file\n', encoding='utf-8')
        report = migrate.migrate(TEMPLATE, target, force=True)
        self.assertEqual(report['held_by'], 'old')
        self.assertFalse((target / 'scripts').exists())
        self.assertIn('was still holding', (target / 'docs/logs/MAINTENANCE_LOG.md').read_text(encoding='utf-8'))
        from wslib.validate import validate
        self.assertEqual(validate(target), [])


if __name__ == '__main__':
    unittest.main()
