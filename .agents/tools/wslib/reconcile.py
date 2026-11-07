"""Reconcile user messages in docs/chats/ against the rows recorded in docs/state/.

The tool cannot judge meaning. It lists every user message that no row has accounted for yet, and
the agent answers each one: the IDs that record it, or the reason it needs no record.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import logs, tables
from .coverage import redact
from .core import READ_ONLY, WorkspaceError, atomic_write, read, safe_path, state_of
from .locks import lock
from .messages import entries, routine
from .schema import CACHE_DIR, CHAT_DIR, CHAT_INDEX, PREFIX_TABLE

LOG = 'RECONCILE_LOG'
CACHE = CACHE_DIR + '/messages.json'
CACHE_RULES = 2  # raised when message IDs or the routine rule change, so cached lists are read again
INDEX_HEADERS = ('Date', 'Host', 'Session', 'Messages', 'Transcript', 'Raw copy')
REASONS = ('question', 'chat', 'duplicate', 'superseded', 'out-of-scope', 'secret')


def texts(path: Path) -> dict:
    """Message id to text for the user messages in one transcript file."""
    content = path.read_text(encoding='utf-8', errors='replace')
    return {mid: body for _, _, _, mid, body in entries(content) if mid}


def _valid(entry, key) -> bool:
    return (isinstance(entry, dict) and entry.get('key') == key and isinstance(entry.get('messages'), list)
            and all(isinstance(m, list) and len(m) == 2 and isinstance(m[0], str) and isinstance(m[1], bool)
                    for m in entry['messages']))


def user_messages(root: Path) -> list:
    """(message id, session file, routine) for every user message in the copied transcripts, in index order.

    Parsed messages are cached per transcript by size and modification time, because the per-turn
    hook calls this on every user message.
    """
    rows = tables.parse(read(root, CHAT_INDEX), INDEX_HEADERS, CHAT_INDEX)
    try:
        cache = json.loads((root / CACHE).read_text(encoding='utf-8'))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    fresh, found, seen = {}, [], set()
    for row in rows:
        rel = row.get('Transcript', 'none')
        if not rel.startswith(CHAT_DIR + '/'):
            continue
        try:
            path = safe_path(root, rel)
        except WorkspaceError:
            continue
        if not path.is_file():
            continue
        info = path.stat()
        key = [info.st_size, info.st_mtime_ns, CACHE_RULES]
        entry = cache.get(rel)
        if not _valid(entry, key):
            entry = {'key': key, 'messages': [[mid, routine(mid, body)] for mid, body in texts(path).items()]}
        fresh[rel] = entry
        for mid, is_routine in entry['messages']:
            if mid not in seen:
                seen.add(mid)
                found.append((mid, rel, is_routine))
    if fresh != cache and not os.environ.get('WS_NO_CACHE') and not READ_ONLY.get():
        try:
            (root / CACHE_DIR).mkdir(parents=True, exist_ok=True)
            atomic_write(root / CACHE, json.dumps(fresh))
        except OSError:
            pass
    return found


def accounted(root: Path) -> dict:
    return {row['Message']: row for row in logs.all_rows(root, LOG)}


def pending(root: Path) -> list:
    """(message id, session file) for each user message that no log row accounts for."""
    done = accounted(root)
    return [(mid, rel) for mid, rel, is_routine in user_messages(root) if mid not in done and not is_routine]


def at_seal(root: Path, cp) -> tuple:
    """(open messages that block READY, open messages saved after the last seal). A seal lists the messages open at
    that moment; one saved later, by a Stop hook after the checkpoint or with the next user message, is left to the
    next session. A seal of 3.8 or older lists none, so then every open message blocks."""
    found = pending(root)
    if not cp or not isinstance(cp.get('messages_open'), list):
        return found, []
    sealed = set(cp['messages_open'])
    return [m for m in found if m[0] in sealed], [m for m in found if m[0] not in sealed]


def unlisted(root: Path) -> list:
    """Transcripts in docs/chats/ that INDEX.md does not list, so nothing reconciles their messages."""
    folder = root / CHAT_DIR
    if not folder.is_dir():
        return []
    listed = {row.get('Transcript') for row in tables.parse(read(root, CHAT_INDEX), INDEX_HEADERS, CHAT_INDEX)}
    found = []
    for path in sorted(folder.glob('*/*.md')):
        rel = path.relative_to(root).as_posix()
        if rel in listed:
            continue
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                if stream.readline().startswith('# Transcript '):
                    found.append(rel)
        except OSError:
            continue
    return found


def unlisted_text(found: list) -> str:
    return (f'{len(found)} transcripts in docs/chats/ are not listed in docs/chats/INDEX.md, so nothing reconciles '
            f'their messages ({", ".join(found[:3])}{" and more" if len(found) > 3 else ""}). Add a row for each to '
            'INDEX.md, or move the file out of docs/chats/')


def _known_ids(root: Path) -> set:
    ids = {r['ID'] for t in PREFIX_TABLE.values() for r in tables.rows(root, t)}
    return ids | {r['ID'] for r in tables.closed_rows(root)}


def mark(root: Path, message: str, ids: str | None, reason: str | None, confirm: int | None = None) -> dict:
    """Record how one message was handled: by row IDs, or by a reason it needs none. "all" gives every open message
    one reason, so it must name how many it marks."""
    if bool(ids) == bool(reason):
        raise WorkspaceError('give either --ids R1,T2 or --reason, not both')
    with lock(root):
        state = state_of(root)
        from .core import require_session
        from .claims import CALLER
        require_session(root, state)
        if not state.get('writer') and not CALLER.get():
            raise WorkspaceError('no session owns the workspace. Run "ws start" first')
        open_ids = {mid for mid, _ in pending(root)}
        targets = sorted(open_ids) if message == 'all' else [message]
        if message == 'all' and not reason:
            raise WorkspaceError('"all" needs --reason; map messages with requirements to IDs one by one')
        if message == 'all' and targets and confirm != len(targets):
            raise WorkspaceError(f'"all" would give {len(targets)} open messages one reason. Read them with "ws reconcile", '
                                 'map each that asks for something to its rows, then mark the rest with --confirm '
                                 f'{len(targets)}' + (f' (not {confirm})' if confirm is not None else ''))
        for mid in targets:
            if mid not in open_ids:
                known = {m for m, _, _ in user_messages(root)}
                raise WorkspaceError(f'{mid} is not an open message' + ('' if mid in known else '; run "ws reconcile" for the list'))
        if ids:
            given = list(dict.fromkeys(i.upper() for i in re.split(r'[\s,;]+', ids.strip()) if i))
            unknown = [i for i in given if i not in _known_ids(root)]
            if unknown:
                raise WorkspaceError(f'unknown IDs: {", ".join(unknown)}. Record the row with "ws add" first')
            if not given:
                raise WorkspaceError('--ids names no row; give IDs such as R4,P2')
            outcome = ', '.join(given)
        else:
            head = reason.split(':', 1)[0].strip().lower()
            if head not in REASONS:
                raise WorkspaceError(f'reason must start with one of: {", ".join(REASONS)}, for example "chat: greeting"')
            outcome = 'no record: ' + redact(' '.join(reason.split()))
            if message == 'all':
                outcome += f' (reconcile all, {len(targets)} messages)'
        for mid in targets:
            logs.append(root, LOG, {'Message': mid, 'Outcome': outcome})
    return {'marked': targets, 'outcome': outcome}


def review(root: Path, last=20) -> list:
    """The last user messages beside what accounts for each: the rows that record it, with their text, or the
    reason none is needed. A sample for checking the bookkeeping by eye; messages are shown redacted."""
    from .ops import short
    done = accounted(root)
    rows = {r['ID']: r for t in PREFIX_TABLE.values() for r in tables.rows(root, t)}
    rows.update({r['ID']: r for r in tables.closed_rows(root)})
    picked = [(mid, rel) for mid, rel, is_routine in user_messages(root) if not is_routine][-max(1, last):]
    bodies, lines = {}, []
    for mid, rel in picked:
        if rel not in bodies:
            bodies[rel] = texts(root / rel)
        lines.append(f'{mid}  {rel}\n    user: {short(redact(bodies[rel].get(mid, "")), 300)}')
        entry = done.get(mid)
        if not entry:
            lines.append('    -> NOT RECONCILED')
            continue
        outcome = entry['Outcome']
        if outcome.startswith('no record:'):
            lines.append(f'    -> {outcome}')
            continue
        for rid in re.findall(r'\b[A-Z][1-9]\d*\b', outcome):
            row = rows.get(rid) or {}
            field = PREFIX_TABLE[rid[0]].summary if rid[0] in PREFIX_TABLE else 'Summary'
            lines.append(f'    -> {rid} {row.get("Status", "unknown")}: {short(row.get(field) or row.get("Summary", ""), 160)}')
    return lines


def summary_line(root: Path) -> str | None:
    try:
        count, missing = len(pending(root)), unlisted(root)
    except (WorkspaceError, OSError, ValueError) as error:
        return f'docs/chats/ cannot be reconciled: {str(error).splitlines()[0][:160]}. Repair it, then run "ws reconcile"'
    parts = [f'{count} user messages in docs/chats/ are not reconciled with the state files. '
             'Run "ws reconcile" and confirm each one is recorded'] if count else []
    return '. '.join(parts + ([unlisted_text(missing)] if missing else [])) or None
