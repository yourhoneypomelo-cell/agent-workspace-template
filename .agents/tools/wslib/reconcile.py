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
from .core import WorkspaceError, atomic_write, lock, read, safe_path, sha, state_of
from .schema import CACHE_DIR, CHAT_DIR, CHAT_INDEX, HEADING_NOTE, PREFIX_TABLE

LOG = 'RECONCILE_LOG'
CACHE = CACHE_DIR + '/messages.json'
MESSAGE_RE = re.compile(r'^## (\d+)\. (user|assistant)' + HEADING_NOTE + r'\n\n(.*?)(?=^## \d+\. (?:user|assistant)'
                        + HEADING_NOTE + r'\n|\Z)', re.M | re.S)
# Messages that carry no requirement: continuation prompts, acknowledgements, bare questions about status.
ROUTINE = re.compile(r'^(?:(?:继续|继续吧|接着|好的?|好|行|可以|ok(?:ay)?|yes|no|是的?|对|嗯|谢谢|thanks?|continue|go on|next|'
                     r'完美丝滑接续任务|完美接续中断任务|继续中断任务|继续未完成任务)[。.!！,，\s]*)+$', re.I)
ROUTINE_MAX = 40
REASONS = ('question', 'chat', 'duplicate', 'superseded', 'out-of-scope', 'secret')


def message_id(text: str) -> str:
    return 'm' + sha(' '.join(text.split()).encode('utf-8'))[:10]


def routine(text: str) -> bool:
    return len(text) <= ROUTINE_MAX and bool(ROUTINE.match(text))


def texts(path: Path) -> dict:
    """Message id to text for the user messages in one transcript file."""
    content = path.read_text(encoding='utf-8', errors='replace')
    bodies = (m.group(3).strip() for m in MESSAGE_RE.finditer(content) if m.group(2) == 'user')
    return {message_id(body): body for body in bodies if body}


def _valid(entry, key) -> bool:
    return (isinstance(entry, dict) and entry.get('key') == key and isinstance(entry.get('messages'), list)
            and all(isinstance(m, list) and len(m) == 2 and isinstance(m[0], str) and isinstance(m[1], bool)
                    for m in entry['messages']))


def user_messages(root: Path) -> list:
    """(message id, session file, routine) for every user message in the copied transcripts, in index order.

    Parsed messages are cached per transcript by size and modification time, because the per-turn
    hook calls this on every user message.
    """
    rows = tables.parse(read(root, CHAT_INDEX), ('Date', 'Host', 'Session', 'Messages', 'Transcript', 'Raw copy'), CHAT_INDEX)
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
        key = [info.st_size, info.st_mtime_ns]
        entry = cache.get(rel)
        if not _valid(entry, key):
            entry = {'key': key, 'messages': [[mid, routine(body)] for mid, body in texts(path).items()]}
        fresh[rel] = entry
        for mid, is_routine in entry['messages']:
            if mid not in seen:
                seen.add(mid)
                found.append((mid, rel, is_routine))
    if fresh != cache and not os.environ.get('WS_NO_CACHE'):
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


def _known_ids(root: Path) -> set:
    ids = {r['ID'] for t in PREFIX_TABLE.values() for r in tables.rows(root, t)}
    return ids | {r['ID'] for r in tables.closed_rows(root)}


def mark(root: Path, message: str, ids: str | None, reason: str | None) -> dict:
    """Record how one message was handled: by row IDs, or by a reason it needs none."""
    if bool(ids) == bool(reason):
        raise WorkspaceError('give either --ids R1,T2 or --reason, not both')
    with lock(root):
        state = state_of(root)
        from .core import require_session
        require_session(root, state)
        if not state.get('writer'):
            raise WorkspaceError('no session owns the workspace. Run "ws start" first')
        open_ids = {mid for mid, _ in pending(root)}
        targets = sorted(open_ids) if message == 'all' else [message]
        if message == 'all' and not reason:
            raise WorkspaceError('"all" needs --reason; map messages with requirements to IDs one by one')
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
        for mid in targets:
            logs.append(root, LOG, {'Message': mid, 'Outcome': outcome})
    return {'marked': targets, 'outcome': outcome}


def summary_line(root: Path) -> str | None:
    try:
        count = len(pending(root))
    except (WorkspaceError, OSError, ValueError) as error:
        return f'docs/chats/ cannot be reconciled: {str(error).splitlines()[0][:160]}. Repair it, then run "ws reconcile"'
    if not count:
        return None
    return (f'{count} user messages in docs/chats/ are not reconciled with the state files. '
            'Run "ws reconcile" and confirm each one is recorded')
