"""DeepSeek Harness sessions (U17). The store is zstd-compressed, one frame per append. The decoder is the standard
library on Python 3.14, the backports.zstd package, or a Python 3.14 found on this machine. Node is never used:
looked up by name it can run a node.exe from the current folder."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

STORE = Path(os.environ.get('DSH_HOME') or Path.home() / '.dsh') / 'sessions'
MAX_STORE = 50 * 1024 * 1024  # compressed bytes of one session file
MAX_TEXT = 200 * 1024 * 1024  # decompressed characters; a 96 KB file can expand to 1 GB
# Run by a Python 3.14 when this one has no zstd: frame by frame, exit code 3 once the output passes the limit in argv[1].
HELPER = ('import sys\nfrom compression import zstd\nlimit, size, data = int(sys.argv[1]), 0, sys.stdin.buffer.read()\n'
          'while data:\n    part = zstd.ZstdDecompressor()\n    while not part.eof:\n'
          '        chunk = part.decompress(data, max_length=1 << 20)\n        data = b""\n        size += len(chunk)\n'
          '        if size > limit:\n            sys.exit(3)\n        sys.stdout.buffer.write(chunk)\n'
          '        if not chunk and part.needs_input:\n            break\n'
          '    data = part.unused_data if part.eof else b""\n')


def project_key(folder: Path) -> str:
    """The store folder of a project: the port of projectKey in DSH format.ts, matched on 9 of 9 local folders."""
    text = str(folder.resolve())
    out = []
    raw = text.encode('utf-16-le')
    units = [int.from_bytes(raw[i:i + 2], 'little') for i in range(0, len(raw), 2)]
    for unit in units:
        char = chr(unit) if unit < 0xD800 or unit > 0xDFFF else None
        if char and char in '/\\:':
            if not out or out[-1] != '-':
                out.append('-')
        elif char and re.fullmatch(r'[A-Za-z0-9._-]', char):
            out.append(char)
        else:
            out.append(f'~{unit:04X}')
    key = ''.join(out).lstrip('-')[:251]
    return f'--{key}--'


def _launcher() -> str | None:
    """The Windows py launcher by absolute path. Looked up by name, Windows would run a py.exe in the project."""
    for base in (os.environ.get('WINDIR'), os.environ.get('LOCALAPPDATA') and Path(os.environ['LOCALAPPDATA']) / 'Programs/Python/Launcher'):
        if base and (Path(base) / 'py.exe').is_file():
            return str(Path(base) / 'py.exe')
    return None


def _python314() -> list:
    """Interpreters of version 3.14 or newer that carry compression.zstd, without running anything unknown."""
    found = []
    launcher = _launcher()
    for line in (_run([launcher, '-0p']) if launcher else '').splitlines():
        match = re.search(r'(\d+)\.(\d+)\S*\s+\*?\s*(\S.*python\.exe)\s*$', line, re.I)
        if match and (int(match[1]), int(match[2])) >= (3, 14):
            found.append(match[3].strip())
    local = Path.home() / '.local/bin/python3.14.exe'
    if local.is_file():
        found.append(str(local))
    return [p for p in found if Path(p).is_absolute() and Path(p).is_file()]


def _run(argv: list, data: bytes | None = None) -> str:
    try:
        out = subprocess.run(argv, input=data, capture_output=True, timeout=120)
        return out.stdout.decode('utf-8', 'replace') if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _bounded(zstd, raw: bytes) -> str:
    """Decompress every frame, refusing output over MAX_TEXT before it is held in memory."""
    out, size, data = [], 0, raw
    while data:
        part = zstd.ZstdDecompressor()
        while not part.eof:
            chunk = part.decompress(data, max_length=1 << 20)
            data = b''
            size += len(chunk)
            if size > MAX_TEXT:
                raise ValueError('session file expands past the size limit')
            out.append(chunk)
            if not chunk and part.needs_input:
                break
        data = part.unused_data if part.eof else b''
    return b''.join(out).decode('utf-8', 'replace')


def decoder(in_process: bool = False):
    """A function that turns the bytes of a store file into text, or None with the reason."""
    try:
        from compression import zstd  # Python 3.14 and newer
        return lambda raw: _bounded(zstd, raw), None
    except ImportError:
        pass
    try:
        from backports import zstd
        return lambda raw: _bounded(zstd, raw), None
    except ImportError:
        pass
    if in_process:  # ws start: an external interpreter per file is too slow; ws chats import dsh uses one
        return None, 'no zstd decoder in this Python; run "ws chats import dsh"'
    for exe in _python314():
        try:
            usable = subprocess.run([exe, '-c', 'from compression import zstd'], capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            usable = False
        if usable:
            return lambda raw, exe=exe: _run([exe, '-c', HELPER, str(MAX_TEXT)], raw), None
    return None, ('DeepSeek Harness sessions are zstd-compressed. Install Python 3.14 or newer, or run '
                  '"pip install backports.zstd", then run "ws chats import dsh" again')


def sessions(root: Path) -> list:
    """(session id, store file) for the root sessions of this project; subagent sessions are skipped."""
    folder = STORE / project_key(root)
    return [(p.parent.name, p) for p in sorted(folder.glob('*/session.v*.jsonl.zstd'))] if folder.is_dir() else []


def records(text: str) -> list:
    """Visible records in order, after edits and rewinds were applied, or [] for a subagent session."""
    out = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'session':
            if record.get('delegationDepth') or record.get('parentSession'):
                return []
            continue
        op = record.get('surfaceOp')
        source = ((record.get('data') or {}).get('source') or {}).get('kind') if isinstance(record.get('data'), dict) else None
        if isinstance(op, dict) and op.get('op') == 'replace' and source != 'compact-checkpoint' \
                and record.get('type') in ('user/message', 'assistant/message'):
            start, end = op.get('startSeq'), op.get('endSeq')
            out = [r for r in out if not (isinstance(r.get('seq'), int) and start <= r['seq'] <= end)]
        out.append(record)
    return out


def messages(text: str) -> list:
    """(role, text, note) per typed user message and assistant reply. Injected user records and reasoning are skipped."""
    from .capture import _time
    result = []
    for record in records(text):
        data = record.get('data') if isinstance(record.get('data'), dict) else {}
        if record.get('type') == 'user/message' and (data.get('source') or {}).get('kind') == 'user':
            role, parts = 'user', data.get('content') or []
        elif record.get('type') == 'assistant/message':
            role, parts = 'assistant', (data.get('message') or {}).get('content') or []
        else:
            continue
        body = '\n'.join(p.get('text', '') for p in parts if isinstance(p, dict) and p.get('type') == 'text').strip()
        if body:
            result.append((role, body, _time({'timestamp': record.get('time')})))
    return result


def import_sessions(root: Path, automatic: bool = False, since: float | None = None) -> dict:
    """Write docs/chats/dsh/<session>.md for each root session of this project. Unchanged files are rewritten
    with the same text, so a second import changes nothing. With since, older sessions stay out."""
    from .capture import _index, rewrite
    from .locks import lock
    found = [(sid, path) for sid, path in sessions(root) if since is None or path.stat().st_mtime >= since]
    if not found:
        return {'host': 'dsh', 'sessions': 0, 'messages': 0}
    decode, reason = decoder(in_process=automatic)
    if not decode:
        return {'host': 'dsh', 'sessions': 0, 'messages': 0, 'skipped': reason}
    written, total = 0, 0
    for sid, path in found:
        name = re.sub(r'[^A-Za-z0-9_-]', '-', sid)[:64]
        target = root / f'docs/chats/dsh/{name}.md'
        if path.stat().st_size > MAX_STORE or target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
            continue
        try:
            found_messages = messages(decode(path.read_bytes()))
        except Exception:  # one unreadable session must not stop the rest
            continue
        if not found_messages:
            continue
        rel = f'docs/chats/dsh/{name}.md'
        with lock(root):
            rewrite(root, rel, 'dsh', name, found_messages, path.name)
            _index(root, 'dsh', name, len(found_messages), rel, 'none')
        written, total = written + 1, total + len(found_messages)
    return {'host': 'dsh', 'sessions': written, 'messages': total}
