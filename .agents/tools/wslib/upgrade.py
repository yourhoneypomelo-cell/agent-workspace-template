"""ws upgrade: bring a project to this template version, file by file, and the rebaseline it ends with.

Each template file is compared three ways: the base B (what the project was installed with, from its MANIFEST.json),
the local L (the project's file now) and the new N (this template). A file nobody edited is replaced; a file the
project edited is kept, merged where its form allows, or set aside for a hand merge. Tool code is all or nothing."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from . import logs
from .core import WorkspaceError, checkpoint_of, fingerprint, lock, now, save_state, sha, state_of
from .evidence import RULES
from .schema import HOOK_FILES, MAINTAINER_FILES, MANIFEST, RUNTIME_FILES, SCHEMA, SEARCH_IGNORE, VERSION

# Files the template owns in a project. Only these and the hook settings may be taken into a checkpoint by a
# rebaseline, so it can never hide a change to the project's own files.
TEMPLATE_OWNED = frozenset({*RUNTIME_FILES, MANIFEST, '.agents/.gitattributes', '.agents/.gitignore',
                            'docs/.gitattributes', 'docs/chats/.gitignore', *SEARCH_IGNORE, *HOOK_FILES.values()})


def rebaseline(root: Path, paths, note: str, upgraded: dict | None = None, removed=()) -> dict:
    """Take the current content of template files and hook settings into the checkpoint of a released workspace,
    keeping everything else it recorded, so a tool or hook change is not reported as unsaved work while product
    changes still are. removed names files an older release shipped and an upgrade deleted; their entries go.
    Returns the new checkpoint pointer."""
    from .ops import claims_working, short, write_checkpoint
    paths, removed = sorted(set(paths)), sorted(set(removed))
    foreign = [p for p in paths if p not in TEMPLATE_OWNED] + \
        [p for p in removed if not _template_file(p) or (root / p).exists()]
    if foreign:
        raise WorkspaceError(f'a rebaseline takes only template files and hook settings, not {foreign[0]}. Project '
                             'files go into the checkpoint with "ws checkpoint"')
    with lock(root):
        state = state_of(root)
        if state.get('writer') or claims_working(state):
            raise WorkspaceError('the workspace is not released, so the session that owns it saves the change with '
                                 '"ws checkpoint"')
        cp = checkpoint_of(root, state)
        if not cp:
            raise WorkspaceError('the workspace has no checkpoint yet; run "ws checkpoint"')
        logs.append(root, 'MAINTENANCE_LOG', {'Event': 'rebaseline', 'Detail': short(note, 300)})
        current, files = fingerprint(root), dict(cp['files'])
        for rel in [*paths, *removed, logs.path_of('MAINTENANCE_LOG')]:
            if rel in current:
                files[rel] = current[rel]
            else:
                files.pop(rel, None)
        done = {'note': short(note, 200), 'paths': paths, **({'removed': removed} if removed else {})}
        manifest = {**cp, 'created_at': now(), 'files': files, 'rebaselined': done}
        if upgraded:
            manifest['upgraded'] = upgraded
        pointer = write_checkpoint(root, manifest)
        state['checkpoint'] = pointer
        state['revision'] += 1
        save_state(root, state)
    return pointer


UPGRADES = 'docs/archive/upgrades'
STAGING = '.agents/cache/upgrade-staging'
RULES_MARK = '\n## Project rules\n'
KEEP_LOCAL = ('CLAUDE.md', 'CODEBUDDY.md', '.gemini/settings.json')


class Blocked(WorkspaceError):
    """The upgrade must not start: exit code 2."""


class RestoreFailed(WorkspaceError):
    """Files could not all be put back; the journal stays at "applying" until a rollback succeeds."""
    exit_code = 3


def _hash(text: str) -> str:
    return sha(text.replace('\r\n', '\n').encode('utf-8'))


def _local(target: Path, rel: str):
    path = target / rel
    return path.read_bytes().decode('utf-8', 'replace').replace('\r\n', '\n') if path.is_file() else None


def is_tool_code(rel: str) -> bool:
    return rel == '.agents/tools/ws.py' or rel.startswith('.agents/tools/wslib/')


def project_version(target: Path) -> str:
    found = re.search(r"^VERSION = '([^']+)'", _local(target, '.agents/tools/wslib/schema.py') or '', re.M)
    return found[1] if found else 'unknown'


def _template_file(rel: str) -> bool:
    """A file a release puts in a project, as opposed to a maintainer file, which ws tidy handles."""
    return (rel.startswith('.agents/') or rel in RUNTIME_FILES) and rel not in MAINTAINER_FILES \
        and not rel.startswith(('.agents/tools/tests/', '.agents/cache/')) and rel != MANIFEST


def _base(target: Path, assume_base: Path | None) -> dict:
    """B: hashes of the template files the project was installed with, from its MANIFEST.json, or from an older
    release package (a folder or a zip) when the manifest is missing."""
    if assume_base and assume_base.is_file():
        import zipfile
        with zipfile.ZipFile(assume_base) as bundle:
            names = [n for n in bundle.namelist() if not n.endswith('/')]
            strip = len({n.split('/', 1)[0] for n in names}) == 1 and all('/' in n for n in names)
            files = {(n.split('/', 1)[1] if strip else n): bundle.read(n).decode('utf-8', 'replace') for n in names}
        return {rel: _hash(text) for rel, text in files.items() if _template_file(rel)}
    if assume_base:
        files = [p.relative_to(assume_base).as_posix() for p in assume_base.rglob('*') if p.is_file()]
        return {rel: _hash(_local(assume_base, rel)) for rel in files if _template_file(rel)}
    try:
        files = json.loads(_local(target, MANIFEST) or '{}').get('files') or {}
    except ValueError:
        files = {}
    return {rel: value for rel, value in files.items() if _template_file(rel)}


def _hook_files(target: Path) -> list:
    from .hooks import _is_ours
    found = []
    for rel in dict.fromkeys(HOOK_FILES.values()):
        try:
            data = json.loads(_local(target, rel) or 'null')
        except ValueError:
            continue
        if isinstance(data, dict) and (_is_ours(data) or any(k.startswith('workspace-') for k in data)):
            found.append(rel)
    return found


def preflight(target: Path, force=False, reason=None):
    """Refuse what an upgrade must not touch. Read-only."""
    from .ops import claims_working
    if not (target / 'docs/state/HANDOFF.md').is_file():
        if (target / 'docs/state/TODO.md').is_file():
            raise Blocked(f'{target} is a continuity.v2 workspace. Convert it first: '
                          f'python .agents/tools/ws.py migrate --target "{target}" --dry-run')
        raise Blocked(f'{target} holds no workspace (docs/state/HANDOFF.md is missing)')
    agents = target / '.agents'
    try:
        linked = agents.is_symlink() or bool(getattr(os.lstat(agents), 'st_file_attributes', 0) & 0x400)
    except OSError:
        linked = False
    if linked:
        raise Blocked(f'{agents} is a link to another folder; an upgrade would change that project too')
    unfinished = [p.parent.name for p in sorted((target / UPGRADES).glob('*/plan.json'))
                  if _journal_state(p.parent) == 'applying']
    if unfinished:
        raise Blocked(f'upgrade {unfinished[0]} was interrupted. Put the files back first with '
                      f'"ws upgrade --target <project> --rollback {unfinished[0]}", then upgrade again')
    state = state_of(target)
    if state.get('schema') != SCHEMA:
        raise Blocked(f'the workspace declares {state.get("schema")}; this tool reads {SCHEMA}. Use a newer tool')
    from .validate import conflict_markers
    for marker in conflict_markers(target)[:1]:
        raise Blocked(marker)
    if (state.get('writer') or claims_working(state)) and not (force and reason):
        raise Blocked(f'{state.get("writer") or "a parallel session"} is working in this workspace. Let it checkpoint, '
                      'or, if the user says so, add --force --reason "<what the user said>"')
    return state


def plan(source: Path, target: Path, assume_base: Path | None = None, overwrite_tools=False) -> dict:
    """Every file operation of an upgrade, without touching anything."""
    from .core import config
    from .distribution import installed_manifest, merged, static_payload
    new, base = static_payload(source), _base(target, assume_base)
    try:
        pending_adapters = set(config(target).get('pending_adapters') or [])
    except (WorkspaceError, ValueError, OSError):
        pending_adapters = set()
    ops, blocked = [], []
    for rel in sorted(set(new) | set(base)):
        local, wanted, was = _local(target, rel), new.get(rel), base.get(rel)
        mine = None if local is None else _hash(local)
        op, text = {'path': rel, 'before': mine}, wanted
        if wanted is None:
            action = 'delete' if mine is not None and mine == was else ('orphan' if mine is not None else 'none')
        elif mine == _hash(wanted):
            action = 'none'
        elif mine is None:
            action = 'skip' if was and rel in pending_adapters else 'write'
            op['note'] = 'deleted in the project' if was else 'new in this version'
        elif mine == was or (is_tool_code(rel) and overwrite_tools):
            action = 'replace'
        elif is_tool_code(rel):
            action = 'blocked'
            blocked.append(rel)
        elif rel == 'AGENTS.md' and RULES_MARK in local and _hash(local.split(RULES_MARK, 1)[0].rstrip('\n') + '\n') == was:
            # The template part is untouched: the new contract goes on top of the project's own rules.
            action, text = 'merge', wanted.rstrip('\n') + '\n' + RULES_MARK + local.split(RULES_MARK, 1)[1]
        elif rel in KEEP_LOCAL:
            text = merged(rel, local, wanted)
            action = 'keep' if _hash(text) == mine else 'merge'
        else:
            action = 'pending'
        op['action'] = action
        if action in ('write', 'replace', 'merge', 'pending'):
            op.update(text=text, after=_hash(text))
        ops.append(op)
    manifest = installed_manifest(source, new)
    changes = [o for o in ops if o['action'] in ('write', 'replace', 'merge', 'delete')]
    if changes or _local(target, MANIFEST) != manifest:
        ops.append({'path': MANIFEST, 'action': 'replace' if (target / MANIFEST).is_file() else 'write',
                    'before': None if _local(target, MANIFEST) is None else _hash(_local(target, MANIFEST)),
                    'after': _hash(manifest), 'text': manifest})
    return {'from': project_version(target), 'to': VERSION, 'operations': ops, 'blocked': blocked,
            'hooks': _hook_files(target)}


def summary(result: dict) -> dict:
    counts = {}
    for op in result['operations']:
        if op['path'] != MANIFEST:
            counts[op['action']] = counts.get(op['action'], 0) + 1
    return {'from': result['from'], 'to': result['to'], 'counts': counts, 'hooks': result['hooks'],
            'pending': [o['path'] for o in result['operations'] if o['action'] == 'pending'],
            'blocked': result['blocked'],
            'orphans': [o['path'] for o in result['operations'] if o['action'] == 'orphan']}


def _check(target: Path, commands=('check',)) -> tuple:
    """(exit code, error lines) of "ws check", then of any other read-only command in commands, run by the project's
    own tool with no cache and no import. A code above 1 means the tool failed."""
    import subprocess
    env = dict(os.environ, WS_NO_CACHE='1', WS_IMPORT='0', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    code, errors = 0, []
    for command in commands:
        try:
            done = subprocess.run([sys.executable, str(target / '.agents/tools/ws.py'), '--root', str(target), command],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
                                  timeout=300)
        except (OSError, subprocess.SubprocessError) as error:
            return 99, errors + [str(error)]
        if done.returncode not in (0, 1) or 'Traceback' in done.stderr:
            return done.returncode or 99, errors + done.stderr.splitlines()[-5:]
        if command == 'check':
            code, errors = done.returncode, [l for l in done.stdout.splitlines() if l.startswith('ERROR')]
    return code, errors


def _hooks_rewrite(target: Path, rels: list) -> dict:
    """New text for each hook file: the tool's entries rewritten with this version's settings, the user's kept."""
    from .hooks import _commands, hook_settings, merge_hooks, with_python
    out = {}
    for rel in rels:
        current = json.loads(_local(target, rel))
        commands = [c.replace('\\', '/') for c in _commands(current)]
        # Hosts that share a file (CodeBuddy and WorkBuddy) keep the one their entries name.
        hosts = [h for h, r in HOOK_FILES.items() if r == rel]
        host = next((h for h in hosts if any(f'--hook {h}' in c or f'--host {h}' in c for c in commands)), hosts[0])
        used = [c.split(' .agents/tools/ws.py', 1)[0].split(' tools/ws.py', 1)[0] for c in commands if 'tools/ws.py' in c]
        settings = with_python(hook_settings(host)[1], used[0] if used else 'python')
        text = json.dumps(merge_hooks(current, settings), indent=2) + '\n'
        if _hash(text) != _hash(_local(target, rel)):
            out[rel] = text
    return out


def run(source: Path, target: Path, dry_run=False, force=False, reason=None, assume_base=None, no_hooks=False,
        overwrite_tools=False) -> dict:
    target = target.absolute()
    if target.resolve() == source.resolve():
        raise Blocked('run ws upgrade from the new template folder, with --target naming the project')
    preflight(target, force, reason)
    if overwrite_tools and not reason:
        raise Blocked('--overwrite-modified-tools needs --reason "<what the user said>"')
    result = plan(source, target, assume_base, overwrite_tools)
    hooks = {} if no_hooks else _hooks_rewrite(target, result['hooks'])
    report = summary(result)
    report['hook_rewrites'] = sorted(hooks)
    if no_hooks:
        report['stale_hooks'] = result['hooks']
    try:
        from . import tables
        from .evidence import rules_notes
        from .schema import TABLES
        report['evidence'] = rules_notes(target, tables.rows(target, TABLES['tasks']))
    except (WorkspaceError, ValueError, OSError):
        report['evidence'] = []
    if result['blocked']:
        raise Blocked('these tool files were changed in the project, so the upgrade would mix two versions: ' +
                      ', '.join(result['blocked'][:6]) + '. Restore them, or add --overwrite-modified-tools --reason '
                      '"<what the user said>" to back them up and replace them')
    if dry_run:
        return report
    changes = [o for o in result['operations'] if o['action'] in ('write', 'replace', 'merge', 'delete')]
    if not changes and not hooks:
        report['changed'] = False
        return report
    needed = 3 * sum(len(o.get('text') or '') for o in result['operations']) + 3 * sum(map(len, hooks.values()))
    if shutil.disk_usage(target).free < needed:
        raise Blocked(f'{target} has less than {needed // 1024 + 1} KB free, which the backup and staging copies need')
    before_code, before_errors = _check(target)
    name = f'{re.sub(r"[^0-9]", "", now())[:14]}-{result["from"]}-to-{result["to"]}'
    folder, n = target / UPGRADES / name, 1
    while folder.exists():
        n += 1
        folder = target / UPGRADES / f'{name}-{n}'
    with lock(target):
        _apply(target, folder, result, hooks, state_of(target))
    touched = [o['path'] for o in changes if o['action'] != 'delete'] + [MANIFEST] + sorted(hooks)
    try:
        rebaseline(target, [p for p in touched if p in TEMPLATE_OWNED], f'upgrade {result["from"]} to {result["to"]}',
                   upgraded={'from': result['from'], 'to': result['to'], 'at': now()},
                   removed=[o['path'] for o in changes if o['action'] == 'delete'])
        report['rebaselined'] = True
    except WorkspaceError as error:
        report['rebaselined'] = False
        report['note'] = f'{error}. The upgraded files show as unsaved changes until then'
    after_code, after_errors = _check(target, ('check', 'brief'))
    # A project the old tool could not read either keeps the upgrade: going back would not help it.
    if after_code not in (0, 1) and before_code in (0, 1):
        rollback(target, folder.name, force=True)
        raise WorkspaceError(f'the new tool failed on this project ({after_errors[-1:]}), so the upgrade was rolled back')
    report.update(changed=True, folder=folder.relative_to(target).as_posix(),
                  new_errors=sorted(set(after_errors) - set(before_errors)), rollback=f'--rollback {folder.name}')
    (folder / 'report.md').write_bytes(('# Upgrade report\n\n```json\n' + json.dumps(report, indent=1) + '\n```\n')
                                       .encode('utf-8'))
    return report


def _journal_state(folder: Path):
    try:
        return json.loads((folder / 'journal.json').read_text(encoding='utf-8')).get('state')
    except (OSError, ValueError, AttributeError):
        return None


def _move(source: Path, path: Path):
    for attempt in range(5):
        try:
            return os.replace(source, path)
        except PermissionError:
            # Windows refuses replacement while an editor or scanner holds the file.
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def _apply(target: Path, folder: Path, result: dict, hooks: dict, state: dict):
    """Back up, stage, then replace file by file, MANIFEST last; the journal says how far it got. An error puts every
    file back, so only a stop nothing can catch (a killed process, a power cut) leaves the journal at "applying"."""
    from .core import atomic_write
    backup, staging = folder / 'backup', target / STAGING
    ops = [o for o in result['operations'] if o['action'] in ('write', 'replace', 'merge', 'delete')]
    ops += [{'path': rel, 'action': 'replace', 'before': _hash(_local(target, rel)), 'after': _hash(text), 'text': text}
            for rel, text in hooks.items()]
    ops.sort(key=lambda o: o['path'] == MANIFEST)
    keep = ['docs/state/HANDOFF.md', logs.path_of('MAINTENANCE_LOG')]
    try:
        keep.append(state['checkpoint']['manifest'])
    except (KeyError, TypeError):
        pass
    doc = {'from': result['from'], 'to': result['to'], 'revision': state.get('revision'),
           'operations': [{k: v for k, v in o.items() if k != 'text'} for o in ops], 'kept': keep}
    folder.mkdir(parents=True)
    try:
        (folder / 'plan.json').write_bytes((json.dumps(doc, indent=1) + '\n').encode('utf-8'))
        for rel in [o['path'] for o in ops if o['before'] is not None] + keep:
            if (target / rel).is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                (backup / rel).write_bytes((target / rel).read_bytes())
        for op in [o for o in result['operations'] if o['action'] == 'pending']:
            (folder / 'new' / op['path']).parent.mkdir(parents=True, exist_ok=True)
            (folder / 'new' / op['path']).write_bytes(op['text'].encode('utf-8'))
        for op in ops:
            if op['action'] != 'delete':
                atomic_write(staging / op['path'], op['text'])
                if _hash(_local(staging, op['path'])) != op['after']:
                    raise WorkspaceError(f'staging {op["path"]} wrote other bytes than planned; nothing was replaced')
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    done = []
    atomic_write(folder / 'journal.json', json.dumps({'state': 'applying', 'done': done}))
    try:
        for op in ops:
            path = target / op['path']
            if op['action'] == 'delete':
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                _move(staging / op['path'], path)
            done.append(op['path'])
            atomic_write(folder / 'journal.json', json.dumps({'state': 'applying', 'done': done}))
    except Exception as error:
        try:
            _restore(target, folder, doc, moved_on=False)
        except Exception as again:
            raise RestoreFailed(f'the upgrade stopped at {op["path"]} ({error}), and putting the files back failed too '
                                f'({again}). Close programs that hold project files, then run "ws upgrade --target '
                                f'<project> --rollback {folder.name}"') from again
        raise WorkspaceError(f'the upgrade stopped at {op["path"]} ({error}); every file was put back, so the project '
                             'is as it was') from error
    atomic_write(folder / 'journal.json', json.dumps({'state': 'applied', 'done': done}))
    shutil.rmtree(staging, ignore_errors=True)


def _restore(target: Path, folder: Path, doc: dict, moved_on: bool):
    from .core import atomic_write
    for op in reversed(doc['operations']):
        path, saved = target / op['path'], folder / 'backup' / op['path']
        if saved.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(saved, path)
        elif op['before'] is None:
            path.unlink(missing_ok=True)
    if not moved_on:
        for rel in doc.get('kept') or []:
            if (folder / 'backup' / rel).is_file():
                shutil.copyfile(folder / 'backup' / rel, target / rel)
    shutil.rmtree(target / STAGING, ignore_errors=True)
    atomic_write(folder / 'journal.json', json.dumps({'state': 'rolled-back'}))


def rollback(target: Path, name: str, force=False) -> dict:
    """Put back every file an upgrade replaced, wrote or deleted, from its backup, and the state line with them."""
    target = target.absolute()
    folder = target / UPGRADES / name
    if not (folder / 'plan.json').is_file():
        raise WorkspaceError(f'no upgrade {name} in {UPGRADES}')
    if _journal_state(folder) == 'rolled-back':
        raise WorkspaceError(f'upgrade {name} was rolled back already')
    later = [p.parent.name for p in sorted((target / UPGRADES).glob('*/plan.json'))
             if p.parent.name > name and _journal_state(p.parent) != 'rolled-back']
    if later:
        raise WorkspaceError(f'upgrade {later[0]} came after {name}; roll that one back first')
    doc = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
    with lock(target):
        # The upgrade's own rebaseline takes one revision; anything beyond it is a session's work.
        moved_on = state_of(target).get('revision', 0) > (doc.get('revision') or 0) + 1
        if moved_on and not force:
            raise WorkspaceError('sessions have written since the upgrade, so a rollback would undo their state too. '
                                 'Add --force to put back only the template files')
        try:
            _restore(target, folder, doc, moved_on)
        except OSError as error:
            raise RestoreFailed(f'putting the files of {name} back failed ({error}). Close programs that hold project '
                                'files, then run the rollback again') from error
    done = {'rolled_back': name, 'files': len(doc['operations'])}
    if moved_on:
        done['note'] = ('the state the sessions wrote stays, so the checkpoint still records the upgraded files: the '
                        'next "ws checkpoint" takes the restored ones')
    if _rules_of(target) < RULES:
        from . import tables
        from .evidence import refused_by_rules_1
        from .schema import TABLES
        try:
            again = refused_by_rules_1(target, tables.rows(target, TABLES['tasks']))
        except (WorkspaceError, ValueError, OSError):
            again = []
        if again:
            done['verify_again'] = again
            done['verify_note'] = ('the restored tool reads the output of these runs with summary rules 1 and refuses '
                                   'it: run "ws verify <task>" for each again')
    return done


def _rules_of(target: Path) -> int:
    """The newest summary rules the project's own tool knows; a tool from before 3.7.0 knows only rules 1."""
    found = re.search(r'^RULES = (\d+)', _local(target, '.agents/tools/wslib/evidence.py') or '', re.M)
    return int(found[1]) if found else 1


def scan(source: Path, root: Path, depth=3) -> list:
    """One line per workspace under root, up to depth folders down. Read-only: no lock, no cache, no project code."""
    from .schema import PRUNE_DIRS
    found = []

    def walk(folder: Path, level: int):
        if (folder / 'docs/state/HANDOFF.md').is_file() or (folder / 'docs/state/TODO.md').is_file():
            found.append(describe(source, folder))
            return
        if level >= depth:
            return
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.is_dir(follow_symlinks=False) and entry.name not in PRUNE_DIRS and not entry.name.startswith('.') \
                    and not getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:
                walk(Path(entry.path), level + 1)
    walk(root.absolute(), 0)
    return found


def describe(source: Path, folder: Path) -> dict:
    line = {'path': str(folder), 'git': (folder / '.git').exists()}
    if not (folder / 'docs/state/HANDOFF.md').is_file():
        return {**line, 'schema': 'continuity.v2', 'plan': 'migrate first'}
    try:
        state = state_of(folder)
        result = plan(source, folder)
    except (WorkspaceError, ValueError, OSError) as error:
        return {**line, 'schema': 'continuity.v3', 'error': str(error)}
    base = _base(folder, None)
    return {**line, 'schema': state.get('schema'), 'version': result['from'], 'manifest_entries': len(base),
            'modified_tool_files': len(result['blocked']), 'released': not state.get('writer'),
            'hooks': result['hooks'], 'plan': summary(result)['counts']}
