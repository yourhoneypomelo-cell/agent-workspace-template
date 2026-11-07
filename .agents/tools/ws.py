"""Workspace continuity tool. Run "python .agents/tools/ws.py --help" for the command list."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

if sys.version_info < (3, 10):  # before wslib, which needs 3.10; this file keeps to the 3.7 grammar
    print(f'ERROR: ws.py needs Python 3.10 or newer, and {sys.executable} is Python '
          f'{".".join(map(str, sys.version_info[:3]))}. Run it with a newer one, for example '
          '"python3.12 .agents/tools/ws.py ...". On macOS the python3 that comes with the system is 3.9: install '
          'Python from python.org or with Homebrew. For hooks: ws hooks enable <host> --python python3.12', file=sys.stderr)
    if '--hook' in sys.argv or sys.argv[1:2] == ['capture']:  # a hook must never break the host session
        host = sys.argv[sys.argv.index('--hook') + 1] if '--hook' in sys.argv[:-1] else ''
        print({'kiro': '', 'cursor': '{"continue": true}'}.get(host, '{}'))
        sys.exit(0)
    sys.exit(2)

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wslib import capture, distribution, lint, migrate, ops, validate  # noqa: E402
from wslib.core import READ_ONLY, WorkspaceError, configure_stdout, read, session_key  # noqa: E402

READ_ONLY_COMMANDS = ('brief', 'turn', 'status', 'check', 'lint', 'doctor')
from wslib.hooks import (  # noqa: E402,F401  (the tests use hook_settings, _commands, _is_ours, interpreter)
    CLAUDE_SHAPED, HOSTS, _commands, _is_ours, disable_hooks, enable_hooks, hook_settings, interpreter,
)
from wslib.schema import VERSION  # noqa: E402

TOOL = Path(__file__).resolve()
TEMPLATE_ROOT = TOOL.parents[2]

COMMANDS = '''commands:
  brief [--retired]          print the resume summary, or every retired row in full (read-only)
  turn                       print the per-turn reminder used by prompt-submit hooks (read-only)
  note TEXT                  append one progress line to SESSION_LOG; cheap, use it every few turns
  status                     ownership, revision and unsaved files as JSON (read-only)
  check [--ready] [--strict] validate the workspace (read-only)
  init --goal TEXT           first run only: record the goal and claim the workspace
  start [--session KEY]      claim the workspace; with the key the brief hook printed, resume it after compaction
  start --task T5 [--task T6]   claim only these tasks, so another session can work on others in parallel
  add TABLE --set f=v ...    add a row; the ID is assigned and the matching log row written
  set ID --set f=v ...       change a row; status changes and edits are logged
  card --set f=v ...         change handoff card fields
  goal TEXT [--source S]     change the goal when the user widens or narrows it; the old text is logged
  verify [IDs] [--done] -- CMD   run acceptance, store evidence, optionally mark tasks done
  verify --stale             run again every done task whose files changed after it was verified
  checkpoint --stop TEXT --next TEXT [--keep]   save and seal; releases the workspace unless --keep
  compact [--dry-run] [--prune-evidence]        move closed rows to CLOSED_ITEMS.md, roll logs
  snapshot --label NAME [PATHS]                 zip the documents before a large reorganization; no restore
  hooks enable|show|disable HOST  write or remove hook settings: claude, codex, cursor, gemini, copilot, kiro, antigravity,
                             grok, codebuddy, workbuddy, qoder, qwen; --python CMD sets the interpreter command
  capture --host H --event E read a hook payload on stdin and copy the transcript
  chats import HOST          copy this project's sessions from a local store: kimi, codex, antigravity,
                             kiro, cursor, workbuddy, codebuddy, qoder, qwen, gemini, dsh
  reconcile [ID --ids R1,T2 | --reason "chat: ..."]   list user messages not yet matched to rows, or mark one
  reconcile --review [--last N]  the last user messages beside the rows or reasons that account for them
  lint                       advisory layout and wording checks for reusable documents
  doctor [--json]            hooks, interpreter, session identity and tool files at a glance, each problem with its
                             fix (read-only); exit 1 when a problem is found
  tidy [--dry-run] [--force] remove template maintainer files an older install left here; add search ignore files
  upgrade --target DIR       bring a project to this template version (from the new template folder); --dry-run
                             first, --rollback NAME to undo, --scan FOLDER to list the workspaces under a folder
  install --target DIR       copy this template into a project (from the template folder); --merge --dry-run --diff
                             shows what merging would change
  export --output DIR        write a clean template copy and a zip
  migrate                    convert a continuity.v2 workspace in place
  release [--keep-old] [--skip-full REASON]   maintainer: gate, stamp, build and test dist/agent-workspace-<version>.zip
  stamp                      maintainer: update .agents/template/MANIFEST.json only

tables: requirements, questions, preferences, features, tasks, decisions
'''


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='ws.py', description=f'Workspace continuity tool {VERSION}',
                                epilog=COMMANDS, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=None, help='project root (default: the folder that holds .agents)')
    subs = p.add_subparsers(dest='command', required=True, metavar='COMMAND')

    def owned(sub):
        sub.add_argument('--writer', help='session label; required with shared ownership')
        sub.add_argument('--rev', type=int, help='expected revision; required with shared ownership')
        return sub

    brief = subs.add_parser('brief')
    brief.add_argument('--hook', choices=HOSTS, help='print in the session-start hook format of this host')
    brief.add_argument('--retired', action='store_true', help='list every retired row in full, newest first')
    turn = subs.add_parser('turn')
    turn.add_argument('--hook', choices=HOSTS, help='print in the prompt-submit hook format of this host')
    note = subs.add_parser('note')
    note.add_argument('text', nargs='+')
    subs.add_parser('status')
    check = subs.add_parser('check')
    check.add_argument('--ready', action='store_true', help='also require a released, sealed workspace')
    check.add_argument('--strict', action='store_true', help='also check links in reusable documents')
    check.add_argument('--adapters', action='store_true', help='also check adapters marked pending')
    init = subs.add_parser('init')
    init.add_argument('--goal', required=True)
    init.add_argument('--writer')
    init.add_argument('--session', help='session key printed by the brief hook')
    start = subs.add_parser('start')
    start.add_argument('--writer')
    start.add_argument('--session', help='session key printed by the brief hook; resumes ownership after compaction')
    start.add_argument('--force', action='store_true', help='take over although the owner window still runs or ownership is shared; give --reason')
    start.add_argument('--task', action='append', default=[], metavar='ID',
                       help='claim only these tasks, so another session can work on others at the same time')
    start.add_argument('--reason')
    add = owned(subs.add_parser('add'))
    add.add_argument('table')
    add.add_argument('--set', action='append', default=[], metavar='FIELD=VALUE')
    add.add_argument('--source', help='where this came from, for example "user 2026-10-31"')
    set_ = owned(subs.add_parser('set'))
    set_.add_argument('id')
    set_.add_argument('--set', action='append', default=[], metavar='FIELD=VALUE', required=True)
    set_.add_argument('--source')
    set_.add_argument('--move-detail', metavar='PATH',
                      help='append the full current row to PATH under docs/specs/ or docs/reports/, then apply --set')
    card = owned(subs.add_parser('card'))
    card.add_argument('--set', action='append', default=[], metavar='FIELD=VALUE', required=True)
    goal = owned(subs.add_parser('goal'))
    goal.add_argument('text', nargs='+', help='the new goal, one sentence')
    goal.add_argument('--source', help='for example "user 2026-11-05"')
    verify = owned(subs.add_parser('verify'))
    verify.add_argument('ids', nargs='*', metavar='TASK')
    verify.add_argument('--done', action='store_true', help='mark the tasks done when the evidence is accepted')
    verify.add_argument('--kind', choices=('test', 'check'))
    verify.add_argument('--report', choices=('json', 'junit'), help='the command writes a report to $CONTINUITY_REPORT')
    verify.add_argument('--label')
    verify.add_argument('--timeout', type=int, default=900)
    verify.add_argument('--because', help='why the command differs from the task acceptance; logged')
    verify.add_argument('--stale', action='store_true', help='run again every done task whose files changed after it '
                        'was verified, once per acceptance command')
    cp = owned(subs.add_parser('checkpoint'))
    cp.add_argument('--stop', required=True, help='exact stop point, one line')
    cp.add_argument('--next', required=True, help='concrete next step, one line')
    cp.add_argument('--set', action='append', default=[], metavar='FIELD=VALUE', help='other card fields')
    cp.add_argument('--keep', action='store_true', help='keep ownership (intermediate save)')
    compact = owned(subs.add_parser('compact'))
    compact.add_argument('--dry-run', action='store_true')
    compact.add_argument('--prune-evidence', action='store_true', help='delete evidence files no row references')
    snap = subs.add_parser('snapshot', help='zip the documents (and named paths) before a large reorganization')
    snap.add_argument('paths', nargs='*', help='extra product paths to include')
    snap.add_argument('--label', required=True, help='for example before-docs-merge')
    snap.add_argument('--pin', action='store_true', help='never prune this snapshot')
    hooks = subs.add_parser('hooks')
    hooks.add_argument('action', choices=('enable', 'show', 'disable'))
    hooks.add_argument('host', choices=HOSTS)
    hooks.add_argument('--python', metavar='CMD', help='interpreter command the hooks run, such as python3 or "py -3"; '
                       'by default the first of python, python3 and py -3 that is 3.10 or newer')
    cap = subs.add_parser('capture')
    cap.add_argument('--host', required=True)
    cap.add_argument('--event', default='unknown')
    chats = subs.add_parser('chats')
    chats.add_argument('action', choices=('import',))
    chats.add_argument('host', choices=capture.IMPORT_HOSTS)
    rec = subs.add_parser('reconcile')
    rec.add_argument('message', nargs='?', help='message ID from the list, or "all" with --reason')
    rec.add_argument('--ids', help='rows that record the message, for example R4,P2')
    rec.add_argument('--reason', help='why no row is needed: question, chat, duplicate, superseded, out-of-scope, secret')
    rec.add_argument('--limit', type=int, default=20)
    rec.add_argument('--review', action='store_true', help='show the last user messages beside the rows or reasons '
                     'that account for them')
    rec.add_argument('--last', type=int, default=20, help='how many messages --review shows')
    subs.add_parser('lint')
    tidy = subs.add_parser('tidy', help='remove template maintainer files an older install left in this project')
    tidy.add_argument('--dry-run', action='store_true')
    tidy.add_argument('--force', action='store_true', help='also remove maintainer files that differ from this release')
    install = subs.add_parser('install')
    install.add_argument('--target', type=Path, required=True)
    install.add_argument('--dry-run', action='store_true')
    install.add_argument('--merge', action='store_true', help='merge an existing AGENTS.md, CLAUDE.md and .gemini/settings.json')
    install.add_argument('--allow-modified', action='store_true')
    install.add_argument('--diff', action='store_true', help='with --dry-run, print each merge as a diff')
    doctor = subs.add_parser('doctor', help='hooks, interpreter, session identity and tool files at a glance')
    doctor.add_argument('--json', action='store_true')
    up = subs.add_parser('upgrade', help='bring a project to this template version; run from the new template folder')
    up.add_argument('--target', type=Path)
    up.add_argument('--dry-run', action='store_true', help='show the plan and write nothing')
    up.add_argument('--force', action='store_true', help='upgrade although a session works, or roll back past its writes')
    up.add_argument('--reason', help='what the user said, for --force and --overwrite-modified-tools')
    up.add_argument('--assume-base', type=Path, metavar='PACKAGE', help='the older release, a folder or zip, when the '
                    'project has no MANIFEST.json')
    up.add_argument('--no-hooks', action='store_true', help='leave hook settings as they are and list the stale ones')
    up.add_argument('--overwrite-modified-tools', action='store_true', help='back up and replace tool code the project '
                    'changed; needs --reason')
    up.add_argument('--rollback', metavar='NAME', help='put back the files of the upgrade folder NAME')
    up.add_argument('--scan', type=Path, metavar='FOLDER', help='list the workspaces under FOLDER (read-only)')
    up.add_argument('--depth', type=int, default=3)
    export = subs.add_parser('export')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--allow-modified', action='store_true')
    mig = subs.add_parser('migrate')
    mig.add_argument('--target', type=Path, required=True, help='the continuity.v2 project to convert')
    mig.add_argument('--dry-run', action='store_true')
    mig.add_argument('--force', action='store_true', help='migrate even though a v2 writer still holds the workspace')
    rel = subs.add_parser('release')
    rel.add_argument('--keep-old', action='store_true', help='keep packages of earlier versions in dist/')
    rel.add_argument('--skip-full', metavar='REASON', help='release without a passing full self-test run on this code; '
                     'the reason is printed in dist/README.md')
    subs.add_parser('stamp')
    return p


def read_stdin() -> str:
    """Hosts send UTF-8 JSON. Read bytes so the Windows console code page cannot garble it."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ''
        data = sys.stdin.buffer.read()
    except (OSError, ValueError, AttributeError):
        return ''
    for encoding in ('utf-8-sig', 'utf-16'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


def hook_brief(root: Path, host: str):
    """SessionStart hook: print the brief in the format the host injects into context."""
    try:
        payload = json.loads(read_stdin() or '{}')
        raw = capture._first(payload, capture.SESSION_KEYS) if isinstance(payload, dict) else None
    except ValueError:
        raw = None
    try:
        text = ops.brief(root, session_key(raw) if raw else None)
    except Exception as error:  # a hook must never break the host session
        text = f'Workspace brief unavailable ({error}). Read AGENTS.md and run: python .agents/tools/ws.py check'
    text = ('The workspace brief below was printed by ws brief at session start, so step 1 of "Start of every session" '
            'is done. Do not run ws brief again; continue with step 2.\n\n') + text
    if len(text) > BRIEF_LIMIT:
        # Claude Code saves longer hook output to a file and shows the model only a preview.
        text = cut_brief(text, BRIEF_LIMIT - 200)
    if host in ('claude', 'gemini', 'codex', *CLAUDE_SHAPED):
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': text}}))
    elif host == 'antigravity':
        print(json.dumps({'injectSteps': [{'systemMessage': {'systemMessage': text}}]}))
    elif host == 'cursor':
        print(json.dumps({'additional_context': text}))
    elif host == 'copilot':
        print(json.dumps({'additionalContext': text}))
    else:
        print(text)


BRIEF_LIMIT = 9000


def cut_brief(text: str, limit: int) -> str:
    """Shorten a brief for a hook. The Next section holds the start command and session key, so it is kept and
    the sections before it lose their tails first."""
    note = '\n[Brief cut. Run: python .agents/tools/ws.py brief]\n'
    head, sep, tail = text.partition('\n## Next\n')
    tail = sep + tail if sep else ''
    room = max(limit - len(tail) - len(note), 0)
    return head[:room].rsplit('\n', 1)[0] + '\n' + note + tail
COMPACTED = '.agents/cache/compacted'
# Hosts whose session start hook does not run again after compaction; their next per-turn hook adds the brief.
REBRIEF_AFTER_COMPACT = ('gemini', 'antigravity', 'cursor')

TURN_EVENTS = {'claude': 'UserPromptSubmit', 'codex': 'UserPromptSubmit', 'gemini': 'BeforeAgent',
               **{name: 'UserPromptSubmit' for name in CLAUDE_SHAPED}}
PROMPT_IN_PAYLOAD = ('kiro', 'cursor')


def taken_over(root: Path, payload, host: str) -> str:
    """The hook payload names this conversation. When the workspace was claimed with another conversation's brief key,
    or on Cursor under another CURSOR_CONVERSATION_ID, tell this one to stop writing before it does anything. Cursor's
    conversation_id is that variable's value; other hosts' payload ids are not known to match their variables."""
    try:
        raw = capture._first(payload, capture.SESSION_KEYS) if isinstance(payload, dict) else None
        if not raw:
            return ''
        from wslib.core import session_key, state_of
        state = state_of(root)
        owner = state.get('session') or {}
        if not state.get('writer') or owner.get('via') not in (('key', 'env') if host == 'cursor' else ('key',)):
            return ''
        mine = session_key(session_key(raw))
        claimed = {(c.get('session') or {}).get('id') for c in (state.get('claims') or {}).values() if not c.get('released_at')}
        if mine == owner.get('id') or mine in claimed:
            return ''
        return (f'Workspace: {state["writer"]} took over this workspace in another conversation. Do not write with ws '
                'or edit files; tell the user, re-read docs/state/HANDOFF.md, and continue only if the user says this '
                'conversation should take it back with ws start.')
    except Exception:  # a hook must never break the host session
        return ''


def hook_turn(root: Path, host: str):
    """Prompt-submit hook: remind the agent to record before acting. Silent on any failure."""
    raw = read_stdin()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if host == 'antigravity' and isinstance(payload, dict) and payload.get('invocationNum', 0) != 0:
        # PreInvocation fires before every model call; remind only before the first one.
        print('{}')
        return
    if host in PROMPT_IN_PAYLOAD and isinstance(payload, dict):
        # These hosts give hooks no transcript file, so the prompt is saved here, one message per turn.
        try:
            os.environ.setdefault('WS_LOCK_WAIT', '3')
            capture.journal(root, host, payload, 'user', capture._first(payload, capture.PROMPT_KEYS) or '')
        except Exception as error:  # a hook must never break the host session
            print(f'capture skipped: {str(error).splitlines()[0][:200]}', file=sys.stderr)
    kinds = []
    if isinstance(payload, dict):
        from wslib import nudge
        from wslib.coverage import credential_kinds, redact_pasted
        prompt = capture._first(payload, capture.PROMPT_KEYS) or ''
        if prompt and not prompt.startswith(nudge.MESSAGE[:40]):
            # The marker sits in an ignored cache folder, but a pasted key must not land on disk unredacted.
            nudge.remember(root, host, capture.session_name(payload), redact_pasted(prompt[:200])[:80])
        try:
            from wslib.core import CREDENTIALS
            kinds = credential_kinds(prompt) if prompt and CREDENTIALS.get() == 'ask' else []
        except Exception:  # a hook must never break the host session
            kinds = []
    try:
        text = ops.turn_context(root)
    except Exception:  # a hook must never break the host session
        text = ops.turn_reminder(root)
    try:
        from wslib.nudge import turn_record
        record = turn_record(root)
        text = text + ' ' + record if record else text
    except Exception:  # a hook must never break the host session
        pass
    taken = taken_over(root, payload, host)
    if taken:
        text = taken + '\n\n' + text
    if kinds:
        text = SECRET_AGENT.format(', '.join(kinds)) + '\n\n' + text
    marker = root / COMPACTED
    if host in REBRIEF_AFTER_COMPACT and marker.exists():
        try:
            marker.unlink()
            head = text + '\n\nThe context was compacted. Current workspace brief:\n\n'
            raw = capture._first(payload, capture.SESSION_KEYS) if isinstance(payload, dict) else None
            brief = ops.brief(root, session_key(raw) if raw else None)
            room = BRIEF_LIMIT - len(head) - 120
            if len(brief) > room:
                brief = cut_brief(brief, max(room, 0))
            text = head + brief
        except Exception:  # a hook must never break the host session
            pass
    shown = SECRET_USER.format(', '.join(kinds)) if kinds else ''
    if host in TURN_EVENTS:
        out = {'hookSpecificOutput': {'hookEventName': TURN_EVENTS[host], 'additionalContext': text}}
        print(json.dumps({**out, 'systemMessage': shown} if shown else out))
    elif host == 'antigravity':
        print(json.dumps({'injectSteps': [{'ephemeralMessage': text}]}))
    elif host == 'cursor':
        # Cursor drops additional_context longer than 10,000 characters.
        out = {'continue': True, 'additional_context': text[:BRIEF_LIMIT]}
        print(json.dumps({**out, 'user_message': shown} if shown else out))
    else:
        print(text)
        if shown:
            print(shown, file=sys.stderr)


# The credential notice of the prompt hook (B41). It names the kind of credential, never the value, and never blocks.
# It is sent only while the project has no credential rule; after the user decides, the rule speaks for itself.
SECRET_AGENT = ('This message contains a credential ({}). The project has no rule yet for keeping credentials. Use it '
                'for the task, but before writing it into a file, a command, a log or a commit, ask the user once how '
                'this project keeps credentials (as written in a file they name, in environment variables, or out of '
                'files), then record the answer: ws add preference and the WORKSPACE "credentials" setting.')
SECRET_USER = ('Workspace: this message contains a credential ({}). Until you decide how this project keeps credentials, '
               'the agent will ask before writing it anywhere, and saved transcripts are redacted.')


def autosave(root: Path):
    """Stop hook helper: an intermediate checkpoint when WORKSPACE sets "autosave": true and the state is valid.

    It never waits for a busy lock and never writes to stdout, because hosts read hook stdout as JSON."""
    from wslib.core import config, state_of
    previous = os.environ.get('WS_LOCK_WAIT')
    os.environ['WS_LOCK_WAIT'] = '0'
    try:
        if not config(root).get('autosave') or not state_of(root).get('writer'):
            return
        card_now = ops.card(root)
        with contextlib.redirect_stdout(io.StringIO()):
            ops.checkpoint(root, card_now.get('stop_point', 'autosave'), card_now.get('next_step', 'continue'), [], keep=True)
        print('autosave: checkpoint saved', file=sys.stderr)
    except Exception as error:  # never break the host; a refused autosave is fine
        print(f'autosave skipped: {str(error).splitlines()[0][:200]}', file=sys.stderr)
    finally:
        if previous is None:
            os.environ.pop('WS_LOCK_WAIT', None)
        else:
            os.environ['WS_LOCK_WAIT'] = previous


def find_root(start: Path | None) -> Path:
    """The project is the folder that holds this copy of ws.py, wherever the command runs from."""
    if start:
        return start.resolve()
    return TEMPLATE_ROOT


def linked_agents() -> str | None:
    """Where .agents points when it is a symbolic link or a junction: the project found from ws.py would be another."""
    agents = Path(os.path.abspath(__file__)).parents[1]
    try:
        linked = agents.is_symlink() or bool(getattr(os.lstat(agents), 'st_file_attributes', 0) & 0x400)
    except OSError:
        return None
    return str(agents.resolve()) if linked else None


def main(argv=None) -> int:
    configure_stdout()
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = []
    if '--' in argv:
        index = argv.index('--')
        argv, rest = argv[:index], argv[index + 1:]
    args, extra = parser().parse_known_args(argv)
    if extra:
        hint = ''
        if '--set' in argv:
            hint = ('\nA --set value with spaces needs quotes: --set "requirement=Login works". '
                    'In PowerShell use single quotes around the whole field=value')
        print(f'ERROR: unexpected arguments: {" ".join(extra)}{hint}', file=sys.stderr)
        return 2
    target = None if args.root else linked_agents()
    if target:
        print(f'ERROR: .agents in this project is a link to {target}, so ws.py would read and write that other '
              'project. Copy the .agents folder into this project instead of linking it', file=sys.stderr)
        if getattr(args, 'hook', None) or args.command == 'capture':  # a hook must never break the host session
            print({'kiro': '', 'cursor': '{"continue": true}'}.get(getattr(args, 'hook', None), '{}'))
            return 0
        return 2
    root = find_root(args.root)
    if args.command in READ_ONLY_COMMANDS:
        READ_ONLY.set(True)  # the cache is not written; the turn hook still keeps its Stop-nudge marker
    try:
        from wslib.core import CREDENTIALS, config
        CREDENTIALS.set(config(root)['credentials'])
    except Exception:  # a broken or missing WORKSPACE block keeps the cautious default
        pass
    if getattr(args, 'hook', None) and args.command in ('brief', 'turn'):
        try:
            hook_brief(root, args.hook) if args.command == 'brief' else hook_turn(root, args.hook)
        except Exception as error:  # a hook must never break the host session
            print(f'hook skipped: {str(error).splitlines()[0][:200]}', file=sys.stderr)
            print({'kiro': '', 'cursor': '{"continue": true}'}.get(args.hook, '{}'))
        return 0
    try:
        if args.command == 'brief' and args.hook:
            hook_brief(root, args.hook)
        elif args.command == 'brief' and args.retired:
            from wslib.views import retired_list
            print(retired_list(root), end='')
        elif args.command == 'brief':
            print(ops.brief(root), end='')
        elif args.command == 'turn':
            if args.hook:
                hook_turn(root, args.hook)
            else:
                print(ops.turn_context(root))
        elif args.command == 'note':
            ops.note(root, ' '.join(args.text))
        elif args.command == 'status':
            print(json.dumps(ops.status(root), ensure_ascii=False, indent=2))
        elif args.command == 'check':
            errors = validate.validate(root, strict=args.strict, ready=args.ready, adapters=args.adapters)
            for warning in validate.advisories(root):
                print('WARNING: ' + warning)
            for error in errors:
                print('ERROR: ' + error)
            label = 'READY' if args.ready else 'PASS'
            print(f'Workspace: {"FAIL" if errors else label}')
            return 1 if errors else 0
        elif args.command == 'init':
            ops.init(root, args.goal, args.writer, args.session)
        elif args.command == 'start':
            ops.start(root, args.writer, args.force, args.reason, args.session, tasks=[t for v in args.task for t in v.replace(',', ' ').split()])
        elif args.command == 'add':
            ops.add(root, args.table, args.set, args.source, args.writer, args.rev)
        elif args.command == 'set':
            ops.set_row(root, args.id, args.set, args.source, args.writer, args.rev, move_detail=args.move_detail)
        elif args.command == 'card':
            ops.set_card(root, args.set, args.writer, args.rev)
        elif args.command == 'goal':
            ops.set_goal(root, ' '.join(args.text), args.source, args.writer, args.rev)
        elif args.command == 'verify' and args.stale:
            if args.ids or rest or args.done or args.because:
                raise WorkspaceError('verify --stale takes no task IDs, command, --done or --because: it runs each '
                                     "stale task's own acceptance and keeps it done")
            return ops.verify_stale(root, args.timeout, args.writer, args.rev)
        elif args.command == 'verify':
            return ops.verify(root, args.ids, rest, args.done, args.kind, args.report, args.label, args.timeout, args.writer, args.rev,
                              args.because)
        elif args.command == 'checkpoint':
            ops.checkpoint(root, args.stop, args.next, args.set, args.keep, args.writer, args.rev)
        elif args.command == 'compact':
            print(json.dumps(ops.compact(root, args.dry_run, args.prune_evidence, args.writer, args.rev), ensure_ascii=False, indent=2))
        elif args.command == 'snapshot':
            from wslib import snapshot
            result = snapshot.take(root, args.label, args.paths, args.pin)
            print(json.dumps(result, ensure_ascii=False))
            print(f'Saved. Nothing restores it in place: extract with "{result["extract"]}", compare, copy back by hand.')
        elif args.command == 'hooks' and args.action == 'disable':
            disable_hooks(root, args.host)
        elif args.command == 'hooks':
            enable_hooks(root, args.host, args.action == 'show', args.python)
        elif args.command == 'capture':
            # Hosts give hooks a few seconds; a busy workspace must not stall the host.
            os.environ.setdefault('WS_LOCK_WAIT', '3')
            payload = {}
            if args.event.lower() in ('precompact', 'precompress'):
                try:
                    (root / COMPACTED).parent.mkdir(parents=True, exist_ok=True)
                    (root / COMPACTED).write_text(args.host, encoding='utf-8')
                except OSError:
                    pass
            try:
                payload = json.loads(read_stdin() or '{}')
                result = capture.capture(root, args.host, args.event, payload if isinstance(payload, dict) else {})
            except Exception as error:  # a hook must never break the host session
                result = {'captured': False, 'reason': f'{type(error).__name__}: {error}'}
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            if args.event in ('Stop', 'stop', 'agentStop', 'AfterAgent'):
                from wslib import nudge
                body = payload if isinstance(payload, dict) else {}
                text = nudge.check(root, body, capture.session_name(body)) if args.host != 'kiro' else None
                if text:
                    print(nudge.answer(args.host, text))
                    return 0
                autosave(root)
            return 0
        elif args.command == 'chats':
            print(json.dumps(capture.import_sessions(root, args.host), ensure_ascii=False))
        elif args.command == 'reconcile':
            from wslib import reconcile
            if args.review:
                print('\n'.join(reconcile.review(root, args.last)) or 'No user message is saved in docs/chats/.')
            elif args.message:
                print(json.dumps(reconcile.mark(root, args.message, args.ids, args.reason), ensure_ascii=False))
            else:
                open_items = reconcile.pending(root)
                if not open_items:
                    print('All user messages in docs/chats/ are reconciled.')
                bodies = {}
                for mid, rel in open_items[:max(1, args.limit)]:
                    if rel not in bodies:
                        bodies[rel] = reconcile.texts(root / rel)
                    print(f'{mid}  {rel}\n    {" ".join(bodies[rel].get(mid, "").split())[:300]}')
                if len(open_items) > args.limit:
                    print(f'... and {len(open_items) - args.limit} more')
                if open_items:
                    print('\nFor each: ws reconcile <ID> --ids R4,P2   or   ws reconcile <ID> --reason "chat: greeting"')
        elif args.command == 'tidy':
            print(json.dumps(distribution.tidy(root, args.dry_run, args.force), ensure_ascii=False, indent=2))
        elif args.command == 'lint':
            issues = lint.run(root)
            for issue in issues:
                print(issue)
            print(f'Lint: {len(issues)} findings (advisory)')
        elif args.command == 'doctor':
            from wslib import doctor
            report = doctor.run(root)
            print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else doctor.render(report), end='')
            return 1 if report['problems'] else 0
        elif args.command == 'upgrade':
            from wslib import upgrade
            if args.scan:
                for line in upgrade.scan(TEMPLATE_ROOT, args.scan, args.depth):
                    print(json.dumps(line, ensure_ascii=False))
                return 0
            if not args.target:
                raise WorkspaceError('ws upgrade needs --target <project>, or --scan <folder>')
            if args.rollback:
                print(json.dumps(upgrade.rollback(args.target, args.rollback, args.force), ensure_ascii=False))
                return 0
            report = upgrade.run(TEMPLATE_ROOT, args.target, args.dry_run, args.force, args.reason, args.assume_base,
                                 args.no_hooks, args.overwrite_modified_tools)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if report['pending'] and not args.dry_run else 0
        elif args.command == 'install':
            result = distribution.install(TEMPLATE_ROOT, args.target, args.dry_run, args.merge, args.allow_modified,
                                          args.diff)
            diffs = result.pop('diff', {})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            for text in diffs.values():
                print(text)
            if args.dry_run and result['conflicts']:
                return 1
        elif args.command == 'export':
            print(json.dumps(distribution.export(TEMPLATE_ROOT, args.output, args.allow_modified), ensure_ascii=False, indent=2))
        elif args.command == 'migrate':
            print(json.dumps(migrate.migrate(TEMPLATE_ROOT, args.target, args.dry_run, args.force), ensure_ascii=False, indent=2))
        elif args.command == 'release':
            if root != TEMPLATE_ROOT or ops.status(root)['mode'] != 'bootstrap':
                raise WorkspaceError('release runs only in the template folder, which stays in bootstrap mode. '
                                     'A project folder cannot publish the template')
            print(json.dumps(distribution.release(TEMPLATE_ROOT, args.keep_old, args.skip_full), ensure_ascii=False, indent=2))
        elif args.command == 'stamp':
            print(json.dumps(distribution.stamp(TEMPLATE_ROOT), ensure_ascii=False))
    except (WorkspaceError, ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return getattr(error, 'exit_code', 2)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
