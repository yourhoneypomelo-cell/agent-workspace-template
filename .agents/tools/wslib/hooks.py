"""Host hook settings: the file each host reads its hooks from, the entries ws.py writes there, and how a later
"ws hooks enable" recognizes and replaces the tool's own entries while keeping the user's."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .core import WorkspaceError, atomic_write
from .schema import ADAPTERS, HOOK_FILES

HOOK = 'python .agents/tools/ws.py'
HOSTS = ('claude', 'codex', 'cursor', 'gemini', 'copilot', 'kiro', 'antigravity', 'grok', 'codebuddy', 'workbuddy', 'qoder', 'qwen')
# Hosts that read Claude Code's hook format from their own settings file.
CLAUDE_SHAPED = ('codebuddy', 'workbuddy', 'qoder', 'qwen')


# Host hook settings. Every hook calls ws.py, which never fails the host.
def hook_settings(host: str) -> tuple:
    if host in CLAUDE_SHAPED:
        _, settings = hook_settings('claude')
        text = json.dumps(settings).replace('--hook claude', f'--hook {host}').replace('--host claude', f'--host {host}')
        return HOOK_FILES[host], json.loads(text)
    if host == 'claude':
        def entry(cmd):
            return [{'hooks': [{'type': 'command', 'command': cmd}]}]
        return HOOK_FILES[host], {'hooks': {
            'SessionStart': [{'matcher': 'startup|resume|clear|compact',
                              'hooks': [{'type': 'command', 'command': f'{HOOK} brief --hook claude'}]}],
            'UserPromptSubmit': entry(f'{HOOK} turn --hook claude'),
            'PreCompact': entry(f'{HOOK} capture --host claude --event PreCompact'),
            'Stop': entry(f'{HOOK} capture --host claude --event Stop'),
            'SessionEnd': [{'hooks': [{'type': 'command', 'command': f'{HOOK} capture --host claude --event SessionEnd',
                                       'timeout': 10}]}],
        }}
    if host == 'cursor':
        def entry(cmd):
            return [{'command': cmd}]
        return HOOK_FILES[host], {'version': 1, 'hooks': {
            'sessionStart': entry(f'{HOOK} brief --hook cursor'),
            'beforeSubmitPrompt': entry(f'{HOOK} turn --hook cursor'),
            'afterAgentResponse': entry(f'{HOOK} capture --host cursor --event afterAgentResponse'),
            'preCompact': entry(f'{HOOK} capture --host cursor --event preCompact'),
            'stop': entry(f'{HOOK} capture --host cursor --event stop'),
            'sessionEnd': entry(f'{HOOK} capture --host cursor --event sessionEnd'),
        }}
    if host == 'gemini':
        def entry(name, cmd):
            return [{'hooks': [{'name': name, 'type': 'command', 'command': cmd}]}]
        return HOOK_FILES[host], {'hooks': {
            'SessionStart': entry('workspace-brief', f'{HOOK} brief --hook gemini'),
            'BeforeAgent': entry('workspace-turn', f'{HOOK} turn --hook gemini'),
            'PreCompress': entry('workspace-capture', f'{HOOK} capture --host gemini --event PreCompress'),
            'AfterAgent': entry('workspace-capture', f'{HOOK} capture --host gemini --event AfterAgent'),
            'SessionEnd': entry('workspace-capture', f'{HOOK} capture --host gemini --event SessionEnd'),
        }}
    if host == 'codex':
        def entry(cmd, **timeout):
            # Codex runs "command" through a POSIX shell; commandWindows is its documented Windows override.
            return [{'hooks': [{'type': 'command', 'command': cmd, 'commandWindows': cmd, **timeout}]}]
        return HOOK_FILES[host], {'hooks': {
            'SessionStart': entry(f'{HOOK} brief --hook codex'),
            'UserPromptSubmit': entry(f'{HOOK} turn --hook codex'),
            'PreCompact': entry(f'{HOOK} capture --host codex --event PreCompact'),
            'Stop': entry(f'{HOOK} capture --host codex --event Stop'),
            # Codex gives SessionEnd one second unless told otherwise, and three at most.
            'SessionEnd': entry(f'{HOOK} capture --host codex --event SessionEnd', timeout=3),
        }}
    if host == 'grok':
        def entry(cmd):
            return [{'hooks': [{'type': 'command', 'command': cmd, 'timeout': 30}]}]
        return HOOK_FILES[host], {'hooks': {
            'PreCompact': entry(f'{HOOK} capture --host grok --event PreCompact'),
            'Stop': entry(f'{HOOK} capture --host grok --event Stop'),
            'SessionEnd': entry(f'{HOOK} capture --host grok --event SessionEnd'),
        }}
    if host == 'kiro':
        return HOOK_FILES[host], {'version': 'v1', 'hooks': [
            {'name': 'workspace-brief', 'trigger': 'SessionStart',
             'action': {'type': 'command', 'command': f'{HOOK} brief --hook kiro'}},
            {'name': 'workspace-turn', 'trigger': 'UserPromptSubmit',
             'action': {'type': 'command', 'command': f'{HOOK} turn --hook kiro'}},
            {'name': 'workspace-stop', 'trigger': 'Stop',
             'action': {'type': 'command', 'command': f'{HOOK} capture --host kiro --event Stop'}},
        ]}
    if host == 'antigravity':
        # Antigravity runs hook commands from the folder that holds hooks.json, which is .agents/.
        local = 'python tools/ws.py'
        return HOOK_FILES[host], {
            'workspace-brief': {'SessionStart': [{'type': 'command', 'command': f'{local} brief --hook antigravity', 'timeout': 30}]},
            'workspace-turn': {'PreInvocation': [{'type': 'command', 'command': f'{local} turn --hook antigravity', 'timeout': 30}]},
            'workspace-capture': {'Stop': [{'type': 'command', 'command': f'{local} capture --host antigravity --event Stop', 'timeout': 30}]},
        }

    def entry(cmd):
        return [{'type': 'command', 'bash': cmd, 'powershell': cmd, 'timeoutSec': 30}]
    return HOOK_FILES['copilot'], {'version': 1, 'hooks': {
        'sessionStart': entry(f'{HOOK} brief --hook copilot'),
        'preCompact': entry(f'{HOOK} capture --host copilot --event preCompact'),
        'agentStop': entry(f'{HOOK} capture --host copilot --event agentStop'),
        'sessionEnd': entry(f'{HOOK} capture --host copilot --event sessionEnd'),
    }}


OURS = re.compile(r'(?:^|[\s/])(?:\.agents/)?tools/ws\.py\s+(?:brief|turn|capture)\b')
COMMAND_KEYS = ('command', 'bash', 'powershell', 'commandWindows')


def _commands(value) -> list:
    """The command strings in a hook entry, under whichever key the host uses."""
    if isinstance(value, dict):
        return [c for k, v in value.items() for c in ([v] if k in COMMAND_KEYS and isinstance(v, str) else _commands(v))]
    if isinstance(value, list):
        return [c for item in value for c in _commands(item)]
    return []


def _is_ours(entry) -> bool:
    """A hook entry this tool wrote: a command runs ws.py brief, turn or capture, with any interpreter and the path
    relative, absolute, quoted or through a variable such as $CLAUDE_PROJECT_DIR."""
    return any(OURS.search(re.sub(r'["\']', ' ', c.replace('\\', '/'))) for c in _commands(entry))


def interpreter() -> str:
    """The first of python, python3 and py -3 that runs Python 3.10 or newer here; the Windows Store placeholder does
    not count. Hook files keep the command name, not a path: they travel with the project to other machines."""
    import shutil
    import subprocess
    for command in (['python'], ['python3'], ['py', '-3']):
        found = shutil.which(command[0])
        if not found or 'windowsapps' in found.lower():
            continue
        try:
            done = subprocess.run([found, *command[1:], '-c', 'import sys; print(sys.version_info >= (3, 10))'],
                                  capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.stdout.strip() == 'True':
            return ' '.join(command)
    return 'python'


def with_python(value, python: str):
    """Hook settings whose commands start with the given interpreter command instead of python."""
    if isinstance(value, dict):
        return {k: python + v[6:] if k in COMMAND_KEYS and isinstance(v, str) and v.startswith('python ')
                else with_python(v, python) for k, v in value.items()}
    if isinstance(value, list):
        return [with_python(item, python) for item in value]
    return value


def merge_hooks(existing, ours: dict) -> dict:
    """Add our hooks to a host settings file. User hooks are kept; our older entries are replaced."""
    if not isinstance(existing, dict):
        raise WorkspaceError('the hook settings file must hold a JSON object at the top level')
    result = dict(existing)
    for key, value in ours.items():
        if key.startswith('workspace-'):
            result[key] = value  # Antigravity named hook groups: always the current definition
            continue
        if key != 'hooks':
            result.setdefault(key, value)
            continue
        current = result.get('hooks')
        if isinstance(value, list):
            if current is None:
                current = []
            if not isinstance(current, list):
                raise WorkspaceError('"hooks" in the settings file must be a list for this host')
            names = {item['name'] for item in value}
            kept = [item for item in current if not (isinstance(item, dict) and item.get('name') in names) and not _is_ours(item)]
            result['hooks'] = kept + value
            continue
        if current is None:
            current = {}
        if not isinstance(current, dict):
            raise WorkspaceError('"hooks" in the settings file must be an object that maps event names to lists')
        hooks = dict(current)
        for event, entries in value.items():
            present = hooks.get(event) or []
            if not isinstance(present, list):
                raise WorkspaceError(f'hooks.{event} in the settings file must be a list')
            for item in present:
                if not isinstance(item, dict) or ('hooks' in item and not isinstance(item['hooks'], list)):
                    raise WorkspaceError(f'hooks.{event} holds an entry that is not a hook object; fix the file first')
            hooks[event] = [item for item in present if not _is_ours(item)] + entries
        result['hooks'] = hooks
    return result


LEGACY_HOOK_FILES = {'kiro': ('.kiro/hooks/workspace-brief.json',)}


def enable_hooks(root: Path, host: str, show: bool, python: str | None = None):
    rel, settings = hook_settings(host)
    settings = with_python(settings, python or interpreter())
    path = root / rel
    for old in LEGACY_HOOK_FILES.get(host, ()):
        legacy = root / old
        if not show and legacy.is_file() and 'ws.py' in legacy.read_text(encoding='utf-8', errors='replace'):
            legacy.unlink()
            print(f'Removed {old}; its hooks moved to {rel}.')
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding='utf-8') or '{}')
        except ValueError as error:
            raise WorkspaceError(f'{rel} is not valid JSON ({error}); fix it before enabling hooks')
    merged = merge_hooks(existing, settings)
    text = json.dumps(merged, indent=2) + '\n'
    if show:
        print(f'# {rel}\n{text}')
        return
    backup = root / backup_path(rel)
    if path.is_file() and not backup.exists() and without_ours(existing) == existing:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
    atomic_write(path, text)
    print(json.dumps({'written': rel, 'host': host}))
    print('Hooks are active in new sessions. See .agents/guides/HOSTS.md for what each hook does.')
    _settle(root, rel, f'hooks enable {host}: {rel} rewritten')


# The settings file as it was before the first "hooks enable", so "hooks disable" can give it back byte for byte.
HOOK_BACKUPS = 'docs/archive/hook-backups'


def backup_path(rel: str) -> str:
    return f'{HOOK_BACKUPS}/{rel.replace("/", "__")}'


def without_ours(data: dict) -> dict:
    """A settings object without this tool's hook entries and named groups."""
    result = {k: v for k, v in data.items() if not k.startswith('workspace-')}
    hooks = result.get('hooks')
    if isinstance(hooks, list):
        result['hooks'] = [item for item in hooks if not _is_ours(item)]
    elif isinstance(hooks, dict):
        kept = {event: [i for i in v if not _is_ours(i)] if isinstance(v, list) else v for event, v in hooks.items()}
        result['hooks'] = {event: v for event, v in kept.items() if v != [] or hooks[event] == []}
    return result


def disable_hooks(root: Path, host: str):
    """Take this tool's entries out of a host settings file. The file gets its bytes from before the first enable
    back when nothing else changed since; a file left with no hooks at all is removed."""
    rel = HOOK_FILES[host]
    path, backup = root / rel, root / backup_path(rel)
    if not path.is_file():
        print(json.dumps({'removed': False, 'host': host, 'file': rel}))
        return
    try:
        current = json.loads(path.read_text(encoding='utf-8') or '{}')
    except ValueError as error:
        raise WorkspaceError(f'{rel} is not valid JSON ({error}); fix it before disabling hooks')
    if not isinstance(current, dict):
        raise WorkspaceError(f'{rel} must hold a JSON object at the top level')
    left = without_ours(current)

    def bare(data: dict) -> dict:
        return {k: v for k, v in data.items() if not (k == 'hooks' and not v)}
    try:
        saved = backup.read_bytes().decode('utf-8') if backup.is_file() else None
        restored = saved is not None and bare(json.loads(saved or '{}')) == bare(left)
    except ValueError:
        saved, restored = None, False
    if restored:
        atomic_write(path, saved)
    elif all(k == 'version' or (k == 'hooks' and not v) for k, v in left.items()):
        path.unlink()
    else:
        atomic_write(path, json.dumps(left, indent=2) + '\n')
    backup.unlink(missing_ok=True)
    print(json.dumps({'removed': True, 'host': host, 'file': rel, 'restored': restored, 'deleted': not path.exists()}))
    _settle(root, rel, f'hooks disable {host}: {rel} rewritten')


def _settle(root: Path, rel: str, note: str):
    """A hook file that is also a watched adapter goes into the checkpoint of a released workspace at once."""
    if rel not in ADAPTERS:
        return
    from .upgrade import rebaseline
    try:
        rebaseline(root, [rel], note)
        print(f'{rel} is also a watched project file; the workspace was released, so its checkpoint now holds it.')
    except WorkspaceError:
        print(f'{rel} is also a watched project file, so the workspace shows it as changed until "ws checkpoint" '
              'saves it.')
