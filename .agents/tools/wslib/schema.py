"""Public file layout, table definitions and protocol tokens."""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = 'continuity.v3'
VERSION = '3.8.0'
NONE = 'none'
PROTOCOL_MARKER = '<!-- AGENT-PROTOCOL: continuity.v3 -->'

STATE_DIR = 'docs/state'
LOG_DIR = 'docs/logs'
CHAT_DIR = 'docs/chats'
SPEC_DIR = 'docs/specs'
ARCHIVE_DIR = 'docs/archive'
TOOLS_DIR = '.agents/tools'
CACHE_DIR = '.agents/cache'
TEMPLATE_DIR = '.agents/template'
GUIDE_DIR = '.agents/guides'

STATE_NAMES = ('HANDOFF', 'REQUIREMENTS', 'PREFERENCES', 'FEATURES', 'TASKS', 'ARCHITECTURE', 'DESIGN')
LOG_NAMES = ('SESSION_LOG', 'REQUIREMENT_LOG', 'CHANGE_LOG', 'MAINTENANCE_LOG', 'RECONCILE_LOG')
# Logs added after 3.2.0. A project upgraded by replacing .agents/ lacks them until the first write.
OPTIONAL_LOGS = ('RECONCILE_LOG',)
CLOSED = 'docs/logs/CLOSED_ITEMS.md'
GUIDES = ('QUICKSTART', 'PROTOCOL', 'STRUCTURE', 'HOSTS', 'MAINTAINING', 'DESIGN_REQUIREMENTS', 'FIXES')
SKILLS = ('spec-workflow', 'maintain-project-state', 'save-session-log')
ADAPTERS = ('CLAUDE.md', 'CODEBUDDY.md', '.gemini/settings.json', '.kiro/steering/workspace.md',
            '.trae/rules/workspace.md')

HANDOFF = 'docs/state/HANDOFF.md'
REQUIREMENTS = 'docs/state/REQUIREMENTS.md'
ARCHITECTURE = 'docs/state/ARCHITECTURE.md'
CHAT_INDEX = 'docs/chats/INDEX.md'
# Optional text after a transcript heading "## 3. user": the UTC time, a compaction mark and, since 3.9, the message
# ID. Kept strict, so a body line in a transcript written before 3.6 cannot start being read as a heading.
HEADING_NOTE = r'(?: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)?(?: \(after compaction\))?(?: \[m[0-9a-f]{10}(?:[0-9a-f]{2})?\])?'
LOCK = '.agents/cache/ws.lock'  # the lock file of 3.8 and older, still honored while its process runs
FLOCK = '.agents/cache/ws.flock'  # locked by the operating system, never written or deleted
LOCK_INFO = '.agents/cache/ws.lock.info'  # who holds FLOCK, for messages only
FINGERPRINT_CACHE = '.agents/cache/fingerprint.json'
SELFTEST = '.agents/cache/selftest.json'

T0 = ('AGENTS.md', 'docs/state/HANDOFF.md', 'docs/state/REQUIREMENTS.md', 'docs/state/PREFERENCES.md')
T1 = T0 + ('docs/state/FEATURES.md', 'docs/state/TASKS.md', 'docs/state/ARCHITECTURE.md', 'docs/state/DESIGN.md')

LIB_MODULES = ('__init__', 'schema', 'core', 'tables', 'evidence', 'logs', 'validate', 'views', 'ops', 'capture', 'nudge', 'words', 'coverage',
               'reconcile', 'runs', 'rows', 'claims', 'distribution', 'defaults', 'lint', 'migrate', 'snapshot', 'dsh', 'verifying', 'retired',
               'hooks', 'upgrade', 'doctor', 'delivery', 'permits', 'locks', 'messages', 'compaction', 'redaction')
TEST_MODULES = ('support', 'test_core', 'test_workflow', 'test_distribution', 'test_reconcile', 'test_capture', 'test_tracking',
                'test_nudge', 'test_review', 'test_session', 'test_messages', 'test_probes', 'test_v36', 'test_field',
                'test_static', 'test_regressions', 'test_upgrade', 'test_doctor', 'test_v38', 'test_v39', 'run')
# Files only the template maintainer uses. They stay in the template folder and are never installed into a project:
# a business agent searching its project should not find the template's own requirements, history or self-tests.
MAINTAINER_GUIDES = ('MAINTAINING', 'DESIGN_REQUIREMENTS', 'FIXES')
TEMPLATE_MARKER = '.agents/TEMPLATE_CHECKOUT.md'
# Folder preview READMEs: GitHub shows the first lines when a folder is opened. They are for
# browsing the repository, so they stay in the template source and are never installed into a project.
FOLDER_PREVIEWS = ('.agents/README.md', f'{GUIDE_DIR}/README.md', '.agents/skills/README.md',
                   '.agents/tools/README.md', f'{TEMPLATE_DIR}/README.md')
MAINTAINER_FILES = (TEMPLATE_MARKER,
    *(f'{GUIDE_DIR}/{name}.md' for name in MAINTAINER_GUIDES),
    *(f'{TOOLS_DIR}/tests/{name}.py' for name in TEST_MODULES),
    f'{TEMPLATE_DIR}/examples/minimal_cycle.py',
    *FOLDER_PREVIEWS,
)
# What a project receives.
RUNTIME_FILES = (
    'AGENTS.md', *ADAPTERS,
    *(f'{GUIDE_DIR}/{name}.md' for name in GUIDES if name not in MAINTAINER_GUIDES),
    *(f'.agents/skills/{name}/SKILL.md' for name in SKILLS),
    f'{TOOLS_DIR}/ws.py',
    *(f'{TOOLS_DIR}/wslib/{name}.py' for name in LIB_MODULES),
    *(f'{TEMPLATE_DIR}/spec/{name}.md' for name in ('requirements', 'design', 'tasks')),
    f'{TEMPLATE_DIR}/module-AGENTS.md', f'{TEMPLATE_DIR}/TOOL_TRIAL.md', f'{TEMPLATE_DIR}/forms.md',
    *(f'{TEMPLATE_DIR}/examples/{name}.py' for name in ('unittest_json', 'pytest_junit', 'go_json')),
)
# Everything the template folder holds and the manifest hashes.
STATIC_FILES = RUNTIME_FILES + MAINTAINER_FILES
# Search tools that read these files (ripgrep, so Claude Code and Codex search; Cursor) skip the tool's code.
SEARCH_IGNORE = ('.ignore', '.cursorindexingignore')
SEARCH_IGNORE_TEXT = ('# Written by the workspace template: agents searching this project skip the workspace tool.\n'
                      '# They stay readable: open them by path when you need them.\n.agents/tools/\n.agents/cache/\n')
GENERATED_FILES = (
    'README.md',
    *(f'{STATE_DIR}/{name}.md' for name in STATE_NAMES),
    *(f'{LOG_DIR}/{name}.md' for name in LOG_NAMES), CLOSED,
    CHAT_INDEX,
)
REQUIRED = tuple(p for p in RUNTIME_FILES + GENERATED_FILES
                 if p != 'README.md' and p not in {f'{LOG_DIR}/{n}.md' for n in OPTIONAL_LOGS})
MANIFEST = f'{TEMPLATE_DIR}/MANIFEST.json'

CARD_FIELDS = (
    'phase', 'current_task', 'current_feature', 'stop_point', 'last_verification', 'baseline',
    'extra_reads', 'risks', 'next_step', 'recovery_notes', 'next_acceptance',
)
OPTIONAL_CARD_FIELDS = ('current_task', 'current_feature', 'baseline', 'extra_reads')
PLACEHOLDERS = {'', '...', 'todo', 'tbd', '<fill>', 'fill me'}

# Directory names that hold dependencies, build output, caches or IDE state.
PRUNE_DIRS = frozenset({
    '.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', '.tox', '.nox', 'dist', 'build', '.next', '.nuxt', '.svelte-kit', '.turbo', '.parcel-cache',
    '.angular', '.expo', 'target', 'out', 'obj', 'coverage', 'htmlcov', '.cache', '.gradle', '.idea', '.vscode',
    '.dart_tool', 'Pods', 'DerivedData', '.terraform', 'test-results',
})
DIST_DIR = 'dist'
PACKAGE_PREFIX = 'agent-workspace-'
# The settings file each host reads its hooks from, written by "ws hooks enable". Every one is outside the watched
# files except .gemini/settings.json, which is also the Gemini adapter.
HOOK_FILES = {
    'claude': '.claude/settings.json', 'codex': '.codex/hooks.json', 'cursor': '.cursor/hooks.json',
    'gemini': '.gemini/settings.json', 'copilot': '.github/hooks/workspace.json', 'kiro': '.kiro/hooks/workspace.json',
    'antigravity': '.agents/hooks.json', 'grok': '.grok/hooks/workspace.json', 'codebuddy': '.codebuddy/settings.json',
    'workbuddy': '.codebuddy/settings.json', 'qoder': '.qoder/settings.json', 'qwen': '.qwen/settings.json',
}
PRUNE_PATHS = ('.tmp', 'tmp', '.scratch', 'dist', 'docs/archive', 'docs/chats', '.agents/cache', '.agents/hooks.json', '.claude', '.cursor', '.codex',
               '.kimi-code', '.grok', '.dsh', '.codebuddy', '.qoder', '.qwen', '.github/hooks', '.kiro/hooks')
PRUNE_FILES = frozenset({'.DS_Store', 'Thumbs.db', 'desktop.ini', '.coverage', 'coverage.xml'})
SECRET_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.pyc', '.log')
# Database journals, editor swap files and process output change while services and tests run; they are never source.
SCRATCH_SUFFIXES = ('.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.db-journal', '.sqlite-wal', '.sqlite-shm',
                    '.sqlite-journal', '.swp', '.tmp', '.out', '.pid')
# Edits under these paths describe the work. They never make test evidence stale.
NON_SOURCE = ('docs/', '.agents/', '.gemini/', '.kiro/', '.trae/', 'AGENTS.md', 'CLAUDE.md', 'CODEBUDDY.md', 'README.md',
              *SEARCH_IGNORE)


@dataclass(frozen=True)
class Table:
    key: str
    prefix: str
    file: str
    headers: tuple
    statuses: tuple
    closed: frozenset
    retired: frozenset
    summary: str
    required: tuple
    defaults: dict = field(default_factory=dict)
    log: str | None = None


TABLES = {
    'requirements': Table(
        'requirements', 'R', REQUIREMENTS,
        ('ID', 'Status', 'Requirement', 'Acceptance', 'Detail', 'Reason'),
        ('active', 'deprecated', 'removed', 'replaced'),
        frozenset({'deprecated', 'removed', 'replaced'}), frozenset({'deprecated', 'removed', 'replaced'}),
        'Requirement', ('Requirement', 'Acceptance'), {'Detail': 'inline', 'Reason': NONE}, 'REQUIREMENT_LOG'),
    'questions': Table(
        'questions', 'Q', REQUIREMENTS,
        ('ID', 'Status', 'Question', 'Context', 'Answer'),
        ('open', 'deferred', 'answered', 'dropped'),
        frozenset({'answered', 'dropped'}), frozenset(),
        'Question', ('Question',), {'Context': NONE, 'Answer': NONE}, 'REQUIREMENT_LOG'),
    'preferences': Table(
        'preferences', 'P', 'docs/state/PREFERENCES.md',
        ('ID', 'Status', 'Preference', 'Source', 'Confidence'),
        ('active', 'retired'),
        frozenset({'retired'}), frozenset({'retired'}),
        'Preference', ('Preference', 'Source'), {'Confidence': 'stated'}, 'REQUIREMENT_LOG'),
    'features': Table(
        'features', 'F', 'docs/state/FEATURES.md',
        ('ID', 'Status', 'Behavior', 'Requirements', 'Tasks', 'Reason', 'Replacement'),
        ('planned', 'building', 'unverified', 'shipped', 'deprecated', 'removed', 'replaced'),
        frozenset({'deprecated', 'removed', 'replaced'}), frozenset({'deprecated', 'removed', 'replaced'}),
        'Behavior', ('Behavior', 'Requirements', 'Tasks'), {'Reason': NONE, 'Replacement': NONE}, 'CHANGE_LOG'),
    'tasks': Table(
        'tasks', 'T', 'docs/state/TASKS.md',
        ('ID', 'Status', 'Requirements', 'Scope', 'Action', 'Acceptance', 'Depends', 'Evidence', 'Reason'),
        ('todo', 'doing', 'unverified', 'blocked', 'done', 'dropped'),
        frozenset({'done', 'dropped'}), frozenset({'dropped'}),
        'Action', ('Requirements', 'Scope', 'Action', 'Acceptance'), {'Depends': NONE, 'Evidence': NONE, 'Reason': NONE}, None),
    'decisions': Table(
        'decisions', 'D', 'docs/state/DESIGN.md',
        ('ID', 'Status', 'Decision', 'Reason', 'Source'),
        ('adopted', 'superseded', 'rejected'),
        frozenset({'superseded', 'rejected'}), frozenset({'superseded', 'rejected'}),
        'Decision', ('Decision', 'Reason', 'Source'), {}, 'CHANGE_LOG'),
}
PREFIX_TABLE = {t.prefix: t for t in TABLES.values()}
# Statuses whose row needs a Reason: the retired ones, plus a blocked task, so the blocker is written down.
NEEDS_REASON = {key: t.retired | ({'blocked'} if key == 'tasks' else frozenset()) for key, t in TABLES.items()}
TABLE_ALIASES = {}
for _t in TABLES.values():
    TABLE_ALIASES.update({_t.key: _t.key, _t.key[:-1]: _t.key, _t.prefix.lower(): _t.key})

LOG_HEADERS = {
    'SESSION_LOG': ('Date', 'Writer', 'Stop point', 'Next step', 'Verification', 'Changes'),
    'REQUIREMENT_LOG': ('Date', 'ID', 'Event', 'Detail', 'Source'),
    'CHANGE_LOG': ('Date', 'ID', 'Event', 'Detail', 'Source'),
    'MAINTENANCE_LOG': ('Date', 'Event', 'Detail'),
    'RECONCILE_LOG': ('Date', 'Message', 'Outcome'),
}

# credentials: how the project keeps passwords, keys and tokens, as the user decided. ask = not decided yet.
DEFAULT_CONFIG = {'ownership': 'solo', 'exclude': [], 'credentials': 'ask', 'chat_import': 'ask'}
CREDENTIAL_RULES = ('ask', 'plain', 'redact')
# AGENTS.md is read in full at every session start; 14 KB leaves room under Antigravity's 24,000-byte cut.
BUDGETS = {'AGENTS.md': 14000, 'T0': 26000, 'state': 16000, 'log': 64000}
CHECKPOINTS_KEPT = 10
OUTPUT_LIMIT = 200_000
