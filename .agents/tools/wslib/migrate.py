"""Convert a continuity.v2 workspace in place. Every replaced file is backed up first."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import defaults, tables
from .core import WorkspaceError, atomic_write, card_text, default_state, now, today, with_goal, with_state
from .distribution import installed_manifest, static_payload
from .schema import CLOSED, MANIFEST, NONE, SCHEMA, TABLES

CARD = {'阶段': 'phase', '当前任务': 'current_task', '当前功能': 'current_feature', '停止点': 'stop_point',
        '最近验证': 'last_verification', '当前基线': 'baseline', '本批加读': 'extra_reads', '风险与阻塞': 'risks',
        '下一步': 'next_step', '恢复线索': 'recovery_notes', '下步验收': 'next_acceptance'}
COLUMNS = {'状态': 'Status', '需求': 'Requirement', '验收': 'Acceptance', '详情': 'Detail', '原因': 'Reason',
           '范围': 'Scope', '动作': 'Action', '依赖': 'Depends', '证据': 'Evidence', '行为': 'Behavior',
           '任务': 'Tasks', '替代': 'Replacement'}
STATUS = {
    'requirements': {'确认': 'active', '废弃': 'deprecated', '已移除': 'removed', '已替代': 'replaced'},
    'tasks': {'未开始': 'todo', '进行中': 'doing', '已实现未验证': 'unverified', '阻塞': 'blocked', '完成': 'done', '放弃': 'dropped'},
    'features': {'计划': 'planned', '进行中': 'building', '已实现未验证': 'unverified', '已交付': 'shipped',
                 '废弃': 'deprecated', '已移除': 'removed', '已替代': 'replaced'},
}
V2_LOGS = {'REVISION': 'SESSION_LOG', 'PROJECT': 'SESSION_LOG', 'REQUIREMENTS': 'REQUIREMENT_LOG',
           'CHANGE': 'CHANGE_LOG', 'MAINTENANCE': 'MAINTENANCE_LOG'}
V2_SYSTEM = (
    'TEMPLATE-MANIFEST.json', '.cursor/rules/00-handoff.mdc', '.github/copilot-instructions.md', '.kiro/steering/00-handoff.md',
    'docs/state/TODO.md', 'docs/state/LOG_INDEX.md',
    *(f'docs/logs/{n}.md' for n in V2_LOGS), 'docs/chats/CURRENT.md', 'docs/chats/TRANSCRIPT.md',
    *(f'docs/guides/{n}.md' for n in ('ADAPTERS', 'PROTOCOL', 'STRUCTURE', 'QUICKSTART', 'CONVERSATIONS', 'WORKED_EXAMPLE', 'MERGE')),
    *(f'docs/templates/{n}' for n in ('ORIGIN.json', 'TOOL_TRIAL.md', 'module/AGENTS.md', 'spec/requirements.md', 'spec/design.md',
                                      'spec/tasks.md', 'examples/minimal_cycle.py', 'examples/unittest_json.py',
                                      'examples/pytest_junit.py', 'examples/go_json.py')),
    *(f'scripts/{n}.py' for n in ('reports', 'state_updates', 'merge_review', 'verification', 'distribution', 'history',
                                  'diagnostics', 'agent_state', 'continuity', 'template_data', 'check_continuity',
                                  'validate_workspace', 'handoff', 'create_baseline', 'test_agent_state',
                                  'test_check_continuity', 'test_validate_workspace', 'capture', 'capture_stage',
                                  'document_audit', 'selftest_agent_state', 'selftest_check_continuity',
                                  'selftest_validate_workspace')),
)


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8-sig').replace('\r\n', '\n') if path.is_file() else ''


def _v2_rows(text: str, first_header: str) -> list:
    for _, headers, raw in tables.blocks(text):
        if headers and headers[0] == 'ID' and first_header in headers:
            return [dict(zip(headers, [c.replace('&#124;', '|').strip('`') for c in cells])) for _, cells in raw]
    return []


def _convert(row: dict, key: str) -> dict:
    out = {COLUMNS.get(k, k): (NONE if v == '无' else v) for k, v in row.items()}
    if key in ('features', 'tasks'):
        out['Requirements'] = out.pop('Requirement', NONE)
    out['Status'] = STATUS[key].get(row.get('状态', ''), row.get('状态', ''))
    return out


def _v2_goal(text: str) -> str:
    if '<!-- GOAL:START -->' in text:
        body = text.split('<!-- GOAL:START -->', 1)[1].split('<!-- GOAL:END -->', 1)[0]
    else:
        match = re.search(r'^## (?:一句话|Goal)\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
        body = match[1] if match else ''
    return re.sub(r'<!--.*?-->', '', body, flags=re.S).strip()


def migrate(source: Path, target: Path, dry_run=False, force=False) -> dict:
    target = target.absolute()
    todo = target / 'docs/state/TODO.md'
    if not todo.is_file():
        raise WorkspaceError(f'{todo} not found; migrate expects a continuity.v2 workspace')
    text = _read(todo)
    block = text.split('<!-- CONTINUITY:START -->', 1)[1].split('<!-- CONTINUITY:END -->', 1)[0] if '<!-- CONTINUITY:START -->' in text else '{}'
    old_state = json.loads(block)
    if old_state.get('schema') != 'continuity.v2':
        raise WorkspaceError(f'unsupported source schema {old_state.get("schema")}')
    held_by = old_state.get('writer')
    if held_by and not force:
        raise WorkspaceError(f'writer {held_by} still owns the v2 workspace. Close that agent session, then rerun with '
                             '--force; files that changed after its last checkpoint are kept and listed by ws start')
    card_body = text.split('<!-- HANDOFF:START -->', 1)[1].split('<!-- HANDOFF:END -->', 1)[0] if '<!-- HANDOFF:START -->' in text else ''
    old_card = {}
    for line in card_body.splitlines():
        match = re.fullmatch(r'\s*([^：:]+)[：:]\s*(.*?)\s*', line)
        if match and match[1].strip() in CARD:
            old_card[CARD[match[1].strip()]] = NONE if match[2] == '无' else match[2]
    requirements_text = _read(target / 'docs/state/REQUIREMENTS.md')
    converted = {
        'requirements': [_convert(r, 'requirements') for r in _v2_rows(requirements_text, '验收')],
        'tasks': [_convert(r, 'tasks') for r in _v2_rows(_read(target / 'docs/state/TASKS.md'), '范围')],
        'features': [_convert(r, 'features') for r in _v2_rows(_read(target / 'docs/state/FEATURES.md'), '行为')],
    }
    prefs = []
    for number, row in enumerate(_v2_rows(_read(target / 'docs/state/PREFERENCES.md'), '偏好'), 1):
        source_text = row.get('来源', '') + ('; ' + row['证据'] if row.get('证据') else '')
        prefs.append({'ID': row['ID'] if re.fullmatch(r'P[1-9]\d*', row.get('ID', '')) else f'P{number}', 'Status': 'active',
                      'Preference': row.get('偏好', ''), 'Source': source_text or 'v2', 'Confidence': row.get('置信度', 'stated')})
    keep_live = {old_card.get('current_task'), old_card.get('current_feature')}
    files = defaults.documents()
    closed_text = files[CLOSED]
    moved = []
    reopened = set()
    for key in ('tasks', 'requirements', 'features'):
        rows = converted[key]
        t = TABLES[key]
        live = []
        for row in rows:
            if row['Status'] in t.closed and row['ID'] not in keep_live:
                entry = tables.closed_entry(t, row, NONE, today())
                if entry['Evidence'].lower() != NONE:
                    # Verified under continuity.v2 and never run again in v3, so coverage counts it apart.
                    entry['Evidence'] = 'v2: ' + entry['Evidence']
                closed_text = tables.append(closed_text, tables.CLOSED_HEADERS, CLOSED, entry)
                moved.append(row['ID'])
                continue
            if key == 'tasks' and row['Status'] == 'done':
                row['Status'] = 'unverified'
                row['Reason'] = 'v2 evidence; run ws.py verify again'
                reopened.add(row['ID'])
            if key == 'features' and row['Status'] == 'shipped' and reopened & set(tables.refs(row.get('Tasks', NONE), 'T')):
                row['Status'] = 'unverified'
            if row['Status'] in t.retired:
                rel = f'docs/logs/{t.log}.md'
                from . import logs
                files[rel] = logs.add(files[rel], t.log, {'ID': row['ID'], 'Event': row['Status'],
                                                          'Detail': row.get('Reason', NONE), 'Source': 'continuity.v2 migration'})
            live.append(row)
        text_t = files[t.file]
        for row in live:
            text_t = tables.append(text_t, t.headers, t.file, {h: row.get(h, t.defaults.get(h, NONE)) for h in t.headers})
        files[t.file] = text_t
    for row in prefs:
        t = TABLES['preferences']
        files[t.file] = tables.append(files[t.file], t.headers, t.file, row)
    files[CLOSED] = closed_text
    goal_text = _v2_goal(requirements_text)
    files['docs/state/REQUIREMENTS.md'] = with_goal(files['docs/state/REQUIREMENTS.md'], goal_text or 'unknown; ask the user')
    for name in ('ARCHITECTURE', 'DESIGN'):
        old = _read(target / f'docs/state/{name}.md')
        body = re.sub(r'<!-- WORKSPACE:START -->.*?<!-- WORKSPACE:END -->', '', old, flags=re.S).strip()
        if body:
            files[f'docs/state/{name}.md'] += '\n## Before migration\n\nContent of the continuity.v2 file, kept verbatim.\n\n' + \
                re.sub(r'^(#{1,5}) ', lambda m: '#' * min(6, len(m[1]) + 2) + ' ', body, flags=re.M) + '\n'
    for old_name, new_name in V2_LOGS.items():
        old = _read(target / f'docs/logs/{old_name}.md')
        body = '\n'.join(old.split('\n')[1:]).strip()
        if body and not body.startswith('Append dated observations'):
            rel = f'docs/logs/{new_name}.md'
            files[rel] += f'\n## Before migration: {old_name}\n\n' + re.sub(r'^(#{1,5}) ', lambda m: '#' * min(6, len(m[1]) + 2) + ' ', body, flags=re.M) + '\n'
    fields = {k: v for k, v in old_card.items() if v}
    moved_paths = {'docs/chats/CURRENT.md': 'docs/chats/legacy/CURRENT.md', 'docs/chats/TRANSCRIPT.md': 'docs/chats/legacy/TRANSCRIPT.md',
                   'docs/state/TODO.md': 'docs/state/HANDOFF.md', 'docs/state/LOG_INDEX.md': 'docs/state/HANDOFF.md'}
    if fields.get('extra_reads', NONE) != NONE:
        paths = [moved_paths.get(p.strip().strip('`'), p.strip().strip('`')) for p in re.split(r'[;,]', fields['extra_reads']) if p.strip()]
        fields['extra_reads'] = '; '.join(dict.fromkeys(paths)) or NONE
    fields['phase'] = 'migrated to continuity.v3'
    fields['next_step'] = 'Run ws.py start, review migrated rows and docs/chats/legacy/, re-verify unverified tasks, checkpoint'
    fields['recovery_notes'] = f'v2 files backed up in docs/archive/v2-backup/; {len(moved)} closed rows moved to CLOSED_ITEMS.md'
    handoff = card_text(files['docs/state/HANDOFF.md'], fields)
    state = default_state()
    state.update(mode='active', revision=int(old_state.get('revision') or 0) + 1)
    handoff = handoff.replace('## Unfinished work\n\nNone.', '## Unfinished work\n\nDecisions and questions from v2 chat files are in `docs/chats/legacy/`. Register the ones that still apply with `ws.py add decision` and `ws.py add question`.')
    files['docs/state/HANDOFF.md'] = with_state(handoff, state)
    payload = static_payload(source, allow_modified=True)
    payload.update(files)
    payload[MANIFEST] = installed_manifest(source, payload)
    removals = [rel for rel in V2_SYSTEM if (target / rel).is_file()]
    report = {'target': str(target), 'writes': sorted(payload), 'removals': removals, 'closed_rows': moved,
              'goal': goal_text, 'backup': 'docs/archive/v2-backup/'}
    if dry_run:
        return report
    backup = target / 'docs/archive/v2-backup'
    if backup.exists():
        raise WorkspaceError(f'{backup} exists; a previous migration may have run')
    for rel in sorted(set(removals) | {r for r in payload if (target / r).is_file()}):
        destination = backup / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / rel, destination)
    for rel in ('docs/chats/CURRENT.md', 'docs/chats/TRANSCRIPT.md'):
        if (target / rel).is_file():
            atomic_write(target / 'docs/chats/legacy' / Path(rel).name, _read(target / rel))
    for rel in removals:
        (target / rel).unlink()
    for rel, content in payload.items():
        atomic_write(target / rel, content)
    for folder in ('scripts/__pycache__', 'scripts', 'docs/guides', 'docs/templates/examples', 'docs/templates/spec',
                   'docs/templates/module', 'docs/templates'):
        path = target / folder
        if folder.endswith('__pycache__') and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    log = target / 'docs/logs/MAINTENANCE_LOG.md'
    from . import logs
    detail = f'continuity.v2 revision {old_state.get("revision")} to {SCHEMA} at {now()}'
    if held_by:
        detail += f'; v2 writer {held_by} was still holding the workspace (--force)'
    atomic_write(log, logs.add(_read(log), 'MAINTENANCE_LOG', {'Event': 'migrate', 'Detail': detail}))
    from .ops import seal
    state['checkpoint'] = seal(target, 'migration')
    atomic_write(target / 'docs/state/HANDOFF.md', with_state(_read(target / 'docs/state/HANDOFF.md'), state))
    report['held_by'] = held_by
    return report
