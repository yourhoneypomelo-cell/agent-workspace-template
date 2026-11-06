# Structure

Folder layout, naming, size limits and writing style for every file in the workspace.

## Layout

```text
project/
├── AGENTS.md                    contract, read first by every agent
├── CLAUDE.md                    imports AGENTS.md for Claude Code
├── README.md                    project home page, kept on install
├── .gemini/settings.json        makes Gemini CLI and Antigravity load AGENTS.md
├── .kiro/steering/workspace.md  makes Kiro load AGENTS.md
├── .ignore, .cursorindexingignore keep .agents/tools/ and .agents/cache/ out of agent searches
├── .agents/                     system files, identical in every project
│   ├── tools/ws.py              command line tool
│   ├── tools/wslib/             tool modules
│   ├── guides/                  this guide and the other runtime guides
│   ├── skills/<name>/SKILL.md   workflows loaded on demand
│   ├── template/                spec, module and trial templates, examples
│   └── cache/                   rebuildable cache, safe to delete, not committed
├── ops/                         optional: scripts that project guides call
├── .tmp/                        optional: scratch scripts and probe output, never watched
└── docs/                        project facts, different in every project
    ├── state/                   current facts, seven fixed files
    ├── guides/                  optional: project procedures, one topic per file
    ├── reports/                 optional: audits and reports the user reads, one topic per file
    ├── logs/                    history tables and CLOSED_ITEMS.md
    ├── specs/<slug>/            requirements.md, design.md, tasks.md
    ├── chats/                   copied transcripts and INDEX.md
    └── archive/                 checks/, checkpoints/, logs/, upgrades/
```

The split is simple: `.agents/` is the same in every project, and `ws upgrade` replaces what the project
did not edit. `docs/` belongs to the project and is never overwritten by the template.
Never put project files in `.agents/`: `ws check` lists them, because an upgrade may delete them.
Reports go in `docs/reports/`, throwaway scripts and command output in `.tmp/`.

## Windows

- Run the tool as `python .agents/tools/ws.py`; if `python` opens the Store, use `py -3`.
- Windows PowerShell 5.1 has no `&&`. Run commands one per line, or use `;` and check `$LASTEXITCODE`.
- Write paths in state files and `exclude` with forward slashes; the tool converts backslashes in `exclude`.
- Save files as UTF-8 without a BOM. PowerShell 5.1 `Set-Content` and `Out-File` add one; use
  `[IO.File]::WriteAllText(path, text)` or write the file from Python.
- `$name` inside double quotes is expanded by PowerShell before a remote shell sees it. Use single quotes
  or put the remote commands in a script under `ops/`.

## Project guides

A procedure that every agent must follow the same way, in any tool, belongs in a project guide.
Examples: how to reach a server, how to deploy, how to run a data job.

1. Write `docs/guides/<topic>.md`: what it controls, how to use it, conventions, failure handling.
2. Put scripts it calls in `ops/`, and test them before you write the guide.
3. Write credentials the way the project's credential rule says (AGENTS.md Rule 6): as written when the user
   chose that, or by location, such as an SSH key path or an environment variable.
4. `ws brief` lists every guide under "Project guides", so the next session finds it.
5. Register the procedure as a requirement and a task, and verify the task with the script.

## Naming

| Item | Convention | Example |
| --- | --- | --- |
| State and log files | UPPER_SNAKE_CASE, fixed set | `HANDOFF.md`, `CHANGE_LOG.md` |
| Guides | UPPER_SNAKE_CASE | `PROTOCOL.md` |
| Folders and spec slugs | lower-case, kebab-case | `docs/specs/csv-import/` |
| Spec files | lower-case, fixed names | `requirements.md`, `design.md`, `tasks.md` |
| Archives | name, date, sequence | `change_log-2026-10-31-001.md` |
| IDs | prefix letter and number | `R12`, `T40`, `Q3` |
| Host entry files | the name the host expects | `AGENTS.md`, `CLAUDE.md`, `SKILL.md` |

Every file name in `docs/state/` and `docs/logs/` is unique across the workspace.
Current facts live at fixed paths. Versions belong in logs and version control, never in file names.

## Size

The documents stay small because each kind of content has one place and the tool moves history out.

| Content | Lives in | Read at session start |
| --- | --- | --- |
| Open and recent work | `docs/state/` tables | yes |
| Closed rows | `docs/logs/CLOSED_ITEMS.md` | no, searched on demand |
| How a fact changed | `docs/logs/*_LOG.md` | no |
| Long requirement detail | `docs/specs/<slug>/` | when the task names it |
| Raw evidence | `docs/archive/checks/` | no |
| Conversations | `docs/chats/` | no |

Budgets, checked by `ws check` as warnings:

| Scope | Budget |
| --- | --- |
| AGENTS.md | 14 KB |
| T0 files together | 26 KB |
| One state file | 16 KB |
| One live log | 64 KB, then rolled automatically |

When a budget is exceeded, run `ws compact`. If it is still exceeded, move requirement detail into
specs and shorten long cells. Do not drop open requirements, constraints or IDs.

## Record forms

State files hold current facts, so they are written as forms, not as a work diary.
`.agents/template/forms.md` has a form for each common record: component, decision, finding and
project procedure. Each field holds one fact, and a fact is changed where it is, not restated.

Why forms and not prose. A real DESIGN.md written as dated session notes reached 22 KB in two
days. The gateway entry alone was 1.7 KB, and its port, start script and open work appeared
again in later entries: the port 7 times, Wiley 8 times, boot 12 times. The same entry as forms
keeps all of its facts in about the same space. The saving comes later: the next change edits
one field instead of adding a paragraph that restates the rest. A missing field is also visible,
which prose hides.

Forms do not fit everything. Rationale that needs an argument, and requirement detail, go to
`docs/specs/<slug>/`. Keep a field to one line. If it needs more, that is a spec.

`ws lint` reports dated headings and paragraphs longer than six lines in `docs/state/`, and the
checkpoint repeats the count, so the diary style is caught early.

## Writing a cell

A table cell holds one fact in one line.

| Column | Good | Too much |
| --- | --- | --- |
| Requirement | Export the task list as JSON with id, text and done | A paragraph mixing motivation, design and tests |
| Acceptance | `python -m pytest tests/test_export.py` | "Make sure export works well" |
| Reason | User dropped CSV on 2026-10-29 | A copy of the chat |

Put background in a spec and link it in the Detail column.

## Short rows, complete records

The state files are what a new session reads first, so a row must be readable on its own. The
records behind it are the memory of the project, so nothing is dropped to make a row short.
Each fact has one place, and every other place points to it:

| Kind of fact | Where it lives | What the state row holds |
| --- | --- | --- |
| What was decided and the deciding reason | DESIGN.md row | The whole decision and reason, one sentence each |
| Measurements, hashes, byte counts, test counts | The evidence file in `docs/archive/checks/` | The verdict and the evidence path |
| The full argument, rejected options, probe matrices | `docs/specs/<slug>/design.md` or `docs/reports/<topic>.md` | A one-line conclusion and the path |
| How a version changed over time | CHANGE_LOG, written by `ws set`, or the spec | The current behavior only |
| A user's words | The requirement row, verbatim, however long | Unchanged; a long requirement links its spec for the rest |
| Audit and build codes such as `ME-02` | The Terms table of ARCHITECTURE.md | The code, now defined |

Moving detail out of a row works in this order: write the detail to its file, check the path, then
shorten the row to the conclusion and the path. Never delete a fact, a number or a user's words to
make a row shorter. If the detail has no home yet, leave the row long; `ws lint` only reports it.

A row a new session can use answers four questions without opening another file: what it is, its
state, why, and where the rest is. Example:

| Too much in the row | Readable row with the record kept |
| --- | --- |
| `D55 adopted: Unpaywall gateway adopted after audit T56: tree byte-identical (sha a9ff...), 34/34 tests 3.27 s, live matrix green (arXiv 211,707 B, Range 206/416, closed 403...), P1 found: no SSRF netguard...` | `D55 adopted: Adopt the Unpaywall gateway as F15; the T56 audit matched the deployed tree and passed 34 of 34 tests. One P1 remains: no SSRF guard on candidate fetches (T57). Detail: docs/reports/unpaywall-t56.md` |

`ws lint` reports state cells over 400 characters, cells that list several facts, version
histories, codes missing from the Terms table and paths that do not exist. `ws add` and `ws set`
save every value in full and only print a note.

## Writing style

These rules apply to guides, skills, templates and any prose an agent adds to `docs/`.
`ws lint` checks the mechanical ones.

### Structure

- One level-1 heading, then one or two sentences on the purpose of the document.
- Level-2 headings for topics and level-3 for subtopics. Do not skip levels.
- Order sections by what the reader needs first. Put procedures before background.
- Use a table for records and comparisons, a numbered list for ordered steps, bullets for parallel rules.
- Leave out sections that would be empty. A short reference needs no summary at the end.

### Sentences

- Write one idea per sentence. Name the actor and the action: "Run `ws checkpoint`."
- Prefer concrete nouns and numbers to adjectives: "64 KB" instead of "large".
- State each fact once, in its owner file. Elsewhere, link to it.
- Mark unknowns as "unknown". Mark how a conclusion is known: "measured" (a command ran, with its
  output), "read in code" (file and function) or "inferred". A statement about the current system
  carries its date, because it goes stale.
- Locate by function, heading or anchor text, not by line number, in rules and guides. Keep changing
  numbers out of headings. A dated finding may cite `file:line`.
- Keep proper names, commands, paths and quoted user text exactly as written.
- Write for a reader who has not seen this conversation. Define a code the first time it appears,
  name the file or command instead of "the script" or "as above", and give the next step as one action.
- Concise means no repetition and no filler. It never means fewer facts: keep every number, path,
  condition and exception the next session needs, and move long detail to its file instead of cutting it.
- Write each file in one language, as PREFERENCES.md says. Quoted user text stays in its own language.

### Punctuation and characters

- End sentences with a period. Use commas and periods instead of dashes.
- Avoid chains of semicolons and slashes. Write "requirements and tasks", not "requirements/tasks".
- Use bold only for a warning the reader must not miss. No emoji or decorative symbols.
- Wrap prose at about 100 characters. Keep commands, URLs and table rows on one line.
- UTF-8, LF line endings, one newline at the end of the file.

### Words to avoid

Filler and sales words add no information. Replace them with the behavior they claim.

| Instead of | Write |
| --- | --- |
| seamless handoff | the next session reads HANDOFF.md and continues |
| robust validation | the validator rejects missing IDs and broken references |
| it is important to note that X | X |
| leverage the tool | use the tool |

## Diagrams

Use plain text diagrams. Every agent and terminal reads them, and they need no renderer.
Draw only flows and trees that a table cannot show. Keep each diagram under 15 lines.
