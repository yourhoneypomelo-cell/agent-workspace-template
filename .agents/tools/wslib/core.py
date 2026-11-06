"""File access, locking, machine state, handoff card and fingerprints."""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .schema import (
    ARCHITECTURE, CACHE_DIR, CARD_FIELDS, CREDENTIAL_RULES, DEFAULT_CONFIG, FINGERPRINT_CACHE, HANDOFF, LOCK, NONE,
    NON_SOURCE, PRUNE_DIRS, PRUNE_FILES, PRUNE_PATHS, REQUIRED, REQUIREMENTS, SCHEMA, SCRATCH_SUFFIXES, SECRET_SUFFIXES,
)


class WorkspaceError(ValueError):
    """A user-facing error. The message states the cause and the fix."""


_OVERRIDES = contextvars.ContextVar('ws_overrides', default=None)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def today():
    return dt.datetime.now().astimezone().date().isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8'))


def configure_stdout():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def linked(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except OSError:
        return False


def safe_path(root: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or ':' in str(rel) or '\\' in str(rel):
        raise WorkspaceError(f'unsafe relative path: {rel}')
    target = root / p
    for part in (target, *target.parents):
        if part == root:
            break
        if part.exists() and linked(part):
            raise WorkspaceError(f'linked paths are not supported: {rel}')
    return target


def read(root: Path, rel: str) -> str:
    overrides = _OVERRIDES.get()
    if overrides and rel in overrides:
        return overrides[rel]
    path = safe_path(root, rel)
    if not path.is_file():
        raise WorkspaceError(f'missing file: {rel}')
    return path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')


@contextlib.contextmanager
def preview(changes: dict):
    """Let validators read proposed file contents before anything is written."""
    merged = dict(_OVERRIDES.get() or {})
    merged.update(changes)
    token = _OVERRIDES.set(merged)
    try:
        yield
    finally:
        _OVERRIDES.reset(token)


def atomic_write(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows refuses replacement while an editor or scanner holds the file.
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write(root: Path, rel: str, text: str):
    atomic_write(safe_path(root, rel), text)


# Process liveness without signals: os.kill(pid, 0) terminates the process on Windows.
def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: the process exists but this user may not open it
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


LOCK_ORPHAN_SECONDS = 60


@contextlib.contextmanager
def lock(root: Path):
    path = safe_path(root, LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + float(os.environ.get('WS_LOCK_WAIT', '30'))
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            try:
                holder = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                holder = {}
            if holder.get('pid') and not pid_alive(int(holder['pid'])):
                path.unlink(missing_ok=True)
                continue
            # A crash while the lock was written leaves an empty or NUL-filled file that names no process.
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if not holder.get('pid') and age > LOCK_ORPHAN_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise WorkspaceError(
                    f'another ws.py command is running (pid {holder.get("pid", "unknown")}, lock {int(age)} s old). '
                    'Wait and retry. Do not delete the lock while another window may run ws; a lock that names no '
                    f'process is removed after {LOCK_ORPHAN_SECONDS} s.')
            time.sleep(0.1)
    nonce = os.urandom(8).hex()
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'created_at': now(), 'nonce': nonce}))
        yield
    finally:
        _release(path, nonce)


def _release(path: Path, nonce: str):
    """Remove the lock only while it is still ours: a process that took us for dead may have taken it since."""
    try:
        if json.loads(path.read_text(encoding='utf-8')).get('nonce') == nonce:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


# Machine state: one single-line HTML comment at the end of HANDOFF.md.
STATE_RE = re.compile(r'^<!-- CONTINUITY (\{.*\}) -->$', re.M)


def default_state():
    return {'schema': SCHEMA, 'mode': 'bootstrap', 'revision': 0, 'writer': None, 'writer_revision': None,
            'checkpoint': None}


def state_of(root: Path) -> dict:
    text = read(root, HANDOFF)
    found = STATE_RE.findall(text)
    if len(found) != 1:
        raise WorkspaceError(f'{HANDOFF} must contain exactly one "<!-- CONTINUITY {{...}} -->" line')
    data = json.loads(found[0])
    if not isinstance(data, dict):
        raise WorkspaceError('the CONTINUITY line must hold a JSON object')
    return data


def state_line(state: dict) -> str:
    return '<!-- CONTINUITY ' + json.dumps(state, ensure_ascii=False, sort_keys=True) + ' -->'


def with_state(text: str, state: dict) -> str:
    if len(STATE_RE.findall(text)) != 1:
        raise WorkspaceError(f'{HANDOFF} must contain exactly one CONTINUITY line')
    return STATE_RE.sub(lambda _: state_line(state), text)


CLAIMS_RE = re.compile(r'\n*<!-- CLAIMS:START -->.*?<!-- CLAIMS:END -->\n?', re.S)


def with_claims(text: str, state: dict) -> str:
    """Refresh the "Parallel sessions" block, which sits just above the CONTINUITY line."""
    from .claims import render
    text = CLAIMS_RE.sub('\n', text)
    block = render(state)
    if not block:
        return text
    index = STATE_RE.search(text).start()
    return text[:index].rstrip('\n') + '\n\n' + block + '\n' + text[index:]


def save_state(root: Path, state: dict):
    write(root, HANDOFF, with_state(with_claims(read(root, HANDOFF), state), state))


# Handoff card: a two-column Markdown table between CARD markers.
CARD_START, CARD_END = '<!-- CARD:START -->', '<!-- CARD:END -->'


def split_cells(line: str) -> list:
    body = line.strip()
    if body.startswith('|'):
        body = body[1:]
    if body.endswith('|') and not body.endswith('\\|'):
        body = body[:-1]
    return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', body)]


def escape_cell(value: str) -> str:
    return str(value).replace('\r', ' ').replace('\n', ' ').replace('|', '\\|').strip()


def card_region(text: str):
    if text.count(CARD_START) != 1 or text.count(CARD_END) != 1 or text.index(CARD_START) > text.index(CARD_END):
        raise WorkspaceError(f'{HANDOFF} needs one CARD:START/CARD:END block')
    return text.index(CARD_START) + len(CARD_START), text.index(CARD_END)


def parse_card(text: str) -> dict:
    a, b = card_region(text)
    offset = text[:a].count('\n') + 1
    fields = {}
    for number, line in enumerate(text[a:b].split('\n'), offset):
        if not line.strip().startswith('|'):
            continue
        cells = split_cells(line)
        if len(cells) != 2:
            raise WorkspaceError(f'{HANDOFF}:{number}: card rows need two cells: | field | value |')
        key, value = cells
        if key in ('Field', '') or re.fullmatch(r':?-{3,}:?', key):
            continue
        if key not in CARD_FIELDS:
            raise WorkspaceError(f'{HANDOFF}:{number}: unknown card field "{key}"; valid: {", ".join(CARD_FIELDS)}')
        if key in fields:
            raise WorkspaceError(f'{HANDOFF}:{number}: duplicate card field "{key}"')
        fields[key] = value
    return fields


def render_card(fields: dict) -> str:
    lines = ['', '| Field | Value |', '| --- | --- |']
    lines += [f'| {key} | {escape_cell(fields.get(key, NONE)) or NONE} |' for key in CARD_FIELDS]
    return '\n'.join(lines) + '\n'


def card(root: Path) -> dict:
    return parse_card(read(root, HANDOFF))


def card_text(text: str, changes: dict) -> str:
    fields = parse_card(text)
    fields.update(changes)
    a, b = card_region(text)
    return text[:a] + render_card(fields) + text[b:]


# Goal: the text between GOAL markers in REQUIREMENTS.md.
GOAL_START, GOAL_END = '<!-- GOAL:START -->', '<!-- GOAL:END -->'


def goal_region(text: str):
    if text.count(GOAL_START) != 1 or text.count(GOAL_END) != 1 or text.index(GOAL_START) > text.index(GOAL_END):
        raise WorkspaceError(f'{REQUIREMENTS} needs one GOAL:START/GOAL:END block')
    return text.index(GOAL_START) + len(GOAL_START), text.index(GOAL_END)


def goal_of(text: str) -> str:
    a, b = goal_region(text)
    return re.sub(r'<!--.*?-->', '', text[a:b], flags=re.S).strip()


def goal(root: Path) -> str:
    return goal_of(read(root, REQUIREMENTS))


def with_goal(text: str, value: str) -> str:
    a, b = goal_region(text)
    return text[:a] + '\n' + value.strip() + '\n' + text[b:]


# Workspace configuration: JSON between WORKSPACE markers in ARCHITECTURE.md.
CONFIG_RE = re.compile(r'<!-- WORKSPACE:START -->\s*(.*?)\s*<!-- WORKSPACE:END -->', re.S)


def config(root: Path) -> dict:
    text = read(root, ARCHITECTURE)
    found = CONFIG_RE.findall(text)
    if len(found) != 1:
        raise WorkspaceError(f'{ARCHITECTURE} needs one WORKSPACE:START/WORKSPACE:END block')
    try:
        data = json.loads(found[0])
    except ValueError as error:
        raise WorkspaceError(f'{ARCHITECTURE}: WORKSPACE block is not valid JSON: {error}') from error
    if not isinstance(data, dict):
        raise WorkspaceError(f'{ARCHITECTURE}: WORKSPACE block must be a JSON object')
    merged = {**DEFAULT_CONFIG, **data}
    if merged['ownership'] not in ('solo', 'shared'):
        raise WorkspaceError('WORKSPACE ownership must be "solo" or "shared"')
    patterns = merged['exclude']
    if not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns):
        raise WorkspaceError('WORKSPACE exclude must be a list of relative glob patterns, such as ["data/**", "*.sqlite"]')
    patterns = merged['exclude'] = [p.replace('\\', '/') for p in patterns]
    bad = [p for p in patterns if not p or '..' in Path(p).parts or Path(p).is_absolute() or ':' in p]
    if bad:
        raise WorkspaceError(f'WORKSPACE exclude pattern "{bad[0]}" must be relative to the project root, '
                             'with forward slashes and no drive letter, such as "data/**"')
    if merged['credentials'] not in CREDENTIAL_RULES:
        raise WorkspaceError('WORKSPACE credentials must be "ask" (the user has not decided), "plain" (credentials are '
                             'kept as written) or "redact" (credentials are kept out of files)')
    pending = merged.get('pending_adapters', [])
    if not isinstance(pending, list) or any(not isinstance(p, str) for p in pending):
        raise WorkspaceError('WORKSPACE pending_adapters must be a list of paths')
    return merged


# Watched files and content fingerprints.
def _excluded(rel: str, name: str, patterns: list) -> bool:
    if name in PRUNE_DIRS or name in PRUNE_FILES:
        return True
    if any(rel == p or rel.startswith(p + '/') for p in PRUNE_PATHS):
        return True
    if name == '.env' or name.startswith('.env.') or name.lower().endswith(SECRET_SUFFIXES + SCRATCH_SUFFIXES):
        return True
    return any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(rel, p.rstrip('/') + '/*') for p in patterns)


def _entry_linked(entry) -> bool:
    try:
        if entry.is_symlink():
            return True
        return bool(getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True


def _scan(root: Path) -> dict:
    """rel path -> (size, mtime_ns) for every watched file. One directory listing per folder."""
    patterns = config(root)['exclude']
    found = {}
    pending = [(str(root), '')]
    while pending:
        folder, prefix = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            rel = prefix + entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if not (_excluded(rel, entry.name, patterns) or _entry_linked(entry)):
                    pending.append((entry.path, rel + '/'))
                continue
            if rel in REQUIRED or not (_excluded(rel, entry.name, patterns) or _entry_linked(entry)):
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                found[rel] = (info.st_size, info.st_mtime_ns)
    return found


def watched_files(root: Path) -> list:
    return sorted(_scan(root))


def _load_cache(root: Path) -> dict:
    if os.environ.get('WS_NO_CACHE'):
        return {}
    try:
        data = json.loads((root / FINGERPRINT_CACHE).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# The project's credential rule for this command, set by ws.py from the WORKSPACE block (default "ask").
CREDENTIALS = contextvars.ContextVar('ws_credentials', default='ask')

# Read-only commands set this, so brief, status, check, turn and lint never write a file, not even the cache.
READ_ONLY = contextvars.ContextVar('ws_read_only', default=False)


def _save_cache(root: Path, cache: dict):
    if os.environ.get('WS_NO_CACHE') or READ_ONLY.get():
        return
    try:
        (root / CACHE_DIR).mkdir(parents=True, exist_ok=True)
        atomic_write(root / FINGERPRINT_CACHE, json.dumps(cache, sort_keys=True))
    except OSError:
        pass


# Line endings are normalized for these, so a CRLF checkout does not look like an edit.
TEXT_SUFFIXES = frozenset({
    '.md', '.txt', '.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json', '.yaml', '.yml', '.toml', '.ini',
    '.cfg', '.html', '.css', '.scss', '.vue', '.svelte', '.go', '.rs', '.java', '.kt', '.c', '.h', '.cpp', '.hpp',
    '.cs', '.rb', '.php', '.sh', '.ps1', '.bat', '.sql', '.xml', '.csv', '.mdc', '.swift', '.dart', '.lua',
})


def _handoff_hash(text: str) -> str:
    return sha(STATE_RE.sub('', text).encode('utf-8'))


def fingerprint(root: Path, source_only=False) -> dict:
    """Hash watched files. HANDOFF is hashed without its CONTINUITY line."""
    cache = _load_cache(root)
    fresh = {}
    result = {}
    overrides = _OVERRIDES.get() or {}
    for rel, (size, mtime) in sorted(_scan(root).items()):
        if source_only and rel.startswith(NON_SOURCE):
            continue
        if rel in overrides:
            text = overrides[rel]
            result[rel] = _handoff_hash(text) if rel == HANDOFF else sha(text.encode('utf-8'))
            continue
        path = root / rel
        if rel == HANDOFF:
            result[rel] = _handoff_hash(path.read_text(encoding='utf-8-sig').replace('\r\n', '\n'))
            continue
        key = f'{size}:{mtime}'
        cached = cache.get(rel)
        if cached and cached[0] == key:
            value = cached[1]
        else:
            try:
                if path.suffix.lower() in TEXT_SUFFIXES and size <= 8 << 20:
                    value = sha(path.read_bytes().replace(b'\r\n', b'\n'))
                else:
                    h = hashlib.sha256()
                    with path.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1 << 20), b''):
                            h.update(chunk)
                    value = h.hexdigest()
            except OSError:
                continue
        fresh[rel] = [key, value]
        result[rel] = value
    if not overrides and fresh != cache and not source_only:
        _save_cache(root, fresh)
    return result


def difference(old: dict, new: dict) -> dict:
    return {
        'added': sorted(new.keys() - old.keys()),
        'removed': sorted(old.keys() - new.keys()),
        'modified': sorted(p for p in new.keys() & old.keys() if old[p] != new[p]),
    }


def drift_count(changes: dict) -> int:
    return sum(len(v) for v in changes.values())


def describe_drift(changes: dict, limit=5) -> str:
    names = changes['added'] + changes['modified'] + changes['removed']
    if not names:
        return 'none'
    shown = ', '.join(names[:limit])
    return shown + (f' and {len(names) - limit} more' if len(names) > limit else '')


def checkpoint_of(root: Path, state: dict):
    pointer = state.get('checkpoint')
    if pointer is None:
        return None
    if not isinstance(pointer, dict) or not re.fullmatch(r'docs/archive/checkpoints/[0-9A-Za-z_-]+\.json', pointer.get('manifest', '')):
        raise WorkspaceError('invalid checkpoint pointer in the CONTINUITY line')
    path = safe_path(root, pointer['manifest'])
    if not path.is_file():
        raise WorkspaceError(f'checkpoint manifest missing: {pointer["manifest"]}')
    raw = path.read_bytes()
    if sha(raw) != pointer.get('sha256'):
        raise WorkspaceError(f'checkpoint manifest checksum mismatch: {pointer["manifest"]}')
    data = json.loads(raw)
    if data.get('schema') != 'checkpoint.v3':
        raise WorkspaceError(f'unsupported checkpoint schema in {pointer["manifest"]}')
    return data


def new_id(prefix='') -> str:
    return prefix + uuid.uuid4().hex[:12]


def writer_label() -> str:
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M')
    return f's-{stamp}-{uuid.uuid4().hex[:4]}'


# Session identity (U35, U36). One variable per host, visible to shell commands. Codex subagent threads share
# CODEX_SESSION_ID with their root thread (CODEX_THREAD_ID differs, so it is not used). ZCode sets
# CLAUDE_CODE_SESSION_ID and ZCODE_SESSION_ID to one value, and a subagent gets its own; variables with different
# values mean nested hosts.
# Kiro sets KIRO_SESSION_ID to the root conversation for agent shell commands and hooks (kiro-agent extension.js,
# Kse.snapshot passed as sessionEnv to the shell spawn); its subagents share it.
# Cursor sets CURSOR_CONVERSATION_ID in agent shell commands to the conversation_id its hooks receive. It stays the
# same through compaction, and a Cursor subagent has its own.
SESSION_VARS = ('WS_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_SESSION_ID', 'QWEN_CODE_SESSION_ID', 'ZCODE_SESSION_ID',
                'KIRO_SESSION_ID', 'CURSOR_CONVERSATION_ID')


def session_key(raw: str) -> str:
    return 'k-' + sha(('session:' + raw).encode('utf-8'))[:10]


def env_session() -> str | None:
    """The key of the host session named by the environment, or None when no variable or several values are set.
    A host started from a Cursor agent shell inherits CURSOR_CONVERSATION_ID, so that variable gives way to the others."""
    named = {n: os.environ[n] for n in SESSION_VARS if os.environ.get(n)}
    if len(set(named.values())) > 1:
        named.pop('CURSOR_CONVERSATION_ID', None)
    found = set(named.values())
    return session_key(found.pop()) if len(found) == 1 else None


def session_identity(given: str | None = None) -> dict | None:
    """{'id', 'via'}. A host variable wins over --session (the key the brief hook printed), so a key copied from
    another session cannot replace the real identity. The stored id is a hash of the key, never the key."""
    env = env_session()
    if env:
        # ZCode gives each subagent its own id, so its id resumes a session but never refuses a write.
        return {'id': session_key(env), 'via': 'host' if os.environ.get('ZCODE_SESSION_ID') else 'env'}
    return {'id': session_key(given), 'via': 'key'} if given else None


DELEGATED_VARS = ('WS_ROLE',)


def delegated() -> bool:
    """True in a subagent or helper window started with WS_ROLE=worker or WS_ROLE=readonly. Such a session reads
    the state but never claims it, so it cannot take the workspace from the session that started it."""
    return os.environ.get('WS_ROLE', '').strip().lower() in ('worker', 'readonly', 'read-only', 'subagent')


# Host process identity (U35). Every agent tool runs ws.py as a child of its own long-lived process: the IDE, the CLI
# or the desktop app. The nearest ancestor that is not a shell, interpreter or terminal is that host. Its pid and start
# time tell whether the window that owns the workspace still runs, on hosts with or without a session variable.
SHELLS = frozenset({
    'bash', 'sh', 'zsh', 'fish', 'dash', 'ksh', 'cmd', 'powershell', 'pwsh', 'conhost', 'openconsole', 'python',
    'python3', 'pythonw', 'py', 'node', 'env', 'sudo', 'timeout', 'nohup', 'script', 'tmux', 'screen', 'wsl', 'winpty',
    'mintty', 'git', 'uv', 'uvx', 'npx', 'tsx', 'deno', 'bun', 'sshd', 'login', 'windowsterminal', 'wt',
})


def _process_table() -> dict:
    """pid -> (parent pid, executable name without .exe, lower case)."""
    table = {}
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                        ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                        ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                        ('pcPriClassBase', wintypes.LONG), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_char * 260)]
        kernel = ctypes.windll.kernel32
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = kernel.CreateToolhelp32Snapshot(2, 0)
        if not snap or snap == wintypes.HANDLE(-1).value:
            return table
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            ok = kernel.Process32First(snap, ctypes.byref(entry))
            while ok:
                name = entry.szExeFile.decode('utf-8', 'replace').lower()
                table[entry.th32ProcessID] = (entry.th32ParentProcessID, name[:-4] if name.endswith('.exe') else name)
                ok = kernel.Process32Next(snap, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snap)
        return table
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            text = stat.read_text()
            name = text[text.index('(') + 1:text.rindex(')')].lower()
            table[int(stat.parent.name)] = (int(text[text.rindex(')') + 2:].split()[1]), name)
        except (OSError, ValueError, IndexError):
            continue
    if not table and sys.platform == 'darwin':
        import subprocess
        try:
            out = subprocess.run(['ps', '-axo', 'pid=,ppid=,comm='], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return table
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), Path(parts[2]).name.lower())
    return table


def host_process() -> dict | None:
    """{'pid', 'started', 'name'} of the host that runs this command, or None when it cannot be found.

    WS_HOST_PID names the host directly, for wrappers that start ws.py through a helper process."""
    given = os.environ.get('WS_HOST_PID', '').strip()
    if given.isdigit():
        alive, started = process_info(int(given))
        return {'pid': int(given), 'started': started, 'name': 'WS_HOST_PID'} if alive else None
    try:
        table = _process_table()
    except (OSError, ValueError, AttributeError):
        return None
    pid, seen = os.getppid(), set()
    while pid in table and pid not in seen and pid > 4:
        seen.add(pid)
        parent, name = table[pid]
        if name not in SHELLS:
            alive, started = process_info(pid)
            return {'pid': pid, 'started': started, 'name': name} if alive else None
        pid = parent
    # The chain broke at a shell that already exited, as after "bash -c" in some terminals: liveness stays unknown.
    return None


def host_alive(host: dict | None) -> bool | None:
    """True when the recorded host still runs, False when it exited or its pid now names another process, None when
    nothing was recorded or the system refuses to say."""
    if not host or not host.get('pid'):
        return None
    alive, started = process_info(int(host['pid']))
    if alive is None:
        return None
    if not alive:
        return False
    if host.get('started') and started and abs(started - host['started']) > 2:
        return False
    return True


def same_host(a: dict | None, b: dict | None) -> bool:
    return bool(a and b) and a.get('pid') == b.get('pid') and (
        not a.get('started') or not b.get('started') or abs(a['started'] - b['started']) <= 2)


def same_session(state: dict, mine: dict | None) -> bool:
    owner = state.get('session') or {}
    if not mine or mine['id'] != owner.get('id'):
        return False
    # A key resumes a key-claimed session only. A session claimed through a host variable needs that variable.
    return mine['via'] == owner.get('via') or owner.get('via') != 'env'


def other_session(state: dict, mine: dict | None = None) -> bool:
    """A write is refused when this process is named by a host variable and the owner was claimed under another
    identity. An owner with no identity, or a caller with none, is not refused: nothing tells them apart."""
    mine, owner = mine or session_identity(), state.get('session') or {}
    return bool(mine) and mine['via'] == 'env' and bool(owner.get('id')) and mine['id'] != owner['id']


def other_session_text(owner: str, who: str = 'this session') -> str:
    return (f'{owner} holds the workspace for another conversation, so {who} must stop writing. A subagent reports its '
            f'result to the conversation that started it. Otherwise {owner} took over the workspace: re-read '
            'docs/state/HANDOFF.md before doing anything else')


def other_host(state: dict) -> bool:
    """A write from another application window while the owner's window still runs. A host session variable, when
    set, already decides; two chats inside one application share a process and cannot be told apart here."""
    if (session_identity() or {}).get('via') == 'env':
        return False
    owner, mine = state.get('host'), host_process()
    return bool(owner and mine) and not same_host(owner, mine) and host_alive(owner) is True


def live_host_text(host: dict) -> str:
    import datetime as dt
    since = dt.datetime.fromtimestamp(host['started']).strftime('%Y-%m-%d %H:%M') if host.get('started') else 'unknown'
    return f'{host.get("name", "host")} pid {host["pid"]}, started {since}'


def require_session(root: Path, state: dict):
    """For note, reconcile and snapshot: refuse a worker, and an old window that a host variable names, without validating.
    A parallel session that holds a claim passes; its label is set for the log row. The session that released the
    workspace with its checkpoint takes it back, as on any other write."""
    if delegated():
        raise WorkspaceError('this session runs with WS_ROLE set, as a subagent or helper window, so it never writes the '
                             'workspace. Report the result to the session that started it')
    from .claims import CALLER, caller
    who = caller(state)
    if who not in (None, 'primary'):
        CALLER.set(who)
        return
    if not state.get('writer'):
        from .ops import resume_released
        resume_released(root, state)
    if other_session(state):
        raise WorkspaceError(other_session_text(state.get('writer')))
    if other_host(state):
        raise WorkspaceError(f'{state.get("writer")} owns the workspace from another window that is still running '
                             f'({live_host_text(state["host"])}), so this window must not write')


# Long operations (U6). A detached job is recorded in recovery_notes as "pid=<n> log=<path>"; the brief checks it.
JOB_RE = re.compile(r'(?<![A-Za-z0-9_])pid=(\d{1,10})(?!\d)(?:\s+started=(\S+))?(?!\s+(?:exited|done|finished)\b)')


def process_info(pid: int):
    """(alive, created) for a process. alive is None when the system refuses to say; created is a POSIX time or
    None. A recorded creation time tells a reused pid from the job, so a dead job is never reported running."""
    if pid <= 0:
        return False, None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return (None if kernel.GetLastError() == 5 else False), None
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            times = [wintypes.FILETIME() for _ in range(4)]
            created = None
            if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                created = ticks / 1e7 - 11644473600
            return code.value == 259, created
        finally:
            kernel.CloseHandle(handle)
    if not pid_alive(pid):
        return False, None
    try:
        start = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19])
        boot = next(float(l.split()[1]) for l in Path('/proc/stat').read_text().splitlines() if l.startswith('btime'))
        return True, boot + start / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return True, None


def windows_pid(pid: int) -> int:
    """Git Bash prints its own pid for "$!"; Windows knows the job by another one, readable only while it runs."""
    if os.name != 'nt' or not os.environ.get('MSYSTEM'):
        return pid
    import shutil
    import subprocess
    bash = shutil.which('bash')
    if not bash:
        return pid
    try:
        out = subprocess.run([bash, '-c', f'cat /proc/{pid}/winpid'], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else pid
    except (OSError, subprocess.SubprocessError, ValueError):
        return pid


def stamp_jobs(text: str) -> str:
    """Resolve each recorded pid to the Windows pid and add its start time, at the moment the card is written."""
    def stamp(match):
        if match[2]:
            return match[0]
        pid = windows_pid(int(match[1]))
        alive, created = process_info(pid)
        if alive is False:
            raise WorkspaceError(f'pid {match[1]} is not running. Record the pid of the job itself while it runs, '
                                 f'or write "pid={match[1]} exited" for a job that finished')
        when = dt.datetime.fromtimestamp(created).isoformat(timespec='seconds') if created else 'unknown'
        return f'pid={pid} started={when}'
    return JOB_RE.sub(stamp, text)
