"""Clean contents of the generated project files."""
from __future__ import annotations

from .core import default_state, state_line
from .schema import LOG_HEADERS, TABLES, VERSION
from .tables import CLOSED_HEADERS


def table(headers) -> str:
    return '| ' + ' | '.join(headers) + ' |\n| ' + ' | '.join('---' for _ in headers) + ' |\n'


ARCHIVE_TABLE = table(('Path', 'Rows', 'SHA-256'))

HANDOFF = f'''# Handoff

Where the work stopped and what comes next.
Change it with `ws.py card` or `ws.py checkpoint`; the tool keeps the table format.

<!-- CARD:START -->

| Field | Value |
| --- | --- |
| phase | bootstrap |
| current_task | none |
| current_feature | none |
| stop_point | Template installed; the project has not been inspected |
| last_verification | Not run |
| baseline | none |
| extra_reads | none |
| risks | The goal, entry points and acceptance commands are unknown |
| next_step | Ask the user for the goal, then run ws.py init --goal "..." |
| recovery_notes | No running processes |
| next_acceptance | ws.py check --ready passes after the first checkpoint |
<!-- CARD:END -->

## Unfinished work

None.

{state_line(default_state())}
'''

REQUIREMENTS = f'''# Requirements

The confirmed goal, scope, requirements and open questions.
Detail that does not fit in a table row goes to `docs/specs/<slug>/requirements.md`.

## Goal

<!-- GOAL:START -->
<!-- GOAL:END -->

## Scope

- In scope: unknown until the first inspection.
- Out of scope: none recorded.

## Requirements

{table(TABLES["requirements"].headers)}
## Open questions

{table(TABLES["questions"].headers)}
## Idea pool

Ideas the user mentioned but did not confirm.
They get an ID only after confirmation.

- None.
'''

PREFERENCES = f'''# Preferences

Stable preferences of the user, such as reply language, code style or review habits.
One-off instructions do not belong here.
Use confidence `stated` when the user said it and `inferred` when you concluded it.

{table(TABLES["preferences"].headers)}

## Not adopted

Ways of working left out on purpose. Bring one back only when the user asks.

- Expert personas, tips or flattery to raise the quality of an answer.
- Spelling out a tree of thoughts, or gathering and rewriting prompts automatically.
- Encouraging set phrases in results.
- Facts from an earlier window's chat or a tool's private memory that the state files do not hold.
'''

FEATURES = f'''# Features

What the product does, including capabilities that were removed or replaced.
A removed row keeps its ID and reason so nobody rebuilds it by accident.

{table(TABLES["features"].headers)}'''

TASKS = f'''# Tasks

Work items with their acceptance command and evidence.
A task becomes `done` only through `ws.py verify <ID> --done`.
Write `check: <command>` as acceptance for builds or linters that report no test count.

{table(TABLES["tasks"].headers)}'''

ARCHITECTURE = '''# Architecture

How the project is built and run.
Fill this during the first inspection and keep it current.

## Entry points

| Path | Role |
| --- | --- |
| unknown | Inspect the repository |

## Commands

| Purpose | Command |
| --- | --- |
| Run tests | unknown |
| Build | unknown |
| Start locally | unknown |

## Environment

- Runtime and versions: unknown.
- Configuration and secrets: name environment variables only.

Known command problems: a command that failed and the form that worked. The brief shows the last five rows.

| Command | Symptom | Working form |
| --- | --- | --- |

## Components

One block per component, in the form from `.agents/template/forms.md`. Delete this line when the
first block is written.

## Terms

Project codes that state rows use, such as audit finding IDs or build names. A new session looks them up here.

| Term | Meaning | Detail |
| --- | --- | --- |

## Watch scope

`ws.py` hashes project files to find changes made after the last checkpoint.

- Skipped by default: dependency, build, cache and IDE folders.
- `exclude`: generated paths that still cause noise, such as `"data/**"`, `"*.sqlite"` or `"*.out"`.
  A test that writes such a file otherwise fails verification with the file named. Never exclude source code.
- `ownership`: `shared` only when several people write to one checkout.
- `credentials`: how the user wants passwords, keys and tokens kept. `ask` until the user has answered,
  then `plain` (as written, where the user said) or `redact` (out of the workspace files).

<!-- WORKSPACE:START -->
{"ownership": "solo", "exclude": [], "credentials": "ask"}
<!-- WORKSPACE:END -->
'''

DESIGN = f'''# Design

The adopted approach and the decisions behind it.
Rejected and superseded decisions stay listed so they are not proposed again.

## Approach

Not established yet.

## Decisions

{table(TABLES["decisions"].headers)}'''

LOG_INTRO = {
    'SESSION_LOG': ('Session log', 'One row per checkpoint, written by `ws.py checkpoint`.'),
    'REQUIREMENT_LOG': ('Requirement log', 'Changes to the goal, requirements, questions and preferences, written by `ws.py add` and `ws.py set`.'),
    'CHANGE_LOG': ('Change log', 'Added, changed, removed and replaced features and decisions, written by `ws.py add` and `ws.py set`.'),
    'MAINTENANCE_LOG': ('Maintenance log', 'Initialization, takeovers, compaction and migrations, written by the tool.'),
    'RECONCILE_LOG': ('Reconcile log', 'How each user message in `docs/chats/` was accounted for, written by `ws.py reconcile`.'),
}


def log(name: str) -> str:
    title, intro = LOG_INTRO[name]
    return (f'# {title}\n\n{intro}\n'
            'Older rows move to `docs/archive/logs/` when the file grows; the archive table lists them with their hashes.\n\n'
            f'{table(LOG_HEADERS[name])}\n## Archives\n\n{ARCHIVE_TABLE}')


CLOSED = f'''# Closed items

Rows that left the state files through `ws.py compact`.
Their IDs stay reserved forever.
Search here before adding a feature or requirement that sounds familiar.

{table(CLOSED_HEADERS)}'''

CHAT_INDEX = '''# Conversation index

Transcripts copied by host hooks, one file per session.
Run `ws.py hooks enable <host>` once per tool; see `.agents/guides/HOSTS.md`.
These files are records, not current facts. The state files win when they disagree.

| Date | Host | Session | Messages | Transcript | Raw copy |
| --- | --- | --- | --- | --- | --- |
'''

CHAT_GITIGNORE = '# Raw host transcripts can contain tool output and paths. Commit the Markdown copies only.\n*/raw/\n'
GITATTRIBUTES = '# Keep workspace records byte-identical across Windows and Unix checkouts.\n* text=auto eol=lf\n'

README = f'''# Agent workspace

A file-based memory for long projects built with AI coding agents.
Requirements, decisions, tasks, evidence and the exact stop point live in `docs/`.
A new window or a different tool reads them and continues where the last session stopped.

Version {VERSION}. Python 3.10 or newer, standard library only.

## Layout

```text
AGENTS.md              contract every agent reads first
CLAUDE.md              Claude Code import of AGENTS.md
.agents/
  tools/ws.py          the workspace tool
  guides/              protocol, structure and host setup
  skills/              step-by-step workflows
  template/            spec templates and examples
docs/
  state/               current facts, read at every session start
  logs/                history tables written by the tool
  specs/<slug>/        detail for large requirements
  chats/               transcripts copied by hooks
  archive/             evidence, checkpoints, rolled logs
```

## Session cycle

```text
brief -> read state -> start -> work and record -> verify -> checkpoint
  ^                                                              |
  +------------------- next window or next tool -----------------+
```

## First use

1. Unzip `dist/agent-workspace-<version>.zip` of the template into an empty folder.
   For an existing project, run `ws.py install --target <project> --dry-run` from the template.
2. Open the project in any agent tool and say: "Read AGENTS.md and start."
3. Give the goal in one sentence when the agent asks for it.
4. Optional: `python .agents/tools/ws.py hooks enable claude` saves transcripts and injects
   the brief at session start. Hosts `cursor`, `gemini` and `copilot` work the same way.

## Switching windows or tools

Ask the current agent to checkpoint.
In the new window say "Read AGENTS.md and continue."
If the old window died without saving, the new agent sees the unsaved files in `ws.py brief` and takes over.

## Guides

| Guide | Use |
| --- | --- |
| [Quickstart](.agents/guides/QUICKSTART.md) | Installation, first session, daily use |
| [Protocol](.agents/guides/PROTOCOL.md) | Formats, ownership, evidence and recovery |
| [Structure](.agents/guides/STRUCTURE.md) | Folders, naming, document size and writing style |
| [Hosts](.agents/guides/HOSTS.md) | Per-tool entry files and hooks |
'''


def documents() -> dict:
    result = {
        'README.md': README,
        'docs/state/HANDOFF.md': HANDOFF,
        'docs/state/REQUIREMENTS.md': REQUIREMENTS,
        'docs/state/PREFERENCES.md': PREFERENCES,
        'docs/state/FEATURES.md': FEATURES,
        'docs/state/TASKS.md': TASKS,
        'docs/state/ARCHITECTURE.md': ARCHITECTURE,
        'docs/state/DESIGN.md': DESIGN,
        'docs/logs/CLOSED_ITEMS.md': CLOSED,
        'docs/chats/INDEX.md': CHAT_INDEX,
        'docs/chats/.gitignore': CHAT_GITIGNORE,
        'docs/.gitattributes': GITATTRIBUTES,
    }
    for name in LOG_INTRO:
        result[f'docs/logs/{name}.md'] = log(name)
    return result
