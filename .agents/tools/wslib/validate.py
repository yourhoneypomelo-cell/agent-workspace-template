"""Structural and semantic checks. Each error names the file, the cause and the fix."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import evidence, logs, tables
from .core import (
    WorkspaceError, card, checkpoint_of, config, describe_drift, difference, exists, fingerprint, goal, lock_busy, read,
    rewatch, safe_path, sha, state_of,
)
from .schema import (
    ADAPTERS, BUDGETS, CARD_FIELDS, CLOSED, NEEDS_REASON, GUIDE_DIR, LOG_DIR, LOG_NAMES, NONE, OPTIONAL_CARD_FIELDS,
    PLACEHOLDERS, PREFIX_TABLE, PROTOCOL_MARKER, REQUIRED, SCHEMA, SKILLS, SPEC_DIR, STATE_DIR, STATE_NAMES,
    STATIC_FILES, T0, TABLES, RUNTIME_FILES, MAINTAINER_FILES,
)

SPEC_RE = re.compile(r'docs/specs/[a-z0-9]+(?:-[a-z0-9]+)*/requirements\.md')


def _entries(root: Path, rel: str) -> set:
    path = root / rel
    return {p.name for p in path.iterdir() if p.is_file() and p.suffix == '.md'} if path.is_dir() else set()


def _pointer_size(rel: str, text: str) -> int:
    """Bytes of an adapter without the hooks its host keeps in the same settings file."""
    if rel.endswith('.json'):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return len(json.dumps({k: v for k, v in data.items() if k != 'hooks'}, ensure_ascii=False).encode('utf-8'))
    return len(text.encode('utf-8'))


def structure(root: Path, strict=False, adapters=False) -> list:
    errors = [f'missing file: {rel}' for rel in REQUIRED if not (root / rel).is_file()]
    if errors:
        return errors
    for directory, names in ((STATE_DIR, STATE_NAMES), (LOG_DIR, (*LOG_NAMES, 'CLOSED_ITEMS'))):
        extra = _entries(root, directory) - {n + '.md' for n in names}
        if extra:
            errors.append(f'{directory}: unexpected files {", ".join(sorted(extra))}; these folders hold a fixed set, put notes in docs/specs/ instead')
    agents = read(root, 'AGENTS.md')
    if agents.count(PROTOCOL_MARKER) != 1:
        errors.append(f'AGENTS.md must contain the line {PROTOCOL_MARKER} exactly once')
    for rel in T0[1:]:
        if rel not in agents:
            errors.append(f'AGENTS.md must name the T0 file {rel}')
    try:
        cfg = config(root)
    except WorkspaceError as error:
        return errors + [str(error)]
    pending = [] if adapters else cfg.get('pending_adapters', [])
    for rel in ADAPTERS:
        if rel in pending:
            continue
        text = read(root, rel)
        if 'AGENTS.md' not in text or _pointer_size(rel, text) > 2500:
            errors.append(f'{rel} must stay a short pointer to AGENTS.md')
    if 'CLAUDE.md' not in pending and not re.search(r'^@AGENTS\.md\s*$', read(root, 'CLAUDE.md'), re.M):
        errors.append('CLAUDE.md must contain the import line @AGENTS.md')
    if '.gemini/settings.json' not in pending:
        try:
            names = json.loads(read(root, '.gemini/settings.json')).get('context', {}).get('fileName')
        except (ValueError, AttributeError):
            names = None
        if 'AGENTS.md' not in (names if isinstance(names, list) else [names]):
            errors.append('.gemini/settings.json: context.fileName must include "AGENTS.md"')
    if '.kiro/steering/workspace.md' not in pending:
        head = read(root, '.kiro/steering/workspace.md').split('---')
        if len(head) < 3 or not re.search(r'^inclusion:\s*always\s*$', head[1], re.M):
            errors.append('.kiro/steering/workspace.md needs front matter "inclusion: always"')
    for name in SKILLS:
        text = read(root, f'.agents/skills/{name}/SKILL.md')
        if not text.startswith('---\n') or f'name: {name}' not in text or 'description:' not in text:
            errors.append(f'.agents/skills/{name}/SKILL.md needs front matter with name and description')
    if strict:
        # Only the template's own files: README.md is the project's page, and its links are the project's business.
        for rel in [p for p in STATIC_FILES if p.endswith('.md')]:
            if rel in pending or not (root / rel).is_file():
                continue
            text = re.sub(r'```.*?```', '', read(root, rel), flags=re.S)
            for target in re.findall(r'\]\(([^)\s]+)\)', text):
                if re.match(r'[a-z]+:|#', target):
                    continue
                resolved = ((root / rel).parent / target.split('#', 1)[0]).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    errors.append(f'{rel}: broken link {target}')
                elif rel in RUNTIME_FILES and resolved.relative_to(root.resolve()).as_posix() in MAINTAINER_FILES:
                    errors.append(f'{rel}: links {target}, which projects do not receive')
    return errors


START_MARK = re.compile(r'^<{7}(?: .*)?$')
MIDDLE_MARK = re.compile(r'^={7}$')
END_MARK = re.compile(r'^>{7}(?: .*)?$')
MARKED_DIRS = (STATE_DIR, LOG_DIR, SPEC_DIR)


def _conflict_line(text: str):
    """Line number of a git conflict: a <<<<<<< line, then =======, then >>>>>>>, outside fenced code blocks. A
    setext heading underline or an example inside a fence is not a conflict."""
    fence, stage, first = None, 0, 0
    for number, line in enumerate(text.replace('\r\n', '\n').split('\n'), 1):
        mark = tables.FENCE_RE.match(line)
        if mark:
            fence = None if fence and mark[1][0] == fence else (fence or mark[1][0])
            continue
        if fence:
            continue
        if START_MARK.match(line):
            stage, first = 1, number
        elif stage == 1 and MIDDLE_MARK.match(line):
            stage = 2
        elif stage == 2 and END_MARK.match(line):
            return first
    return None


def conflict_markers(root: Path) -> list:
    """Git conflict markers in state, log and spec files. Rows below a marker belong to no table, so IDs and checks
    would silently ignore them (U33)."""
    found = []
    for folder in MARKED_DIRS:
        path = root / folder
        for file in sorted(path.rglob('*.md')) if path.is_dir() else []:
            line = _conflict_line(file.read_text(encoding='utf-8-sig', errors='replace'))
            if line:
                rel = file.relative_to(root).as_posix()
                found.append(f'{rel}:{line}: unresolved merge conflict marker. Resolve it, keeping the '
                             'rows of both sides with distinct IDs, then run "ws.py check"')
    return found


NEGATION_RE = re.compile(r"(?<![A-Za-z])(?:not|no|never|don't|do not|dropped|removed|replaced|retired|rejected|superseded|instead of)(?![A-Za-z])|[不别勿弃]", re.I)
CITED_ID_RE = re.compile(r'(?<![A-Za-z0-9])([RTFQDP][1-9]\d*)(?![A-Za-z0-9])(?!\s*(?:19|20)\d\d)', re.I)


def card_citations(all_ids: dict, live_ids: set, fields: dict) -> list:
    """The next step must not send the next session to retired work (U5, U15). Done tasks may be cited.
    A citation in the same clause as a negation ("T2 dropped, do not rebuild") is allowed. "Q1 2027" is a date."""
    errors = []
    for key in ('next_step', 'next_acceptance'):
        text = fields.get(key, '')
        bad = []
        for clause in re.split(r'[;；。.!?！？\n]|，|,\s+(?=and\b|but\b|then\b)', text):
            negated = bool(NEGATION_RE.search(clause))
            for hit in CITED_ID_RE.finditer(clause):
                rid = hit[1].upper()
                status = all_ids.get(rid)
                if status is None or status in ('done', 'answered') or (rid in live_ids and status not in PREFIX_TABLE[rid[0]].closed):
                    continue
                if not negated:
                    bad.append(f'{rid} ({status})')
        if bad:
            errors.append(f'HANDOFF.md: {key} cites {", ".join(dict.fromkeys(bad))}. Point it at live work, or say the '
                          'row is not to be redone ("T2 dropped, do not rebuild")')
    return errors


def _ledger_status(table, row) -> str:
    return row.get('Status', '')


def gather(root: Path) -> dict:
    """Parse every state table and the closed-item archive."""
    live = {key: tables.rows(root, t) for key, t in TABLES.items()}
    closed = tables.closed_rows(root)
    return {'live': live, 'closed': closed}


def ledger(data: dict) -> dict:
    result = {}
    for key, rows in data['live'].items():
        for row in rows:
            result[row['ID']] = row['Status']
    for row in data['closed']:
        result[row['ID']] = row['Status']
    return result


# The error of a check that stopped before its end begins with this; guarded() then refuses every write.
INCOMPLETE = 'check stopped early: '


def state_line_errors(state: dict) -> list:
    """What is wrong with the CONTINUITY line itself: the first problem only, since each check relies on the ones before."""
    if state.get('schema') != SCHEMA:
        return [f'HANDOFF.md declares schema {state.get("schema")}; this tool reads {SCHEMA}. Run "ws.py migrate" for older workspaces']
    if state.get('mode') not in ('bootstrap', 'active') or type(state.get('revision')) is not int or state['revision'] < 0:
        return ['the CONTINUITY line has an invalid mode or revision']
    writer = state.get('writer')
    if writer is not None and (not isinstance(writer, str) or not writer.strip()):
        return ['the CONTINUITY line has an invalid writer']
    if writer and (type(state.get('writer_revision')) is not int or not 0 < state['writer_revision'] <= state['revision']):
        return ['the CONTINUITY line has an invalid writer_revision']
    return []


def semantics(root: Path, ready=False, sealing=False, card_changes=None) -> list:
    errors = conflict_markers(root)
    if errors:
        return errors
    try:
        state = state_of(root)
        if state.get('schema') != SCHEMA:
            return state_line_errors(state)
        # A bad state line or checkpoint does not end the check: guarded() compares the errors before and after a
        # change, and stopping here would hide every error the change adds.
        errors += state_line_errors(state)
        writer = state.get('writer')
        try:
            cp = checkpoint_of(root, state)
        except (WorkspaceError, ValueError, TypeError, OSError) as error:
            errors.append(str(error))
            cp = None
        fields = card(root)
        fields.update(card_changes or {})
        for key in CARD_FIELDS:
            value = fields.get(key, '').strip()
            if key not in fields:
                errors.append(f'HANDOFF.md: card field "{key}" is missing')
            elif value.lower() in PLACEHOLDERS or (value.lower() == NONE and key not in OPTIONAL_CARD_FIELDS):
                errors.append(f'HANDOFF.md: card field "{key}" needs a real value')
        if state['mode'] == 'active' and not goal(root):
            errors.append('REQUIREMENTS.md: an active workspace needs a goal between the GOAL markers')
        data = gather(root)
        live = data['live']
        all_ids = ledger(data)
        live_ids = {r['ID'] for rows in live.values() for r in rows}
        for key, t in TABLES.items():
            for row in live[key]:
                rid = row['ID']
                if row['Status'] not in t.statuses:
                    errors.append(f'{t.file}: {rid} has status "{row["Status"]}"; valid: {", ".join(t.statuses)}')
                for field in t.required:
                    if not row.get(field, '').strip() or row[field].strip().lower() == NONE:
                        errors.append(f'{t.file}: {rid} needs a value for {field.lower()}')
                if row['Status'] in NEEDS_REASON[key] and 'Reason' in t.headers and row.get('Reason', '').strip().lower() in ('', NONE):
                    errors.append(f'{t.file}: {rid} is {row["Status"]} and needs a reason')
        closed_ids = set()
        for row in data['closed']:
            rid = row['ID']
            t = PREFIX_TABLE.get(rid[:1])
            if not t or not tables.ID_RE.match(rid):
                errors.append(f'{CLOSED}: invalid ID "{rid}"')
                continue
            if row['Status'] not in t.closed:
                errors.append(f'{CLOSED}: {rid} has status "{row["Status"]}"; closed {t.key} use {", ".join(sorted(t.closed))}')
            if rid in live_ids:
                errors.append(f'{rid} appears in both {t.file} and {CLOSED}; keep one row')
            closed_ids.add(rid)
        for old_id, old_status in ((cp or {}).get('ledger') or {}).items():
            t = PREFIX_TABLE.get(old_id[:1])
            if old_id not in all_ids:
                errors.append(f'{old_id} was removed. IDs are permanent: restore the row or move it to {CLOSED} with "ws.py compact"')
            elif t and old_status in t.retired and all_ids[old_id] not in t.retired:
                errors.append(f'{old_id} was {old_status}; a retired ID cannot return. Add a new row instead')
        requirement_ids = {r['ID'] for r in live['requirements']} | {i for i in closed_ids if i[0] == 'R'}
        task_rows = {r['ID']: r for r in live['tasks']}
        task_status = {**{i: s for i, s in all_ids.items() if i[0] == 'T'}}
        feature_ids = {i for i in all_ids if i[0] == 'F'}
        for row in live['requirements']:
            detail = row.get('Detail', 'inline')
            if detail != 'inline':
                if not SPEC_RE.fullmatch(detail):
                    errors.append(f'REQUIREMENTS.md: {row["ID"]} detail must be "inline" or docs/specs/<slug>/requirements.md')
                else:
                    folder = detail.rsplit('/', 1)[0]
                    missing = [n for n in ('requirements', 'design', 'tasks') if not exists(root, f'{folder}/{n}.md')]
                    if missing:
                        errors.append(f'{detail}: spec folder is missing {", ".join(n + ".md" for n in missing)}')
        for row in live['tasks']:
            rid = row['ID']
            for ref in _refs(errors, 'TASKS.md', rid, row.get('Requirements', ''), 'R', allow_none=False):
                if ref not in requirement_ids:
                    errors.append(f'TASKS.md: {rid} names unknown requirement {ref}')
            for ref in _refs(errors, 'TASKS.md', rid, row.get('Depends', NONE), 'T'):
                if ref == rid or ref not in task_status:
                    errors.append(f'TASKS.md: {rid} depends on unknown task {ref}')
                elif row['Status'] == 'done' and task_status[ref] != 'done':
                    errors.append(f'TASKS.md: {rid} is done but its dependency {ref} is {task_status[ref]}')
        errors += _cycle(task_rows)
        errors += _task_evidence(root, state, cp, live['tasks'])
        closed_log = {r['ID'] for name in ('REQUIREMENT_LOG', 'CHANGE_LOG') for r in logs.all_rows(root, name)}
        for row in live['features']:
            rid = row['ID']
            for ref in _refs(errors, 'FEATURES.md', rid, row.get('Requirements', ''), 'R', allow_none=False):
                if ref not in requirement_ids:
                    errors.append(f'FEATURES.md: {rid} names unknown requirement {ref}')
            feature_tasks = _refs(errors, 'FEATURES.md', rid, row.get('Tasks', ''), 'T', allow_none=False)
            for ref in feature_tasks:
                if ref not in task_status:
                    errors.append(f'FEATURES.md: {rid} names unknown task {ref}')
            if row['Status'] == 'shipped' and any(task_status.get(ref) != 'done' for ref in feature_tasks):
                errors.append(f'FEATURES.md: {rid} is shipped, so every task in its tasks column must be done')
            for ref in _refs(errors, 'FEATURES.md', rid, row.get('Replacement', NONE), 'F'):
                if ref == rid or ref not in feature_ids:
                    errors.append(f'FEATURES.md: {rid} names unknown replacement {ref}')
        for key in ('requirements', 'features'):
            t = TABLES[key]
            for row in live[key]:
                if row['Status'] in t.retired and row['ID'] not in closed_log:
                    errors.append(f'{row["ID"]} is {row["Status"]} without a log row; change status with "ws.py set" so the log is written')
        for row in live['questions']:
            if row['Status'] == 'deferred' and row.get('Answer', NONE).lower() == NONE:
                errors.append(f'REQUIREMENTS.md: {row["ID"]} is deferred without the default it proceeds on; '
                              f'ws set {row["ID"]} --set "answer=default: ..."')
        for key, prefix in (('current_task', 'T'), ('current_feature', 'F')):
            # One ID or a list such as "T3, T4": parallel subtasks are normal.
            for value in _refs(errors, 'HANDOFF.md', key, fields.get(key, NONE), prefix):
                if value not in all_ids:
                    errors.append(f'HANDOFF.md: {key} names unknown ID {value}')
                elif sealing and key == 'current_task':
                    status = {r['ID']: r['Status'] for r in live['tasks']}.get(value)
                    if status in ('done', 'dropped') or status is None:
                        errors.append(f'HANDOFF.md: current_task names {value}, which is {status or "closed"}. '
                                      'Set it to the tasks now in progress, or none')
        for rel in re.findall(r'`([^`]+)`', fields.get('extra_reads', '')):
            if not exists(root, rel):
                errors.append(f'HANDOFF.md: extra_reads names a missing path {rel}')
        baseline = fields.get('baseline', NONE).strip('`')
        if baseline.lower() != NONE and not exists(root, baseline):
            errors.append(f'HANDOFF.md: baseline path does not exist: {baseline}')
        if ready:
            errors += card_citations(all_ids, live_ids, fields)
        if state['mode'] == 'bootstrap' and all_ids:
            errors.append('a bootstrap workspace must not contain IDs; run "ws.py init" first')
        for name in LOG_NAMES:
            logs.all_rows(root, name)
        if cp:
            for rel, expected in (cp.get('evidence') or {}).items():
                path = safe_path(root, rel)
                if not path.is_file() or sha(path.read_bytes()) != expected:
                    errors.append(f'sealed evidence was changed or deleted: {rel}')
        if ready:
            from .coverage import findings
            errors += [message for level, message in findings(root, live) if level == 'block']
            if cp and stale_policy(root, cp) == 'block':
                found = regressions(root, cp, live['tasks'])
                if found:
                    errors.append(f'{", ".join(rid for rid, _ in found[:8])} changed after being verified and must be '
                                  'verified again before READY: run "ws.py verify --stale"')
            # A saved user message that no row accounts for may hold a requirement the next session never sees.
            from .reconcile import pending
            try:
                unreconciled = pending(root)
            except (WorkspaceError, OSError, ValueError):
                unreconciled = []
            if unreconciled:
                errors.append(f'{len(unreconciled)} saved user messages are not reconciled ({", ".join(m for m, _ in unreconciled[:5])}'
                              f'{" and more" if len(unreconciled) > 5 else ""}). Run "ws reconcile", record what each one '
                              'asks for or give the reason none is needed, then checkpoint again')
            if '<!-- SYNC-PENDING -->' in read(root, 'docs/state/HANDOFF.md'):
                errors.append('HANDOFF.md holds a SYNC-PENDING marker; finish the partial update first')
            if state['mode'] != 'active':
                errors.append('the workspace is still in bootstrap mode; run "ws.py init"')
            if writer:
                errors.append(f'writer {writer} still owns the workspace; run "ws.py checkpoint" without --keep')
            from .claims import alive
            for label, entry in sorted((state.get('claims') or {}).items()):
                if alive(entry):
                    errors.append(f'{label} is still working on {", ".join(entry["scope"]["tasks"]) or "the whole tree"}; '
                                  'the workspace is READY when every session has checkpointed')
            if lock_busy(root):
                errors.append('another ws.py command is running; check again when it has finished')
            from .coverage import secret_warnings
            errors += [w for w in secret_warnings(root) if w.startswith(('docs/state/', 'docs/specs/', 'docs/guides/', 'ops/'))]
            if not state.get('checkpoint'):
                errors.append('no checkpoint yet; run "ws.py checkpoint"')
        if cp and not sealing:
            changes = difference(rewatch(root, cp['files']), fingerprint(root))
            if any(changes.values()):
                errors.append('files changed after the last checkpoint: ' + describe_drift(changes, 10) +
                              '. Review them, then run "ws.py checkpoint"')
        if state['mode'] == 'active' and not state.get('checkpoint') and not sealing:
            errors.append('no checkpoint yet; run "ws.py checkpoint" after the initial inspection')
    except (WorkspaceError, ValueError, KeyError, TypeError, OSError) as error:
        errors.append(INCOMPLETE + str(error))
    return errors


def _refs(errors: list, label: str, rid: str, value: str, prefix: str, allow_none=True) -> list:
    try:
        return tables.refs(value, prefix, allow_none)
    except WorkspaceError as error:
        errors.append(f'{label}: {rid}: {error}')
        return []


def _cycle(task_rows: dict) -> list:
    """The tasks on a dependency cycle. A task that only waits on one is not named: changing it fixes nothing."""
    graph = {}
    for rid, row in task_rows.items():
        try:
            graph[rid] = set(tables.refs(row.get('Depends', NONE), 'T')) & set(task_rows)
        except WorkspaceError:
            graph[rid] = set()

    def returns(start: str) -> bool:
        seen, stack = set(), list(graph[start])
        while stack:
            node = stack.pop()
            if node == start:
                return True
            if node not in seen:
                seen.add(node)
                stack.extend(graph[node])
        return False
    members = sorted(t for t in graph if returns(t))
    return ['TASKS.md: dependency cycle among ' + ', '.join(members)] if members else []


def _fresh(cp, row: dict) -> bool:
    """A done task that changed since the last seal: newly done, redefined, or given other evidence."""
    rid = row['ID']
    return (((cp or {}).get('ledger') or {}).get(rid) != 'done'
            or ((cp or {}).get('task_definitions') or {}).get(rid) != evidence.task_definition(row)
            or ((cp or {}).get('task_evidence') or {}).get(rid) != row.get('Evidence'))


def _drift(root: Path, row: dict, proof: dict, current_files: dict):
    """The files in a task's scope that changed after its evidence was recorded, described; None when none did, and
    "unknown" when the evidence holds no file hashes."""
    from .core import digest
    if proof.get('source') == digest(current_files):
        return None
    if not proof.get('source_files'):
        return 'unknown'
    recorded = rewatch(root, proof['source_files'], source_only=True)
    diff = difference(recorded, current_files)
    scope = evidence.scope_paths(row, set(current_files) | set(recorded), acceptance=True)
    if scope is not None:
        diff = {k: [n for n in v if evidence.in_scope(n, scope)] for k, v in diff.items()}
    return describe_drift(diff, 6) if any(diff.values()) else None


def regressions(root: Path, cp=None, task_rows=None, current_files=None, fresh_too=False) -> list:
    """(task, changed files) for sealed done tasks whose scope changed after their evidence: the regressions a seal
    alone would hide. fresh_too adds the tasks changed since the seal, whose staleness is an error anyway. Evidence
    without file hashes cannot be scoped and is left out."""
    if cp is None:
        state = state_of(root)
        cp = checkpoint_of(root, state) if state.get('checkpoint') else None
    rows = gather(root)['live']['tasks'] if task_rows is None else task_rows
    current_files = fingerprint(root, source_only=True) if current_files is None else current_files
    found = []
    for row in rows:
        if row['Status'] != 'done' or (_fresh(cp, row) and not fresh_too):
            continue
        for rel in evidence.evidence_paths(row.get('Evidence', '')):
            try:
                proof = evidence.load(root, rel, evidence.acceptance_kind(row))
            except (WorkspaceError, ValueError, OSError):
                continue
            changed = _drift(root, row, proof, current_files)
            if changed and changed != 'unknown':
                found.append((row['ID'], changed))
                break
    return found


def stale_policy(root: Path, cp) -> str:
    """"block" or "warn" for regressions: the WORKSPACE setting stale_evidence, block by default. The first session
    after an upgrade only warns, so work verified under an older tool can be run again before READY needs it."""
    if (cp or {}).get('upgraded') or (cp or {}).get('after_upgrade'):
        return 'warn'
    try:
        return config(root).get('stale_evidence', 'block')
    except WorkspaceError:
        return 'block'


def regression_text(found: list) -> str:
    return ('done tasks whose files changed after they were verified: ' + '; '.join(f'{rid} ({changed})' for rid, changed
            in found[:6]) + ('; and more' if len(found) > 6 else '') + '. Run "ws.py verify --stale" to run their '
            'acceptance again')


def _task_evidence(root: Path, state: dict, cp, task_rows: list) -> list:
    errors = []
    current_files = None
    for row in task_rows:
        if row['Status'] != 'done':
            continue
        rid = row['ID']
        paths = evidence.evidence_paths(row.get('Evidence', ''))
        if not paths:
            errors.append(f'TASKS.md: {rid} is done without evidence; run "ws.py verify {rid} --done"')
            continue
        definition = evidence.task_definition(row)
        fresh = _fresh(cp, row)
        for rel in paths:
            try:
                proof = evidence.load(root, rel, evidence.acceptance_kind(row))
            except (WorkspaceError, ValueError, OSError) as error:
                errors.append(f'TASKS.md: {rid}: {error}')
                continue
            if not fresh:
                continue
            if proof.get('schema') == 'verification.v5' and 'for_tasks' in proof and rid not in proof['for_tasks']:
                errors.append(f'TASKS.md: {rid} cites {rel}, which verified other tasks. Run "ws.py verify {rid} --done" '
                              'with its acceptance command')
                continue
            if proof.get('task_definitions', {}).get(rid) != definition:
                errors.append(f'TASKS.md: {rid} changed after {rel} was recorded; run "ws.py verify {rid}" again')
            writer = state.get('writer')
            claim = (state.get('claims') or {}).get(proof.get('writer')) or {}
            if claim and (not claim.get('released_at') or rid in (claim.get('released_tasks') or [])):
                pass  # written by a parallel session that works on, or finished, this task since the last seal
            elif not writer or proof.get('writer') != writer or not (state.get('writer_revision') or 0) <= proof.get('revision', -1) <= state['revision']:
                errors.append(f'TASKS.md: {rid} needs evidence from the current session; run "ws.py verify {rid}"')
            if current_files is None:
                current_files = fingerprint(root, source_only=True)
            changed = _drift(root, row, proof, current_files)
            if changed:
                errors.append(f'TASKS.md: {rid}: files in its scope changed after {rel}: {changed}. Run "ws.py verify {rid}" '
                              'again; if a file is generated output, add it to WORKSPACE exclude in ARCHITECTURE.md first')
    return errors


SPEC_IDS_RE = re.compile(r'^Requirement IDs:\s*(.*)$', re.M)
SPEC_TEMPLATE_MARKS = ('# Requirement detail: <name>', 'lists the three tasks')


def spec_warnings(root: Path, data: dict) -> list:
    """Spec folders against the rows that link them (U8). Warnings only: a spec is detail, not state."""
    folder = root / SPEC_DIR
    slugs = sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
    if not slugs:
        return []
    links = {}
    for row in data['live']['requirements']:
        found = SPEC_RE.search(row.get('Detail', ''))
        if found:
            links.setdefault(found[0].split('/')[2], set()).add(row['ID'])
    archive = root / 'docs/archive/closed'
    for path in sorted(archive.glob('R*.md')) if archive.is_dir() else []:
        found = SPEC_RE.search(path.read_text(encoding='utf-8', errors='replace'))
        if found:
            links.setdefault(found[0].split('/')[2], set()).add(path.stem)
    known = set(ledger(data))
    result = []
    for slug in slugs:
        rel = f'{SPEC_DIR}/{slug}/requirements.md'
        linked = links.get(slug, set())
        if not linked:
            result.append(f'{SPEC_DIR}/{slug}/ is linked by no requirement. Put "{rel}" in the Detail column of '
                          'its requirement, or move the folder out of docs/specs/')
            continue
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if any(mark in text for mark in SPEC_TEMPLATE_MARKS):
            result.append(f'{rel} still holds the template text; fill it in or remove the example rows')
        line = SPEC_IDS_RE.search(text)
        named = set(re.findall(r'\bR[1-9]\d*\b', line[1])) if line else set()
        unknown = sorted(named - known)
        if unknown:
            result.append(f'{rel} names {", ".join(unknown)}, which no row has')
        missing = sorted(linked - named)
        if line and missing and not re.search(r'R<n>', line[1]):
            result.append(f'{rel}: {", ".join(missing)} links this spec but its "Requirement IDs:" line does not name it')
    return result


def advisories(root: Path) -> list:
    """Size, coverage and credential warnings. They never block a save."""
    from .coverage import findings, secret_warnings
    result = budget_warnings(root)
    try:
        from .distribution import maintainer_leftovers
        left = maintainer_leftovers(root)
        if left:
            result.append(f'{len(left)} template maintainer files are in this project ({", ".join(left[:3])}{" and more" if len(left) > 3 else ""}). '
                          'They are not for project work and show up in searches. Remove them with "ws tidy"')
    except (WorkspaceError, ValueError, OSError):
        pass
    try:
        from .coverage import project_file_in_agents
        from .core import watched_files
        stray = [rel for rel in watched_files(root) if project_file_in_agents(rel)]
        if stray:
            result.append(f'{len(stray)} project files are under .agents/, which an upgrade may replace: '
                          f'{", ".join(stray[:4])}. Move reports to docs/reports/ and scratch files to .tmp/')
    except (WorkspaceError, ValueError, OSError):
        pass
    try:
        data = gather(root)
        result += [message for level, message in findings(root, data['live']) if level == 'warn']
        result += spec_warnings(root, data)
        result += secret_warnings(root)
        result += evidence.rules_notes(root, data['live']['tasks'])
        result += evidence.scope_notes(root, data['live']['tasks'])
        state = state_of(root)
        cp = checkpoint_of(root, state) if state.get('checkpoint') else None
        found = regressions(root, cp, data['live']['tasks'])
        if found:
            result.append(regression_text(found) + (' READY waits for that.' if stale_policy(root, cp) == 'block' else
                          ' READY does not wait for it: stale_evidence is "warn", or this is the first session after '
                          'an upgrade.'))
    except (WorkspaceError, ValueError, OSError):
        pass
    return result


# compact moves only closed rows, so files of prose and adopted decisions need another way out.
BUDGET_FIX = {
    'ARCHITECTURE': 'Keep one short form per component here and move procedures to docs/guides/<topic>.md and '
                    'component detail to docs/specs/<slug>/design.md, linked by path',
    'DESIGN': 'Run "ws.py compact" for superseded and rejected rows; shorten long Reason cells to one sentence and move '
              'the argument to docs/specs/<slug>/design.md, linked by path',
}


def budget_warnings(root: Path) -> list:
    warnings = []
    size = lambda rel: (root / rel).stat().st_size if (root / rel).is_file() else 0
    if size('AGENTS.md') > BUDGETS['AGENTS.md']:
        warnings.append(f'AGENTS.md is {size("AGENTS.md")} bytes; keep it under {BUDGETS["AGENTS.md"]}. Move detail to .agents/guides/')
    t0 = sum(size(rel) for rel in T0)
    if t0 > BUDGETS['T0']:
        warnings.append(f'T0 files total {t0} bytes (budget {BUDGETS["T0"]}). Run "ws.py compact" or move requirement detail into docs/specs/')
    for name in STATE_NAMES:
        rel = f'{STATE_DIR}/{name}.md'
        if size(rel) > BUDGETS['state']:
            warnings.append(f'{rel} is {size(rel)} bytes (budget {BUDGETS["state"]}). ' + BUDGET_FIX.get(name, 'Run "ws.py compact"'))
    agents = (root / 'AGENTS.md').read_text(encoding='utf-8') if (root / 'AGENTS.md').is_file() else ''
    if agents.count('\n') > 200:
        warnings.append(f'AGENTS.md has {agents.count(chr(10))} lines; Claude Code advises under 200. Move detail to .agents/guides/')
    # Hosts truncate long rule files: Antigravity at 24,000 bytes, Codex at 32 KiB.
    if size('AGENTS.md') > 24000:
        warnings.append('AGENTS.md is over 24,000 bytes, where Antigravity truncates it')
    claude = (root / 'CLAUDE.md').read_text(encoding='utf-8') if (root / 'CLAUDE.md').is_file() else None
    if claude is not None and not re.search(r'^@AGENTS\.md\s*$', claude, re.M):
        warnings.append('CLAUDE.md does not import AGENTS.md; Claude Code then ignores AGENTS.md. Add the line "@AGENTS.md"')
    buddy = (root / 'CODEBUDDY.md').read_text(encoding='utf-8') if (root / 'CODEBUDDY.md').is_file() else None
    if buddy is not None and 'AGENTS.md' not in buddy:
        warnings.append('CODEBUDDY.md exists, so CodeBuddy and WorkBuddy skip AGENTS.md. Add the line "@AGENTS.md" to it')
    try:
        warnings += shadow_warnings(root)
    except (WorkspaceError, ValueError, OSError):
        pass  # a broken WORKSPACE block is reported as an error elsewhere
    return warnings


def shadow_warnings(root: Path) -> list:
    """Files that make a host replace the root contract, and nested chains a host truncates. A CLAUDE.local.md is
    harmless here: the shipped CLAUDE.md imports AGENTS.md, and a missing CLAUDE.md is already an error."""
    from .core import watched_files
    warnings = []
    files = watched_files(root)
    for rel in [r for r in files if r.rsplit('/', 1)[-1] == 'AGENTS.override.md']:
        warnings.append(f'{rel} exists; Codex reads it instead of the AGENTS.md in that folder. '
                        'Move its rules into AGENTS.md and delete it')
    for rel in [r for r in files if r.endswith('/AGENTS.md')]:
        # Codex joins AGENTS.md from the root down to the working folder and stops at 32 KiB.
        parts = rel.split('/')[:-1]
        chain = ['AGENTS.md'] + [f'{"/".join(parts[:i])}/AGENTS.md' for i in range(1, len(parts) + 1)]
        total = sum((root / r).stat().st_size for r in chain if (root / r).is_file())
        if total > 32768:
            warnings.append(f'AGENTS.md files from the root down to {rel} total {total} bytes; Codex stops reading at '
                            '32 KiB, so the deepest rules are cut. Shorten the nested file')
    return warnings


def validate(root: Path, strict=False, ready=False, sealing=False, card_changes=None, adapters=False) -> list:
    errors = structure(root, strict, adapters)
    if errors:
        return errors
    return semantics(root, ready=ready, sealing=sealing, card_changes=card_changes)
