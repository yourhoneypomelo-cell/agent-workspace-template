"""ws snapshot: a zip of the documents before a large reorganization (U40). No restore command: a restore that
overwrites files is how other tools destroyed work, so the copy is extracted next to the project and compared."""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from pathlib import Path

from . import logs
from .core import WorkspaceError, card, card_text, now, read, safe_path, save_state, sha, state_of, write
from .locks import lock
from .schema import ADAPTERS, HANDOFF, PRUNE_DIRS, PRUNE_FILES, SECRET_SUFFIXES

FOLDER = 'docs/archive/snapshots'
DEFAULT_SCOPE = ('AGENTS.md', 'README.md', *ADAPTERS, 'docs/state', 'docs/specs', 'docs/guides', 'docs/logs', 'ops',
                 'docs/chats/INDEX.md', 'docs/archive/logs', 'docs/archive/closed', 'docs/archive/rows')
MAX_BYTES = 100 * 1024 * 1024
MAX_FILES = 10_000
KEEP_BYTES = 100 * 1024 * 1024
KEEP_COUNT = 5


SECRET_NAME = re.compile(r'(?i)^(?:id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|\.npmrc|\.pypirc|\.netrc|\.git-credentials|'
                         r'credentials(?:\.json)?|creds?\.json|token(?:s)?\.(?:txt|json)|secrets?\.(?:json|ya?ml|toml|txt))$')


def _skip(name: str) -> bool:
    return (name in PRUNE_DIRS or name in PRUNE_FILES or name == '.env' or name.startswith('.env.')
            or name.endswith(SECRET_SUFFIXES) or bool(SECRET_NAME.match(name)))


def _linked(path: Path) -> bool:
    """A symbolic link or a Windows junction: following it could copy files from outside the project."""
    try:
        return path.is_symlink() or bool(getattr(os.stat(path, follow_symlinks=False), 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True


def files_in(root: Path, paths: list) -> dict:
    """{relative path: size} for the default scope plus the named paths, with the watcher's skip rules. Links,
    secret files and earlier snapshots are never included."""
    found = {}
    inside = safe_path(root, FOLDER).resolve()
    real_root = root.resolve()
    for rel in list(DEFAULT_SCOPE) + list(paths):
        path = safe_path(root, rel)
        if path.resolve() == inside or inside in path.resolve().parents:
            raise WorkspaceError(f'{rel} is inside {FOLDER}; a snapshot cannot hold other snapshots')
        if _linked(path) and path.exists():
            continue
        if path.is_file() and not _skip(path.name):
            found[path.relative_to(root).as_posix()] = path.stat().st_size
        elif path.is_dir():
            for folder, dirs, names in os.walk(path):
                here = Path(folder)
                dirs[:] = [d for d in dirs if not _skip(d) and not _linked(here / d)
                           and (here / d).resolve() != inside and real_root in (here / d).resolve().parents]
                for name in names:
                    full = here / name
                    if not _skip(name) and not _linked(full):
                        found[full.relative_to(root).as_posix()] = full.stat().st_size
        elif rel in paths:
            raise WorkspaceError(f'{rel} does not exist')
    return found


def recovery_files(root: Path, state: dict) -> list:
    """What a copy of the documents needs to pass "ws check": the checkpoint manifest the state line names and the
    evidence the task rows and the seal cite, with their reports."""
    from .core import checkpoint_of
    from .evidence import evidence_paths
    from . import tables
    from .schema import TABLES
    try:
        sealed = list((checkpoint_of(root, state) or {}).get('evidence') or {})
    except (WorkspaceError, ValueError, OSError):
        sealed = []
    rows = tables.rows(root, TABLES['tasks']) + tables.closed_rows(root)
    found = [state['checkpoint']['manifest']] if state.get('checkpoint') else []
    for rel in sorted({p for r in rows for p in evidence_paths(r.get('Evidence', ''))} | set(sealed)):
        found.append(rel)
        try:
            report = json.loads(read(root, rel)).get('report') if rel.endswith('.json') else None
        except (OSError, ValueError, WorkspaceError):
            report = None
        if report:
            found.append(report['path'])
    return [rel for rel in dict.fromkeys(found) if (root / rel).is_file()]


def _largest(files: dict) -> str:
    sizes = {}
    for rel, size in files.items():
        top = rel.split('/', 1)[0]
        sizes[top] = sizes.get(top, 0) + size
    return ', '.join(f'{name} {size / 1048576:.1f} MB' for name, size in sorted(sizes.items(), key=lambda i: -i[1])[:5])


def take(root: Path, label: str, paths: list, pin: bool) -> dict:
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', label or '') or len(label) > 60:
        raise WorkspaceError('--label takes up to 60 characters of lowercase words joined by hyphens, for example before-docs-merge')
    with lock(root):
        state = state_of(root)
        from .core import require_session
        from .claims import label_of
        from .permits import permit
        from .validate import conflict_markers
        require_session(root, state)
        if state['mode'] != 'active' or not label_of(state):
            raise WorkspaceError('no session owns the workspace; run "ws.py start" first')
        # The snapshot sets the card's baseline, and the card belongs to whoever works alone.
        permit(state, 'workspace', what='ws snapshot')
        for marker in conflict_markers(root)[:1]:
            raise WorkspaceError(marker)
        files = files_in(root, [*paths, *recovery_files(root, state)])
        total = sum(files.values())
        if total > MAX_BYTES or len(files) > MAX_FILES:
            raise WorkspaceError(f'snapshot refused: {len(files)} files, {total / 1048576:.1f} MB; the limit is '
                                 f'{MAX_FILES} files and {MAX_BYTES // 1048576} MB. Largest: {_largest(files)}. Name narrower paths')
        folder = safe_path(root, FOLDER)
        folder.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(folder).free
        if free < 2 * total + 1024 ** 3:
            raise WorkspaceError(f'snapshot refused: {free / 1024 ** 3:.1f} GB free on the drive of {FOLDER}; it needs '
                                 f'twice the {total / 1048576:.1f} MB copied plus 1 GB. Nothing was written')
        ignore = folder / '.gitignore'
        if not ignore.exists():
            ignore.write_bytes(b'*\n!.gitignore\n')
        for stale in folder.glob('*.partial'):
            stale.unlink()
        stamp = re.sub(r'[^0-9]', '', now())[:14]
        name = f'{stamp}-{label}{".pinned" if pin else ""}.zip'
        partial = folder / (name + '.partial')
        manifest = {'label': label, 'created_at': now(), 'writer': label_of(state), 'files': {}}
        with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for rel in sorted(files):
                raw = (root / rel).read_bytes()
                manifest['files'][rel] = [len(raw), sha(raw)]
                bundle.writestr(rel, raw)
            bundle.writestr('SNAPSHOT.json', json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')
        os.replace(partial, folder / name)
        rel = f'{FOLDER}/{name}'
        earlier = card(root).get('baseline', '').strip('`')
        write(root, HANDOFF, card_text(read(root, HANDOFF), {'baseline': f'`{rel}`'}))
        pruned = prune(root, folder, rel, earlier)
        state['revision'] += 1
        state['last_write_at'] = now()
        save_state(root, state)
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'snapshot', 'Detail': f'{rel}: {len(files)} files' +
                                              (f'; pruned {", ".join(pruned)}' if pruned else '')})
    return {'snapshot': rel, 'files': len(files), 'bytes': total, 'pruned': pruned,
            'extract': f'python -m zipfile -e {rel} {FOLDER}/extract-{stamp}/'}


def prune(root: Path, folder: Path, newest: str, earlier: str = '') -> list:
    """Delete the oldest unpinned snapshots while more than 100 MB and more than five remain. The pinned ones and
    the one the card names as baseline are never deleted."""
    baseline = card(root).get('baseline', '').strip('`')
    candidates = sorted(p for p in folder.glob('*.zip') if not p.name.endswith('.pinned.zip')
                        and f'{FOLDER}/{p.name}' not in (baseline, newest, earlier))
    pruned = []
    while len(candidates) > KEEP_COUNT and sum(p.stat().st_size for p in candidates) > KEEP_BYTES:
        oldest = candidates.pop(0)
        oldest.unlink()
        pruned.append(oldest.name)
    return pruned
