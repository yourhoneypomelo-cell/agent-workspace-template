"""Copy host transcripts into docs/chats/ from hook events. Never raises into the host."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import tables
from .core import atomic_write, read, safe_path, today
from .locks import lock
from .coverage import redact, redact_json_lines, redact_pasted
from .messages import STAMP_RE, carry, new_id, routine
from .schema import CHAT_INDEX, HEADING_NOTE

INDEX_HEADERS = ('Date', 'Host', 'Session', 'Messages', 'Transcript', 'Raw copy')
TRANSCRIPT_KEYS = ('transcript_path', 'transcriptPath', 'transcript', 'transcriptFile')
SESSION_KEYS = ('session_id', 'sessionId', 'conversation_id', 'conversationId', 'chat_id')
MAX_RAW = 50 * 1024 * 1024


def _first(data: dict, keys) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get('type') in (None, 'text', 'input_text', 'output_text') \
                    and not item.get('thought'):  # Qwen and Gemini mark hidden reasoning parts
                parts.append(_text(item.get('text') or item.get('content') or ''))
        # Claude Code puts a system reminder part before the typed text; drop injected parts, keep the rest.
        typed = [p for p in parts if p and not p.lstrip().startswith(INJECTED_PREFIXES)]
        return '\n'.join(typed if typed else [p for p in parts if p])
    if isinstance(content, dict):
        return _text(content.get('text') or content.get('content') or content.get('parts') or '')
    return ''


def _role(record: dict) -> str | None:
    for candidate in (record, record.get('message') if isinstance(record.get('message'), dict) else None,
                      record.get('payload') if isinstance(record.get('payload'), dict) else None):
        if not candidate:
            continue
        role = candidate.get('role') or candidate.get('type') or candidate.get('author')
        if isinstance(role, dict):
            role = role.get('role')
        if role in ('user', 'human'):
            return 'user'
        if role in ('assistant', 'model', 'ai', 'gemini'):
            return 'assistant'
    return None


# Text the host injects as a user turn: instructions, environment, reminders.
INJECTED_PREFIXES = ('<system-reminder>', '<system-reminder ', '<command-', '# AGENTS.md instructions', '<environment_context>',
                     '<user_instructions>', '<INSTRUCTIONS>', '<skills_instructions>', '<turn_aborted>',
                     '<user_info>', '<rules>', '<recent_agents_context>',
                     'The last user message was not recorded and no reason was given.',
                     '[Request interrupted by user', '<local-command-', '<heartbeat>', '<subagent_notification>',
                     '<external_codex_apps_', '<recommended_plugins>', '<codex_delegation>',
                     '<send_user_message_question_reply>')
# Codex IDE extension: open files and selections come first, the typed text follows the last heading.
CODEX_IDE_REQUEST = re.compile(r'^## My request(?: for Codex)?:[ \t]*$', re.M)
CODEX_IDE_START = ('# Context from my IDE setup', '# Files pasted by the user', '# Files mentioned by the user')
# Claude Code origin kinds whose text the host wrote: background task results, cloud-agent continuations.
HOST_ORIGINS = ('task-notification', 'auto-continuation')


def _answers(record: dict):
    """A user's choice in a host question tool, which hosts store as tool output, not as a user turn."""
    result = record.get('toolUseResult')
    if isinstance(result, dict) and isinstance(result.get('answers'), dict) and result['answers']:
        # Claude Code AskUserQuestion
        lines = [f'{q}: {a}' for q, a in result['answers'].items() if isinstance(a, str)]
        return ('user', 'Answered: ' + '; '.join(lines)) if lines else None
    payload = record.get('payload') if isinstance(record.get('payload'), dict) else None
    if payload and payload.get('type') == 'interaction_resolved' and isinstance(payload.get('selectedOption'), str):
        # Kiro question tool; tool approvals carry an outcome but no selected option
        return ('user', 'Answered: ' + payload['selectedOption'])
    return None


def _message(record: dict):
    """Return (role, text) for a visible message, or None for tool traffic and metadata."""
    answered = _answers(record)
    if answered:
        return answered
    provider = record.get('providerData') if isinstance(record.get('providerData'), dict) else {}
    if record.get('isMeta') or provider.get('isMeta'):
        return None  # CodeBuddy and WorkBuddy mark host-inserted turns
    if record.get('isCompactSummary') or record.get('type') == 'api-request-blob':
        return None  # Claude Code compaction summary and API request dumps, written as user turns
    if isinstance(record.get('origin'), dict) and record['origin'].get('kind') in HOST_ORIGINS:
        return None  # Claude Code: typed text has kind "human"; unknown kinds are kept
    if provider.get('skipRun') or provider.get('error'):
        return None  # WorkBuddy error stubs such as "502" or "aborted"
    if record.get('provenance') not in (None, 'real_user', 'assistant_output'):
        return None  # Qwen Code marks system-inserted turns
    if record.get('type') == 'response_item' and (record.get('payload') or {}).get('type') != 'message':
        return None
    if record.get('type') == 'event_msg':
        return None
    if isinstance(record.get('payload'), dict) and 'id' in record and 'timestamp' in record and \
            record['payload'].get('type') in ('user', 'assistant', 'tool_call', 'tool_result', 'agent_note',
                                              'turn_start', 'turn_end', 'usage_summary', 'session_metadata',
                                              'session_event', 'steering_inclusion', 'pending_interaction',
                                              'interaction_resolved', 'sub_agent_start', 'sub_agent_complete',
                                              'session_start', 'tombstone'):
        # Kiro session log: user text, and assistant text spoken to the user ("Say")
        inner = record['payload']
        if inner.get('type') == 'user' and isinstance(inner.get('content'), str) and inner['content'].strip():
            return 'user', inner['content'].strip()
        if inner.get('type') == 'assistant' and inner.get('operationType') == 'Say' and isinstance(inner.get('content'), str):
            text = inner['content'].strip()
            return ('assistant', text) if text else None
        return None
    if record.get('type') == 'user' and record.get('synthetic_reason'):
        return None  # Grok inserts reminders and project instructions as user turns
    if record.get('type') == 'USER_INPUT' and record.get('source') == 'USER_EXPLICIT':
        # Antigravity wraps the typed request in USER_REQUEST tags and appends metadata.
        found = re.search(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', str(record.get('content', '')), re.S)
        text = (found[1] if found else str(record.get('content', ''))).strip()
        return ('user', text) if text else None
    if record.get('type') == 'PLANNER_RESPONSE':
        text = str(record.get('content') or record.get('response') or '').strip()
        return ('assistant', text) if text else None
    if record.get('type') in ('GENERIC', 'SYSTEM_MESSAGE', 'USER_INPUT'):
        return None
    if record.get('type') == 'agent.message.appended':
        # Kimi Code wire log: a user turn has origin "user"; assistant turns carry text parts.
        inner = (record.get('message') or {}).get('message') or {}
        if inner.get('role') == 'user' and ((record['message'].get('meta') or {}).get('origin') or {}).get('kind') != 'user':
            return None
        record = {'message': inner}
    elif record.get('type', '').startswith(('context.', 'turn.', 'llm.', 'profile.', 'plugin.')):
        return None
    role = _role(record)
    if not role:
        return None
    body = record.get('message') if isinstance(record.get('message'), dict) else record.get('payload') if isinstance(record.get('payload'), dict) else record
    text = _text(body.get('content') if 'content' in body else body.get('text') or body.get('parts'))
    text = text.strip()
    if role == 'user' and '<user_query>' in text:
        # Cursor wraps the typed text in user_query tags next to timestamps and attachments.
        found = re.search(r'<user_query>\s*(.*?)\s*</user_query>', text, re.S)
        text = found[1].strip() if found else text
    if role == 'user' and text.startswith(CODEX_IDE_START):
        # An attachment-only message has nothing after the heading; keep it whole rather than lose it.
        headings = list(CODEX_IDE_REQUEST.finditer(text))
        text = text[headings[-1].end():].strip() or text if headings else text
    if not text or text.startswith(INJECTED_PREFIXES):
        return None
    return role, text


def _replay_gemini(records: list) -> list:
    """Gemini CLI chat logs are a change log: `$set.messages` holds earlier turns, a repeated id replaces
    a message, `$rewindTo` drops a message and everything after it, `$patch` removes or reorders ids."""
    order, by_id = [], {}

    def put(message):
        if not isinstance(message, dict) or 'type' not in message:
            return
        key = message.get('id') if isinstance(message.get('id'), str) and message.get('id') else f'_{len(order)}'
        if key not in by_id:
            order.append(key)
        by_id[key] = message

    for record in records:
        if isinstance(record.get('$set'), dict):
            for message in record['$set'].get('messages') or []:
                put(message)
        elif '$rewindTo' in record:
            target = record['$rewindTo']
            if isinstance(target, str) and target in by_id:
                cut = order.index(target)
                for key in order[cut:]:
                    by_id.pop(key, None)
                del order[cut:]
        elif isinstance(record.get('$patch'), dict):
            patch = record['$patch']
            def ids(name):
                value = patch.get(name)
                return [k for k in value if isinstance(k, str)] if isinstance(value, list) else []
            for key in ids('removeIds'):
                if key in by_id:
                    by_id.pop(key)
                    order.remove(key)
            for update in patch.get('updates') if isinstance(patch.get('updates'), list) else []:
                if isinstance(update, dict) and isinstance(update.get('id'), str) and update['id'] in by_id:
                    by_id[update['id']] = {**by_id[update['id']], **update}
            wanted = list(dict.fromkeys(k for k in ids('orderIds') if k in by_id))
            if wanted:
                order = wanted + [k for k in order if k not in wanted]
        else:
            put(record)
    return [by_id[key] for key in order]


COMPACTED = '(after compaction)'


def _time(record: dict) -> str:
    """The record's UTC time as 2026-10-31T14:02:05Z, or '' when the host stores none."""
    value = record.get('timestamp') or record.get('created_at') or record.get('createdAt')
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            moment = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        elif isinstance(value, str) and value.strip():
            moment = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            moment = moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        else:
            return ''
    except (ValueError, OverflowError, OSError):
        return ''
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def extract(path: Path, timed: bool = False) -> list:
    """(role, text) for each visible message. With timed, (role, text, note): the note holds the time and a
    compaction mark and is written in the heading, never in the text, so message IDs stay the same."""
    raw = path.read_text(encoding='utf-8', errors='replace')
    records = []
    stripped = raw.lstrip()
    if stripped.startswith('[') or (stripped.startswith('{') and '\n{' not in stripped[:2000]):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = data.get('messages') or data.get('history') or data.get('items') or []
            records = [r for r in data if isinstance(r, dict)]
        except ValueError:
            records = []
    if not records:
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
    if any('$set' in r or '$rewindTo' in r or '$patch' in r for r in records):
        records = _replay_gemini(records)
    for notice in [r for r in records if r.get('type') == 'resend-fork-notice' and r.get('editedUserItemId')]:
        # WorkBuddy: an edited and resent message replaces the original and the replies it got.
        ids = [r.get('id') for r in records]
        at = next((i for i, r in enumerate(records) if r is notice), -1)
        if notice['editedUserItemId'] in ids[:max(at, 0)]:
            records = records[:ids.index(notice['editedUserItemId'])] + records[at:]
    messages, gap = [], False
    for record in records:
        gap = gap or bool(record.get('isCompactSummary')) or record.get('type') == 'compacted'
        found = _message(record)
        # Codex writes some messages twice in a row, as an event and as a response item.
        if found and (not messages or messages[-1][:2] != found):
            note = ' '.join(filter(None, (_time(record), COMPACTED if gap else '')))
            messages.append((*found, note))
            gap = False
    return messages if timed else [m[:2] for m in messages]


HEADING_RE = re.compile(r'^(## \d+\. (?:user|assistant)' + HEADING_NOTE + r')[ \t]*$', re.M)
MAX_MESSAGE = 200_000


def escape_headings(text: str) -> str:
    """A message line that looks like a message heading would split the message when it is read back."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if len(text) > MAX_MESSAGE:
        text = text[:MAX_MESSAGE] + f'\n\n[truncated: the message had {len(text)} characters]'
    return HEADING_RE.sub(r' \1', text)


def render(host: str, session: str, messages: list, source: str, old: str = '', rel: str = '') -> str:
    """The transcript file. User messages keep the IDs they have in old, the file being replaced."""
    lines = [f'# Transcript {host} {session}', '', f'Source: `{source}`. Copied by the {host} hook; secrets matching common key patterns are redacted.', '']
    cleaned = []
    for number, (role, text, *note) in enumerate(messages, 1):
        body = escape_headings(redact_pasted(text) if role == 'user' else redact(text))
        cleaned.append((number, role, body, note[0] if note and note[0] else ''))
    users = [(number, body, (STAMP_RE.search(note) or [''])[0]) for number, role, body, note in cleaned if role == 'user']
    ids = iter(carry(old, rel or f'docs/chats/{host}/{session}.md', users))
    for number, role, body, note in cleaned:
        suffix = (f' {note}' if note else '') + (f' [{next(ids)}]' if role == 'user' else '')
        lines += [f'## {number}. {role}{suffix}', '', body, '']
    return '\n'.join(lines)


def rewrite(root: Path, rel: str, host: str, session: str, messages: list, source: str):
    """Write a transcript again from the host's copy. Call with the lock held: a prompt hook may be appending."""
    path = safe_path(root, rel)
    old = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
    atomic_write(path, render(host, session, messages, source, old, rel))


def _same_dir(a: str, b: Path) -> bool:
    """An empty or relative folder would resolve against the current directory and match any project."""
    if not isinstance(a, str) or not os.path.isabs(a):
        return False
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(str(b.resolve()))
    except (OSError, ValueError):
        return False


IMPORT_HOSTS = ('kimi', 'codex', 'antigravity', 'kiro', 'cursor', 'workbuddy', 'codebuddy', 'qoder', 'qwen', 'gemini', 'dsh')
# Stores that name the project folder in an index or a first line, so a scan takes about a second.
# Cursor and Antigravity stores must be read in full; import them by hand with "ws chats import".
AUTO_IMPORT = ('kimi', 'codex', 'kiro', 'workbuddy', 'codebuddy', 'qoder', 'qwen', 'gemini', 'dsh')
# Stores laid out as <home>/projects/<folder>/... whose lines carry the session's "cwd".
CWD_STORES = {
    'workbuddy': [('WORKBUDDY_HOME', '.workbuddy-ai'), (None, '.workbuddy')],
    'codebuddy': [('CODEBUDDY_CONFIG_DIR', '.codebuddy')],
    'qoder': [('QODER_HOME', '.qoder'), ('QODER_CONFIG_DIR', '.qoder')],
    'qwen': [('QWEN_HOME', '.qwen')],
}
CWD_PATTERNS = ('projects/*/*.jsonl', 'projects/*/transcript/*.jsonl', 'projects/*/chats/*.jsonl')
CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return ''


SCAN_CACHE = '.agents/cache/session-scan.json'
# Part of each cached scan result's key: results found under older matching rules are scanned again.
SCAN_RULES = 2


def _markers(root: Path) -> list:
    """Byte forms of the project path as it appears in host transcripts: plain, JSON-escaped and with slashes, and
    on Windows with the drive letter in either case."""
    text = str(root.resolve())
    forms = {text, text.replace('\\', '/')}
    if re.match(r'[A-Za-z]:', text):
        forms |= {f[0].swapcase() + f[1:] for f in forms}
    return sorted({f.encode('utf-8') for f in forms} | {json.dumps(f)[1:-1].encode('utf-8') for f in forms}
                  | {json.dumps(f, ensure_ascii=False)[1:-1].encode('utf-8') for f in forms})


def _mentions(root: Path, paths: list) -> list:
    """Paths whose text names this project. Results are cached by size and modification time, because a
    host store can hold gigabytes of transcripts that would otherwise be read at every session start."""
    markers = _markers(root)
    # A mention ends where the path does: "E:/a/T8" does not mention E:/a/T80.
    mention = re.compile(b'(?:' + b'|'.join(re.escape(m) for m in markers) + rb')(?=[\\/"\'\s])')
    cache_path = root / SCAN_CACHE
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    fresh, found = {}, []
    for path in paths:
        try:
            info = path.stat()
        except OSError:
            continue
        key = f'{SCAN_RULES}:{info.st_size}:{info.st_mtime_ns}'
        hit = cache.get(str(path))
        if isinstance(hit, list) and len(hit) == 2 and hit[0] == key and isinstance(hit[1], bool):
            match = hit[1]
        else:
            match = False
            try:
                with path.open('rb') as stream:
                    tail = b''
                    for chunk in iter(lambda: stream.read(1 << 20), b''):
                        if mention.search(tail + chunk):
                            match = True
                            break
                        tail = (tail + chunk)[-512:]
                    else:
                        match = any(tail.endswith(m) for m in markers)
            except OSError:
                continue
        fresh[str(path)] = [key, match]
        if match:
            found.append(path)
    if fresh != cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(cache_path, json.dumps(fresh))
        except OSError:
            pass
    return found


CWD_CACHE = '.agents/cache/session-cwd.json'


def _session_folders(root: Path, paths: list, first_line: bool) -> dict:
    """path -> the working folder a session file records. A session never moves to another folder, so a
    found answer is cached by path and only new files are read."""
    cache_path = root / CWD_CACHE
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    result, changed = {}, False
    for path in paths:
        key = str(path)
        if isinstance(cache.get(key), str) and cache[key]:
            result[key] = cache[key]
            continue
        try:
            with path.open('rb') as stream:
                head = stream.read(65536).decode('utf-8', errors='replace')
                if not first_line and not CWD_RE.search(head):
                    head += stream.read(1 << 20).decode('utf-8', errors='replace')
        except OSError:
            continue
        match = CWD_RE.search(head.split('\n', 1)[0] if first_line else head)
        folder = _json_string(match[1]) if match else ''
        if folder:
            cache[key] = folder
            changed = True
        result[key] = folder
    if changed:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(cache_path, json.dumps(cache))
        except OSError:
            pass
    return result


THREAD_SOURCE_RE = re.compile(r'"thread_source"\s*:\s*"([^"]*)"')
SUBAGENT_RE = re.compile(r'"source"\s*:\s*\{\s*"subagent"')


def _codex_delegated(path: Path) -> bool:
    """A Codex subagent or guardian rollout: its user turns are prompts the agent wrote, not the user."""
    try:
        with path.open('rb') as stream:
            head = stream.readline(65536).decode('utf-8', errors='replace')
    except OSError:
        return False
    found = THREAD_SOURCE_RE.search(head)  # newer CLIs: "user", "subagent" or "guardian_review"
    return found[1] != 'user' if found else bool(SUBAGENT_RE.search(head))


def local_sessions(root: Path, host: str) -> list:
    """Find (session_id, transcript_path) pairs a host stored for this project folder."""
    found = []
    home = Path.home()
    if host in CWD_STORES:
        seen = set()
        for variable, default in CWD_STORES[host]:
            base = Path(os.environ[variable]) if variable and os.environ.get(variable) else home / default
            paths = [p for pattern in CWD_PATTERNS for p in (base.glob(pattern) if base.is_dir() else []) if p not in seen]
            seen.update(paths)
            folders = _session_folders(root, paths, first_line=False)
            found += [(p.stem, p) for p in paths if _same_dir(folders.get(str(p), ''), root)]
        found.sort(key=lambda item: item[1].stat().st_mtime)
        return found[-50:]
    if host == 'gemini':
        # Gemini CLI: ~/.gemini/projects.json maps each project folder to a slug under tmp/.
        base = Path(os.environ.get('GEMINI_HOME') or home / '.gemini')
        try:
            projects = json.loads((base / 'projects.json').read_text(encoding='utf-8')).get('projects') or {}
        except (OSError, ValueError, AttributeError):
            projects = {}
        projects = projects if isinstance(projects, dict) else {}
        slugs = [slug for folder, slug in projects.items()
                 if isinstance(slug, str) and re.fullmatch(r'[A-Za-z0-9._-]+', slug) and slug not in ('.', '..')
                 and _same_dir(folder, root)]
        for slug in slugs:
            for path in (base / 'tmp' / slug / 'chats').glob('*.jsonl'):
                found.append((path.stem, path))
        found.sort(key=lambda item: item[1].stat().st_mtime)
        return found[-50:]
    if host == 'kiro':
        # Kiro IDE: sessions/<workspace hash>/<session>/session.json names the workspace folders.
        base = Path(os.environ.get('KIRO_HOME') or home / '.kiro') / 'sessions'
        for meta in base.glob('*/sess_*/session.json') if base.is_dir() else []:
            try:
                data = json.loads(meta.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            folders = (data.get('workspacePaths') or []) + (data.get('rootPaths') or [])
            log = meta.with_name('messages.jsonl')
            if log.is_file() and any(isinstance(f, str) and _same_dir(f, root) for f in folders):
                found.append((meta.parent.name, log))
        found.sort(key=lambda item: item[1].stat().st_mtime)
    elif host == 'cursor':
        # Cursor keeps agent transcripts per project folder, but the folder name does not say which project.
        # A transcript belongs here when it mentions this project's path.
        base = home / '.cursor' / 'projects'
        paths = list(base.glob('*/agent-transcripts/*/*.jsonl')) if base.is_dir() else []
        found = [(p.stem, p) for p in _mentions(root, paths)]
        found.sort(key=lambda item: item[1].stat().st_mtime)
    elif host == 'kimi':
        base = Path(os.environ.get('KIMI_CODE_HOME') or home / '.kimi-code')
        index = base / 'session_index.jsonl'
        if index.is_file():
            for line in index.read_text(encoding='utf-8', errors='replace').splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                wire = Path(item.get('sessionDir', '')) / 'agents' / 'main' / 'wire.jsonl'
                if _same_dir(item.get('workDir', ''), root) and wire.is_file():
                    found.append((item['sessionId'], wire))
    elif host == 'codex':
        base = Path(os.environ.get('CODEX_HOME') or home / '.codex') / 'sessions'
        paths = sorted(base.rglob('rollout-*.jsonl')) if base.is_dir() else []
        # The first line is the session meta; it names the working folder.
        folders = _session_folders(root, paths, first_line=True)
        found = [(p.stem, p) for p in paths if _same_dir(folders.get(str(p), ''), root) and not _codex_delegated(p)]
    elif host == 'antigravity':
        # The transcript has no working directory, so match conversations that touched this project's files.
        paths = []
        for app in ('antigravity-cli', 'antigravity', 'antigravity-ide', 'antigravity-id'):
            brain = home / '.gemini' / app / 'brain'
            paths += list(brain.glob('*/.system_generated/logs/transcript.jsonl')) if brain.is_dir() else []
        found = [(p.parents[2].name, p) for p in _mentions(root, paths)]
        found.sort(key=lambda item: item[1].stat().st_mtime)
    else:
        raise ValueError(f'import supports {", ".join(IMPORT_HOSTS)}; use hooks for {host}')
    return found[-50:]


def import_sessions(root: Path, host: str, since: float | None = None) -> dict:
    """Copy this project's sessions of one host. With since, a session last written before that time stays out."""
    if host == 'dsh':
        from . import dsh
        return dsh.import_sessions(root, since=since)
    results = [capture(root, host, 'import', {'session_id': sid, 'transcript_path': str(path)})
               for sid, path in local_sessions(root, host) if since is None or path.stat().st_mtime >= since]
    return {'host': host, 'sessions': len(results), 'messages': sum(r.get('messages', 0) for r in results)}


IMPORT_QUESTION = ("Ask the user once, in your reply: may ws start copy this project's chats from the AI tools on this "
                   'machine (Codex, Kiro, Kimi Code, Gemini, Qwen Code, Qoder, CodeBuddy, WorkBuddy and DeepSeek '
                   'Harness) into docs/chats/, leaving out chats from before the workspace was set up? Then set '
                   'WORKSPACE "chat_import" in docs/state/ARCHITECTURE.md to "on" or "off".')


def import_rule(root: Path) -> tuple:
    """("on", "off" or "ask", and the time sessions must be newer than, or None). WS_IMPORT=0 or 1 in the environment
    wins over WORKSPACE "chat_import", so a user can decide for every project at once (owner decision D1)."""
    from .core import WorkspaceError, config
    try:
        settings = config(root)
    except (WorkspaceError, ValueError, OSError):
        settings = {}
    rule = {'0': 'off', '1': 'on'}.get(os.environ.get('WS_IMPORT', ''), settings.get('chat_import', 'ask'))
    since = settings.get('chat_import_since')
    if since:
        moment = datetime.fromisoformat(str(since))
        since = (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return rule, since or None


def import_all(root: Path, since: float | None = None) -> dict:
    """Copy this project's sessions from every host store found on this machine. Never raises."""
    found = {}
    for host in AUTO_IMPORT:
        try:
            if host == 'dsh':
                from . import dsh
                result = dsh.import_sessions(root, automatic=True, since=since)
            else:
                result = import_sessions(root, host, since)
        except Exception:  # an unreadable store of one host must not stop the others
            continue
        if result['sessions']:
            found[host] = result['sessions']
    return found


def session_name(payload: dict) -> str:
    raw = _first(payload, SESSION_KEYS) or 'unknown'
    name = re.sub(r'[^A-Za-z0-9_-]', '-', raw)[:64].strip('-') or 'unknown'
    # Different IDs that clean to the same name, such as a/b and a-b, keep separate files.
    return name if name == raw else f'{name[:52]}-{hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]}'


def journal(root: Path, host: str, payload: dict, role: str, text: str) -> dict:
    """Append one message to docs/chats/<host>/<session>.md for hosts whose hooks send the text, not a file."""
    text = text.strip() if isinstance(text, str) else ''
    if not text or text.startswith(INJECTED_PREFIXES):
        return {'captured': False, 'reason': 'no message text in the hook payload'}
    host = re.sub(r'[^a-z0-9-]', '-', host.lower())[:24] or 'host'
    session = session_name(payload)
    rel = f'docs/chats/{host}/{session}.md'
    with lock(root):
        return _append(root, host, session, rel, role, text)


def submit(root: Path, host: str, payload: dict) -> dict:
    """Prompt-submit hook: save the user message as it arrives, so the turn can reconcile it before its checkpoint.
    The text is cleaned as the host's own copy will be, and the Stop hook's rewrite keeps the ID it gets here."""
    prompt = _first(payload, PROMPT_KEYS)
    found = _message({'role': 'user', 'content': prompt}) if prompt else None
    if not found:
        return {'captured': False, 'reason': 'no typed text in the hook payload'}
    source = _first(payload, TRANSCRIPT_KEYS)
    if host == 'codex' and source and Path(source).is_file() and _codex_delegated(Path(source)):
        return {'captured': False, 'reason': 'a subagent or guardian thread; its prompts come from the agent'}
    return journal(root, host, payload, 'user', found[1])


def _append(root: Path, host: str, session: str, rel: str, role: str, text: str) -> dict:
    path = safe_path(root, rel)
    existing = path.read_text(encoding='utf-8') if path.is_file() else ''
    numbers = [int(n) for n in re.findall(r'^## (\d+)\. (?:user|assistant)' + HEADING_NOTE + '$', existing, re.M)]
    if not existing:
        existing = f'# Transcript {host} {session}\n\nWritten by the {host} hooks one message at a time; secrets matching common key patterns are redacted.\n'
    last = re.findall(r'^## \d+\. (user|assistant)' + HEADING_NOTE + r'\n\n(.*?)(?=^## \d+\. |\Z)', existing, re.M | re.S)
    body = escape_headings(redact_pasted(text) if role == 'user' else redact(text))
    if last and last[-1][0] == role and last[-1][1].strip() == body.strip():
        return {'captured': False, 'reason': 'same message already written'}
    number = max(numbers, default=0) + 1
    _index(root, host, session, number, rel, None)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')  # the hook fires as the message arrives
    mid = new_id(rel, number, body) if role == 'user' else ''
    mark = f' [{mid}]' if mid else ''
    atomic_write(path, existing.rstrip('\n') + f'\n\n## {number}. {role} {stamp}{mark}\n\n{body}\n')
    found = {'captured': True, 'messages': number, 'transcript': rel}
    return {**found, 'id': mid} if mid and not routine(mid, body.strip()) else found


def _index(root: Path, host: str, session: str, count: int, transcript_rel: str, raw_rel: str | None):
    """Add or update the INDEX.md row of a session. A raw_rel of None keeps the raw copy the row names."""
    index = read(root, CHAT_INDEX)
    row = {'Date': today(), 'Host': host, 'Session': session, 'Messages': str(count),
           'Transcript': transcript_rel, 'Raw copy': raw_rel or 'none'}
    existing = [r for r in tables.parse(index, INDEX_HEADERS, CHAT_INDEX) if r['Session'] == session and r['Host'] == host]
    if raw_rel is None and existing:
        row['Raw copy'] = existing[0].get('Raw copy') or 'none'
    if existing:
        start, actual, raw = tables._find(index, INDEX_HEADERS, CHAT_INDEX)
        lines = index.split('\n')
        for i, cells in raw:
            if cells[1:3] == [host, session]:
                lines[i] = tables.render_row(actual, row)
        index = '\n'.join(lines)
    else:
        index = tables.append(index, INDEX_HEADERS, CHAT_INDEX, row)
    atomic_write(safe_path(root, CHAT_INDEX), index)


PROMPT_KEYS = ('prompt', 'user_prompt', 'userPrompt')
REPLY_KEYS = ('last_assistant_message', 'lastAssistantMessage', 'text', 'response')


def capture(root: Path, host: str, event: str, payload: dict) -> dict:
    source = _first(payload, TRANSCRIPT_KEYS) or (os.environ.get('CURSOR_TRANSCRIPT_PATH') if host == 'cursor' else None)
    if not source:
        # Kiro and Cursor send the prompt and the reply in the hook payload instead of a transcript file.
        prompt, reply = _first(payload, PROMPT_KEYS), _first(payload, REPLY_KEYS)
        if prompt or reply:
            return journal(root, host, payload, 'user' if prompt else 'assistant', prompt or reply)
        return {'captured': False, 'reason': 'the hook payload has no transcript path and no message text'}
    host = re.sub(r'[^a-z0-9-]', '-', host.lower())[:24] or 'host'
    session = session_name(payload)
    path = Path(source).expanduser()
    if not path.is_file():
        return {'captured': False, 'reason': f'transcript not found: {source}'}
    if host == 'codex' and _codex_delegated(path):
        return {'captured': False, 'reason': 'a subagent or guardian thread; its prompts come from the agent'}
    folder = f'docs/chats/{host}'
    messages = extract(path, timed=True)
    last = payload.get('last_assistant_message') or payload.get('lastAssistantMessage')
    # Hosts flush the transcript after Stop hooks run, so the final reply may be missing from the file.
    if isinstance(last, str) and last.strip() and ('assistant', last.strip()) not in [m[:2] for m in messages]:
        messages.append(('assistant', last.strip(), ''))
    with lock(root):
        transcript_rel = f'{folder}/{session}.md'
        if messages:
            rewrite(root, transcript_rel, host, session, messages, path.name)
        raw_rel = f'{folder}/raw/{session}{path.suffix or ".txt"}'
        if path.stat().st_size <= MAX_RAW and os.environ.get('WS_CAPTURE_RAW', '1') != '0':
            # The raw copy keeps the host format but gets the same redaction as the Markdown copy.
            text = path.read_text(encoding='utf-8', errors='replace')
            atomic_write(safe_path(root, raw_rel), redact_json_lines(text))
        else:
            raw_rel = 'none'
        _index(root, host, session, len(messages), transcript_rel if messages else 'none', raw_rel)
    return {'captured': True, 'messages': len(messages), 'transcript': transcript_rel, 'event': event}
