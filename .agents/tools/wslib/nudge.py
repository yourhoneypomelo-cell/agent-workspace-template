"""Stop-hook nudge: once per user message, ask the agent to record it if the turn wrote nothing.

The prompt hook stores the workspace revision when a user message arrives. Any `ws add`, `set`, `note`,
or `checkpoint` raises the revision, and a
`ws note` or `ws reconcile` mark adds a log row. If a turn ends with the revision unchanged, the agent
neither recorded the message nor said why it needs no record, so the Stop hook asks once. The marker is
cleared before the hook answers, so a second stop always passes and no loop is possible.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import logs
from .core import atomic_write, config, state_of
from .schema import CACHE_DIR

MARKER = CACHE_DIR + '/pending-turn.json'
# The row IDs and statuses at the previous user message, so the next prompt hook can say what that turn recorded.
TURN_LEDGER = CACHE_DIR + '/turn-ledger.json'

# Mode markers (AGENTS.md, "On every user message"): the user starts a message with one of these words and a colon.
# The prompt hook keeps the mode for that turn, so ws can refuse what the mode rules out. It lapses with the next
# message, after MODE_MINUTES, and for a session other than the one the message came from.
MODE = CACHE_DIR + '/turn-mode.json'
MODES = {'discuss': ('讨论', 'discuss'), 'readonly': ('只读', 'read-only', 'readonly'), 'confirm': ('确认', 'confirm')}
MODE_MINUTES = 30
MODE_TEXT = {
    'discuss': 'The user marked this message as discussion: put its ideas in the Idea pool with "ws idea", add no '
               'requirement, and change no product file.',
    'readonly': 'The user marked this message read-only: change no file and run no ws write; reading is fine.',
    'confirm': 'The user marked this message as a confirmation: record what it confirms as rows now.',
}


def message_mode(prompt: str):
    head = (prompt or '').lstrip()
    for mode, words in MODES.items():
        if any(re.match(re.escape(word) + r'\s*[:：]', head, re.I) for word in words):
            return mode
    return None


def turn_mode(root: Path, prompt: str, session: str | None) -> str:
    """Keep the marker a user message starts with for its turn, and return the sentence the prompt hook adds."""
    mode = message_mode(prompt)
    if mode:
        atomic_write(root / MODE, json.dumps({'mode': mode, 'at': time.time(), 'session': session}))
    else:
        (root / MODE).unlink(missing_ok=True)
    return MODE_TEXT.get(mode, '')


def mode_refusal(root: Path, adding: str | None = None):
    """Why the mode of this turn rules out a write: every write in a read-only turn, and a requirement in a
    discussion turn. None when it does not."""
    from .core import env_session
    try:
        data = json.loads((root / MODE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or time.time() - float(data.get('at') or 0) > MODE_MINUTES * 60:
        return None
    if data.get('session') and env_session() and data['session'] != env_session():
        return None
    if data.get('mode') == 'readonly':
        return 'the user marked this message read-only, so this turn writes nothing. Answer from what you read'
    if data.get('mode') == 'discuss' and adding == 'requirements':
        return ('the user marked this message as discussion, so it adds no requirement. Put the idea in the Idea pool '
                'with "ws idea \\"...\\"", and add the requirement once the user confirms it')
    return None


def turn_record(root: Path) -> str:
    """What the previous turn recorded, as one sentence for the prompt hook, and a new snapshot for the next turn.
    Empty on the first turn the hook sees."""
    from . import validate
    from .ops import short
    from .schema import PREFIX_TABLE
    data = validate.gather(root)
    now = validate.ledger(data)
    rows = {r['ID']: r for found in data['live'].values() for r in found}
    try:
        before = json.loads((root / TURN_LEDGER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        before = None
    atomic_write(root / TURN_LEDGER, json.dumps(now))
    if not isinstance(before, dict):
        return ''
    items = [f'{rid} {short(rows[rid].get(PREFIX_TABLE[rid[0]].summary, ""), 80)}' if rid in rows else rid
             for rid in now if rid not in before]
    items += [f'{rid} {before[rid]} -> {now[rid]}' for rid in now if rid in before and before[rid] != now[rid]]
    if not items:
        return ('The previous turn recorded nothing in the state files. If the user stated a requirement, change, '
                'decision, preference or question there, record it now.')
    return 'The previous turn recorded: ' + '; '.join(items[:8]) + ('; and more' if len(items) > 8 else '') + '.'

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
