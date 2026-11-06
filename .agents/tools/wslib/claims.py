"""Parallel sessions (U35). Each session claims tasks; the paths and resources they name decide what it may touch.

A session that claims no task holds the whole tree, so the single-session case works as before. Two claims that
share a task, a path or a resource are refused unless the user forces one, and the force is logged."""
from __future__ import annotations

import contextvars
import datetime as dt
import re
from pathlib import Path

from . import evidence, tables
from .core import WorkspaceError, host_alive, host_process, same_host, session_identity, watched_files
from .schema import TABLES

RESOURCE_RE = re.compile(r'\bresource:([A-Za-z0-9_.\-/]+)')
WHOLE = {'tasks': [], 'paths': None, 'resources': []}
RECENT_SECONDS = 20 * 60
# A host process such as an IDE or desktop app outlives its conversations; past this age a claim is stale.
STALE_SECONDS = 12 * 3600
# The label of the parallel claim that makes this command, set by require_owner; None for the main session.
CALLER = contextvars.ContextVar('ws_caller', default=None)


def task_rows(root: Path) -> dict:
    return {r['ID']: r for r in tables.rows(root, TABLES['tasks'])}


def scope_of(root: Path, ids: list, rows: dict | None = None) -> dict:
    """Tasks, paths and resources a claim holds. A task that names no existing path holds the whole tree."""
    rows = rows or task_rows(root)
    files = set(watched_files(root))
    paths, resources, whole = [], [], not ids
    for rid in ids:
        row = rows.get(rid)
        if row is None:
            raise WorkspaceError(f'{rid} is not a live task in docs/state/TASKS.md')
        if row['Status'] in ('done', 'dropped'):
            raise WorkspaceError(f'{rid} is {row["Status"]}; claim an open task')
        text = row.get('Scope', '') + ' ' + row.get('Acceptance', '')
        resources += RESOURCE_RE.findall(text)
        found = evidence.scope_paths(row, files)
        if found is None:
            whole = True
        else:
            paths += found
    return {'tasks': list(ids), 'paths': None if whole else sorted(set(paths)), 'resources': sorted(set(resources))}


def _overlap(a, b) -> list:
    if a is None or b is None:
        return ['the whole tree']
    return sorted({x for x in a for y in b if x == y or x.startswith(y + '/') or y.startswith(x + '/')})


def conflicts(mine: dict, other: dict) -> list:
    """Why two scopes cannot be worked on at once; empty when they can."""
    reasons = []
    shared_tasks = sorted(set(mine['tasks']) & set(other['tasks']))
    if shared_tasks:
        reasons.append('task ' + ', '.join(shared_tasks))
    paths = _overlap(mine['paths'], other['paths'])
    if paths:
        reasons.append('paths ' + ', '.join(paths[:4]))
    resources = sorted(set(mine['resources']) & set(other['resources']))
    if resources:
        reasons.append('resource ' + ', '.join(resources))
    return reasons


def _age(stamp) -> float | None:
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError, ValueError):
        return None


_HERE = []


def _here():
    if not _HERE:
        _HERE.append(host_process())
    return _HERE[0]


def alive(entry: dict) -> bool:
    """Whether a session still counts as working.

    Its window has exited: no. Its window is another running process: yes, for up to 12 hours since its last write.
    Its window is the one running this command, or cannot be checked: only while it wrote within 20 minutes, because
    one application window hosts many conversations and its process says nothing about any one of them."""
    if entry.get('released_at'):
        return False
    age = _age(entry.get('last_write_at') or entry.get('claimed_at'))
    window = host_alive(entry.get('host'))
    if window is False:
        return False
    if window is True and not same_host(entry.get('host'), _here()):
        return age is None or age < STALE_SECONDS
    return age is not None and age < RECENT_SECONDS


def primary_entry(state: dict) -> dict:
    return {'host': state.get('host'), 'last_write_at': state.get('last_write_at'), 'claimed_at': state.get('claimed_at'),
            'scope': state.get('scope') or WHOLE}


def holders(state: dict, exclude: str | None = None) -> list:
    """(label, scope) of every working session except the one named."""
    found = []
    if state.get('writer') and state['writer'] != exclude and alive(primary_entry(state)):
        found.append((state['writer'], state.get('scope') or WHOLE))
    for label, entry in (state.get('claims') or {}).items():
        if label != exclude and alive(entry):
            found.append((label, entry['scope']))
    return found


def clashes(state: dict, scope: dict, exclude: str | None = None) -> list:
    """(label, reasons) of the working sessions this scope collides with."""
    return [(label, why) for label, other in holders(state, exclude) for why in [conflicts(scope, other)] if why]


def clash_text(found: list) -> str:
    return '; '.join(f'{label} holds {", ".join(why)}' for label, why in found)


def caller(state: dict, writer: str | None = None):
    """'primary', the label of a parallel claim, or None when this process holds nothing it can prove."""
    # A released claim holds nothing; the session that made it starts afresh like any other.
    claims = {k: v for k, v in (state.get('claims') or {}).items() if not v.get('released_at')}
    if writer:
        if writer == state.get('writer'):
            return 'primary'
        return writer if writer in claims else None
    mine = session_identity()
    if mine:
        if (state.get('session') or {}).get('id') == mine['id']:
            return 'primary'
        for label, entry in claims.items():
            if (entry.get('session') or {}).get('id') == mine['id']:
                return label
        return None
    host = host_process()
    matches = [label for label, entry in claims.items() if not entry.get('session') and same_host(entry.get('host'), host)]
    if len(matches) == 1 and not (state.get('writer') and same_host(state.get('host'), host)):
        return matches[0]
    return None


def label_of(state: dict) -> str | None:
    """The label this command writes under: the claim set by require_owner, or the main writer."""
    return CALLER.get() or state.get('writer')


def guard_tasks(state: dict, ids, what='change') -> None:
    """Refuse touching tasks another working session claimed."""
    mine = label_of(state)
    for label, scope in holders(state, exclude=mine):
        taken = sorted(set(scope['tasks']) & set(ids))
        if taken:
            raise WorkspaceError(f'{", ".join(taken)} belongs to {label}, which is still working, so this session must '
                                 f'not {what} it. Ask the user; that session records its own tasks')


def require_alone(state: dict, what: str) -> None:
    """Workspace-wide changes wait until no other session is working."""
    others = holders(state, exclude=label_of(state))
    if others:
        raise WorkspaceError(f'{what} changes the whole workspace, and {", ".join(l for l, _ in others)} is still working. '
                             'Wait until it checkpoints, or ask the user')


def only_mine(state: dict, errors: list) -> list:
    """Validation errors about tasks other working sessions hold belong to them, not to this checkpoint."""
    theirs = {t for _, scope in holders(state, exclude=label_of(state)) for t in scope['tasks']}
    if not theirs:
        return errors
    kept = []
    for error in errors:
        named = set(re.findall(r'\bT[1-9]\d*\b', error))
        if named and named <= theirs:
            continue
        kept.append(error)
    return kept


def kept_hashes(state: dict, previous: dict | None, files_now: dict) -> dict:
    """File hashes for a seal while others work: their unsaved files keep the old hash, so a later session still
    sees them as unfinished work."""
    others = holders(state, exclude=label_of(state))
    if not others or not previous:
        return files_now
    old = previous.get('files') or {}
    scopes = [scope['paths'] for _, scope in others]
    if any(paths is None for paths in scopes):
        return files_now  # someone holds the whole tree; nothing here is theirs alone

    def theirs(rel):
        return any(rel == p or rel.startswith(p + '/') for paths in scopes for p in paths)
    result = {rel: (old[rel] if theirs(rel) and rel in old else value) for rel, value in files_now.items()
              if not (theirs(rel) and rel not in old)}
    for rel, value in old.items():
        if theirs(rel) and rel not in files_now:
            result[rel] = value
    return result


def render(state: dict) -> str:
    """The "Parallel sessions" block of HANDOFF.md, or '' when only one session works."""
    claims = state.get('claims') or {}
    if not claims:
        return ''
    rows = []
    for label, entry in sorted(claims.items()):
        scope = entry['scope']
        if entry.get('released_at'):
            label = label + ' (released)'
            scope = {**scope, 'tasks': entry.get('released_tasks') or []}
        cells = [label, ', '.join(scope['tasks']) or 'none',
                 'whole tree' if scope['paths'] is None else (', '.join(scope['paths']) or 'none'),
                 ', '.join(scope['resources']) or 'none', entry.get('stop_point') or 'none',
                 entry.get('next_step') or 'none', entry.get('last_write_at') or entry.get('claimed_at') or 'unknown']
        rows.append('| ' + ' | '.join(c.replace('|', '/').replace('\n', ' ') for c in cells) + ' |')
    return ('<!-- CLAIMS:START -->\n## Parallel sessions\n\nWritten by ws. Each row is a session working on the tasks it '
            'claimed. Its stop point and next step are here; the card above belongs to the main session.\n\n'
            '| Writer | Tasks | Paths | Resources | Stop point | Next step | Last write |\n'
            '| --- | --- | --- | --- | --- | --- | --- |\n' + '\n'.join(rows) + '\n<!-- CLAIMS:END -->\n')
