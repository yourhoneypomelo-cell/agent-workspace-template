"""Bring a project to this template version: the rebaseline that takes template files into the checkpoint."""
from __future__ import annotations

from pathlib import Path

from . import logs
from .core import WorkspaceError, checkpoint_of, fingerprint, lock, now, save_state, state_of
from .schema import HOOK_FILES, MANIFEST, RUNTIME_FILES, SEARCH_IGNORE

# Files the template owns in a project. Only these and the hook settings may be taken into a checkpoint by a
# rebaseline, so it can never hide a change to the project's own files.
TEMPLATE_OWNED = frozenset({*RUNTIME_FILES, MANIFEST, '.agents/.gitattributes', '.agents/.gitignore',
                            'docs/.gitattributes', 'docs/chats/.gitignore', *SEARCH_IGNORE, *HOOK_FILES.values()})


def rebaseline(root: Path, paths, note: str, upgraded: dict | None = None) -> dict:
    """Take the current content of template files and hook settings into the checkpoint of a released workspace,
    keeping everything else it recorded, so a tool or hook change is not reported as unsaved work while product
    changes still are. Returns the new checkpoint pointer."""
    from .ops import claims_working, short, write_checkpoint
    paths = sorted(set(paths))
    foreign = [p for p in paths if p not in TEMPLATE_OWNED]
    if foreign:
        raise WorkspaceError(f'a rebaseline takes only template files and hook settings, not {foreign[0]}. Project '
                             'files go into the checkpoint with "ws checkpoint"')
    with lock(root):
        state = state_of(root)
        if state.get('writer') or claims_working(state):
            raise WorkspaceError('the workspace is not released, so the session that owns it saves the change with '
                                 '"ws checkpoint"')
        cp = checkpoint_of(root, state)
        if not cp:
            raise WorkspaceError('the workspace has no checkpoint yet; run "ws checkpoint"')
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'rebaseline', 'Detail': short(note, 300)})
        current, files = fingerprint(root), dict(cp['files'])
        for rel in [*paths, logs.path_of('MAINTENANCE_LOG')]:
            if rel in current:
                files[rel] = current[rel]
            else:
                files.pop(rel, None)
        manifest = {**cp, 'created_at': now(), 'files': files, 'rebaselined': {'note': short(note, 200), 'paths': paths}}
        if upgraded:
            manifest['upgraded'] = upgraded
        pointer = write_checkpoint(root, manifest)
        state['checkpoint'] = pointer
        state['revision'] += 1
        save_state(root, state)
    return pointer
