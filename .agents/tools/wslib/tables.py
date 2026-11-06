"""Markdown table parsing and row edits for the state, log and closed-item files."""
from __future__ import annotations

import re
from pathlib import Path

from .core import WorkspaceError, escape_cell, read, split_cells
from .schema import CLOSED, NONE, TABLES, Table

ID_RE = re.compile(r'^([A-Z])([1-9]\d*)$')
LEGACY_CLOSED_HEADERS = ('ID', 'Status', 'Summary', 'Reason', 'Replacement', 'Evidence', 'Closed')
# Row: path of the full, untruncated row in docs/archive/closed/, or "none" for rows closed before 3.6.
CLOSED_HEADERS = LEGACY_CLOSED_HEADERS + ('Row',)
FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})')


def blocks(text: str):
    """Yield (header_index, headers, [(line_index, cells)]) for each live table."""
    lines = text.split('\n')
    fence = None
    i = 0
    while i < len(lines):
        line = lines[i]
        marker = FENCE_RE.match(line)
        if marker:
            mark = marker[1]
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1]:
                fence = None
            i += 1
            continue
        if fence or not line.lstrip().startswith('|') or i + 1 >= len(lines):
            i += 1
            continue
        delimiter = split_cells(lines[i + 1])
        if not lines[i + 1].lstrip().startswith('|') or not all(re.fullmatch(r':?-{3,}:?', c) for c in delimiter):
            i += 1
            continue
        headers = tuple(split_cells(line))
        rows = []
        j = i + 2
        while j < len(lines) and lines[j].lstrip().startswith('|'):
            rows.append((j, split_cells(lines[j])))
            j += 1
        yield i, headers, rows
        i = j


def _find(text: str, headers: tuple, label: str):
    found = [b for b in blocks(text) if set(b[1]) == set(headers)]
    if len(found) != 1:
        raise WorkspaceError(f'{label}: expected one table with columns {" | ".join(headers)}, found {len(found)}')
    return found[0]


def parse(text: str, headers: tuple, label: str, prefix: str | None = None) -> list:
    _, actual, raw = _find(text, headers, label)
    if prefix is not None and actual[0] != 'ID':
        raise WorkspaceError(f'{label}: the ID column must come first')
    result = []
    for index, cells in raw:
        if len(cells) != len(actual):
            raise WorkspaceError(f'{label}:{index + 1}: row has {len(cells)} cells, header has {len(actual)}')
        row = dict(zip(actual, cells))
        if prefix is not None:
            match = ID_RE.match(row['ID'])
            if not match or match[1] != prefix:
                raise WorkspaceError(f'{label}:{index + 1}: invalid ID "{row["ID"]}"; use {prefix}1, {prefix}2, ...')
        result.append(row)
    ids = [r['ID'] for r in result if 'ID' in r] if prefix is not None or headers[0] == 'ID' else []
    if len(ids) != len(set(ids)):
        raise WorkspaceError(f'{label}: duplicate IDs: {", ".join(sorted({i for i in ids if ids.count(i) > 1}))}')
    return result


def rows(root: Path, table: Table) -> list:
    return parse(read(root, table.file), table.headers, table.file, table.prefix)


def upgrade_closed(text: str) -> str:
    """Add the Row column to a CLOSED_ITEMS table written before 3.6, and to 7-cell rows pasted into a 3.6 table
    (a merge from an older branch). Rows are rebuilt from their cells, so escaped pipes survive."""
    legacy = [b for b in blocks(text) if tuple(b[1]) == LEGACY_CLOSED_HEADERS]
    current = [b for b in blocks(text) if tuple(b[1]) == CLOSED_HEADERS]
    if len(legacy) + len(current) != 1:
        return text
    start, _, raw = (legacy or current)[0]
    lines = text.split('\n')
    lines[start] = render_row(CLOSED_HEADERS, {h: h for h in CLOSED_HEADERS})
    lines[start + 1] = '| ' + ' | '.join('---' for _ in CLOSED_HEADERS) + ' |'
    for index, cells in raw:
        if len(cells) == len(LEGACY_CLOSED_HEADERS):
            lines[index] = render_row(CLOSED_HEADERS, {**dict(zip(LEGACY_CLOSED_HEADERS, cells)), 'Row': 'none'})
    return '\n'.join(lines)


def closed_rows(root: Path) -> list:
    return parse(upgrade_closed(read(root, CLOSED)), CLOSED_HEADERS, CLOSED)


def closed_entry(t: Table, row: dict, full: str, closed: str) -> dict:
    """The CLOSED_ITEMS row for a closed row of table t. A task's summary starts with its requirement IDs: once the
    task is closed, requirement coverage reads them from there and nowhere else."""
    from .ops import short
    cited = row.get('Requirements', NONE) if t.key == 'tasks' else NONE
    return {'ID': row['ID'], 'Status': row['Status'],
            'Summary': short(('' if cited.lower() == NONE else f'{cited}: ') + row.get(t.summary, ''), 200),
            'Reason': short(row.get('Reason') or row.get('Answer') or NONE, 160),
            'Replacement': row.get('Replacement', NONE), 'Evidence': row.get('Evidence', NONE), 'Closed': closed, 'Row': full}


def render_row(headers: tuple, row: dict) -> str:
    return '| ' + ' | '.join(escape_cell(row.get(h, NONE)) or NONE for h in headers) + ' |'


def upsert(text: str, headers: tuple, label: str, row: dict) -> str:
    """Replace the row with the same ID, or append it to the end of the table."""
    start, actual, raw = _find(text, headers, label)
    lines = text.split('\n')
    rendered = render_row(actual, row)
    for index, cells in raw:
        if cells and cells[0] == row['ID']:
            lines[index] = rendered
            return '\n'.join(lines)
    insert_at = raw[-1][0] + 1 if raw else start + 2
    lines.insert(insert_at, rendered)
    return '\n'.join(lines)


def append(text: str, headers: tuple, label: str, row: dict) -> str:
    start, actual, raw = _find(text, headers, label)
    lines = text.split('\n')
    lines.insert(raw[-1][0] + 1 if raw else start + 2, render_row(actual, row))
    return '\n'.join(lines)


def remove(text: str, headers: tuple, label: str, ids: set) -> str:
    _, _, raw = _find(text, headers, label)
    drop = {index for index, cells in raw if cells and cells[0] in ids}
    return '\n'.join(line for i, line in enumerate(text.split('\n')) if i not in drop)


def refs(value: str, prefixes: str, allow_none=True) -> list:
    value = (value or '').strip()
    if allow_none and value.lower() in (NONE, ''):
        return []
    parts = [p for p in re.split(r'[\s,;]+', value) if p]
    bad = [p for p in parts if not (ID_RE.match(p) and p[0] in prefixes)]
    if bad or not parts:
        raise WorkspaceError(f'invalid ID list "{value}"; use IDs such as {prefixes[0]}1, {prefixes[0]}2 or "none"')
    return parts


def card_ids(value: str, prefixes: str) -> list:
    """IDs in a card field such as current_task. A malformed value gives no IDs; validation reports it."""
    try:
        return refs(value, prefixes)
    except WorkspaceError:
        return []


def table_for(name: str) -> Table:
    from .schema import TABLE_ALIASES
    key = TABLE_ALIASES.get(name.lower())
    if not key:
        raise WorkspaceError(f'unknown table "{name}"; valid: {", ".join(TABLES)}')
    return TABLES[key]


def table_for_id(identifier: str) -> Table:
    from .schema import PREFIX_TABLE
    match = ID_RE.match(identifier)
    if not match or match[1] not in PREFIX_TABLE:
        raise WorkspaceError(f'unknown ID "{identifier}"; IDs start with one of {", ".join(PREFIX_TABLE)}')
    return PREFIX_TABLE[match[1]]


def next_id(root: Path, table: Table, ledger: dict) -> str:
    used = {r['ID'] for r in rows(root, table)} | {r['ID'] for r in closed_rows(root)} | set(ledger)
    numbers = [int(i[1:]) for i in used if i.startswith(table.prefix) and ID_RE.match(i)]
    return f'{table.prefix}{max(numbers, default=0) + 1}'


def field_name(table: Table, name: str) -> str:
    lookup = {h.lower(): h for h in table.headers}
    key = lookup.get(name.strip().lower())
    if not key or key == 'ID':
        raise WorkspaceError(f'unknown field "{name}" for {table.key}; valid: {", ".join(h.lower() for h in table.headers if h != "ID")}')
    return key


# Status words agents use across tables, mapped to each table's own value.
STATUS_SYNONYMS = {
    'requirements': {'open': 'active', 'confirmed': 'active', 'deleted': 'removed', 'dropped': 'removed'},
    'features': {'active': 'building', 'in progress': 'building', 'in-progress': 'building', 'doing': 'building',
                 'done': 'shipped', 'delivered': 'shipped', 'complete': 'shipped', 'deleted': 'removed'},
    'tasks': {'open': 'todo', 'active': 'doing', 'in progress': 'doing', 'in-progress': 'doing', 'complete': 'done',
              'completed': 'done', 'abandoned': 'dropped', 'cancelled': 'dropped'},
    'questions': {'closed': 'answered', 'resolved': 'answered', 'later': 'deferred', 'non-blocking': 'deferred'},
    'decisions': {'active': 'adopted', 'accepted': 'adopted'},
    'preferences': {'removed': 'retired', 'dropped': 'retired'},
}


def assignments(table: Table, items: list) -> dict:
    result = {}
    for item in items:
        name, sep, value = item.partition('=')
        if not sep:
            raise WorkspaceError(f'"{item}" is not field=value')
        key = field_name(table, name)
        if key in result:
            raise WorkspaceError(f'field "{key.lower()}" given twice')
        value = value.strip()
        if not value or '\n' in value:
            raise WorkspaceError(f'field "{key.lower()}" must be one non-empty line')
        if key == 'Status':
            value = STATUS_SYNONYMS.get(table.key, {}).get(value.lower(), value.lower())
            if value not in table.statuses:
                raise WorkspaceError(f'{table.key} status "{value}" is not valid; use one of: {", ".join(table.statuses)}')
        result[key] = redact_value(value)
    return result


def redact_value(value: str) -> str:
    """A credential in a row or card field follows the project rule: kept as written under "plain", otherwise stored
    as [REDACTED] until the user decides."""
    from .core import CREDENTIALS
    from .coverage import redact
    cleaned = redact(value)
    if cleaned != value:
        import sys
        print('NOTE: a value looked like a credential and was stored as [REDACTED]. ' +
              ('This project has no credential rule yet: ask the user how credentials are kept, then set WORKSPACE '
               '"credentials" in docs/state/ARCHITECTURE.md ("plain" keeps them as written).' if CREDENTIALS.get() == 'ask'
               else 'The project keeps credentials out of files.'), file=sys.stderr)
    return cleaned
