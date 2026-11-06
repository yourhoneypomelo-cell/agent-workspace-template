"""Install the template into a project, export a clean copy and stamp releases."""
from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from . import defaults
from .core import WorkspaceError, atomic_write, now, sha
from .schema import (ADAPTERS, DIST_DIR, LOG_DIR, MAINTAINER_FILES, MANIFEST, PACKAGE_PREFIX, RUNTIME_FILES, SEARCH_IGNORE,
                     SEARCH_IGNORE_TEXT, STATE_DIR, STATIC_FILES, TEMPLATE_MARKER, VERSION)

MERGEABLE = ('AGENTS.md', 'CLAUDE.md', 'CODEBUDDY.md', '.gemini/settings.json')


def scratch_dir() -> str | None:
    """Folder for temporary build and test trees: WS_TEMP when set, so a full system drive can be avoided."""
    folder = os.environ.get('WS_TEMP')
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
    return folder or None


def static_payload(source: Path, allow_modified=False) -> dict:
    """The runtime files a project receives. Maintainer files stay in the template folder."""
    payload = {}
    missing = [rel for rel in RUNTIME_FILES if not (source / rel).is_file()]
    if missing:
        raise WorkspaceError('the template source is incomplete: ' + ', '.join(missing[:10]))
    for rel in RUNTIME_FILES:
        payload[rel] = (source / rel).read_text(encoding='utf-8').replace('\r\n', '\n')
    manifest_path = source / MANIFEST
    if not allow_modified:
        if not manifest_path.is_file():
            raise WorkspaceError(f'{MANIFEST} is missing; run "ws.py release" in the template checkout')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        changed = [rel for rel, text in payload.items() if manifest.get('files', {}).get(rel) != sha(text.encode('utf-8'))]
        if changed:
            raise WorkspaceError('these template files differ from the release manifest and may hold project rules: ' +
                                 ', '.join(changed[:8]) + '. Use --allow-modified to copy them anyway')
    return payload


def plan(source: Path, target: Path, merge: bool, allow_modified: bool) -> dict:
    target = target.absolute()
    if target.resolve() == source.resolve() or target.resolve().is_relative_to(source.resolve()):
        raise WorkspaceError('the target must be outside the template folder')
    if target.exists() and not target.is_dir():
        raise WorkspaceError('the target must be a directory')
    payload = static_payload(source, allow_modified)
    payload.update(defaults.documents())
    payload[MANIFEST] = (source / MANIFEST).read_text(encoding='utf-8') if (source / MANIFEST).is_file() else '{}\n'
    payload['.agents/.gitattributes'] = defaults.GITATTRIBUTES
    payload['.agents/.gitignore'] = '# Rebuildable hash cache and command lock.\ncache/\n'
    for rel in SEARCH_IGNORE:
        payload[rel] = SEARCH_IGNORE_TEXT
    writes, merges, skipped, conflicts = {}, {}, [], []
    for rel, text in payload.items():
        path = target / rel
        if not path.exists():
            writes[rel] = text
        elif rel in ('README.md', 'docs/chats/.gitignore', 'docs/.gitattributes', '.agents/.gitattributes', '.agents/.gitignore',
                     *SEARCH_IGNORE):
            skipped.append(rel)
        elif rel in MERGEABLE and merge:
            merges[rel] = merged(rel, path.read_text(encoding='utf-8'), text)
        else:
            conflicts.append(rel)
    for folder in (STATE_DIR, LOG_DIR):
        existing = target / folder
        if existing.is_dir():
            ours = {Path(r).name for r in payload if r.startswith(folder + '/')}
            extra = sorted(p.name for p in existing.iterdir() if p.name not in ours)
            if extra:
                conflicts.append(f'{folder}/ already holds {", ".join(extra)}')
    if any(p.startswith('docs/state/') for p in conflicts):
        conflicts.append('docs/state exists: this looks like an installed workspace. Use "ws.py migrate" for continuity.v2 projects')
    return {'target': str(target), 'writes': sorted(writes), 'merges': sorted(merges), 'skipped': skipped,
            'conflicts': conflicts, '_payload': {**writes, **merges}}


def merged(rel: str, existing: str, ours: str) -> str:
    if rel == 'AGENTS.md':
        return ours.rstrip('\n') + '\n\n## Project rules\n\nRules kept from the AGENTS.md that existed before installation.\n\n' + \
            re.sub(r'^# ', '### ', existing.strip(), flags=re.M) + '\n'
    if rel in ('CLAUDE.md', 'CODEBUDDY.md'):
        return existing if re.search(r'^@AGENTS\.md\s*$', existing, re.M) else '@AGENTS.md\n\n' + existing
    data = json.loads(existing or '{}')
    context = data.setdefault('context', {})
    names = context.get('fileName') or ['GEMINI.md']
    names = names if isinstance(names, list) else [names]
    context['fileName'] = ['AGENTS.md', *[n for n in names if n != 'AGENTS.md']]
    return json.dumps(data, indent=2) + '\n'


def install(source: Path, target: Path, dry_run=False, merge=False, allow_modified=False) -> dict:
    result = plan(source, target, merge, allow_modified)
    payload = result.pop('_payload')
    if dry_run:
        return result
    if result['conflicts']:
        raise WorkspaceError('nothing was written. Conflicts:\n  ' + '\n  '.join(result['conflicts']) +
                             '\nUse --merge to merge AGENTS.md, CLAUDE.md and .gemini/settings.json')
    root = Path(result['target'])
    for rel, text in payload.items():
        atomic_write(root / rel, text)
    from .validate import structure
    errors = structure(root, strict=True)
    if errors:
        raise WorkspaceError('installed files fail validation: ' + '; '.join(errors))
    return result


def maintainer_leftovers(root: Path) -> list:
    """Maintainer files an older install copied into a project. None in the template checkout itself."""
    if (root / TEMPLATE_MARKER).is_file():
        return []
    return [rel for rel in MAINTAINER_FILES if (root / rel).is_file()]


def tidy(root: Path, dry_run=False, force=False) -> dict:
    """Remove maintainer files left by an older install, and add the search ignore files. A maintainer file that
    differs from the manifest of the installed release is kept and listed, because someone may have edited it or it
    came from an older release; force removes those too."""
    if (root / TEMPLATE_MARKER).is_file():
        raise WorkspaceError('this is the template checkout; its maintainer files belong here')
    manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8')) if (root / MANIFEST).is_file() else {}
    removed, kept, added = [], [], []
    for rel in maintainer_leftovers(root):
        text = (root / rel).read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
        if force or manifest.get('files', {}).get(rel) == sha(text.encode('utf-8')):
            removed.append(rel)
            if not dry_run:
                (root / rel).unlink()
        else:
            kept.append(rel)
    for rel in SEARCH_IGNORE:
        if not (root / rel).exists():
            added.append(rel)
            if not dry_run:
                atomic_write(root / rel, SEARCH_IGNORE_TEXT)
    if not dry_run:
        for folder in (root / '.agents/tools/tests', root / '.agents/tools/tests/__pycache__'):
            if folder.is_dir() and not any(p for p in folder.iterdir() if p.name != '__pycache__'):
                import shutil
                shutil.rmtree(folder, ignore_errors=True)
    result = {'removed': removed, 'kept_edited': kept, 'added': added, 'dry_run': dry_run}
    if kept:
        result['note'] = ('kept_edited files differ from this release: an older release or a local edit. '
                          'Move anything the project needs into docs/, then run "ws tidy --force"')
    return result


def export(source: Path, output: Path, allow_modified=False) -> dict:
    output = output.absolute()
    archive = output.with_name(output.name + '.zip')
    if output.exists() or archive.exists():
        raise WorkspaceError(f'{output} or {archive.name} exists; choose a new name')
    result = install(source, output, allow_modified=allow_modified)
    _write_zip(output, archive)
    return {'directory': str(output), 'zip': str(archive), 'files': len(result['writes'])}


def stamp(source: Path) -> dict:
    files = {rel: sha((source / rel).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')) for rel in STATIC_FILES}
    manifest = {'schema': 'template-manifest.v3', 'version': VERSION, 'created_at': now(), 'files': files}
    atomic_write(source / MANIFEST, json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return {'manifest': MANIFEST, 'files': len(files)}


def _write_zip(folder: Path, archive: Path):
    """Deterministic order and timestamps, so the same content gives the same bytes."""
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(p for p in folder.rglob('*') if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(folder).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())


def check_package(archive: Path) -> dict:
    """Unpack into a fresh folder and prove a new project can start from it."""
    import subprocess
    import sys
    from .core import state_of
    with tempfile.TemporaryDirectory(prefix='ws-package-check-', dir=scratch_dir()) as folder:
        project = Path(folder) / 'new-project'
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            bad = [n for n in names if n.startswith(('/', '..')) or '/../' in n or ':' in n]
            if bad:
                raise WorkspaceError(f'package holds unsafe paths: {bad[:5]}')
            bundle.extractall(project)
        unexpected = [n for n in names if n.startswith(('docs/archive/', 'docs/specs/', '.agents/cache/', 'dist/'))
                      or '__pycache__' in n or n.endswith('.pyc') or n in MAINTAINER_FILES]
        if unexpected:
            raise WorkspaceError(f'package holds non-template files: {unexpected[:5]}')
        state = state_of(project)
        if state['mode'] != 'bootstrap' or state['revision'] != 0 or state.get('writer'):
            raise WorkspaceError('package state is not a clean bootstrap')
        for rel, text in defaults.documents().items():
            if (project / rel).read_text(encoding='utf-8') != text:
                raise WorkspaceError(f'package file {rel} differs from the clean default')
        tool = [sys.executable, str(project / '.agents/tools/ws.py'), '--root', str(project)]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', WS_NO_CACHE='1')

        def ws(*args):
            run = subprocess.run([*tool, *args], capture_output=True, text=True, encoding='utf-8', env=env)
            if run.returncode != 0:
                raise WorkspaceError(f'package check failed at "ws {" ".join(args)}":\n{run.stdout}{run.stderr}')
        ws('check', '--strict')
        # The unpacked package must install elsewhere without --allow-modified: its manifest matches its files.
        static_payload(project)
        ws('init', '--goal', 'Package smoke test')
        ws('add', 'requirement', '--set', 'requirement=Smoke test runs', '--set', 'acceptance=ws check --ready passes')
        ws('checkpoint', '--stop', 'package smoke test initialized', '--next', 'inspect the project',
           '--set', 'phase=smoke', '--set', 'risks=none confirmed', '--set', 'next_acceptance=ws check --ready')
        ws('check', '--ready')
    return {'files': len(names), 'checked': 'unpacked, validated, init, checkpoint, ready'}


def release(source: Path, keep_old=False) -> dict:
    """Stamp the manifest and replace dist/ with one verified clean package for this version."""
    result = stamp(source)
    dist = source / DIST_DIR
    dist.mkdir(exist_ok=True)
    name = f'{PACKAGE_PREFIX}{VERSION}'
    final = dist / f'{name}.zip'
    with tempfile.TemporaryDirectory(prefix='ws-release-', dir=scratch_dir()) as folder:
        staging = Path(folder) / name
        install(source, staging)
        built = Path(folder) / f'{name}.zip'
        _write_zip(staging, built)
        check = check_package(built)
        data = built.read_bytes()
    temporary = dist / f'.{name}.zip.tmp'
    temporary.write_bytes(data)
    os.replace(temporary, final)
    removed = []
    if not keep_old:
        for old in dist.glob(f'{PACKAGE_PREFIX}*.zip'):
            if old != final:
                old.unlink()
                removed.append(old.name)
    notes = dist / 'README.md'
    atomic_write(notes, f'# Release package\n\nOne clean package per template version, rebuilt by `ws.py release`.\n\n'
                        f'| Field | Value |\n| --- | --- |\n| File | `{final.name}` |\n| Version | {VERSION} |\n'
                        f'| Files | {check["files"]} |\n| SHA-256 | `{sha(data)}` |\n| Built | {now()} |\n\n'
                        '## Start a project\n\n1. Unzip the package into an empty folder. The archive has no top-level folder.\n'
                        '2. Open that folder in an agent tool and say: "Read AGENTS.md and start. The goal is: ..."\n')
    return {**result, 'package': f'{DIST_DIR}/{final.name}', 'sha256': sha(data), 'bytes': len(data),
            'files': check['files'], 'removed': removed, 'verified': check['checked']}


def adapters_present(root: Path) -> list:
    return [rel for rel in ADAPTERS if (root / rel).is_file()]
