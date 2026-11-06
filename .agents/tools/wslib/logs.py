"""Append-only history tables with hash-indexed archives."""
from __future__ import annotations

from pathlib import Path

from . import tables
from .core import WorkspaceError, atomic_write, read, safe_path, sha, today
from .schema import BUDGETS, CLOSED, LOG_DIR, LOG_HEADERS, OPTIONAL_LOGS

ARCHIVE_HEADERS = ('Path', 'Rows', 'SHA-256')
KEEP_AFTER_ARCHIVE = 40


def path_of(name: str) -> str:
    if name == 'CLOSED_ITEMS':
        return CLOSED
    if name not in LOG_HEADERS:
        raise WorkspaceError(f'unknown log "{name}"; valid: {", ".join([*LOG_HEADERS, "CLOSED_ITEMS"])}')
    return f'{LOG_DIR}/{name}.md'


def headers_of(name: str) -> tuple:
    return tables.CLOSED_HEADERS if name == 'CLOSED_ITEMS' else LOG_HEADERS[name]


def _missing_optional(root: Path, name: str) -> bool:
    return name in OPTIONAL_LOGS and not (root / path_of(name)).is_file()


def _text(root: Path, name: str) -> str:
    if _missing_optional(root, name):
        from .defaults import log
        return log(name)
    return read(root, path_of(name))


def live_rows(root: Path, name: str, text: str | None = None) -> list:
    rel = path_of(name)
    return tables.parse(text if text is not None else _text(root, name), headers_of(name), rel)


def archives(root: Path, name: str, text: str | None = None) -> list:
    rel = path_of(name)
    return tables.parse(text if text is not None else _text(root, name), ARCHIVE_HEADERS, rel)


def all_rows(root: Path, name: str) -> list:
    """Archived rows first, then live rows. Archive hashes are verified."""
    result = []
    for entry in archives(root, name):
        path = safe_path(root, entry['Path'])
        if not path.is_file():
            raise WorkspaceError(f'{path_of(name)}: archive missing: {entry["Path"]}')
        raw = path.read_bytes()
        if sha(raw) != entry['SHA-256']:
            raise WorkspaceError(f'{path_of(name)}: archive changed after it was sealed: {entry["Path"]}')
        result += tables.parse(raw.decode('utf-8'), headers_of(name), entry['Path'])
    return result + live_rows(root, name)


def add(text: str, name: str, row: dict) -> str:
    if 'Date' in headers_of(name) and not row.get('Date'):
        row = {**row, 'Date': today()}
    return tables.append(text, headers_of(name), path_of(name), row)


def append(root: Path, name: str, row: dict):
    rel = path_of(name)
    atomic_write(safe_path(root, rel), add(_text(root, name), name, row))


def mentions(rows: list, identifier: str) -> bool:
    return any(r.get('ID') == identifier for r in rows)


def archive_if_large(root: Path, name: str, force=False) -> str | None:
    """Move older rows to docs/archive/logs/ when the live log exceeds its budget."""
    rel = path_of(name)
    if _missing_optional(root, name):
        return None
    text = read(root, rel)
    current = live_rows(root, name, text)
    if not force and len(text.encode('utf-8')) <= BUDGETS['log']:
        return None
    if len(current) <= KEEP_AFTER_ARCHIVE:
        return None
    moved = current[:-KEEP_AFTER_ARCHIVE]
    heading = f'# {name} archive\n\nRows moved from `{rel}` on {today()}. Do not edit; the log index holds this file\'s hash.\n\n'
    body = heading + '| ' + ' | '.join(headers_of(name)) + ' |\n| ' + ' | '.join('---' for _ in headers_of(name)) + ' |\n'
    body += '\n'.join(tables.render_row(headers_of(name), r) for r in moved) + '\n'
    archive_rel = f'docs/archive/logs/{name.lower()}-{today()}-{len(archives(root, name, text)) + 1:03d}.md'
    atomic_write(safe_path(root, archive_rel), body)
    _, _, raw = tables._find(text, headers_of(name), rel)
    drop = {index for index, _ in raw[:len(moved)]}
    remaining = '\n'.join(line for i, line in enumerate(text.split('\n')) if i not in drop)
    remaining = tables.append(remaining, ARCHIVE_HEADERS, rel,
                              {'Path': archive_rel, 'Rows': str(len(moved)), 'SHA-256': sha(body.encode('utf-8'))})
    atomic_write(safe_path(root, rel), remaining)
    return archive_rel
