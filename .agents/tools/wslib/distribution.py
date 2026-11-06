"""Install the template into a project, export a clean copy and stamp releases."""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from . import defaults
from .core import WorkspaceError, atomic_write, digest, now, sha
from .schema import (ADAPTERS, DIST_DIR, GUIDE_DIR, LOG_DIR, MAINTAINER_FILES, MANIFEST, PACKAGE_PREFIX, RUNTIME_FILES,
                     SEARCH_IGNORE, SEARCH_IGNORE_TEXT, SELFTEST, STATE_DIR, STATIC_FILES, TEMPLATE_MARKER, TOOLS_DIR, VERSION)

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
    # A failure part way leaves the target as it was: merged files get their old bytes, new files and folders go.
    originals = {rel: (root / rel).read_bytes() for rel in result['merges']}
    folders = {p for rel in payload for p in (root / rel).parents if p.is_dir()}
    written = []
    try:
        for rel, text in payload.items():
            atomic_write(root / rel, text)
            written.append(rel)
        from .validate import structure
        errors = structure(root, strict=True)
        if errors:
            raise WorkspaceError('installed files fail validation: ' + '; '.join(errors))
    except BaseException:
        for rel in written:
            if rel in originals:
                (root / rel).write_bytes(originals[rel])
            else:
                (root / rel).unlink(missing_ok=True)
        for folder in sorted({p for rel in written for p in (root / rel).parents} - folders, key=lambda p: -len(p.parts)):
            with contextlib.suppress(OSError):
                folder.rmdir()
        raise
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


# Damage a writing tool has done to this source without breaking a test: rows.py held two backspace bytes where
# "\b" was meant, and coverage.py a backslash line continuation flattened into spaces.
CONTROL_BYTE = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def control_bytes(source: Path) -> list:
    """file:line of every control character other than tab and line ends in the template's files."""
    found = []
    for rel in STATIC_FILES:
        path = source / rel
        if path.is_file():
            found += [f'{rel}:{number}: control character' for number, line in enumerate(path.read_bytes().split(b'\n'), 1)
                      if CONTROL_BYTE.search(line)]
    return found


def collapsed_continuations(source: Path) -> list:
    """file:line where two tokens of one line stand five or more spaces apart, the mark of a flattened continuation."""
    import io
    import tokenize
    breaks = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    found = []
    for rel in (r for r in STATIC_FILES if r.endswith('.py') and (source / r).is_file()):
        previous = None
        try:
            for token in tokenize.generate_tokens(io.StringIO((source / rel).read_text(encoding='utf-8')).readline):
                if token.type in breaks:
                    previous = None
                    continue
                if previous and previous.end[0] == token.start[0] and token.start[1] - previous.end[1] >= 5:
                    found.append(f'{rel}:{token.start[0]}: tokens five or more spaces apart; was a line continuation lost?')
                previous = token
        except (tokenize.TokenError, SyntaxError) as error:
            found.append(f'{rel}: cannot be tokenized: {error}')
    return found


def tree_digest(source: Path) -> str:
    """One hash over the static files, so a recorded self-test run can be matched to the code it ran on."""
    return digest({rel: sha((source / rel).read_bytes().replace(b'\r\n', b'\n')) for rel in STATIC_FILES
                   if (source / rel).is_file()})


def run_tier(source: Path, tier: str) -> dict:
    """One tier of the self-tests in a child process. WS_IN_GATE stops the release tests inside it from gating again."""
    import subprocess
    import sys
    import time
    script = source / f'{TOOLS_DIR}/tests/run.py'
    env = dict(os.environ, WS_IN_GATE='1', WS_IMPORT='0', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    started = time.monotonic()
    run = subprocess.run([sys.executable, str(script), '--tier', tier], cwd=script.parent, capture_output=True, text=True,
                         encoding='utf-8', errors='replace', env=env)
    output = run.stdout + run.stderr
    if run.returncode != 0:
        raise WorkspaceError(f'release refused: the {tier} self-tests failed:\n' + '\n'.join(output.strip().splitlines()[-40:]))
    ran = re.findall(r'^Ran (\d+) tests? in', output, re.M)
    return {'tests': int(ran[-1]) if ran else 0, 'seconds': round(time.monotonic() - started, 1)}


def full_run(source: Path, skip_full: str | None = None) -> dict:
    """The record a passing "run.py --tier full" leaves, accepted only for the code it ran on."""
    try:
        record = json.loads((source / SELFTEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        record = {}
    if record.get('passed') is True and record.get('tree') == tree_digest(source):
        return {key: record.get(key) for key in ('tests', 'seconds', 'python', 'at')}
    if skip_full:
        return {'skipped': ' '.join(skip_full.split())}
    if not record:
        reason = 'no full self-test run is recorded'
    elif record.get('passed') is not True:
        reason = 'the last full self-test run failed'
    else:
        reason = 'the code changed after the last full self-test run'
    raise WorkspaceError(f'release refused: {reason}. Run "python {TOOLS_DIR}/tests/run.py --tier full", or give '
                         '--skip-full "<reason>"; the reason is printed in dist/README.md')


def gate(source: Path, skip_full: str | None = None) -> dict:
    """What a release must pass before it stamps the manifest. Returns the self-test runs for dist/README.md."""
    from . import lint
    from .validate import structure
    problems = control_bytes(source) + collapsed_continuations(source) + lint.run(source) + structure(source, strict=True)
    versions = (source / f'{GUIDE_DIR}/MAINTAINING.md').read_text(encoding='utf-8')
    if not re.search(rf'^\| {re.escape(VERSION)} \|', versions, re.M):
        problems.append(f'MAINTAINING.md: the version table has no row for {VERSION}')
    if problems:
        raise WorkspaceError('release refused; fix these first:\n  ' + '\n  '.join(problems[:20]))
    return {'fast': run_tier(source, 'fast'), 'full': full_run(source, skip_full)}


def _tests_text(checks: dict | None) -> str:
    if checks is None:
        return 'not run: release was called without its gate'
    fast, full = checks['fast'], checks['full']
    text = f'fast tier {fast["tests"]} tests in {fast["seconds"]} s; '
    if 'skipped' in full:
        return text + 'full tier skipped: ' + full['skipped'].replace('|', '/')
    return text + f'full tier {full["tests"]} tests in {full["seconds"]} s on Python {full["python"]}, {full["at"]}'


def release(source: Path, keep_old=False, skip_full: str | None = None, gated=True) -> dict:
    """Pass the gate, stamp the manifest and replace dist/ with one verified clean package for this version.
    A failed build puts the previous manifest back, so the checkout never describes a package that was not built."""
    checks = gate(source, skip_full) if gated and not os.environ.get('WS_IN_GATE') else None
    manifest = source / MANIFEST
    previous = manifest.read_bytes() if manifest.is_file() else None
    dist = source / DIST_DIR
    name = f'{PACKAGE_PREFIX}{VERSION}'
    final = dist / f'{name}.zip'
    try:
        result = stamp(source)
        dist.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='ws-release-', dir=scratch_dir()) as folder:
            staging = Path(folder) / name
            install(source, staging)
            built = Path(folder) / f'{name}.zip'
            _write_zip(staging, built)
            check = check_package(built)
            data = built.read_bytes()
    except BaseException:
        if previous is None:
            manifest.unlink(missing_ok=True)
        else:
            manifest.write_bytes(previous)
        raise
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
                        f'| Files | {check["files"]} |\n| SHA-256 | `{sha(data)}` |\n| Built | {now()} |\n'
                        f'| Self-tests | {_tests_text(checks)} |\n\n'
                        '## Start a project\n\n1. Unzip the package into an empty folder. The archive has no top-level folder.\n'
                        '2. Open that folder in an agent tool and say: "Read AGENTS.md and start. The goal is: ..."\n')
    return {**result, 'package': f'{DIST_DIR}/{final.name}', 'sha256': sha(data), 'bytes': len(data),
            'files': check['files'], 'removed': removed, 'verified': check['checked'], 'self_tests': checks}


def adapters_present(root: Path) -> list:
    return [rel for rel in ADAPTERS if (root / rel).is_file()]
