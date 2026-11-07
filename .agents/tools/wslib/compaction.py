"""ws compact: closed rows move to CLOSED_ITEMS.md, each with its full text archived, and large logs roll over."""
from __future__ import annotations

import json
from pathlib import Path

from . import evidence, logs, tables
from .core import card, checkpoint_of, read, safe_path, state_of, today, write
from .locks import lock
from .ops import bump, guarded, require_owner, short
from .schema import CLOSED, LOG_NAMES, NONE, TABLES


def closed_row_path(rid: str) -> str:
    return f'docs/archive/closed/{rid}.md'


def closed_row_text(t, row: dict) -> str:
    """The full row, every column and untruncated, in the table form of its state file."""
    return (f'# {row["ID"]} ({t.key}, {row["Status"]})\n\nMoved from `{t.file}` by `ws compact` on {today()}. '
            'Do not edit; the ID stays retired.\n\n| ' + ' | '.join(t.headers) + ' |\n| ' +
            ' | '.join('---' for _ in t.headers) + ' |\n' + tables.render_row(t.headers, row) + '\n')


def compact(root: Path, dry_run: bool, prune: bool, writer=None, rev=None) -> dict:
    with lock(root):
        state = state_of(root)
        if not dry_run:
            require_owner(root, state, writer, rev)
            from .permits import permit
            permit(state, 'workspace', what='ws compact')
        fields = card(root)
        keep = set(tables.card_ids(fields.get('current_task', NONE), 'T')) | set(tables.card_ids(fields.get('current_feature', NONE), 'F'))
        moved = []
        changes = {}
        archived_rows = {}
        closed_text = tables.upgrade_closed(read(root, CLOSED))
        # A compact that died after writing CLOSED_ITEMS left these rows in both places; finish it.
        already = {r['ID'] for r in tables.parse(closed_text, tables.CLOSED_HEADERS, CLOSED)}
        for t in TABLES.values():
            text = changes.get(t.file) or read(root, t.file)
            closed_rows = [r for r in tables.parse(text, t.headers, t.file, t.prefix) if r['Status'] in t.closed and r['ID'] not in keep]
            if not closed_rows:
                continue
            for row in closed_rows:
                full = closed_row_path(row['ID'])
                archived_rows[full] = closed_row_text(t, row)
                if row['ID'] not in already:
                    closed_text = tables.append(closed_text, tables.CLOSED_HEADERS, CLOSED,
                                                tables.closed_entry(t, row, full, today()))
                moved.append(row['ID'])
            changes[t.file] = tables.remove(text, t.headers, t.file, {r['ID'] for r in closed_rows})
        if moved:
            # Archive first: guarded() writes in dict order, so CLOSED_ITEMS lands before the state files.
            changes = {CLOSED: closed_text, **changes}
        referenced = set()
        for t in TABLES.values():
            for row in tables.parse(changes.get(t.file) or read(root, t.file), t.headers, t.file, t.prefix):
                referenced.update(evidence.evidence_paths(row.get('Evidence', '')))
        for row in tables.parse(closed_text, tables.CLOSED_HEADERS, CLOSED):
            referenced.update(evidence.evidence_paths(row.get('Evidence', '')))
        cp = checkpoint_of(root, state)
        referenced.update((cp or {}).get('evidence', {}))
        checks = safe_path(root, 'docs/archive/checks')
        orphans = sorted(p.relative_to(root).as_posix() for p in checks.glob('*.json')
                         if p.relative_to(root).as_posix() not in referenced) if checks.is_dir() else []
        report = {'moved_to_closed': moved, 'orphan_evidence': orphans, 'archived_logs': [], 'dry_run': dry_run}
        if dry_run:
            return report
        # Full rows go to docs/archive/closed/ before any state file changes. A crash leaves every row in a
        # state file or in the archive, and running compact again finishes the move.
        for rel, body in archived_rows.items():
            write(root, rel, body)
        if changes:
            guarded(root, changes)
        for name in LOG_NAMES:
            archived = logs.archive_if_large(root, name, force=False)
            if archived:
                report['archived_logs'].append(archived)
        if prune:
            for rel in orphans:
                proof = json.loads(read(root, rel))
                if proof.get('report'):
                    safe_path(root, proof['report']['path']).unlink(missing_ok=True)
                safe_path(root, rel).unlink()
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'compact', 'Detail': short(
            f'{len(moved)} closed rows moved to CLOSED_ITEMS.md; {len(orphans)} unreferenced evidence files' +
            (' deleted' if prune else ' kept'), 300)})
        bump(root, state)
        report['revision'] = state['revision']
    return report
