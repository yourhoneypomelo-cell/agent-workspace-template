"""Helpers of ws verify: the verdict line, the run to compare with, and features a verify ships."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import logs, tables, validate
from .core import WorkspaceError, read, safe_path
from .schema import NONE, TABLES


def short(text: str, limit=160) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def verdict_text(data: dict) -> str:
    summary = data['summary']
    if not summary['known']:
        if data['kind'] == 'check':
            met = len(data.get('expected') or [])
            return f'check, exit {data.get("exit_code")}' + (f', {met} expected outputs found' if met else ', no expected output')
        return data['kind']
    text = f'{summary["passed"]} passed, {summary["failed"]} failed'
    extra = summary.get('errors', 0), summary.get('skipped', 0), (data.get('surface') or {}).get('deselected', 0)
    text += ''.join(f', {n} {word}' for n, word in zip(extra, ('errors', 'skipped', 'deselected')) if n)
    return text + (f', exit {data["exit_code"]}' if data.get('exit_code') not in (0, None) else '')


def previous_evidence(root: Path, ids: list, command: list, skip: str | None = None):
    """The accepted run of the same command for these tasks that ran the most tests. Comparing with the largest
    run, not the last, keeps a shrinking surface visible after the first smaller run (U27)."""
    best = None
    folder = safe_path(root, 'docs/archive/checks')
    for path in folder.glob('*.json') if folder.is_dir() else []:
        if skip and path.name == skip.rsplit('/', 1)[-1]:
            continue  # the run being attached is not its own baseline
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if data.get('accepted') and data.get('command') == command and set(ids) & set(data.get('for_tasks') or []):
            if not best or data['summary'].get('total', 0) > best['summary'].get('total', 0):
                best = data
    return best


def ship_features(root: Path, finished: set, task_rows: dict) -> dict:
    """Planned or building features whose last open task this verify finished become shipped (U10). An
    unverified feature waits for the agent, who confirms the behavior first."""
    t = TABLES['features']
    text = read(root, t.file)
    log = read(root, logs.path_of(t.log))
    shipped = []
    done = {rid for rid, status in validate.ledger(validate.gather(root)).items() if status == 'done'}
    for row in tables.parse(text, t.headers, t.file, t.prefix):
        try:
            tasks = tables.refs(row.get('Tasks', NONE), 'T')
        except WorkspaceError:
            continue  # validate reports the malformed cell; verify still records its result
        if row['Status'] not in ('planned', 'building') or not tasks or not set(tasks) & finished:
            continue
        if all(rid in finished or rid in done for rid in tasks):
            text = tables.upsert(text, t.headers, t.file, {**row, 'Status': 'shipped'})
            log = logs.add(log, t.log, {'ID': row['ID'], 'Event': f'{row["Status"]} -> shipped',
                                        'Detail': short(f'tasks {", ".join(tasks)} verified'), 'Source': 'ws verify'})
            shipped.append(row['ID'])
    return {t.file: text, logs.path_of(t.log): log} if shipped else {}


COUNT_RE = re.compile(r'(?<![\w.])(\d{1,6})\s*/\s*(\d{1,6})(?![\w.])')


def unverified_counts(root: Path, text: str, evidence_rels: list) -> list:
    """"n/m" figures in free text that no cited evidence file reports. Session summaries restated counts that the
    evidence did not hold (one said 18/18 where the evidence had 14 PASS lines)."""
    known = set()
    for rel in evidence_rels:
        try:
            data = json.loads(read(root, rel))
        except (OSError, ValueError, WorkspaceError):
            continue
        summary = data.get('summary') or {}
        if summary.get('known'):
            known |= {(summary['passed'], summary['total']), (summary['passed'], summary['passed'] + summary['failed'])}
        output = data.get('output', '')
        known |= {(int(a), int(b)) for a, b in COUNT_RE.findall(output)}
    return [f'{a}/{b}' for a, b in COUNT_RE.findall(text) if (int(a), int(b)) not in known]
