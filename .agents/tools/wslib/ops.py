"""Workspace commands. Write commands hold the lock and return the new revision."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import coverage, evidence, logs, tables, validate
from .coverage import redact
from .core import (
    WorkspaceError, atomic_write, card, card_text, checkpoint_of, config, describe_drift, difference, drift_count,
    fingerprint, goal_of, lock, now, preview, read, rewatch, safe_path, save_state, sha, state_of, today, with_goal,
    with_state, write, writer_label, session_identity, same_session, other_session, other_session_text, delegated,
    host_process, host_alive, same_host, other_host, live_host_text,
)
from .schema import CARD_FIELDS, CHECKPOINTS_KEPT, CLOSED, NEEDS_REASON, HANDOFF, LOG_NAMES, NONE, REQUIREMENTS, SCHEMA, TABLES
from .retired import RETIRE_AS, retired_match, retired_nearest
from .views import INIT_CARD, TURN_REMINDER, brief, recent_minutes, stale_card_fields, status, turn_context  # noqa: F401  (re-exported)

SUMMARY_LIMIT = 160


def short(text: str, limit=SUMMARY_LIMIT) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def emit(data: dict):
    print(json.dumps(data, ensure_ascii=False))


# Ownership
def require_owner(root: Path, state: dict, writer: str | None, rev: int | None) -> str:
    cfg = config(root)
    if state['mode'] != 'active':
        raise WorkspaceError('the workspace is not initialized; run "ws.py init --goal ..."')
    for marker in validate.conflict_markers(root)[:1]:
        raise WorkspaceError(marker)
    if delegated():
        raise WorkspaceError(DELEGATED_MESSAGE)
    from .claims import CALLER, caller
    who = caller(state, writer)
    if who not in (None, 'primary'):
        # A parallel session writes under its own claim; guard_tasks stops it touching another session's tasks.
        state['claims'][who]['last_write_at'] = now()
        CALLER.set(who)
        if rev is not None and rev != state['revision']:
            raise WorkspaceError(f'revision conflict: you passed {rev}, the workspace is at {state["revision"]}. Re-read HANDOFF.md')
        return who
    CALLER.set(None)
    # --rev names the revision the caller read, before a resume below takes one more.
    owner, base = state.get('writer'), state['revision']
    if not owner and resume_released(root, state):
        owner = state['writer']
    if not owner:
        raise WorkspaceError('no session owns the workspace; run "ws.py start" first')
    if cfg['ownership'] == 'shared' and (not writer or rev is None):
        raise WorkspaceError('shared ownership requires --writer and --rev on every write')
    if writer and writer != owner or other_session(state):
        raise WorkspaceError(other_session_text(owner, writer or 'this session'))
    if other_host(state):
        raise WorkspaceError(f'{owner} owns the workspace from another window that is still running '
                             f'({live_host_text(state["host"])}), so this window must not write. If you are a subagent '
                             'or side window, report to that session. If the user says that window is finished, run '
                             '"ws.py start --force --reason \"<what the user said>\""')
    if rev is not None and rev != base:
        raise WorkspaceError(f'revision conflict: you passed {rev}, the workspace is at {state["revision"]}. Re-read HANDOFF.md')
    return owner


DELEGATED_MESSAGE = ('this session runs with WS_ROLE set, as a subagent or helper window, so it never writes the '
                     'workspace. Report the result to the session that started it; that session records it')


def resume_released(root: Path, state: dict) -> bool:
    """The session that released the workspace with a checkpoint writes again before anyone else claimed it.

    Only a host session variable proves it is the same session, so a key from a hook or no variable never resumes.
    The claim is saved at once under a revision of its own: a command that takes the lock twice resumes once, and
    the evidence it records belongs to the resumed claim."""
    mine, last = session_identity(), state.get('released') or {}
    if not (mine and mine['via'] == 'env' and last.get('session') == mine['id'] and last.get('writer')):
        return False
    state['revision'] += 1
    state.update(writer=last['writer'], writer_revision=state['revision'], claimed_at=now(), last_write_at=now(),
                 session=mine, released=None, host=host_process())
    save_state(root, state)
    logs.append(root, 'MAINTENANCE_LOG', {'Event': 'resume', 'Detail': f'{last["writer"]} wrote again after its checkpoint'})
    return True


def bump(root: Path, state: dict):
    state['revision'] += 1
    state['last_write_at'] = now()
    save_state(root, state)


def guarded(root: Path, changes: dict):
    """Write files only if the change adds no new validation error. Nothing is written while the check cannot judge
    the workspace as it stands: the errors it misses before the change would hide the ones the change adds."""
    before = validate.semantics(root, sealing=True)
    unchecked = [e for e in before if e.startswith(validate.INCOMPLETE)] or validate.state_line_errors(state_of(root))
    if unchecked:
        raise WorkspaceError('change rejected; no change can be checked until these are repaired ("ws check" lists '
                             'every problem):\n  ' + '\n  '.join(unchecked))
    with preview(changes):
        after = set(validate.semantics(root, sealing=True))
    new = sorted(after - set(before))
    if new:
        raise WorkspaceError('change rejected; it would introduce:\n  ' + '\n  '.join(new))
    for rel, text in changes.items():
        write(root, rel, text)


def ledger(root: Path) -> dict:
    state = state_of(root)
    cp = checkpoint_of(root, state)
    return (cp or {}).get('ledger') or {}


# Lifecycle
def init(root: Path, goal_text: str, writer: str | None, session: str | None = None):
    goal_text = redact(' '.join(goal_text.split()))
    if not goal_text:
        raise WorkspaceError('--goal must be one non-empty sentence')
    with lock(root):
        state = state_of(root)
        if state['mode'] != 'bootstrap' or state.get('writer'):
            raise WorkspaceError('init only runs once, on a bootstrap workspace. Use "ws.py start" to resume')
        writer = writer or writer_label()
        requirements = with_goal(read(root, REQUIREMENTS), goal_text)
        handoff = card_text(read(root, HANDOFF), {
            **INIT_CARD,
            'stop_point': 'Goal recorded; the project has not been inspected',
            'next_step': 'Inspect code, configuration and tests; fill ARCHITECTURE.md; add the first requirements; checkpoint',
            'recovery_notes': 'No running processes',
        })
        state.update(mode='active', revision=state['revision'] + 1, writer=writer,
                     writer_revision=state['revision'] + 1, claimed_at=now(), session=session_identity(session),
                     last_write_at=now(), host=host_process())
        write(root, HANDOFF, with_state(handoff, state))
        write(root, REQUIREMENTS, requirements)
        logs.append(root, 'REQUIREMENT_LOG', {'ID': 'goal', 'Event': 'set', 'Detail': short(goal_text), 'Source': 'user'})
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'init', 'Detail': f'writer {writer}; schema {SCHEMA}'})
        # Seal at once, so a session that dies before its first checkpoint still leaves a change baseline.
        state['checkpoint'] = seal(root, writer)
        save_state(root, state)
    emit({'mode': 'active', 'revision': state['revision'], 'writer': writer})


def start(root: Path, writer: str | None, force: bool, reason: str | None, session: str | None = None, tasks=()):
    with lock(root):
        state = state_of(root)
        if state['mode'] != 'active':
            raise WorkspaceError('the workspace is not initialized; run "ws.py init --goal ..."')
        if delegated():
            raise WorkspaceError(DELEGATED_MESSAGE + '. Read docs/state/ instead of claiming it')
        cfg = config(root)
        previous = state.get('writer')
        mine = session_identity(session)
        from . import claims
        notes = []
        if previous and (writer == previous and not other_session(state, mine) or not writer and same_session(state, mine)):
            if tasks:
                state['scope'] = claims.rescope(root, state, previous, tasks, force, reason, notes) or state.get('scope')
                save_state(root, state)
            emit({'writer': previous, 'revision': state['revision'], 'resumed': True})
            print('\n'.join(['Same session resumed; continue the recorded next step.', *notes]))
            return
        own = claims.caller(state, writer)
        if own not in (None, 'primary'):
            entry = state['claims'][own]
            if tasks:
                entry['scope'] = claims.rescope(root, state, own, tasks, force, reason, notes) or entry['scope']
            entry['last_write_at'] = now()
            save_state(root, state)
            emit({'writer': own, 'revision': state['revision'], 'resumed': True, 'parallel': True})
            print('\n'.join(['Same parallel session resumed; continue its next step in "Parallel sessions" of HANDOFF.md.',
                             *notes]))
            return
        working = claims.holders(state)
        if working and (tasks or not force):
            # Someone is working. Claim beside them when the scopes do not meet, refuse when they do.
            scope = claims.scope_of(root, list(tasks)) if tasks else claims.WHOLE
            found = claims.clashes(state, scope)
            # Nothing tells two chats in one window apart, so the caller may be the conversation that holds it.
            same_window = (not mine and previous in dict(found) and same_host(state.get('host'), host_process())
                           and (state.get('session') or {}).get('via') != 'env')
            if found and not force and same_window:
                minutes = recent_minutes(state)
                raise WorkspaceError(
                    f'this claim collides with work in progress: {claims.clash_text(found)}. This window already holds '
                    f'the workspace as {previous}' + (f', last written {minutes} min ago' if minutes is not None else '') +
                    '. If you are that conversation, go on without a new start. If you are another conversation in this '
                    'window, ask the user, or claim tasks whose Scope names other paths and resources with '
                    '"ws start --task <ID>". If the user says that conversation is finished, add --force --reason '
                    '"<what the user said>"')
            if found and not force:
                raise WorkspaceError(claims.collision(found))
            label = writer or writer_label()
            state['claims'] = state.get('claims') or {}
            state['claims'][label] = {
                'scope': scope, 'session': mine, 'host': host_process(), 'claimed_at': now(), 'last_write_at': now(),
                'stop_point': None, 'next_step': None}
            state['revision'] += 1
            save_state(root, state)
            detail = f'{label} claimed {", ".join(scope["tasks"]) or "the whole tree"} beside {", ".join(l for l, _ in working)}'
            if found:
                detail += f'; forced over {claims.clash_text(found)}; {redact(reason or "no reason given")}'
            logs.append(root, 'MAINTENANCE_LOG', {'Event': 'parallel claim' + (' forced' if found else ''),
                                                  'Detail': short(detail, 400)})
            emit({'writer': label, 'revision': state['revision'], 'parallel': True, 'tasks': scope['tasks']})
            print(f'Claimed {", ".join(scope["tasks"]) or "the whole tree"} beside the sessions already working. Write only '
                  'within that scope; your stop point and next step go in "Parallel sessions" of HANDOFF.md at checkpoint.')
            return
        cp = checkpoint_of(root, state)
        changes = difference(rewatch(root, cp['files']), fingerprint(root)) if cp else {'added': [], 'removed': [], 'modified': []}
        notes_since = []
        for row in logs.live_rows(root, 'SESSION_LOG'):
            if row['Verification'] != 'note':
                notes_since = []
            elif row['Writer'] == previous:
                notes_since.append(row)
        if previous and cfg['ownership'] == 'shared' and not force:
            raise WorkspaceError(f'{previous} owns the workspace (shared ownership). Confirm that session has '
                                 'stopped, then run "ws.py start --force --reason ..."')
        mine_host = host_process()
        owner_alive = host_alive(state.get('host')) if previous else None
        if previous and same_host(state.get('host'), mine_host):
            # One application window: its chats share the process, so the session variable or brief key decides.
            owner_alive = None
        elif previous and owner_alive and not force:
            raise WorkspaceError(
                f'{previous} owns the workspace and its window is still running ({live_host_text(state["host"])}). '
                'Do not take it over from a subagent, side window or read-only question. If the user says that window '
                'is finished or should stop, run "ws.py start --force --reason \"<what the user said>\""')
        recent = recent_minutes(state)
        last = state.get('released') or {}
        if not previous and not writer and mine and mine['via'] == 'env' and last.get('session') == mine['id']:
            writer = last.get('writer')  # the same conversation claims again after its own checkpoint: one label
        writer = writer or writer_label()
        state.update(writer=writer, revision=state['revision'] + 1, writer_revision=state['revision'] + 1, claimed_at=now(),
                     session=mine, released=None, last_write_at=now(), host=mine_host,
                     scope=claims.scope_of(root, list(tasks)) if tasks else None)
        # Claims whose windows have gone are dropped; the brief and start listed their unsaved files. Released rows
        # stay until the next seal, so the new owner reads where those sessions stopped.
        state['claims'] = {k: v for k, v in (state.get('claims') or {}).items()
                           if claims.alive(v) or v.get('released_at')} or None
        save_state(root, state)
        if previous or drift_count(changes):
            detail = f'{previous or "none"} -> {writer}; unsaved changes: {describe_drift(changes, 8)}'
            if previous:
                detail += {True: '; its window was still running (--force)', False: '; its window had exited',
                           None: '; its window could not be checked'}[owner_alive]
            if reason:
                detail += f'; {redact(reason)}'
            logs.append(root, 'MAINTENANCE_LOG', {'Event': 'takeover' if previous else 'start', 'Detail': short(detail, 400)})
    imported = {}
    if os.environ.get('WS_IMPORT', '1') != '0':
        from .capture import import_all
        imported = import_all(root)
    problems = validate.semantics(root, sealing=True)
    emit({'writer': writer, 'revision': state['revision'], 'took_over_from': previous, 'unsaved_changes': changes,
          'imported_sessions': imported})
    if previous and owner_alive is False:
        print(f'The previous owner {previous} ran in a window that has exited, so this takeover is safe.')
    elif previous and recent is not None and owner_alive is None:
        print(f'WARNING: {previous} wrote {recent} min ago; another conversation may still be working in this folder. '
              'A subagent, side window or read-only question must not claim it: set WS_ROLE=worker and leave the '
              'workspace to that session. Otherwise ask the user which window continues; the other must stop writing.')
    if previous:
        print(f'The previous session ({previous}) did not release the workspace with a final checkpoint. Read '
              '.agents/skills/maintain-project-state/SKILL.md, "Resume", before editing.')
        for row in notes_since[-5:]:
            print(f'  its note: {row["Stop point"]}')
    work = {k: [n for n in v if not n.startswith('docs/logs/')] for k, v in changes.items()}
    if drift_count(work):
        print(f'Files changed after the last checkpoint: {describe_drift(work, 20)}')
        print('Inspect them before editing. They may hold unfinished work from the previous session. How to sort '
              'finished, half-done and noise files: .agents/skills/maintain-project-state/SKILL.md, "Resume".')
    for problem in problems:
        print('WARNING: ' + problem)
    for message in validate.advisories(root):
        print('NOTE: ' + message)


def note(root: Path, text: str):
    """One progress line in SESSION_LOG. No validation and no seal, so it is cheap enough for every turn."""
    text = ' '.join(text.split())
    if not text:
        raise WorkspaceError('ws note needs a one-line text')
    from .coverage import redact
    if delegated():
        raise WorkspaceError(DELEGATED_MESSAGE)
    with lock(root):
        state = state_of(root)
        if state['mode'] != 'active':
            raise WorkspaceError('the workspace is not initialized; run "ws.py init --goal ..."')
        from .core import require_session
        from .claims import CALLER
        require_session(root, state)
        writer = CALLER.get() or state.get('writer')
        if not writer:
            raise WorkspaceError('no session owns the workspace, so a note would leave it unsaved. Run "ws start" first')
        logs.append(root, 'SESSION_LOG', {'Writer': writer, 'Stop point': short(redact(text), 200), 'Next step': NONE,
                                          'Verification': 'note', 'Changes': NONE})
        state['last_write_at'] = now()
        save_state(root, state)
    emit({'noted': True, 'writer': writer})


# Checkpoint
def checkpoint(root: Path, stop: str, next_step: str, sets: list, keep: bool, writer=None, rev=None):
    from .rows import card_fields, log_replaced, replaced_card_values
    stop, next_step = redact(' '.join(stop.split())), redact(' '.join(next_step.split()))
    if not stop or not next_step:
        raise WorkspaceError('--stop and --next need one-line descriptions')
    fields = card_fields(sets)
    if {'stop_point', 'next_step'} & fields.keys():
        raise WorkspaceError('use --stop and --next for those two fields')
    fields.update(stop_point=stop, next_step=next_step)
    with lock(root):
        state = state_of(root)
        owner = require_owner(root, state, writer, rev)
        revision = state['revision']
        from . import claims
        if owner in (state.get('claims') or {}):
            state, others, last = parallel_checkpoint(root, state, owner, stop, next_step, keep)
            parallel = True
        else:
            parallel = False
    if parallel:
        return finish_parallel(root, state, owner, keep, others, last)
    with lock(root):
        state = state_of(root)
        # --rev was checked under the first lock, where a resume may have moved the revision.
        owner = require_owner(root, state, writer, None if rev is None else revision)
        stale = stale_card_fields({**card(root), **fields}, root)
        errors = claims.only_mine(state, validate.validate(root, strict=True, sealing=True, card_changes=fields))
        if errors and keep and SYNC_PENDING in read(root, HANDOFF):
            return sync_pending(root, state, owner, fields, errors)
        if errors:
            raise WorkspaceError('checkpoint refused; fix these first:\n  ' + '\n  '.join(errors) +
                                 f'\nIf you must stop now: add the line {SYNC_PENDING} under "Unfinished work" in '
                                 'HANDOFF.md with what is missing, then run this checkpoint again with --keep. It saves '
                                 'the card without sealing; READY stays refused until the errors are fixed')
        previous = checkpoint_of(root, state)
        changes = difference(rewatch(root, previous['files']), fingerprint(root)) if previous else None
        live = validate.gather(root)['live']
        recorded = coverage.session_summary(root, live, previous)
        notices = [message for _, message in coverage.findings(root, live)]
        from .reconcile import summary_line
        from .views import hooked
        line = summary_line(root)
        if line:
            notices.append(line)
        elif not hooked(root):
            notices.append('no chat of this tool is saved, so nobody can check that every user message was recorded. '
                           'Enable hooks or import chats: .agents/guides/HOSTS.md')
        log_replaced(root, replaced_card_values(card(root), fields))
        for rid, field, value in coverage.hand_edits(root, live, previous):
            logs.append(root, 'CHANGE_LOG', {'ID': rid, 'Event': f'{field.lower()} edited outside ws',
                                             'Detail': short('was: ' + value), 'Source': 'checkpoint'})
        write(root, HANDOFF, card_text(read(root, HANDOFF), fields))
        # Linted after the card is written, so the findings are about the card being saved.
        from .lint import NEED_LINK, fix_hint, state_findings
        touched = None if changes is None else {
            n for n in changes.get('added', []) + changes.get('modified', []) if n.startswith('docs/state/')}
        grown = state_findings(root, touched)
        if grown:
            notices.append(f'{len(grown)} findings in the state files changed this session: diary passages, {NEED_LINK}. '
                           'First ones, with a fix that keeps every fact:' + ''.join(
                               f'\n    {short(f, 180)}\n      fix: {fix_hint(f)}' for f in grown[:3]) +
                           ('\n    ... run "ws lint" for the rest' if len(grown) > 3 else ''))
        files = 'first checkpoint' if changes is None else (
            f'{drift_count(changes)} files: ' + describe_drift(changes, 6) if drift_count(changes) else 'state only')
        from .verifying import unverified_counts
        cited = sorted({rel for row in live['tasks'] for rel in evidence.evidence_paths(row.get('Evidence', ''))})
        claimed = unverified_counts(root, stop, cited)
        if claimed:
            notices.append(f'the stop point states {", ".join(claimed[:4])}, which no evidence file reports. Cite the '
                           'evidence path or the verify line instead of retyping a count')
        logs.append(root, 'SESSION_LOG', {
            'Writer': owner, 'Stop point': short(stop, 200), 'Next step': short(next_step, 200),
            'Verification': short(card(root).get('last_verification', NONE), 120),
            'Changes': short(f'{recorded}; {files}', 240)})
        for name in LOG_NAMES:
            logs.archive_if_large(root, name)
        if not keep and not claims_working(state) and state.get('claims'):
            # Released parallel rows were for the sessions still working; their stop points are in SESSION_LOG.
            # Clear them before the seal, so the sealed HANDOFF.md is the one that stays on disk.
            state['claims'] = None
            save_state(root, state)
        pointer = seal(root, owner, state)
        state['checkpoint'] = pointer
        state['revision'] += 1
        state['last_write_at'] = now()
        if not keep:
            state['released'] = {'writer': owner, 'session': (state.get('session') or {}).get('id')} \
                if (state.get('session') or {}).get('via') == 'env' else None
            state['writer'] = None
            state['writer_revision'] = None
            state['session'] = None
            state['host'] = None
        save_state(root, state)
    emit({'revision': state['revision'], 'writer': state['writer'], 'checkpoint': pointer['manifest'], 'recorded': recorded})
    if recorded == 'no new rows':
        print('This session added no requirement, question, preference, decision, task or feature rows. '
              'If the conversation stated any, record them now with "ws add".')
    for notice in notices:
        print('WARNING: ' + notice)
    if stale:
        print('WARNING: card fields still hold the init text: ' + ', '.join(stale) +
              '. Update them: ws card --set phase=... --set "next_acceptance=..." --set "risks=..."')
    if keep:
        print('Ownership kept. Run "ws checkpoint" without --keep when the session ends.')
    if not keep:
        ready = validate.semantics(root, ready=True)
        if ready:
            print('NOT READY:\n  ' + '\n  '.join(ready))
        else:
            print('READY. State is saved and released. READY does not mean every requirement from the '
                  'conversation was recorded; that is still your job.')


SYNC_PENDING = '<!-- SYNC-PENDING -->'


def sync_pending(root: Path, state: dict, owner: str, fields: dict, errors: list):
    """Save what a refused checkpoint can save: the card and one SESSION_LOG row. Nothing is sealed, the owner
    keeps the workspace, and check --ready keeps failing on the marker until the errors are fixed."""
    from .rows import log_replaced, replaced_card_values
    log_replaced(root, replaced_card_values(card(root), fields))
    write(root, HANDOFF, card_text(read(root, HANDOFF), fields))
    logs.append(root, 'SESSION_LOG', {
        'Writer': owner, 'Stop point': short(fields['stop_point'], 200), 'Next step': short(fields['next_step'], 200),
        'Verification': 'sync-pending', 'Changes': short('not sealed: ' + '; '.join(errors), 240)})
    bump(root, state)
    emit({'revision': state['revision'], 'writer': owner, 'checkpoint': None, 'sync_pending': True})
    print('SAVED WITHOUT SEAL (SYNC-PENDING). Ownership kept. Fix these, remove the marker and checkpoint again:\n  ' +
          '\n  '.join(errors))


def claims_working(state: dict) -> list:
    from .claims import alive
    return [k for k, v in (state.get('claims') or {}).items() if not v.get('released_at') and alive(v)]


def parallel_checkpoint(root: Path, state: dict, label: str, stop: str, next_step: str, keep: bool):
    """Checkpoint of a parallel session: its own tasks are checked and its row in "Parallel sessions" is updated.
    The workspace seal and the card stay with the main session, so nothing another session works on is sealed.
    Returns the state, the validation errors outside this session's tasks, and whether it was the last to leave."""
    from .rows import log_replaced, replaced_card_values
    entry = state['claims'][label]
    mine = set(entry['scope']['tasks'])
    found = validate.validate(root, strict=True, sealing=True)
    errors = [e for e in found if set(re.findall(r'\bT[1-9]\d*\b', e)) & mine]
    if errors:
        raise WorkspaceError('checkpoint refused; fix these first:\n  ' + '\n  '.join(errors))
    try:
        edits = coverage.hand_edits(root, validate.gather(root)['live'], checkpoint_of(root, state))
    except (WorkspaceError, ValueError, OSError):
        edits = []  # a broken table or checkpoint is among the errors found above
    for rid, field, value in edits:
        if rid in mine:
            logs.append(root, 'CHANGE_LOG', {'ID': rid, 'Event': f'{field.lower()} edited outside ws',
                                             'Detail': short('was: ' + value), 'Source': 'checkpoint'})
    entry.update(stop_point=stop, next_step=next_step, last_write_at=now())
    logs.append(root, 'SESSION_LOG', {'Writer': label, 'Stop point': short(stop, 200), 'Next step': short(next_step, 200),
                                      'Verification': 'parallel', 'Changes': short('tasks ' + (', '.join(sorted(mine)) or 'none'), 240)})
    last = False
    if not keep:
        # The row stays, marked released, so the next session reads where this one stopped. It no longer holds
        # anything: its scope is cleared, so nobody is refused because of it.
        entry.update(released_at=now(), scope={'tasks': [], 'paths': [], 'resources': []}, released_tasks=sorted(mine))
        last = not state.get('writer') and not claims_working(state)
        if last and not found:
            # The last session to leave hands over the whole workspace: its stop point and next step go on the
            # card, the parallel rows go (their stop points are in SESSION_LOG), and the workspace is sealed.
            # With errors anywhere it only releases: a seal would make them part of the accepted state.
            fields = {'stop_point': stop, 'next_step': next_step}
            log_replaced(root, replaced_card_values(card(root), fields))
            write(root, HANDOFF, card_text(read(root, HANDOFF), fields))
            state['claims'] = None
            state['revision'] += 1
            save_state(root, state)
            state['checkpoint'] = seal(root, label, state)
    state['revision'] += 1
    save_state(root, state)
    return state, found, last


def finish_parallel(root: Path, state: dict, label: str, keep: bool, others: list, last: bool):
    """Report of a parallel checkpoint, after the lock is released, so the READY check sees the final files."""
    emit({'revision': state['revision'], 'writer': label, 'parallel': True, 'released': not keep})
    if last and others:
        print('NOT READY: you were the last session working, and the workspace was released without a seal because '
              'of these errors outside your tasks. The next session fixes them and checkpoints:\n  ' + '\n  '.join(others))
        return
    if last:
        ready = validate.semantics(root, ready=True)
        print('NOT READY:\n  ' + '\n  '.join(ready) if ready else
              'READY. You were the last session working; the card now holds your stop point and next step.')
        return
    print('Saved. Your row in "Parallel sessions" of HANDOFF.md holds the stop point and next step.' if keep else
          'Released. Your row in "Parallel sessions" of HANDOFF.md holds the stop point until the other sessions '
          'finish; the last one to leave seals the workspace.')
    for error in others:
        if not re.search(r'\bT[1-9]\d*\b', error):
            print('WARNING: ' + error)


def seal(root: Path, owner: str, state: dict | None = None) -> dict:
    data = validate.gather(root)
    task_rows = data['live']['tasks']
    state = state or state_of(root)
    previous = checkpoint_of(root, state) if state.get('checkpoint') else None
    from .claims import kept_hashes, theirs
    files_now = kept_hashes(state, previous, fingerprint(root))
    # Tasks other sessions still work on keep what the previous seal recorded, so their evidence is checked in full
    # when they are sealed; this checkpoint skipped their errors.
    deferred = theirs(state) if previous else set()

    def kept(field: str, fresh: dict) -> dict:
        old = (previous or {}).get(field) or {}
        return {**{k: v for k, v in fresh.items() if k not in deferred}, **{k: old[k] for k in deferred if k in old}}

    untracked = coverage.untracked_carry(root, data['live'], previous, files_now)
    sealed = {}
    for row in task_rows:
        if row['Status'] == 'done':
            for rel in evidence.evidence_paths(row.get('Evidence', '')):
                raw = safe_path(root, rel).read_bytes()
                sealed[rel] = sha(raw)
                proof = json.loads(raw)
                if proof.get('report'):
                    sealed[proof['report']['path']] = sha(safe_path(root, proof['report']['path']).read_bytes())
    manifest = {
        'schema': 'checkpoint.v3', 'created_at': now(), 'writer': owner, 'files': files_now,
        'ledger': kept('ledger', validate.ledger(data)),
        'tracking': {k: list(v) for k, v in coverage.tracking_rows(data['live']).items()},
        'untracked': untracked,
        'task_definitions': kept('task_definitions', {r['ID']: evidence.task_definition(r) for r in task_rows}),
        'task_texts': kept('task_texts', coverage.task_texts(task_rows)),
        'task_evidence': kept('task_evidence', {r['ID']: r.get('Evidence', NONE) for r in task_rows}),
        'evidence': sealed,
        'deferred': sorted(deferred),
    }
    stamp = re.sub(r'[^0-9]', '', manifest['created_at'])[:14]
    rel = f'docs/archive/checkpoints/{stamp}-{sha(json.dumps(manifest, sort_keys=True).encode())[:8]}.json'
    raw = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    atomic_write(safe_path(root, rel), raw)
    folder = safe_path(root, 'docs/archive/checkpoints')
    old = sorted(p for p in folder.glob('*.json') if p.name != rel.rsplit('/', 1)[-1])
    for path in old[:max(0, len(old) - (CHECKPOINTS_KEPT - 1))]:
        path.unlink()
    return {'manifest': rel, 'sha256': sha(raw.encode('utf-8')), 'created_at': manifest['created_at']}


# Maintenance
def previous_row_path(rid: str) -> str:
    return f'docs/archive/rows/{rid}.md'


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
            from .claims import require_alone
            require_alone(state, 'ws compact')
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
                    closed_text = tables.append(closed_text, tables.CLOSED_HEADERS, CLOSED, {
                        'ID': row['ID'], 'Status': row['Status'],
                        'Summary': short((f'{row["Requirements"]}: ' if t.key == 'tasks' else '') + row[t.summary], 200),
                        'Reason': short(row.get('Reason') or row.get('Answer') or NONE, 160),
                        'Replacement': row.get('Replacement', NONE), 'Evidence': row.get('Evidence', NONE),
                        'Closed': today(), 'Row': full})
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


MOVED = {
    'runs': ('SHELL_OPERATORS', 'acceptance_argv', 'previous_evidence', 'ship_features', 'verdict_text', 'verify'),
    'rows': ('DETAIL_DIRS', 'add', 'card_fields', 'log_replaced', 'replaced_card_values', 'set_card', 'set_goal',
             'set_row', 'similar_rows', 'split_source', 'task_edits'),
}


def __getattr__(name):
    """Names that moved to runs.py and rows.py, loaded on first use: both import this module, so importing them here
    at load time would break whichever of the three is imported first."""
    for module, names in MOVED.items():
        if name in names:
            import importlib
            return getattr(importlib.import_module(f'{__package__}.{module}'), name)
    raise AttributeError(f'module {__name__} has no attribute {name}')
