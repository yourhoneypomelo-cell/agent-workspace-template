"""Who may run which write command while other sessions work (3.9.0). One table: each command whose rule is more
than "yes" asks it, and PROTOCOL.md prints it, so the rules and the code cannot drift apart.

The caller is known before a command asks: require_owner or require_session has run, and claims.CALLER names a
parallel session, or holds None for the main session. Sessions that may not write at all (a helper started with
WS_ROLE, an old window, a window with no claim while another session owns the workspace) are refused there."""
from __future__ import annotations

from .core import WorkspaceError

# For each command, the rule for the main session and for a parallel session while other sessions work:
#   yes    allowed
#   own    tasks it holds: a parallel session the tasks of its claim, the main session any task no other session holds
#   free   a row that no task of another working session builds on
#   alone  only when no other session is working
#   no     never
TABLE = (
    ('add', '`ws add`, `ws idea`', 'yes', 'yes'),
    ('task', '`ws set` on a task, `ws verify`', 'own', 'own'),
    ('retire', '`ws set` that retires a requirement or feature', 'free', 'free'),
    ('card', '`ws card`', 'yes', 'no'),
    ('workspace', '`ws goal`, `ws compact`, `ws snapshot`', 'alone', 'alone'),
    ('log', '`ws note`, `ws reconcile`', 'yes', 'yes'),
    ('checkpoint', '`ws checkpoint`', 'yes', 'yes, for its own tasks'),
)
RULES = {key: (main, parallel) for key, _, main, parallel in TABLE}
WORDS = {'yes': 'yes', 'own': 'its own tasks', 'free': 'when no task another session holds builds on the row',
         'alone': 'only when no other session is working', 'no': 'no, the card belongs to the main session',
         'yes, for its own tasks': 'yes, for its own tasks'}


def table_markdown() -> str:
    """The permission table of PROTOCOL.md, "Parallel sessions"."""
    rows = ['| Command | Main session | Parallel session |', '| --- | --- | --- |']
    rows += [f'| {words} | {WORDS[main]} | {WORDS[parallel]} |' for _, words, main, parallel in TABLE]
    return '\n'.join(rows) + '\n'


def permit(state: dict, command: str, tasks=(), what='change', row: str | None = None) -> None:
    """Raise WorkspaceError when this session may not run command now. tasks are the tasks it touches; for retire,
    the tasks that build on row."""
    from .claims import CALLER, holders, label_of
    parallel = CALLER.get()
    rule = RULES[command][1 if parallel else 0]
    others = holders(state, exclude=label_of(state))
    if rule == 'no':
        raise WorkspaceError('the card belongs to the main session. A parallel session records its stop point and next '
                             'step with "ws checkpoint --keep --stop ... --next ..."')
    if rule == 'alone' and others:
        raise WorkspaceError(f'{what} changes the whole workspace, and {", ".join(l for l, _ in others)} is still working. '
                             'Wait until it checkpoints, or ask the user')
    for label, scope in others if rule in ('own', 'free') else []:
        taken = sorted(set(scope['tasks']) & set(tasks))
        if taken and rule == 'own':
            raise WorkspaceError(f'{", ".join(taken)} belongs to {label}, which is still working, so this session must '
                                 f'not {what} it. Ask the user; that session records its own tasks')
        if taken:
            raise WorkspaceError(f'{", ".join(taken)} builds on {row} and belongs to {label}, which is still working, '
                                 f'so this session must not retire {row}. Ask the user; that session records its own tasks')
    if rule == 'own' and parallel:
        # A task outside the claim would be left out of its release, and the main checkpoint could not seal it.
        held = set(((state.get('claims') or {}).get(parallel) or {}).get('scope', {}).get('tasks') or [])
        outside = sorted(set(tasks) - held)
        if outside:
            raise WorkspaceError(f'{", ".join(outside)} is not in the claim of this session, so it must not {what} it. '
                                 f'Claim it first: ws start --task {outside[0]}')
