"""Row, card and goal edits: ws add, ws set, ws card and ws goal."""
from __future__ import annotations

import re
from pathlib import Path

from . import coverage, logs, tables, validate
from .coverage import redact
from .core import (
    WorkspaceError, card, card_text, lock, now, read, safe_path, state_of, today, with_goal, goal_of,
)
from .ops import bump, emit, guarded, ledger, previous_row_path, require_owner, short
from .retired import RETIRE_AS, retired_match, retired_nearest
from .schema import CARD_FIELDS, CLOSED, HANDOFF, NEEDS_REASON, NONE, REQUIREMENTS


# Rows and card
def split_source(t, sets: list, source: str | None) -> tuple:
    """--source and --set source=... mean the same on every table.

    On a table with a Source column (decisions, preferences) the column takes --set source=, or --source when that is
    the only one given. The log row takes --source, or the column value. On other tables either form goes to the log."""
    rest, given = [], None
    for item in sets:
        name, sep, value = item.partition('=')
        if sep and name.strip().lower() == 'source':
            given = value.strip() or given
        else:
            rest.append(item)
    if 'Source' in t.headers and (given or source):
        rest.append(f'source={given or source}')
    return rest, source or given


STOP_WORDS = frozenset('the and for with from that this when then into must should can will user users'.split())


def _words(text: str) -> set:
    lowered = text.lower()
    words = {w for w in re.findall(r'[a-z0-9]{3,}', lowered) if w not in STOP_WORDS}
    han = re.sub(r'[^\u4e00-\u9fff]', '', lowered)
    return words | {han[i:i + 2] for i in range(len(han) - 1)}


def similar_rows(row: dict, rows: list, threshold=0.6) -> list:
    """Active requirements whose text overlaps the new one. A hint only: a new row may refine an old one."""
    mine = _words(row['Requirement'])
    if len(mine) < 4:
        return []
    found = []
    for other in rows:
        if other['Status'] != 'active':
            continue
        theirs = _words(other['Requirement'])
        score = len(mine & theirs) / len(mine | theirs) if theirs else 0
        if score >= threshold:
            found.append((other['ID'], score))
    return sorted(found, key=lambda item: -item[1])[:2]


def add(root: Path, table_name: str, sets: list, source: str | None, writer=None, rev=None):
    t = tables.table_for(table_name)
    sets, source = split_source(t, sets, source)
    fields = tables.assignments(t, sets)
    with lock(root):
        state = state_of(root)
        require_owner(root, state, writer, rev)
        row = {h: '' for h in t.headers}
        row.update(t.defaults)
        row['Status'] = t.statuses[0]
        row.update(fields)
        missing = [h.lower() for h in t.required if not row.get(h, '').strip() or row[h].lower() == NONE]
        if missing:
            raise WorkspaceError(f'{t.key}: missing {", ".join(missing)}. Pass --set {missing[0]}=...')
        row['ID'] = tables.next_id(root, t, ledger(root))
        changes = {t.file: tables.upsert(read(root, t.file), t.headers, t.file, row)}
        if t.log:
            rel = logs.path_of(t.log)
            changes[rel] = logs.add(read(root, rel), t.log, {
                'ID': row['ID'], 'Event': 'added' if row['Status'] == t.statuses[0] else f'added as {row["Status"]}',
                'Detail': short(row[t.summary]), 'Source': redact(source) if source else 'assistant'})
        similar = similar_rows(row, tables.rows(root, t)) if t.key == 'requirements' else []
        revived = retired_match(root, t, row[t.summary])
        nearest = retired_nearest(root, t, row[t.summary], {rid for rid, _, _ in revived})
        guarded(root, changes)
        bump(root, state)
    emit({'id': row['ID'], 'revision': state['revision']})
    from .lint import cell_notes
    for message in cell_notes(fields):
        print(f'NOTE: {row["ID"]} {message}')
    for rid, status, reason in revived:
        print(f'WARNING: {row["ID"]} repeats {rid}, which is {status} ({short(reason, 120)}). Unless the user asked for it '
              f'again in this conversation, set {row["ID"]} to {RETIRE_AS[t.key]} with that reason.')
    if nearest:
        print(f'Closest retired {t.key}; if {row["ID"]} means the same as one of them, ask the user before building it:')
        for _, rid, status, summary, reason in nearest:
            print(f'  {rid} {status}: {short(summary, 100)} ({short(reason, 80)})')
    for other, score in similar:
        print(f'{row["ID"]} is close to {other} ({score:.2f}). If it refines {other}, change {other} with "ws set {other}"; '
              f'if it replaces it, set {other} to replaced with a reason.')


DETAIL_DIRS = ('docs/specs/', 'docs/reports/')


def set_row(root: Path, identifier: str, sets: list, source: str | None, writer=None, rev=None, move_detail=None):
    t = tables.table_for_id(identifier)
    sets, source = split_source(t, sets, source)
    source = redact(source) if source else source
    # "context+=text" appends to a cell instead of replacing it.
    plain, appended = [], set()
    for item in sets:
        name, sep, value = item.partition('=')
        if sep and name.endswith('+'):
            appended.add(tables.field_name(t, name[:-1]))
            item = name[:-1] + '=' + value
        plain.append(item)
    fields = tables.assignments(t, plain)
    with lock(root):
        state = state_of(root)
        require_owner(root, state, writer, rev)
        from . import claims
        if t.key == 'tasks':
            claims.guard_tasks(state, [identifier])
        elif t.key in ('requirements', 'features') and fields.get('Status') in t.retired:
            # Retiring a row that another session's claimed task builds on would pull the ground from under it.
            cited = [rid for rid, row in claims.task_rows(root).items()
                     if re.search(rf'\b{re.escape(identifier)}\b', row.get('Requirements', '') + ' ' + row.get('Scope', ''))]
            claims.guard_tasks(state, cited, f'retire {identifier}, which a claimed task cites; the task')
        current = {r['ID']: r for r in tables.rows(root, t)}
        if identifier not in current:
            closed = {r['ID'] for r in tables.closed_rows(root)}
            if identifier in closed:
                raise WorkspaceError(f'{identifier} is closed and lives in {CLOSED}. Add a new row instead of reopening it')
            raise WorkspaceError(f'{identifier} does not exist; create rows with "ws.py add {t.key}"')
        old = current[identifier]
        for key in appended:
            if old.get(key, NONE).lower() != NONE:
                fields[key] = f'{old[key]}; {fields[key]}'
        row = {**old, **fields}
        overwritten = [(k, old[k]) for k in fields if k not in appended and k not in ('Status',)
                       and old.get(k, NONE).lower() not in (NONE, '') and old[k] != fields[k]]
        if row['Status'] in NEEDS_REASON[t.key] and 'Reason' in t.headers and row.get('Reason', NONE).lower() == NONE:
            raise WorkspaceError(f'{identifier}: give a reason when setting status {row["Status"]}: --set reason=...')
        if t.key == 'questions' and row['Status'] == 'deferred' and row.get('Answer', NONE).lower() == NONE:
            raise WorkspaceError(f'{identifier}: a deferred question needs the default the work proceeds on, so a new session '
                                 'knows what was assumed: --set "answer=default: <what is done until the user decides>"')
        if move_detail:
            # Moving detail out of a row is one step: the full current row goes to its new home, and the shortened
            # row must point there. Nothing is lost, and the reader of the row finds the rest.
            target = move_detail.replace('\\', '/')
            target = target[2:] if target.startswith('./') else target
            if not target.startswith(DETAIL_DIRS) or not target.endswith('.md'):
                raise WorkspaceError('--move-detail takes a .md path under docs/specs/ or docs/reports/, such as '
                                     'docs/reports/gateway-audit.md')
            if not any(target in v for v in row.values()):
                raise WorkspaceError(f'the shortened {identifier} row must name {target}, so a reader finds the detail; '
                                     f'add it to a cell, for example --set "decision=<conclusion>. Detail: {target}"')
            path = safe_path(root, target)
            heading = f'# {identifier} detail\n' if not path.is_file() else read(root, target).rstrip('\n') + '\n'
            moved_text = heading + f'\n## {identifier} as recorded before {today()}\n\n' + '\n'.join(
                f'- {k}: {v}' for k, v in old.items() if k != 'ID') + '\n'
        changes = {t.file: tables.upsert(read(root, t.file), t.headers, t.file, row)}
        if move_detail:
            changes[target] = moved_text
        # The full previous row is kept whenever a long cell is replaced, so shortening a row never loses a fact.
        kept = previous_row_path(identifier) if any(len(value) > 200 for _, value in overwritten) else None
        if kept:
            history = read(root, kept) if safe_path(root, kept).is_file() else f'# Earlier versions of {identifier}\n'
            changes[kept] = history.rstrip('\n') + f'\n\n## Replaced on {now()}\n\n' + '\n'.join(
                f'- {k}: {v}' for k, v in old.items() if k != 'ID') + '\n'
        if t.log:
            rel = logs.path_of(t.log)
            text = read(root, rel)
            if row['Status'] != old['Status']:
                detail = row.get('Reason') if row.get('Reason', NONE).lower() != NONE else row[t.summary]
                if t.key == 'questions' and row.get('Answer', NONE).lower() != NONE:
                    detail = 'answer: ' + row['Answer']
                text = logs.add(text, t.log, {'ID': identifier, 'Event': f'{old["Status"]} -> {row["Status"]}',
                                              'Detail': short(detail), 'Source': source or 'assistant'})
            if row[t.summary] != old[t.summary]:
                text = logs.add(text, t.log, {'ID': identifier, 'Event': 'edited', 'Detail': short('was: ' + old[t.summary]),
                                              'Source': source or 'assistant'})
            if text == read(root, rel) and source and t.key == 'requirements':  # the user confirmed the row
                text = logs.add(text, t.log, {'ID': identifier, 'Event': 'confirmed', 'Detail': short(row[t.summary]),
                                              'Source': source})
            changes[rel] = text
        if t.key == 'tasks':
            edits = task_edits(old, row)
            if edits:
                rel = logs.path_of('CHANGE_LOG')
                text = read(root, rel)
                for event, detail in edits:
                    text = logs.add(text, 'CHANGE_LOG', {'ID': identifier, 'Event': event, 'Detail': short(detail),
                                                         'Source': source or 'assistant'})
                changes[rel] = text
                if any(event.endswith(' edited') for event, _ in edits):
                    rel = logs.path_of('MAINTENANCE_LOG')
                    changes[rel] = logs.add(changes.get(rel) or read(root, rel), 'MAINTENANCE_LOG',
                                            {'Event': 'task edited', 'Detail': f'{identifier}: definition changed'})
        guarded(root, changes)
        bump(root, state)
        affected = []
        if t.key == 'requirements' and (row['Status'] != old['Status'] or row[t.summary] != old[t.summary]):
            affected = coverage.dependents(validate.gather(root)['live'], identifier)
    emit({'id': identifier, 'revision': state['revision']})
    from .lint import cell_notes
    for message in cell_notes({k: v for k, v in row.items() if k in fields}):
        print(f'NOTE: {identifier} {message}')
    for key, value in overwritten:
        print(f'{identifier} {key.lower()} replaced; it was: {short(value, 300)}. Use --set "{key.lower()}+=..." to append instead')
    if move_detail:
        print(f'The full previous {identifier} row is in {target}, and the row now points there.')
    elif kept:
        print(f'The full previous {identifier} row is kept in {kept}. If the detail you removed matters, link that file '
              'or a spec from the row.')
    if affected:
        what = 'was retired' if row['Status'] in t.retired else 'changed'
        print(f'{identifier} {what}. Check these open rows that cite it: {", ".join(affected)}. '
              'Update their scope or acceptance, point them at the new requirement, or drop them with a reason.')


TASK_DEFINITION = ('Requirements', 'Scope', 'Action', 'Acceptance', 'Depends')


def task_edits(old: dict, new: dict) -> list:
    """(event, detail) for a task edit worth a log row: a changed definition field, or a move to blocked or
    dropped. An acceptance switched to an easier command must leave a trace (U43)."""
    found = [(f'{field.lower()} edited', f'was: {old[field]}') for field in TASK_DEFINITION if new.get(field) != old.get(field)]
    if new['Status'] != old['Status'] and new['Status'] in ('blocked', 'dropped'):
        found.append((f'{old["Status"]} -> {new["Status"]}', new.get('Reason', NONE)))
    return found


def card_fields(sets: list) -> dict:
    result = {}
    for item in sets:
        name, sep, value = item.partition('=')
        key = name.strip().lower().replace('-', '_')
        if not sep or key not in CARD_FIELDS:
            raise WorkspaceError(f'unknown card field "{name}"; valid: {", ".join(CARD_FIELDS)}')
        if not value.strip() or '\n' in value:
            raise WorkspaceError(f'card field "{key}" must be one non-empty line')
        result[key] = tables.redact_value(value.strip())
    if 'recovery_notes' in result:
        from .core import stamp_jobs
        result['recovery_notes'] = stamp_jobs(result['recovery_notes'])
    return result


KEPT_CARD = ('risks', 'recovery_notes', 'next_acceptance', 'baseline')


def replaced_card_values(old: dict, new: dict) -> list:
    """Card fields that hold failed attempts and risks. Their old text has no other copy, so it is logged."""
    return [(key, old[key]) for key in KEPT_CARD
            if key in new and old.get(key, NONE).lower() not in (NONE, '', new[key].lower()) and old[key] != new[key]]


def log_replaced(root: Path, replaced: list):
    for key, value in replaced:
        logs.append(root, 'MAINTENANCE_LOG', {'Event': f'card {key} replaced', 'Detail': short('was: ' + value, 400)})


def set_card(root: Path, sets: list, writer=None, rev=None):
    fields = card_fields(sets)
    if not fields:
        raise WorkspaceError('pass at least one --set field=value')
    with lock(root):
        state = state_of(root)
        require_owner(root, state, writer, rev)
        from .claims import CALLER
        if CALLER.get():
            raise WorkspaceError('the card belongs to the main session. A parallel session records its stop point and next '
                                 'step with "ws checkpoint --keep --stop ... --next ..."')
        replaced = replaced_card_values(card(root), fields)
        guarded(root, {HANDOFF: card_text(read(root, HANDOFF), fields)})
        log_replaced(root, replaced)
        bump(root, state)
    emit({'revision': state['revision']})


def set_goal(root: Path, text: str, source: str | None, writer=None, rev=None):
    """Change the goal when the user widens or narrows it. The old text goes to REQUIREMENT_LOG."""
    text = redact(' '.join(text.split()))
    if not text:
        raise WorkspaceError('ws goal needs the new goal as one sentence')
    with lock(root):
        state = state_of(root)
        require_owner(root, state, writer, rev)
        from .claims import require_alone
        require_alone(state, 'ws goal')
        old = goal_of(read(root, REQUIREMENTS))
        if old == text:
            raise WorkspaceError('the goal already reads that way')
        log = logs.add(read(root, logs.path_of('REQUIREMENT_LOG')), 'REQUIREMENT_LOG',
                       {'ID': 'goal', 'Event': 'edited', 'Detail': short('was: ' + old), 'Source': redact(source) if source else 'assistant'})
        guarded(root, {REQUIREMENTS: with_goal(read(root, REQUIREMENTS), text), logs.path_of('REQUIREMENT_LOG'): log})
        bump(root, state)
    emit({'goal': text, 'revision': state['revision']})
