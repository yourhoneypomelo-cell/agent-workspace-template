"""Verification: run a task's recorded acceptance and attach the evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import evidence, logs, tables, validate
from .coverage import redact, redact_pasted
from .core import WorkspaceError, card, card_text, lock, read, safe_path, state_of, today, write
from .ops import bump, emit, guarded, require_owner, short
from .verifying import previous_evidence, ship_features, verdict_text
from .schema import HANDOFF, NONE, TABLES


SHELL_OPERATORS = ('&&', '||', '|', ';', '>', '>>', '<', '2>&1')


def acceptance_argv(row: dict) -> list:
    """The command a task names as its acceptance, split into arguments.

    Backslashes are kept, so Windows paths match what the agent types. Only the first backtick span
    counts when the cell mixes a command with prose. A trailing expect clause is not part of the command."""
    import shlex
    text = evidence.split_expect(evidence.acceptance_text(row))[0].strip()
    if text.lower().startswith('check:'):
        text = text[6:].strip()
    found = re.search(r'`([^`]+)`', text)
    text = (found[1] if found else text).strip().strip('`').strip()
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=False)
        lexer.whitespace_split = True
        lexer.escape = ''
        return list(lexer)
    except ValueError:
        return text.split()


def verify_stale(root: Path, timeout: int, writer=None, rev=None) -> int:
    """Run the acceptance of every done task whose files changed after it was verified, once per command, and attach
    the new evidence. Returns 1 when any run is rejected."""
    stale = [rid for rid, _ in validate.regressions(root, fresh_too=True)]
    if not stale:
        print('No done task has stale evidence.')
        return 0
    rows = {r['ID']: r for r in tables.rows(root, tables.table_for('tasks'))}
    groups = {}
    for rid in stale:
        last = evidence.evidence_paths(rows[rid].get('Evidence', ''))
        try:
            report = (json.loads(read(root, last[-1])).get('report') or {}).get('format') if last else None
        except (WorkspaceError, ValueError, OSError):
            report = None
        groups.setdefault((tuple(acceptance_argv(rows[rid])), report), []).append(rid)
    failed = 0
    for (command, report), ids in groups.items():
        print(f'== verify {" ".join(ids)} -- {" ".join(command)}', flush=True)
        failed += verify(root, ids, list(command), True, None, report, None, timeout, writer, rev) != 0
    return 1 if failed else 0


def verify(root: Path, ids: list, command: list, done: bool, kind: str | None, report: str | None, label: str | None,
           timeout: int, writer=None, rev=None, because: str | None = None) -> int:
    if not command:
        raise WorkspaceError('give the acceptance command after --, for example: ws.py verify T1 -- python -m unittest')
    if timeout < 1:
        raise WorkspaceError('--timeout must be positive')
    with lock(root):
        state = state_of(root)
        owner = require_owner(root, state, writer, rev)
        from .claims import guard_tasks
        guard_tasks(state, ids, 'verify')
        task_table = tables.table_for('tasks')
        task_rows = {r['ID']: r for r in tables.rows(root, task_table)}
        kinds = set()
        for rid in ids:
            if rid not in task_rows:
                raise WorkspaceError(f'{rid} is not a live task in docs/state/TASKS.md')
            kinds.add(evidence.acceptance_kind(task_rows[rid]))
        if len(kinds) > 1:
            raise WorkspaceError('verify tasks with test acceptance and check: acceptance separately')
        needed = kinds.pop() if kinds else (kind or 'test')
        if kind and kind != needed:
            raise WorkspaceError(
                f'the task acceptance is a {needed}, so drop --kind {kind}. ' +
                ('A test run must report passing tests. To accept a command without a test count, set the task '
                 'acceptance to "check: <command>" first with ws set.' if needed == 'test' else
                 'Its acceptance starts with "check:", so run verify without --kind or with --kind check.'))
        # The evidence must come from the command the task names, not an easier one picked later.
        expected = {rid: acceptance_argv(task_rows[rid]) for rid in ids}
        empty = [rid for rid, argv in expected.items() if not argv]
        if empty:
            raise WorkspaceError(f'{empty[0]} has no acceptance command. Set one first: '
                                 f'ws set {empty[0]} --set "acceptance=python -m unittest tests.test_x"')
        piped = [rid for rid, argv in expected.items() if any(a in SHELL_OPERATORS for a in argv)]
        if piped:
            raise WorkspaceError(f'{piped[0]} names a shell pipeline as acceptance, which verify runs without a shell. '
                                 'Put the steps in a script and name the script, for example "python ops/check_all.py"')
        different = [rid for rid, argv in expected.items() if argv != list(command)]
        if different and not because:
            rid = different[0]
            raise WorkspaceError(f'{rid} names the acceptance "{task_rows[rid]["Acceptance"]}", but verify ran '
                                 f'"{" ".join(command)}". Run the recorded command, change the acceptance first with '
                                 f'"ws set {rid} --set acceptance=...", or give --because "<reason>"')
        definitions = {rid: evidence.task_definition(r) for rid, r in task_rows.items()}
        revision = state['revision']
        # Each task's expect clauses must all appear; a run that verifies several tasks meets all of them.
        expected = [e for rid in ids for e in evidence.split_expect(task_rows[rid].get('Acceptance', ''))[1]]
    rel, data = evidence.run(root, list(command), redact(label) if label else (ids[0] if ids else 'check'), owner, revision,
                             needed, timeout, report, definitions, for_tasks=list(ids), expected=expected)
    with lock(root):
        state = state_of(root)
        # With --rev (shared ownership) another writer may not have moved the workspace while the command ran.
        if require_owner(root, state, writer, None if rev is None else revision) != owner:
            raise WorkspaceError(f'{state["writer"]} took over while the command ran; the evidence {rel} is kept but '
                                 'not attached. Re-read docs/state/HANDOFF.md')
        task_rows = {r['ID']: r for r in tables.rows(root, task_table)}
        moved = [rid for rid in ids if rid not in task_rows or evidence.task_definition(task_rows[rid]) != definitions[rid]]
        if moved:
            raise WorkspaceError(f'{moved[0]} changed while the command ran; run verify again')
        summary = data['summary']
        previous = previous_evidence(root, ids, data['command'], skip=rel) if ids else None
        smaller = evidence.shrank(previous, data) if data['accepted'] else []
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'verify ' + ('accepted' if data['accepted'] else 'rejected'),
                                              'Detail': short(f'{", ".join(ids) or "check"}: {verdict_text(data)}' +
                                                              (f'; tests less than before: {"; ".join(smaller)}' if smaller else ''), 300)})
        if different:
            logs.append(root, 'MAINTENANCE_LOG', {'Event': 'verify override',
                                                  'Detail': short(redact_pasted(f'{", ".join(different)}: ran {" ".join(command)}; {because}'), 400)})
        line = f'{today()} {rel.rsplit("/", 1)[-1]}: {verdict_text(data)}' + ('' if data['accepted'] else ' (rejected)')
        skipped = data['summary'].get('skipped', 0) if data['summary'].get('known') else 0
        attach_error = None
        card_now = {'last_verification': short(line, 200)}
        current = tables.card_ids(card(root).get('current_task', NONE), 'T') if done and data['accepted'] else []
        if set(current) & set(ids):
            # Finished tasks leave the card; the others in the list stay.
            card_now['current_task'] = ', '.join(t for t in current if t not in ids) or NONE
        changes = {HANDOFF: card_text(read(root, HANDOFF), card_now)}
        if data['accepted'] and ids:
            text = read(root, task_table.file)
            for rid in ids:
                row = {**task_rows[rid], 'Evidence': rel}
                if done:
                    row['Status'] = 'done'
                text = tables.upsert(text, task_table.headers, task_table.file, row)
            changes[task_table.file] = text
            if done:
                changes.update(ship_features(root, set(ids), task_rows))
            try:
                guarded(root, changes)
            except WorkspaceError as error:
                attach_error = str(error)
                write(root, HANDOFF, changes[HANDOFF])
        else:
            write(root, HANDOFF, changes[HANDOFF])
        bump(root, state)
    emit({'evidence': rel, 'accepted': data['accepted'], 'revision': state['revision'], 'tasks': ids if data['accepted'] and not attach_error else [],
          'marked_done': bool(done and data['accepted'] and not attach_error), 'summary': {k: summary[k] for k in ('parser', 'total', 'passed', 'failed', 'errors', 'skipped')},
          'exit_code': data['exit_code']})
    for reason in data['reasons']:
        print('REJECTED: ' + reason)
    if needed == 'check' and data['accepted'] and not expected:
        print('NOTE: this check has no expect clause, so it proves only that the command exited 0. That is enough for a '
              'build or linter. For behavior, add the output it must print: ws set <ID> --set '
              '"acceptance=check: <command> expect \"<text>\""')
    if skipped and data['accepted']:
        print(f'NOTE: {skipped} tests were skipped. A skipped test proves nothing: check that the tests this task '
              'depends on actually ran before you report it done.')
    if smaller:
        print('NOTE: this run tests less than the previous accepted run of the same command: ' + '; '.join(smaller) +
              '. If that was not the intent of the task, restore the tests; never narrow them just to get a pass.')
    if done and data['accepted'] and not attach_error:
        # A requirement read but not turned into work is the usual silent miss at completion.
        cited = sorted({r for rid in ids for r in re.findall(r'\bR[1-9]\d*\b', task_rows[rid].get('Requirements', ''))})
        rows = {r['ID']: r for r in tables.rows(root, tables.table_for('requirements'))}
        for rid in cited:
            if rid in rows:
                print(f'Check {rid} is met in full: {short(rows[rid]["Requirement"], 300)} | acceptance: {short(rows[rid]["Acceptance"], 160)}')
    if attach_error:
        print('NOT ATTACHED: ' + attach_error)
    tail = data['output'].strip().splitlines()[-30:]
    if tail:
        print('--- output (last 30 lines) ---')
        print('\n'.join(tail))
    return 0 if data['accepted'] and not attach_error else 1
