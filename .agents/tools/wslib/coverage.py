"""Record coverage checks. They catch gaps the format checks cannot see. Credential redaction is in redaction.py."""
from __future__ import annotations

import re
from pathlib import Path

from .core import WorkspaceError, checkpoint_of, difference, fingerprint, goal, local_date, rewatch, state_of
from .schema import NON_SOURCE
from .redaction import (  # noqa: F401  (re-exported)
    credential_kinds, find_secrets, project_file_in_agents, redact, redact_json_lines, redact_pasted,
    secret_warnings,
)

COUNTED = ('requirements', 'questions', 'preferences', 'decisions', 'tasks', 'features')
TRACKING_TABLES = ('requirements', 'tasks')
# Files a project may change without new requirement or task rows.
SUPPORT_SUFFIXES = ('.md', '.txt', '.gitignore', '.gitattributes')


def counts(live: dict) -> dict:
    return {key: len(live.get(key, [])) for key in COUNTED}


def product_changes(root: Path, cp, now: dict) -> list:
    """Product files changed since the last checkpoint, ignoring workspace records and plain docs."""
    if not cp:
        return []
    changes = difference(rewatch(root, cp['files']), now)
    names = changes['added'] + changes['modified']
    return [n for n in names if not n.startswith(NON_SOURCE) and not n.endswith(SUPPORT_SUFFIXES)]


def tracking_rows(live: dict) -> dict:
    """Requirement and task rows, reduced to what describes the work."""
    return {row['ID']: (row['Status'], row.get('Requirement') or row.get('Action', ''), row.get('Scope', ''))
            for key in TRACKING_TABLES for row in live.get(key, [])}


def tracking_changed(cp, live: dict) -> bool:
    """Whether a requirement or task row was added or changed since the last checkpoint."""
    if not cp:
        return True
    before = cp.get('tracking')
    if before is None:  # manifests from 3.1 and earlier hold no row snapshot
        return True
    return {k: list(v) for k, v in tracking_rows(live).items()} != before


def hand_edits(root: Path, live: dict, cp) -> list:
    """(task, field, old value) for task definitions that changed since the last checkpoint without a "ws set" row
    in CHANGE_LOG. The checkpoint keeps the field texts, so an acceptance edited by hand still leaves a trace (U43)."""
    old = (cp or {}).get('task_texts') or {}
    if not old:
        return []
    since = local_date((cp or {}).get('created_at', ''))
    from . import logs
    try:
        logged = {(r['ID'], r['Event']) for r in logs.live_rows(root, 'CHANGE_LOG') if r.get('Date', '') >= since}
    except (ValueError, OSError, WorkspaceError):
        logged = set()
    found = []
    for row in live.get('tasks', []):
        before = old.get(row['ID'])
        if not before:
            continue
        for field, value in before.items():
            events = {(row['ID'], f'{field.lower()} edited'), (row['ID'], f'{field.lower()} edited outside ws')}
            if row.get(field, '') != value and not events & logged:
                found.append((row['ID'], field, value))
    return found


def task_texts(rows: list) -> dict:
    from .evidence import DEFINITION_FIELDS
    return {r['ID']: {f: r.get(f, '') for f in DEFINITION_FIELDS} for r in rows}


def findings(root: Path, live: dict) -> list:
    """(level, message) pairs. 'block' prevents READY; 'warn' is advisory."""
    result = []
    state = state_of(root)
    if state.get('mode') != 'active':
        return result
    cp = checkpoint_of(root, state)
    now = fingerprint(root)
    number = counts(live)
    edits = hand_edits(root, live, cp)
    if edits:
        result.append(('warn', 'Task definitions changed outside "ws set": ' + ', '.join(f'{t} {f.lower()}' for t, f, _ in edits[:6]) +
                               '. The next checkpoint logs the old values; if the change was not meant, restore it now'))
    active = sum(1 for r in live.get('requirements', []) if r['Status'] == 'active')
    # Rows moved to CLOSED_ITEMS by compact are retired too, so they never satisfy the check on their own.
    retired_only = active == 0 and (number['requirements'] > 0 or _closed_requirements(root))
    if goal(root) and (number['requirements'] == 0 and not _closed_requirements(root) or retired_only):
        waiting = any(r['Status'] == 'open' for r in live.get('questions', []))
        if waiting:
            # The session asked the user what to build; READY is allowed while that question is open.
            result.append(('warn', 'REQUIREMENTS.md has a goal but no requirement rows yet. Record them as soon as the '
                                   'open questions are answered'))
        else:
            result.append(('block', 'REQUIREMENTS.md has a goal but no requirement rows. Record the confirmed requirements '
                                    'from the conversation with "ws add requirement"; put unconfirmed details in the Idea '
                                    'pool. If you are waiting for the user, record that with "ws add question"'))
    changed = sorted(set(product_changes(root, cp, now)) | set((cp or {}).get('untracked') or []))
    changed = [name for name in changed if name in now]
    from .schema import STATIC_FILES
    changed = [name for name in changed if name not in STATIC_FILES]
    for rid, cited in orphaned(live, set()):
        result.append(('warn', f'{rid} is open but cites only retired requirements ({", ".join(cited)}). '
                               f'Point it at the replacing requirement with "ws set {rid} --set requirements=...", '
                               'or drop it with a reason'))
    try:
        from .claims import holders
        claimed = {t for _, scope in holders(state_of(root)) for t in scope['tasks']}
    except (WorkspaceError, ValueError, OSError):
        claimed = set()
    try:
        from .validate import regressions
        stale = {rid for rid, _ in regressions(root, cp, live.get('tasks', []), fresh_too=True)} if changed else set()
    except (WorkspaceError, ValueError, OSError):
        stale = set()
    changed = outside_tasks(changed, live, claimed, now, stale)
    if untracked(changed, cp, live):
        result.append(('warn', f'{len(changed)} product files changed since the work was last registered '
                               f'({", ".join(changed[:4])}), but no task is doing and no requirement or task row was '
                               'added or changed. Register the work with "ws add task" or update an existing row'))
    return result


USER_SOURCE = re.compile(r'^\s*(?:user|用户)', re.I)


def inferred(root: Path, live: dict) -> list:
    """Active requirements whose log rows never name the user as the source. Rows older than the log are
    not listed, because nothing says where they came from."""
    from . import logs
    try:
        rows = logs.all_rows(root, 'REQUIREMENT_LOG')
    except (ValueError, OSError, RuntimeError):
        return []
    logged, stated = set(), set()
    for row in rows:
        logged.add(row.get('ID'))
        if USER_SOURCE.match(row.get('Source') or ''):
            stated.add(row.get('ID'))
    return [r['ID'] for r in live.get('requirements', [])
            if r['Status'] == 'active' and r['ID'] in logged and r['ID'] not in stated]


def inferred_line(root: Path, live: dict) -> list:
    ids = inferred(root, live)
    if not ids:
        return []
    return [f'Not stated by the user: {", ".join(ids[:8])}{" and more" if len(ids) > 8 else ""}. '
            'Confirm with the user, then: ws set <ID> --set status=active --source "user <date>"']


def turn_attention(root: Path, live: dict) -> list:
    """The one finding the per-turn reminder repeats: a blocking one, else untracked product changes."""
    found = findings(root, live)
    blocking = [m for level, m in found if level == 'block']
    if blocking:
        return ['Attention: ' + blocking[0]]
    return [UNTRACKED_TURN] if any(UNTRACKED_START in m for _, m in found) else []


UNTRACKED_START = 'product files changed since the work was last registered'
UNTRACKED_TURN = 'Attention: product files changed but no task is doing. Add or start a task before more edits.'


def untracked(changed: list, cp, live: dict) -> bool:
    """Product code changed while no task is in progress and no row changed. A task marked doing covers the
    edits, so the warning stays quiet through normal work and checkpoints."""
    return bool(changed) and not any(r['Status'] == 'doing' for r in live.get('tasks', [])) \
        and not tracking_changed(cp, live)


def outside_tasks(changed: list, live: dict, claimed=(), files=None, stale=()) -> list:
    """Changed files that no finished or claimed task covers. A file inside the Scope of a task that was verified, or
    that a parallel session claimed, or among the files its acceptance runs, is registered work: parallel sessions do
    not mark their tasks doing. A file of a task still todo is not covered: editing it before starting the task is
    what this warns about, and neither is one of a task in stale, whose evidence the change made stale. files are the
    project's files, against which Scope paths are looked up."""
    from . import evidence
    rows = [r for r in live.get('tasks', []) if r['ID'] not in stale and
            ((r['Status'] == 'done' and r.get('Evidence', 'none').lower() != 'none') or r['ID'] in claimed)]
    names = set(changed) | set(files or ())
    scopes = [evidence.scope_paths(r, names, acceptance=True) for r in rows]
    return [f for f in changed if not any(s and evidence.in_scope(f, s) for s in scopes)]


OPEN_TASK = ('todo', 'doing', 'blocked', 'unverified')
LIVE_FEATURE = ('planned', 'building', 'unverified', 'shipped')


def _cited(cell: str) -> list:
    return re.findall(r'\bR[1-9]\d*\b', cell or '')


def dependents(live: dict, rid: str) -> list:
    """Open tasks and live features whose Requirements column cites rid."""
    rows = [r for r in live.get('tasks', []) if r['Status'] in OPEN_TASK]
    rows += [r for r in live.get('features', []) if r['Status'] in LIVE_FEATURE]
    return [r['ID'] for r in rows if rid in _cited(r.get('Requirements', ''))]


def orphaned(live: dict, closed_ids: set) -> list:
    """(row ID, cited IDs) for open work that cites only retired or closed requirements."""
    active = {r['ID'] for r in live.get('requirements', []) if r['Status'] == 'active'}
    result = []
    rows = [r for r in live.get('tasks', []) if r['Status'] in OPEN_TASK]
    rows += [r for r in live.get('features', []) if r['Status'] in LIVE_FEATURE]
    for row in rows:
        cited = _cited(row.get('Requirements', ''))
        if cited and not any(c in active for c in cited):
            result.append((row['ID'], cited))
    return result


def _prefix_ids(summary: str) -> list:
    """The requirement IDs of a closed task: the "R1, R2: " prefix of its summary. "Implement R1 (leave R2 for later)"
    does not verify R2."""
    found = re.match(r'^((?:R[1-9]\d*)(?:,\s*R[1-9]\d*)*):\s', summary or '')
    return re.findall(r'R[1-9]\d*', found[1]) if found else []


def v2_cited(closed: list | None) -> set:
    """Requirements that closed tasks verified under continuity.v2, which were never run again in v3."""
    return {rid for row in closed or [] if row['ID'].startswith('T') and row.get('Evidence', '').startswith('v2:')
            for rid in _prefix_ids(row.get('Summary', ''))}


def requirement_coverage(live: dict, closed: list | None = None, stale=()) -> tuple:
    """(verified, total, unverified IDs): an active requirement counts when a done task with evidence cites it and
    no open task cites it, because an open task means part of the requirement is still unbuilt. A task in stale,
    whose files changed after it was verified, proves nothing until it runs again.

    Done tasks moved to CLOSED_ITEMS.md by compact still count; their Summary keeps the requirement IDs."""
    active = [r['ID'] for r in live.get('requirements', []) if r['Status'] == 'active']
    proven, pending = set(), set()
    for task in live.get('tasks', []):
        if task['Status'] == 'done' and task.get('Evidence', 'none').lower() != 'none' and task['ID'] not in stale:
            proven |= set(_cited(task.get('Requirements', '')))
        elif task['Status'] in OPEN_TASK:
            pending |= set(_cited(task.get('Requirements', '')))
    for row in closed or []:
        evidence = row.get('Evidence', 'none')
        if row['ID'].startswith('T') and row.get('Status') == 'done' and evidence.lower() != 'none' and not evidence.startswith('v2:'):
            proven |= set(_prefix_ids(row.get('Summary', '')))
    missing = [rid for rid in active if rid not in proven or rid in pending]
    return len(active) - len(missing), len(active), missing


def ready_task(live: dict):
    """The first todo task whose dependencies are done, in ID order. A dropped dependency is not done: the task
    needs its Depends changed first, as validation requires for a task marked done."""
    status = {r['ID']: r['Status'] for r in live.get('tasks', [])}
    todo = sorted((r for r in live.get('tasks', []) if r['Status'] == 'todo'), key=lambda r: int(r['ID'][1:]))
    for row in todo:
        needs = re.findall(r'\bT[1-9]\d*\b', row.get('Depends', ''))
        if all(status.get(n, 'done') == 'done' for n in needs):
            return row
    return None


def dropped_needs(live: dict) -> list:
    """(task, its dependencies left once the dropped ones go) for open tasks that wait on a dropped task."""
    status = {r['ID']: r['Status'] for r in live.get('tasks', [])}
    found = []
    for row in live.get('tasks', []):
        needs = re.findall(r'\bT[1-9]\d*\b', row.get('Depends', ''))
        if row['Status'] in OPEN_TASK and any(status.get(n) == 'dropped' for n in needs):
            found.append((row['ID'], [n for n in needs if status.get(n) != 'dropped']))
    return found


def untracked_carry(root: Path, live: dict, cp, now: dict) -> list:
    """Files to keep warning about in the next checkpoint until a requirement or task row changes."""
    if tracking_changed(cp, live):
        return []
    return sorted(set(product_changes(root, cp, now)) | set((cp or {}).get('untracked') or []))


def _closed_requirements(root: Path) -> bool:
    from . import tables
    return any(r['ID'].startswith('R') for r in tables.closed_rows(root))


def session_summary(root: Path, live: dict, cp) -> str:
    """Rows added since the previous checkpoint, for the session log and checkpoint output."""
    before = (cp or {}).get('ledger') or {}
    now = {}
    for key in COUNTED:
        for row in live.get(key, []):
            now[row['ID']] = row['Status']
    added = [rid for rid in now if rid not in before]
    changed = [rid for rid in now if rid in before and before[rid] != now[rid]]
    parts = []
    for prefix, label in (('R', 'requirements'), ('Q', 'questions'), ('P', 'preferences'), ('D', 'decisions'),
                          ('T', 'tasks'), ('F', 'features')):
        n = sum(1 for rid in added if rid.startswith(prefix))
        if n:
            parts.append(f'{n} {label}')
    text = ('added ' + ', '.join(parts)) if parts else 'no new rows'
    if changed:
        text += f'; {len(changed)} status changes'
    return text
