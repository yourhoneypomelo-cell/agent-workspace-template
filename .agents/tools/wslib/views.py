"""Read-only views: status, the resume brief and the per-turn reminder. They never write state."""
from __future__ import annotations

import re
from pathlib import Path

from . import coverage, logs, tables, validate
from .core import WorkspaceError, card, checkpoint_of, config, difference, drift_count, fingerprint, goal, rewatch, state_of
from .schema import CLOSED, HOOK_FILES, NONE, SCHEMA, T0, T1, TABLES


def short(text: str, limit=160) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


# Card values written by init. A checkpoint after real work must replace them.
INIT_CARD = {
    'phase': 'inspection',
    'risks': 'Product entry points and acceptance commands are unknown',
    'next_acceptance': 'ws.py check --ready passes after the first checkpoint',
}


def stale_card_fields(fields: dict, root: Path) -> list:
    """Init placeholders that survived past the first real work."""
    if not any(tables.rows(root, TABLES[k]) for k in ('requirements', 'tasks')):
        return []
    return [k for k, v in INIT_CARD.items() if fields.get(k) == v]


TURN_RULE = ('Workspace rule for this turn: requirements, changes, decisions, preferences and open questions in the '
             'user message are recorded with "python .agents/tools/ws.py add ..." or "ws set ..." before other work, '
             'because the next session sees only the files. They include corrections ("no, not that"), prohibitions '
             '("do not touch X"), rules on how to work, a requirement inside a question and an accepted unusual '
             'choice. A restatement of your own is not one. '
             'Clear requirements get an ID now; only open details go to the Idea pool. '
             'Work is reported done only with evidence recorded after its last change, and a request in this turn '
             'does not waive that.')
# The last sentence follows the "credentials" setting in ARCHITECTURE.md (PROTOCOL.md, "Credentials").
CREDENTIAL_SENTENCES = {
    'ask': 'Passwords and keys the user sent are never repeated or written to a file.',
    'redact': 'Passwords and keys the user sent are never repeated or written to a file; name the variable or file '
              'that holds each one.',
    'plain': 'Passwords and keys the user sent are kept as written, where the user said they go.',
}
TURN_REMINDER = TURN_RULE + ' ' + CREDENTIAL_SENTENCES['ask']


def turn_reminder(root: Path) -> str:
    try:
        mode = config(root)['credentials']
    except (WorkspaceError, ValueError, OSError):
        mode = 'ask'
    return TURN_RULE + ' ' + CREDENTIAL_SENTENCES.get(mode, CREDENTIAL_SENTENCES['ask'])


def turn_context(root: Path) -> str:
    """Per-turn reminder for prompt-submit hooks: the rule plus the current task and open questions."""
    parts = [turn_reminder(root)]
    try:
        info = status(root)
        if info['mode'] == 'bootstrap':
            return parts[0] + ' The workspace is not initialized: read AGENTS.md and run ws brief.'
        live = validate.gather(root)['live']
        fields = card(root)
        task = fields.get('current_task', NONE)
        if task.lower() != NONE:
            parts.append(f'Current task: {task}.')
        open_q = [r['ID'] for r in live['questions'] if r['Status'] == 'open']
        if open_q:
            parts.append('Questions that block work until the user answers: ' + ', '.join(open_q[:8]) + '.')
        parts += coverage.turn_attention(root, live)
        from .reconcile import summary_line
        line = summary_line(root)
        if line:
            parts.append(line + '.')
        if not info['writer']:
            parts.append('No session owns the workspace: run "ws start" before writing.')
    except (WorkspaceError, ValueError, OSError):
        pass
    return ' '.join(parts)


# Read-only views
def status(root: Path) -> dict:
    state = state_of(root)
    cp = checkpoint_of(root, state)
    changes = difference(rewatch(root, cp['files']), fingerprint(root)) if cp else None
    return {'schema': state.get('schema'), 'mode': state['mode'], 'revision': state['revision'], 'writer': state.get('writer'),
            'ownership': config(root)['ownership'], 'checkpoint_at': (cp or {}).get('created_at'),
            'unsaved_changes': None if changes is None else {k: v[:20] for k, v in changes.items()},
            'unsaved_count': None if changes is None else drift_count(changes),
            'recent': recent_minutes(state) if state.get('writer') else None,
            'owner_window': owner_window(state),
            'working': working_sessions(state)}


def working_sessions(state: dict) -> list:
    """(label, tasks) of the sessions still working, other than the one reading the brief."""
    from .claims import caller, holders
    me = caller(state)
    mine = state.get('writer') if me == 'primary' else me
    return [(label, scope['tasks']) for label, scope in holders(state, exclude=mine)]


def owner_window(state: dict) -> str | None:
    """'running', 'exited', 'this' (the caller runs in the owner's window) or None when unknown or released."""
    from .core import host_alive, host_process, same_host
    if not state.get('writer') or not state.get('host'):
        return None
    if same_host(state['host'], host_process()):
        return 'this'
    return {True: 'running', False: 'exited'}.get(host_alive(state['host']))


RECENT_MINUTES = 20


def recent_minutes(state: dict):
    """Minutes since the owner last wrote, when that is recent enough to suggest a live conversation (U35)."""
    import datetime as dt
    times = []
    for key in ('last_write_at', 'claimed_at'):
        try:
            times.append(dt.datetime.fromisoformat(state.get(key) or ''))
        except ValueError:
            pass
    if not times:
        return None
    last = max(times)
    minutes = int((dt.datetime.now(dt.timezone.utc) - last).total_seconds() // 60)
    return minutes if 0 <= minutes < RECENT_MINUTES else None


def project_guides(root: Path) -> list:
    """Project-specific operating guides in docs/guides/, with their titles."""
    folder = root / 'docs/guides'
    result = []
    for path in sorted(folder.glob('*.md')) if folder.is_dir() else []:
        try:
            first = next((l for l in path.read_text(encoding='utf-8').splitlines() if l.startswith('# ')), '# ' + path.stem)
        except OSError:
            continue
        result.append((path.relative_to(root).as_posix(), first[2:].strip()))
    return result


def next_command(root: Path, info: dict, key=None) -> str:
    from .core import delegated
    if delegated():
        return 'none: this session runs with WS_ROLE set, so it reads the state and reports to the session that started it'
    if info['mode'] == 'bootstrap':
        return 'python .agents/tools/ws.py init --goal "<the goal the user confirmed>"' + (f' --session {key}' if key else '')
    if key:
        return f'python .agents/tools/ws.py start --session {key}    (resumes if this session owns it)'
    if info.get('working'):
        busy = '; '.join(f'{label} on {", ".join(tasks) or "the whole tree"}' for label, tasks in info['working'])
        return (f'other sessions are working ({busy}). To work beside them, claim a task whose Scope names other '
                'paths and resources: python .agents/tools/ws.py start --task <ID>. To take one over, ask the user first')
    if info['writer'] and info.get('owner_window') == 'running':
        return (f'do not claim: the window of {info["writer"]} is still running. Ask the user whether it is finished; '
                'if so: python .agents/tools/ws.py start --force --reason "<what the user said>"')
    if info['writer'] and info.get('owner_window') == 'exited':
        return f'python .agents/tools/ws.py start    (the window of {info["writer"]} has exited; inspect unsaved changes first)'
    if info['writer'] and info.get('recent') is not None:
        return (f'do not claim yet: {info["writer"]} wrote {info["recent"]} min ago and may still be working. A subagent or '
                'side window never claims it. Otherwise ask the user, then: python .agents/tools/ws.py start')
    if info['writer']:
        return 'python .agents/tools/ws.py start    (takes over from ' + info['writer'] + '; inspect unsaved changes first)'
    if info['unsaved_count']:
        return 'python .agents/tools/ws.py start    (files changed since the checkpoint; inspect them first)'
    return 'python .agents/tools/ws.py start'


# The brief keeps every prohibition and preference unless they outgrow these sizes, and then says how many are left.
RETIRED_BUDGET = 1800
PREFERENCE_BUDGET = 1200


def fitted(items: list, budget: int) -> tuple:
    """(the items that fit in budget characters, at least one; how many are left out)."""
    shown, size = [], 0
    for item in items:
        if shown and size + len(item) > budget:
            break
        shown.append(item)
        size += len(item) + 2
    return shown, len(items) - len(shown)


def retired_list(root: Path) -> str:
    """Every retired row in full, newest first: what "ws brief --retired" prints."""
    data = validate.gather(root)
    rows = retired_rows(data['live'], data.get('closed') or [])
    return ''.join(f'- {rid} {status}: {text} ({reason})\n' for rid, status, text, reason in reversed(rows)) or '- none\n'


def retired_rows(live: dict, closed: list) -> list:
    """(ID, status, summary, reason) of retired requirements and features and rejected or superseded decisions:
    closed ones first, then live ones. These are what a new session must not bring back."""
    found = [(r['ID'], r['Status'], r['Summary'], r['Reason']) for r in closed
             if r['ID'][:1] in 'RFD' and r['Status'] in ('removed', 'replaced', 'deprecated', 'rejected', 'superseded')]
    for key in ('requirements', 'features', 'decisions'):
        t = TABLES[key]
        found += [(r['ID'], r['Status'], r[t.summary], r.get('Reason', NONE)) for r in live.get(key, []) if r['Status'] in t.retired]
    return found


def job_lines(root: Path, notes: str) -> list:
    """One line per job recorded in recovery_notes: running, exited or replaced, with the end of its log."""
    import datetime as dt
    from .core import JOB_RE, process_info, safe_path
    result = []
    logs_named = re.findall(r'(?i)\blog\s*[=:]\s*`?([^\s`;,]+)', notes)
    for number, match in enumerate(JOB_RE.finditer(notes)):
        pid, started = int(match[1]), match[2]
        alive, created = process_info(pid)
        try:
            recorded = dt.datetime.fromisoformat(started).timestamp() if started and started != 'unknown' else None
        except ValueError:
            recorded = None
        if alive is None:
            state = 'unknown (no access to the process)'
        elif not alive:
            state = 'exited; check its result before starting it again'
        elif recorded and created and abs(created - recorded) > 2:
            state = 'exited, and its pid now belongs to another process; check the result before starting it again'
        else:
            state = 'running' + ('' if recorded else ' (start time not recorded, so a reused pid is not detected)')
        line = f'- job pid {pid}: {state}'
        if number < len(logs_named):
            name = logs_named[number].replace('\\', '/')
            if not re.search(r'\.(?:log|out|txt)$', name, re.I) or re.search(r'(?:^|/)\.env|(?:^|/)docs/state/|secret|token|cred', name, re.I):
                result.append(line + f'; log {name} not shown: name a .log, .out or .txt file')
                continue
            try:
                path = safe_path(root, logs_named[number])
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 4096))
                    tail = [l for l in stream.read().decode('utf-8', 'replace').splitlines() if l.strip()]
                age = int(dt.datetime.now().timestamp() - path.stat().st_mtime)
                from .coverage import redact
                line += f'; log {logs_named[number]} written {age} s ago' + (f', last: {short(redact(tail[-1]), 120)}' if tail else '')
            except (OSError, WorkspaceError):
                line += f'; log {logs_named[number]} not found'
        result.append(line)
    return result


def rejected_runs(root: Path, tasks: list) -> dict:
    """For open tasks: rejected verify runs since the last accepted run or the last edit of the task (U37)."""
    try:
        verify_rows = [r for r in logs.all_rows(root, 'MAINTENANCE_LOG')
                       if r.get('Event') in ('verify accepted', 'verify rejected', 'task edited')]
    except (ValueError, OSError, RuntimeError, WorkspaceError):
        return {}
    result = {}
    for task in tasks:
        if task['Status'] in ('done', 'dropped'):
            continue
        count, last = 0, ''
        for row in verify_rows:
            ids, _, detail = row['Detail'].partition(': ')
            if task['ID'] not in ids.split(', '):
                continue
            if row['Event'] == 'verify rejected':
                count, last = count + 1, detail
            else:
                count = 0  # an accepted run or a changed definition starts over
        if count >= 2:
            result[task['ID']] = (f' ({count} rejected verify runs in a row, last: {short(last, 60)}' +
                                  ('; record what was tried in recovery_notes or ask the user before running it again)'
                                   if count >= 3 else ')'))
    return result


def command_problems(root: Path) -> list:
    """Rows of the "Known command problems" table in ARCHITECTURE.md, so the next session starts with the form that works."""
    from .core import read
    try:
        text = read(root, 'docs/state/ARCHITECTURE.md')
        found = [b for b in tables.blocks(text) if tuple(b[1][:3]) == ("Command", "Symptom", "Working form")]
    except (OSError, ValueError, WorkspaceError):
        return []
    if not found:
        return []
    from .coverage import redact
    rows = [[redact(c) for c in cells] for _, cells in found[0][2] if len(cells) >= 3 and cells[0].strip()]
    return [f'- {short(c[0], 50)}: {short(c[1], 50)} -> {short(c[2], 60)}' for c in rows[-5:]]


def brief(root: Path, sid=None) -> str:
    """A compact resume summary for humans and SessionStart hooks."""
    lines = []
    try:
        info = status(root)
    except (WorkspaceError, ValueError, OSError) as error:
        return f'# Workspace brief\n\nThe workspace state could not be read: {error}\nRead AGENTS.md and run: python .agents/tools/ws.py check\n'
    fields = card(root)
    lines.append(f'# Workspace brief ({SCHEMA}, revision {info["revision"]})')
    lines.append('')
    lines.append(f'Goal: {goal(root) or "not set"}')
    lines.append(f'Owner: {info["writer"] or "none"} | ownership: {info["ownership"]} | last checkpoint: {info["checkpoint_at"] or "none"}')
    try:
        from .core import state_of
        parallel = state_of(root).get('claims') or {}
    except (WorkspaceError, ValueError, OSError):
        parallel = {}
    for label, entry in sorted(parallel.items()):
        tasks = entry.get('released_tasks') if entry.get('released_at') else entry['scope']['tasks']
        lines.append(f'Parallel: {label}{" (released)" if entry.get("released_at") else ""} on '
                     f'{", ".join(tasks or []) or "the whole tree"}; stop point: {short(entry.get("stop_point") or "none", 100)}; '
                     f'next: {short(entry.get("next_step") or "none", 100)}')
    data = validate.gather(root)
    live = data['live']
    attention = validate.conflict_markers(root)
    if info['mode'] == 'active':
        attention += [message for _, message in coverage.findings(root, live)]
        from .reconcile import summary_line
        if summary_line(root):
            attention.append(summary_line(root))
        if info['writer'] and info.get('owner_window') == 'running' and not sid:
            attention.append(f'{info["writer"]} owns the workspace and its window is still running. Do not take over; '
                             'ask the user whether that window is finished. Rules for parallel windows and subagents: '
                             '.agents/guides/PROTOCOL.md, "Ownership"')
        elif info['writer'] and info.get('recent') is not None and not sid and info.get('owner_window') != 'exited':
            attention.append(f'{info["writer"]} owns the workspace and wrote {info["recent"]} min ago, so another '
                             'conversation may be working here. Do not run "ws start" from a subagent, side window or '
                             'read-only question; ask the user before taking over')
        elif info['writer']:
            attention.append(f'{info["writer"]} owns the workspace. ' + ('Run the Next start command' if sid else
                             'If that is not this session, it was interrupted: run "ws start" and inspect the unsaved files'))
    if info['mode'] == 'active':
        from .lint import state_findings
        rows = state_findings(root)
        if rows:
            attention.append(f'{len(rows)} state rows are hard for a new session to read (long cells, several facts in '
                             'one cell, undefined codes, missing paths). Before adding to them, fix the ones you touch: '
                             'run "ws lint"; "ws set <ID> --move-detail <path>" moves detail without losing it')
    if attention:
        lines.append('')
        lines.append('## Attention')
        lines.append('')
        lines += [f'- {message}' for message in attention]
    number = coverage.counts(live)
    lines.append('')
    lines.append('Recorded: ' + ', '.join(f'{number[k]} {k}' for k in coverage.COUNTED))
    try:
        from .validate import regressions
        stale = {rid for rid, _ in regressions(root, task_rows=live['tasks'], fresh_too=True)}
    except (WorkspaceError, ValueError, OSError):
        stale = set()
    verified, total, missing = coverage.requirement_coverage(live, data.get('closed'), stale)
    if total:
        v2 = [rid for rid in missing if rid in coverage.v2_cited(data.get('closed'))]
        lines.append(f'Requirements verified: {verified}/{total}' +
                     (f' (not yet: {", ".join(missing[:8])}{" and more" if len(missing) > 8 else ""})' if missing else '') +
                     (f'; verified under v2 only, not run again in v3: {", ".join(v2[:8])}' if v2 else ''))
    lines += coverage.inferred_line(root, live)
    try:
        from .delivery import delivery_lines
        sealed = checkpoint_of(root, state_of(root))
        lines += delivery_lines(root, sealed, live['tasks'], f'revision {info["revision"]}, last sealed '
                                f'{info["checkpoint_at"] or "never"}, {info["unsaved_count"] or 0} files changed since.')
    except (WorkspaceError, ValueError, OSError):
        pass
    lines.append('')
    lines.append('## Handoff')
    lines.append('')
    for key in ('phase', 'stop_point', 'next_step', 'next_acceptance', 'risks', 'recovery_notes', 'current_task', 'extra_reads'):
        value = fields.get(key, NONE)
        if value.lower() != NONE or key in ('stop_point', 'next_step'):
            lines.append(f'- {key}: {value}')
    lines += job_lines(root, fields.get('recovery_notes', ''))
    if info['mode'] == 'active':
        stale = stale_card_fields(fields, root)
        if stale:
            lines.append(f'- note: {", ".join(stale)} still hold the init text and may be out of date')
    open_questions = [r for r in live['questions'] if r['Status'] == 'open']
    deferred = [r for r in live['questions'] if r['Status'] == 'deferred']
    active = [r for r in live['tasks'] if r['Status'] in ('doing', 'unverified', 'blocked')]
    upcoming = [r for r in live['tasks'] if r['Status'] == 'todo'][:5]
    lines.append('')
    lines.append('## Open questions')
    lines.append('')
    lines += [f'- {r["ID"]}: {r["Question"]}' for r in open_questions] or ['- none']
    if deferred:
        lines.append('')
        lines.append('Proceeding on defaults until the user decides (do not ask again unless the answer would change the work):')
        lines += [f'- {r["ID"]}: {short(r["Question"], 100)} -> {short(r["Answer"], 120)}' for r in deferred[:8]]
    lines.append('')
    lines.append('## Tasks in progress')
    lines.append('')
    failures = rejected_runs(root, live['tasks'])
    active += [r for r in live['tasks'] if r['ID'] in failures and r not in active]
    lines += [f'- {r["ID"]} {r["Status"]}: {short(r["Action"], 100)}' + failures.get(r['ID'], '') +
              (f' (blocked: {short(r["Reason"], 120)})' if r['Status'] == 'blocked' else '') for r in active] or ['- none']
    for rid, rest in coverage.dropped_needs(live):
        lines.append(f'- {rid} waits on a dropped task. If it is still wanted: ws set {rid} --set depends={", ".join(rest) or "none"}')
    ready = coverage.ready_task(live)
    if ready:
        lines.append(f'- ready next: {ready["ID"]} {short(ready["Action"], 80)} (acceptance: {short(ready["Acceptance"], 60)})')
        requirement_rows = {r['ID']: r for r in live['requirements']}
        for rid in re.findall(r'\bR[1-9]\d*\b', ready.get('Requirements', ''))[:3]:
            if rid in requirement_rows:
                lines.append(f'  cites {rid}: {short(requirement_rows[rid]["Requirement"], 160)}')
    others = [r for r in upcoming if not ready or r['ID'] != ready['ID']]
    if others:
        lines.append('- also todo: ' + ', '.join(f'{r["ID"]} {short(r["Action"], 40)}' for r in others[:4]))
    preferences = [r for r in live['preferences'] if r['Status'] == 'active']
    if preferences:
        lines.append('')
        shown, left = fitted([f'{r["ID"]} {short(r["Preference"], 120)}' for r in preferences], PREFERENCE_BUDGET)
        lines.append('Preferences: ' + '; '.join(shown) + (f'; {left} more in docs/state/PREFERENCES.md' if left else ''))
    problems = command_problems(root)
    if problems:
        lines.append('')
        lines.append('## Command problems')
        lines.append('')
        lines += problems
    retired = retired_rows(live, data.get('closed') or [])
    if retired:
        lines.append('')
        where = 'state files and ' + CLOSED if data.get('closed') else 'the state files'
        shown, left = fitted([f'{rid} {status}: {short(text, 80)} ({short(reason, 60)})'
                              for rid, status, text, reason in reversed(retired)], RETIRED_BUDGET)
        lines.append(f'Retired, do not rebuild ({len(retired)}, newest first; all in {where}): ' + '; '.join(shown) +
                     (f'; {left} more: python .agents/tools/ws.py brief --retired' if left else ''))
    sessions = logs.live_rows(root, 'SESSION_LOG')[-4:]
    if sessions:
        lines.append('')
        lines.append('## Recent sessions')
        lines.append('')
        lines += [f'- {r["Date"]} {r["Writer"]}{" (note)" if r["Verification"] == "note" else ""}: {short(r["Stop point"], 120)}'
                  for r in reversed(sessions)]
    guides = project_guides(root)
    if guides:
        lines.append('')
        lines.append('## Project guides')
        lines.append('')
        lines += [f'- `{rel}`: {title}' for rel, title in guides]
    lines.append('')
    lines.append('## Unsaved changes')
    lines.append('')
    if info['unsaved_count']:
        names = info['unsaved_changes']['added'] + info['unsaved_changes']['modified'] + info['unsaved_changes']['removed']
        lines.append(f'- {info["unsaved_count"]} files changed after the checkpoint: ' + ', '.join(names[:10]))
    else:
        lines.append('- none' if info['unsaved_count'] == 0 else '- no checkpoint yet')
    if info['mode'] == 'active' and not hooked(root):
        lines.append('')
        lines.append('Hooks: none enabled and no chat saved, so no message of this tool can be checked against the '
                     'state files, and READY cannot tell whether one was missed. Run "ws hooks enable <host>" once for '
                     'each tool you use, or "ws chats import <host>" (.agents/guides/HOSTS.md).')
    lines.append('')
    lines.append('## Next')
    lines.append('')
    from .core import delegated
    if delegated():
        lines.append('1. Read only what your task needs. Do not run ws start, add, set, card, verify or checkpoint.')
        lines.append('2. Report results, decisions and evidence paths to the session that started you.')
        return '\n'.join(lines) + '\n'
    lines.append('1. Read in full: ' + ', '.join(T0[1:]) + '. Add ' + ', '.join(p for p in T1 if p not in T0) + ' before editing. '
                 'Read .agents/guides/PROTOCOL.md "Evidence" before your first verify or checkpoint.')
    lines.append('2. Run: ' + next_command(root, info, sid))
    return '\n'.join(lines) + '\n'


def hooked(root: Path) -> bool:
    """True when a host settings file runs ws.py, or when docs/chats/INDEX.md lists a saved chat."""
    for rel in dict.fromkeys(HOOK_FILES.values()):
        try:
            if 'ws.py' in (root / rel).read_text(encoding='utf-8'):
                return True
        except OSError:
            continue
    try:
        index = (root / 'docs/chats/INDEX.md').read_text(encoding='utf-8')
    except OSError:
        return False
    return any(line.startswith('| 2') for line in index.splitlines())
