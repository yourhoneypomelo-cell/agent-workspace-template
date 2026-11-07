"""ws doctor: a read-only look at what the workspace needs besides its state files: the interpreter and the hook
settings each host runs, how sessions are told apart, and whether the tool files are the ones a release installed.
It reads files inside the project only, never the user's home folder, and writes nothing, not even the cache."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .core import SESSION_VARS, WorkspaceError, config, delegated, env_session, host_process, linked, state_of
from .schema import HOOK_FILES, MANIFEST, SCHEMA, TEMPLATE_MARKER, VERSION

WS = 'python .agents/tools/ws.py'
# The variable each host sets in the commands it runs. A host started from a Cursor agent shell inherits Cursor's
# variable, so that one names the host only when it is the only one set.
HOST_VARS = {'CLAUDE_CODE_SESSION_ID': 'claude', 'CODEX_SESSION_ID': 'codex', 'QWEN_CODE_SESSION_ID': 'qwen',
             'KIRO_SESSION_ID': 'kiro', 'CURSOR_CONVERSATION_ID': 'cursor'}


def run(root: Path) -> dict:
    """Facts, problems (each with the command that fixes it) and advisory notes."""
    report = {'root': str(root), 'version': VERSION, 'python': f'{sys.version.split()[0]} ({sys.executable})',
              'facts': [], 'problems': [], 'notes': []}

    def add(kind: str, area: str, text: str, fix: str | None = None):
        report[kind].append({'area': area, 'text': text, **({'fix': fix} if fix else {})})
    hooks(root, add)
    session(add)
    state(root, add)
    tool(root, add)
    return report


def render(report: dict) -> str:
    lines = [f'ws doctor {report["version"]} for {report["root"]}, Python {report["python"]}', '']
    lines += [f'- {item["area"]}: {item["text"]}' for item in report['facts']]
    for title, items in (('Problems', report['problems']), ('Notes', report['notes'])):
        if items:
            lines += ['', f'{title} ({len(items)}):']
            for n, item in enumerate(items, 1):
                lines.append(f'{n}. {item["area"]}: {item["text"]}')
                if item.get('fix'):
                    lines.append(f'   fix: {item["fix"]}')
    if not report['problems']:
        lines += ['', 'No problems found.']
    return '\n'.join(lines) + '\n'


def current_host() -> str | None:
    named = [host for var, host in HOST_VARS.items() if os.environ.get(var)]
    others = [host for host in named if host != 'cursor']
    return others[0] if len(others) == 1 else ('cursor' if named == ['cursor'] else None)


def _split(command: str) -> tuple:
    """(interpreter words, script path) of a hook command."""
    text = command.replace('\\', '/')
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    words = words[1:] if words[:1] == ['&'] else words  # PowerShell's call operator
    for i, word in enumerate(words):
        if word.endswith('tools/ws.py'):
            return words[:i], word
    return words, ''


def _action(command: str) -> str:
    """What a hook command asks ws.py to do: the words after the script path."""
    found = re.search(r'tools/ws\.py\s+(.*)$', re.sub(r'["\']', ' ', command.replace('\\', '/')))
    return ' '.join(found[1].split()) if found else command


def _script(root: Path, rel: str, script: str) -> str | None:
    """What is wrong with the script path of a hook command, or None when it is this project's ws.py."""
    if not script or '$' in script or '%' in script:
        return None  # a variable such as $CLAUDE_PROJECT_DIR is the host's to resolve
    given = Path(script)
    # Antigravity runs its hooks from .agents/, the folder that holds hooks.json; the other hosts from the project.
    path = given if given.is_absolute() else (root / '.agents' if rel == HOOK_FILES['antigravity'] else root) / given
    if path.resolve() == (root / '.agents/tools/ws.py').resolve():
        return None
    if given.is_absolute():
        return f'runs {script}, the tool of another folder: the project was probably copied or moved'
    return f'runs {script}, which is not the .agents/tools/ws.py of this project'


def _interpreter(words: list, seen: dict) -> str | None:
    """What is wrong with the interpreter of a hook command, or None when it runs Python 3.9 or newer here."""
    command = ' '.join(words)
    if command not in seen:
        found = shutil.which(words[0]) if words else None
        if not words:
            seen[command] = 'names no interpreter'
        elif not found:
            seen[command] = f'"{words[0]}" is not on PATH here'
        elif 'windowsapps' in found.lower():
            seen[command] = f'"{words[0]}" is the Windows Store placeholder, not Python'
        else:
            try:
                done = subprocess.run([found, *words[1:], '-c', 'import sys; print(sys.version_info >= (3, 9))'],
                                      capture_output=True, text=True, timeout=20)
                seen[command] = None if done.stdout.strip() == 'True' else f'"{command}" is older than Python 3.9'
            except (OSError, subprocess.SubprocessError) as error:
                seen[command] = f'"{command}" does not run ({error})'
    return seen[command]


def hooks(root: Path, add):
    from .hooks import OURS, _commands, hook_settings
    enabled, seen = [], {}
    for rel in dict.fromkeys(HOOK_FILES.values()):
        if not (root / rel).is_file():
            continue
        hosts = [host for host, r in HOOK_FILES.items() if r == rel]
        try:
            data = json.loads((root / rel).read_text(encoding='utf-8-sig') or '{}')
        except ValueError as error:
            add('problems', 'hooks', f'{rel} is not valid JSON ({error}), so {hosts[0]} runs none of its hooks',
                f'repair the file, then run: {WS} hooks enable {hosts[0]}')
            continue
        ours = list(dict.fromkeys(c for c in _commands(data) if OURS.search(re.sub(r'["\']', ' ', c.replace('\\', '/')))))
        if not ours:
            continue
        host = next((h for h in hosts if any(f'--hook {h}' in c or f'--host {h}' in c for c in ours)), hosts[0])
        enabled.append(host)
        wrong = [w for c in ours for w in (_script(root, rel, _split(c)[1]), _interpreter(_split(c)[0], seen)) if w]
        expected = {_action(c) for c in _commands(hook_settings(host)[1])}
        present = {_action(c) for c in ours}
        if expected - present:
            wrong.append('missing: ' + ', '.join(sorted(expected - present)))
        if present - expected:
            wrong.append('from an older version: ' + ', '.join(sorted(present - expected)))
        if wrong:
            add('problems', 'hooks', f'{rel} ({host}): ' + '; '.join(dict.fromkeys(wrong)), f'{WS} hooks enable {host}')
        else:
            add('facts', 'hooks', f'{host}: {len(ours)} hook commands in {rel}, run by "{" ".join(_split(ours[0])[0])}"')
    host = current_host()
    if host and host not in enabled:
        # The template checkout is no project: its sessions maintain the tool and need no hooks.
        add('notes' if (root / TEMPLATE_MARKER).is_file() else 'problems', 'hooks', f'this runs in {host}, but '
            f'{HOOK_FILES[host]} holds no hooks of this tool, so a new {host} session starts without the brief and its '
            'transcript is not copied', f'{WS} hooks enable {host}')
    elif not enabled:
        add('notes', 'hooks', 'no host has hooks enabled, so a session sees the brief only when the agent runs it',
            f'{WS} hooks enable <host>; .agents/guides/HOSTS.md lists the hosts')


def session(add):
    named = [name for name in SESSION_VARS if os.environ.get(name)]
    found = None if named else host_process()
    if env_session():
        add('facts', 'session', f'this session is named by {", ".join(named)}')
    elif named:
        add('notes', 'session', f'{", ".join(named)} hold different values, so none of them names this session; ws '
            'falls back to the host process and the key the brief hook prints')
    elif found:
        add('facts', 'session', f'no session variable is set; sessions are told apart by the host process '
            f'({found["name"]}, pid {found["pid"]})')
    else:
        add('notes', 'session', 'no session variable is set and the host process cannot be found, so a session is '
            'known only by the key the brief hook prints', f'{WS} start --session <the key from the brief>')
    if delegated():
        add('facts', 'session', f'WS_ROLE={os.environ["WS_ROLE"]}: this window reads the state and never claims it')


def state(root: Path, add):
    try:
        current = state_of(root)
    except (WorkspaceError, ValueError) as error:
        add('problems', 'state', f'the state line cannot be read: {error}', f'{WS} check')
        return
    if current.get('schema') != SCHEMA:
        add('problems', 'state', f'the workspace declares {current.get("schema")}; this tool reads {SCHEMA}',
            'from a newer template folder: python .agents/tools/ws.py upgrade --target <this project>')
    add('facts', 'state', f'{current.get("schema")}, {current.get("mode")} mode, revision {current.get("revision")}, '
        f'{"owned by " + current["writer"] if current.get("writer") else "released"}')
    try:
        settings = config(root)
    except WorkspaceError as error:
        add('problems', 'config', str(error), f'repair the WORKSPACE block in docs/state/ARCHITECTURE.md, then {WS} check')
        return
    from .capture import import_rule
    rule, since = import_rule(root)
    imports = rule + (f' (WS_IMPORT={os.environ["WS_IMPORT"]})' if os.environ.get('WS_IMPORT') in ('0', '1') else '') + (
        ', chats from before the setup left out' if rule == 'on' and since else '')
    kept = f' in {len(settings["credential_files"])} named files' if settings['credentials'] == 'plain' else ''
    add('facts', 'config', f'ownership {settings["ownership"]}, credentials {settings["credentials"]}{kept}, chat '
        f'import at start {imports}')


def tool(root: Path, add):
    from .distribution import maintainer_leftovers
    from .upgrade import _hash, _local, is_tool_code
    if linked(root / '.agents'):
        add('problems', 'tool', f'.agents is a link to {(root / ".agents").resolve()}, so ws.py reads and writes that '
            'other project', 'replace the link with a copy of the .agents folder')
    from .locks import holder_text, lock_busy
    try:
        add('facts', 'lock', f'held ({holder_text(root)}): a ws command is running' if lock_busy(root) else 'free')
    except WorkspaceError as error:
        add('problems', 'lock', str(error), 'move the project to a local disk, or set WS_LOCK=legacy for this version')
    template = (root / TEMPLATE_MARKER).is_file()
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        add('problems', 'tool', f'{MANIFEST} is missing or unreadable, so an upgrade cannot tell edited files from older '
            'ones', 'from the new template folder: python .agents/tools/ws.py upgrade --target <this project> '
            '--assume-base <the release this project came from>')
        manifest = {}
    if manifest:
        recorded, files = manifest.get('version'), manifest.get('files') or {}
        restore = f'{WS} stamp' if template else (
            f'restore them from the {recorded} release, or from that release folder run: python .agents/tools/ws.py '
            f'upgrade --target "{root}" --overwrite-modified-tools --reason "<what the user said>"')
        if recorded != VERSION:
            add('problems', 'tool', f'the tool says {VERSION} but {MANIFEST} records {recorded}: tool files were copied '
                'in without the manifest', restore)
        code = [rel for rel in files if is_tool_code(rel)]
        differ = [rel for rel in code if _local(root, rel) is None or _hash(_local(root, rel)) != files[rel]]
        if differ:
            add('problems', 'tool', f'{len(differ)} of {len(code)} tool files differ from the manifest of {recorded}, so '
                f'the tool may mix two versions: {", ".join(differ[:6])}', restore)
        else:
            add('facts', 'tool', f'{len(code)} tool files match the manifest of {recorded}')
        extra = sorted(p.relative_to(root).as_posix() for p in (root / '.agents/tools/wslib').glob('*.py')
                       if p.relative_to(root).as_posix() not in files)
        if extra:
            add('notes', 'tool', f'tool modules no release listed: {", ".join(extra[:6])}',
                'remove them unless the project added them on purpose')
    leftovers = maintainer_leftovers(root)
    if leftovers:
        add('problems', 'tool', f'template maintainer files an older install left here: {", ".join(leftovers[:6])}',
            f'{WS} tidy --dry-run, then {WS} tidy')
