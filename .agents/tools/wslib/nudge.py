"""Stop-hook nudge: once per user message, ask the agent to record it if the turn wrote nothing.

The prompt hook stores the workspace revision when a user message arrives. Any `ws add`, `set`, `note`,
or `checkpoint` raises the revision, and a
`ws note` or `ws reconcile` mark adds a log row. If a turn ends with the revision unchanged, the agent
neither recorded the message nor said why it needs no record, so the Stop hook asks once. The marker is
cleared before the hook answers, so a second stop always passes and no loop is possible.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import logs
from .core import atomic_write, config, state_of
from .schema import CACHE_DIR

MARKER = CACHE_DIR + '/pending-turn.json'

MESSAGE = ('The last user message was not recorded and no reason was given. If it stated a requirement, '
           'change, decision, preference or question, record it now with "python .agents/tools/ws.py add ..." or '
           '"ws set ...". If it needs no record, run "ws note \\"no record: <reason>\\"". Then finish.')


def _answers(root: Path) -> int:
    """Rows that count as answering a message: session notes and reconcile marks. Neither raises the revision."""
    total = 0
    for name in ('SESSION_LOG', 'RECONCILE_LOG'):
        try:
            total += len(logs.live_rows(root, name))
        except Exception:
            return -1
    return total


def enabled(root: Path) -> bool:
    try:
        return bool(config(root).get('stop_nudge'))
    except Exception:
        return False


def remember(root: Path, host: str, session: str, message_id: str):
    """Called by the prompt hook after it saves a user message."""
    if not enabled(root):
        return
    try:
        state = state_of(root)
        if state.get('mode') != 'active':
            return
        atomic_write(root / MARKER, json.dumps({'host': host, 'session': session, 'message': message_id,
                                                'revision': state['revision'], 'notes': _answers(root)}))
    except Exception:
        pass


def _number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 1  # an unreadable loop count is treated as a repeated stop


def check(root: Path, payload: dict, session: str | None = None) -> str | None:
    """Return the nudge text when the turn wrote nothing, else None. Never raises."""
    try:
        if not enabled(root):
            return None
        if payload.get('stop_hook_active') or payload.get('stopHookActive') or _number(payload.get('loop_count')) > 0:
            return None
        if payload.get('reason') not in (None, '', 'end_turn'):
            return None  # Grok also fires Stop at session end
        if str(payload.get('status') or 'completed').lower() not in ('completed', 'success', 'done', 'idle'):
            return None  # a cancelled or failed turn is not asked to record
        if payload.get('fullyIdle') is False:
            return None  # Antigravity: the agent is still working
        path = root / MARKER
        try:
            marker = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not isinstance(marker, dict) or (session and marker.get('session') not in (None, session)):
            return None
        path.unlink(missing_ok=True)
        state = state_of(root)
        if state.get('revision') != marker.get('revision') or _answers(root) != marker.get('notes'):
            return None
        return MESSAGE
    except Exception:
        return None


def answer(host: str, text: str) -> str:
    """The Stop hook output that makes each host continue once with text."""
    if host == 'cursor':
        return json.dumps({'followup_message': text})
    if host == 'antigravity':
        return json.dumps({'decision': 'continue', 'reason': text})
    if host == 'gemini':
        return json.dumps({'decision': 'deny', 'reason': text})
    return json.dumps({'decision': 'block', 'reason': text})
