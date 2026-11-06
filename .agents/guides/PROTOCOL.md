# Protocol

The formats, commands and rules behind AGENTS.md.
Schema `continuity.v3`, template version 3.7.0.

## Model

```text
              docs/state/*.md  (current facts, edited in place)
                    |
      ws add / set / card / verify   validate, assign IDs, write log rows
                    |
              docs/logs/*.md   (history, append only)
                    |
           ws checkpoint             seal hashes, log the session, release
                    |
   docs/archive/checkpoints/*.json   (integrity manifest, last 10 kept)
```

The state files hold the truth. Logs explain how it got there. A checkpoint records the hash of
every watched file, so the next session can tell which files changed after the last save.

## Commands

All commands run from the project root as `python .agents/tools/ws.py <command>`.
Read-only commands (`brief`, `turn`, `status`, `check`, `lint`, `doctor`) never write a file, not even the hash cache
in `.agents/cache/`. The one exception is the per-turn hook, `turn --hook`, which keeps two small markers there
for the Stop nudge.

| Command | Writes | Purpose |
| --- | --- | --- |
| `brief` | no | Resume summary: attention items, goal, card, open questions, tasks, sessions, guides, unsaved files |
| `turn` | no, except the prompt journal of Kiro and Cursor hooks | The per-turn reminder that prompt-submit hooks inject |
| `status` | no | Same facts as JSON |
| `check [--ready] [--strict]` | no | Validate. `--ready` also requires a released, sealed, covered workspace |
| `note TEXT` | yes | One progress line in SESSION_LOG. No validation, no seal |
| `init --goal TEXT` | yes | First run only. Records the goal and claims the workspace |
| `start [--session KEY]` | yes | Claims the workspace, lists unsaved files, imports sessions from the host stores (`WS_IMPORT=0` skips the import). The same session resumes instead of taking over |
| `add TABLE --set f=v` | yes | Adds a row with the next free ID and logs it |
| `set ID --set f=v` | yes | Changes a row. Status changes and summary edits are logged |
| `card --set f=v` | yes | Changes handoff card fields |
| `goal TEXT [--source S]` | yes | Changes the goal; the old text goes to REQUIREMENT_LOG |
| `verify [IDs] [--done] -- CMD` | yes | Runs acceptance, stores evidence, attaches it, optionally marks done |
| `checkpoint --stop T --next T [--keep]` | yes | Seals and logs the session. Releases ownership unless `--keep` |
| `compact [--dry-run]` | yes | Moves closed rows to CLOSED_ITEMS.md, full rows to `docs/archive/closed/`, and rolls long logs |
| `snapshot --label L [PATHS]` | yes | Zips the documents and named paths to `docs/archive/snapshots/` and sets the card `baseline` |
| `hooks enable\|show\|disable HOST` | yes, except `show` | Writes, prints or removes the brief, per-turn and transcript hooks of one host. `disable` gives back the file from before the first enable |
| `doctor [--json]` | no | Hooks, interpreter, session identity, lock and tool files at a glance. Exits with 1 when it finds a problem, and names the fix for each |
| `capture --host H --event E` | yes | Hook target. Copies the transcript named in the payload, or saves the message text it holds |
| `chats import HOST` | yes | Copies this project's sessions from a host store: kimi, codex, antigravity, kiro, cursor, workbuddy, codebuddy, qoder, qwen, gemini or dsh |
| `reconcile [ID --ids \| --reason]` | yes when marking | Lists saved user messages no row accounts for, or marks one |
| `lint` | no | Advisory layout and wording checks |
| `install`, `export`, `migrate`, `release` | yes | Distribution, see QUICKSTART.md |
| `upgrade --target DIR` | yes | Run from a newer template folder: brings the project's template files and hook entries to that version, keeps edited files for a hand merge and takes the new files into the checkpoint. `--dry-run`, `--rollback NAME`, `--scan FOLDER`; see QUICKSTART.md |
| `tidy [--dry-run] [--force]` | yes | Deletes template maintainer files an older install left in a project and adds `.ignore` and `.cursorindexingignore`. Files that differ from this release are listed and kept; `--force` deletes them too |

Field names in `--set` are the column names in lower case. Values are one line.
A pipe character inside a value is escaped automatically.

## Tables

Every state table starts with an `ID` column. IDs are a prefix letter and a number, never reused.

| Table | File | Prefix | Columns |
| --- | --- | --- | --- |
| requirements | REQUIREMENTS.md | R | ID, Status, Requirement, Acceptance, Detail, Reason |
| questions | REQUIREMENTS.md | Q | ID, Status, Question, Context, Answer |
| preferences | PREFERENCES.md | P | ID, Status, Preference, Source, Confidence |
| features | FEATURES.md | F | ID, Status, Behavior, Requirements, Tasks, Reason, Replacement |
| tasks | TASKS.md | T | ID, Status, Requirements, Scope, Action, Acceptance, Depends, Evidence, Reason |
| decisions | DESIGN.md | D | ID, Status, Decision, Reason, Source |

### Status values

| Table | Open | Closed |
| --- | --- | --- |
| requirements | active | deprecated, removed, replaced |
| questions | open (blocks the work it affects), deferred (work goes on with the default in Answer) | answered, dropped |
| preferences | active | retired |
| features | planned, building, unverified, shipped | deprecated, removed, replaced |
| tasks | todo, doing, unverified, blocked | done, dropped |
| decisions | adopted | superseded, rejected |

A row moving to `deprecated`, `removed`, `replaced`, `dropped` or `retired` needs a reason, and so does a
`blocked` task: the brief prints it next to the task.
Write `none` for an empty reference. List several IDs separated by commas: `R1, R4`.

### Cross references

- A task names at least one requirement. Its dependencies name tasks.
- A feature names its requirements and tasks. A shipped feature needs all its tasks done.
- A replacement names a feature. The Detail column is `inline` or a spec path.
- The validator checks every reference against live rows and CLOSED_ITEMS.md.

## Handoff card

The card in HANDOFF.md is a two-column table. All eleven fields are required.

| Field | Content |
| --- | --- |
| phase | Current stage, for example `implementation` |
| current_task | Task IDs in progress, such as `T3` or `T3, T4`, or `none` |
| current_feature | Feature IDs being built, such as `F2` or `F2, F5`, or `none` |
| stop_point | The exact point reached |
| last_verification | Last verify result, written by `ws verify` |
| baseline | Path of a reference snapshot or `none` |
| extra_reads | Paths in backticks the next session must read, or `none` |
| risks | Known risks and blockers |
| next_step | What the next session finishes, and where it stops. Later work belongs in TASKS.md |
| recovery_notes | Running processes (`pid=<n> log=<path>`), failed attempts, how to retry safely |
| next_acceptance | The command or observation that proves the next step |

Write "none confirmed" when you checked and found nothing. Write "unknown" when you did not check.

Write `stop_point` and `next_step` so a session that never saw this conversation can act on them:
name the task ID, the file or command, and one concrete next action. When the next step depends on
the user's choice, say so and point at the open question, instead of listing alternatives.
`recovery_notes` may be long: running jobs, failed attempts and safe retries are worth every line.

A detached run is recorded as `pid=<n> log=<path>` in `recovery_notes`. When the card is written, the tool
turns a Git Bash pid into the Windows pid and adds `started=<time>`; a pid that is not running is refused.
The brief reports each job as running, exited, or exited with its pid reused, and prints the last log line.
Replaced values of `risks`, `recovery_notes`, `next_acceptance` and `baseline` go to MAINTENANCE_LOG.

A one-off instruction such as "review only today" goes in `risks` or a `ws note` with the date and
"this session only". The next session ignores it unless the user repeats it. A lasting rule is a
preference.

The last line of HANDOFF.md is the machine state:
`<!-- CONTINUITY {"schema": "continuity.v3", "mode": "active", "revision": 12, ...} -->`.
Only `ws` writes it. Editing it by hand to silence an error corrupts the workspace.

## Ownership

The main session owns the card and the workspace seal. Other sessions may work beside it on tasks
they claim; see "Parallel sessions" below. Each session has a label such as `s-20261031-1420-a3f9`.

```text
 released (READY) --ws start--> owned by A --ws checkpoint--> released
                                    |
                     A dies or the window closes
                                    |
                     ws start in window B --> owned by B, takeover logged
```

| Setting | Behavior |
| --- | --- |
| `"ownership": "solo"` (default) | One person. `ws start` takes over and logs it when the owner stopped: its window exited, or, where windows cannot be told apart, it wrote nothing for 20 minutes. Otherwise `ws start` is refused until the user confirms with `--force --reason`; `--task` claims tasks beside the owner |
| `"ownership": "shared"` | Several writers on one checkout. Writes need `--writer` and `--rev`. Takeover needs `start --force --reason` |

Set the mode in the WORKSPACE block of ARCHITECTURE.md.

### Parallel sessions

`ws start --task T5 [--task T6]` claims tasks. A claim holds:

| Part | From |
| --- | --- |
| Tasks | The IDs given |
| Paths | Every project path named in each task's Scope or Acceptance (a module `tests.test_x` is `tests/test_x.py`) |
| Resources | Each `resource:<name>` in the Scope, such as `resource:vps/unpaywall` for a deployed service |

A task that names no existing path holds the whole tree, and so does a session that claims no task.
`ws start` compares the claim with every session still working (its window runs, or it wrote within
20 minutes when the window cannot be checked). The claim is refused when they share a task, a path
(one inside the other counts) or a resource; the error names the other session and what it holds.
`--force --reason "<what the user said>"` claims anyway and logs `parallel claim forced` with the reason.
A session that runs `ws start --task` again keeps its claim: the new tasks are checked the same way, and a task
it finished meanwhile is left out with a note. `--writer` names a claim only for the session that made it: its
session variable, or else its window, must match.

| While others work, a session may | It may not |
| --- | --- |
| Add requirements, questions, decisions, preferences and tasks | Change or verify a task another session claimed |
| Change, verify and checkpoint its own tasks | Retire a requirement or feature a claimed task cites |
| Run `ws note`, `ws reconcile` and every read-only command | Run `ws compact`, `ws goal`, `ws snapshot` or edit the card |

A parallel session's `ws checkpoint` checks only its own tasks, logs its hand edits of them, and writes its
stop point and next step to its row under "Parallel sessions" in HANDOFF.md. Without `--keep` the row is
marked released and holds nothing; released rows stay, also after a takeover, until the next seal. The main
session's checkpoint checks everything except tasks still claimed by others, and seals the workspace; files
inside other claims keep their last sealed hash, so the next session still sees them as unsaved, and those
tasks keep their last sealed state (`deferred` in the manifest), so their evidence is checked in full later.
The last session to leave seals only a workspace that passes the whole check; otherwise it releases without a
seal and prints the errors for the next session. The workspace is READY only when no session is working.

Known limit until 3.9.0: a parallel session in the main session's own window that wrote nothing for 20 minutes
counts as gone, so when the main session releases, its row is cleared and its files are sealed as they are.

A conflict the paths cannot show, such as one task changing an interface another task calls, is caught
by the other task's acceptance, which runs against the current code, and by its evidence going stale when
a file in its scope changes.

A session that loses ownership gets an error on its next write that names the new owner, when it
passes `--writer`, or when both it and the new owner run on a host that names its session in an
environment variable (`CLAUDE_CODE_SESSION_ID`, `CODEX_SESSION_ID`, `QWEN_CODE_SESSION_ID`,
`ZCODE_SESSION_ID`, `KIRO_SESSION_ID`, `CURSOR_CONVERSATION_ID`, or `WS_SESSION_ID` set by hand). It must stop and
re-read HANDOFF.md. A Cursor subagent has a `CURSOR_CONVERSATION_ID` of its own, so its writes get the same error,
which tells it to report to the conversation that started it. A host started from a Cursor agent shell inherits
`CURSOR_CONVERSATION_ID`, so any other of these variables wins over it. The per-turn hook compares the conversation
in its payload with the owner, when the owner claimed through the brief key or, on Cursor, through its variable, and
tells another conversation to stop at its next message. A conversation that holds a parallel claim is not told.

Every host is also identified by its window process: the nearest ancestor of ws.py that is not a shell or
interpreter, recorded with its start time when a session claims the workspace. While that process runs, another
window's `ws start` is refused and its writes are refused; the brief tells it "do not claim". When the user says
the old window is finished, `ws start --force --reason "..."` takes over and logs that the window was still running.
When the process has exited, `ws start` takes over without a warning. Two chats inside one application window
share its process, so there the session variable or the brief key decides. `WS_HOST_PID` names the window process
for a wrapper that starts ws.py from a helper. ZCode names each
subagent with its own id, so a ZCode id resumes a session but never refuses a write. `WS_SESSION_ID` must be
unique per conversation; set in a shell profile it would make every window one session.

The same session running `ws start` again, for example after compaction, resumes instead of taking
over, so its evidence stays valid. Hosts without such a variable get a key from the session start
hook: the brief's Next line reads `ws start --session k-...`. The key is used only to resume.

A session on a host with a session variable that released the workspace with `ws checkpoint` may write
again before anyone else claims it: the next write, `ws note`, `ws reconcile` and `ws snapshot` included, resumes
ownership and logs `resume`. The resume takes a revision of its own; `--rev` still names the revision read before
it. Other sessions still need `ws start`.

When the owner's window cannot be checked (its process chain was broken, or it was claimed before 3.6.3) and it
wrote less than 20 minutes ago, the brief's Next line says "do not claim yet" and `ws start` is refused until the
user confirms with `--force --reason`. In the owner's own window with no session variable, the refusal says that
the conversation holding the workspace goes on without a new start, and that another one asks the user.

### Subagents and helper windows

A session started with `WS_ROLE=worker` (or `readonly`) never writes: `start`, `add`, `set`, `card`,
`verify`, `checkpoint` and `compact` refuse with an error, and the brief tells it to report to the
session that started it. Set the variable in the environment of each subagent, workflow step or helper
window, and say the same in its prompt, because some hosts start subagents with the parent's session
variables. The owner records the worker's results and runs `ws verify` itself; a worker may save
command output under `.tmp/`, never under `docs/archive/checks/`.

## Unsaved changes

Files that changed after the last checkpoint are listed by `ws brief`, `ws status` and `ws start`.
They are normal while a session works. After a takeover they show the dead session's unfinished
work, so inspect them before editing.

The watch skips dependency, build, cache and IDE folders, `docs/chats/`, `docs/archive/` and
host settings folders such as `.claude/`. Add other generated paths to `exclude`:

```text
<!-- WORKSPACE:START -->
{"ownership": "solo", "exclude": ["data/raw/**", "*.sqlite"]}
<!-- WORKSPACE:END -->
```

Excluded files have no change detection. Never exclude source code.
File hashes are cached by size and modification time in `.agents/cache/`, which is safe to delete.

## Evidence

`ws verify` runs the command without a shell, from the project root, with a 900-second timeout.
Use a script for pipelines. The command is accepted when all of these hold:

1. Exit code 0.
2. For test acceptance: at least one passing test and no failures or errors.
3. No watched source file changed during the run.

Recognized summaries: Python unittest, pytest, Node TAP, Jest and Vitest. For other runners write a
report with `--report json` (schema `test-summary.v1`) or `--report junit`. The examples in
`.agents/template/examples/` show both.

Evidence records which version of these reading rules summarized its output (`rules`, 2 since 3.7.0) and is
always read again with those rules, so a newer tool never invalidates older evidence. `ws check` notes a done
task whose evidence passed under older rules but would not under the current ones.

The command must match the Acceptance column of each named task, after removing a `check:` prefix
and backticks. Otherwise verify refuses and names both commands. Change the acceptance with
`ws set T4 --set acceptance=...` when it is wrong. `--because "<reason>"` runs a different command
anyway and writes the reason to MAINTENANCE_LOG. This stops a task being proven with an easier test.

- An acceptance with no command, or with shell operators such as `&&` or `|`, is refused. Verify runs
  without a shell, so name a script that runs the steps.
- Backslashes in Windows paths are kept as written.
- Evidence records the tasks it was run for. A task marked done with evidence from another run fails
  the checkpoint.

Evidence is stale when a file in the task's scope changes after it was recorded. The scope is every
project path named in the task's Scope or Acceptance cell (a module such as `tests.test_x` counts as
`tests/test_x.py`); when the cells name no existing path, the whole project counts. Edits under
`docs/`, `.agents/` and the adapter files never make evidence stale. A task marked done must have
evidence from the current owner, recorded after it claimed the workspace.

The watch skips `.tmp/`, `tmp/`, `.scratch/`, database files and journals (`.db`, `.sqlite`, `-wal`,
`-shm`), `.swp`, `.tmp`, `.out` and `.pid` files, so services and probes running next to a verify do not
reject it.

The command runs outside the workspace lock, so other sessions can record while a long acceptance
runs. If ownership or the task changes during the run, the evidence is kept but not attached.

A `check:` run whose output says no tests ran (`Ran 0 tests`, `collected 0 items`) is rejected.

A check of behavior names the output that proves it, with one or more expect clauses after the command:

```text
check: python ops/probe.py expect "HTTP 200" expect /size \d+ bytes/
```

A quoted text must appear in the output; `/.../` is a regular expression. A run without every expected output is
rejected, and the evidence records what was expected, so a later edit of the output fails the checkpoint. A check
with no expect clause proves only exit code 0, which suits a build or linter; verify says so and the card shows
"no expected output".

When a test writes files, point them at an excluded folder such as `.cache/` or `build/`.
Otherwise the run is rejected with the list of changed files.

The verify line names skipped and deselected tests. When an accepted run tests less than the task's
previous accepted run of the same command (fewer tests, more skipped or deselected, a test file
removed, or test runner config changed), verify prints a note. It never refuses: tasks often change
their tests on purpose. Every run adds a `verify accepted` or `verify rejected` row to MAINTENANCE_LOG,
and the brief shows a task with two or more rejected runs in a row.

Editing an acceptance, scope, action, requirements or dependency of a task writes a CHANGE_LOG row
with the old value, so a switch to an easier command stays visible.

## Logs

The tool writes every log row. Agents never need to edit a log by hand.

| Log | Written by | One row per |
| --- | --- | --- |
| SESSION_LOG.md | checkpoint, note | Checkpoint: writer, stop point, next step, verification, rows recorded and files changed. A note row has verification `note` |
| REQUIREMENT_LOG.md | init, add, set | Goal, requirement, question or preference change |
| CHANGE_LOG.md | add, set, verify | Feature or decision change, task definition edit, feature shipped by verify |
| MAINTENANCE_LOG.md | init, start, card, compact, migrate, verify, snapshot | Takeover, compaction, migration, each verify run, `verify --because` override, replaced card values, snapshot |
| RECONCILE_LOG.md | reconcile | How a saved user message was accounted for |

When a log passes 64 KB, the oldest rows move to `docs/archive/logs/`. The log's Archives table
records each file with its row count and SHA-256, and the validator checks those hashes.

## Growth control

| Mechanism | Effect |
| --- | --- |
| `ws compact` | Moves closed rows from state tables to CLOSED_ITEMS.md. IDs stay reserved |
| Log rolling | Keeps the newest 40 rows live once a log passes 64 KB |
| Checkpoint retention | Keeps the newest 10 manifests |
| `compact --prune-evidence` | Deletes evidence files that no row and no checkpoint references |
| Size warnings | `ws check` warns when AGENTS.md passes 14 KB, T0 passes 26 KB or a state file passes 16 KB |
| Specs | Long requirement detail lives in `docs/specs/<slug>/`, outside T0 |

The current task and feature always stay in the live tables, even when closed.

`ws compact` writes each full row, every column untruncated, to `docs/archive/closed/<ID>.md` before it
touches CLOSED_ITEMS.md, and both before the state files. A compact that dies halfway loses nothing;
running it again finishes the move. CLOSED_ITEMS.md keeps a short row with a `Row` column that names the
archive file. Rows closed before 3.6 have `none` there. The brief lists the last five removed or replaced
requirements and features with their reasons, under "Retired, do not rebuild".

`ws snapshot --label before-<what> [PATHS]` zips AGENTS.md, README.md, the adapter files, `docs/state`, `docs/specs`,
`docs/guides`, `docs/logs`, `ops/` and the named paths into `docs/archive/snapshots/`, and points the card
`baseline` at it. It refuses more than 10,000 files or 100 MB, and a drive with less free space than twice
the size plus 1 GB. It skips `.env` files and key files. Snapshots marked `--pin` and the baseline are never
pruned; others are pruned oldest first while more than five remain and they pass 100 MB. Nothing restores a
snapshot in place: extract it next to the project and copy back by hand.

## Coverage

The format checks cannot see the conversation, so three coverage checks catch the common gaps.

| Check | When | Effect |
| --- | --- | --- |
| Goal without requirements | A goal is set and REQUIREMENTS.md has no requirement row, live or closed | Shown first in `ws brief`, blocks `check --ready`. With an open question it is a warning only |
| Code without tracking | Product files changed, no task is `doing`, and no requirement or task row was added or changed | Warning in `brief`, `start`, `check` and `checkpoint`, and one line in the per-turn reminder |
| Nothing recorded | A checkpoint finds no new rows since the previous one | One line in the checkpoint output, a reminder only |

Product files are watched files outside `docs/`, `.agents/` and the adapter files, excluding
Markdown and text files.

A task marked `doing` covers the edits. Otherwise the code-without-tracking warning repeats at every
checkpoint until a requirement or task row is added or changed. Adding a question or editing the Idea
pool does not clear it.

Links between rows are checked as well:

- `ws verify --done` sets a planned or building feature to `shipped` when it finishes the feature's last task,
  with a CHANGE_LOG row. An `unverified` feature waits for the agent.
- `ws add` warns when a new requirement, feature or decision repeats the text of a retired one, and lists
  the three retired rows of that table whose words overlap it most, for the agent to compare by meaning.
- A task definition edited by hand shows in the brief, and the next checkpoint writes its old value to
  CHANGE_LOG as `edited outside ws`. The checkpoint keeps the field texts of every task for this.
- `ws check` and `ws start` warn about a folder in `docs/specs/` that no requirement links, live or
  compacted, a spec whose "Requirement IDs:" line misses the linking row or names an unknown ID, and a
  spec that still holds the template text.
- `ws set` on a requirement that changes its status or text lists the open tasks and live features
  that cite it, so they are updated in the same session.
- `ws check`, the brief and the checkpoint warn when an open task or a live feature cites only
  retired requirements.
- The brief prints `Requirements verified: n/m`, counting active requirements that a done task with
  evidence cites, and the next todo task whose dependencies are done.

## Reconciliation

The coverage checks see an empty table, not a missed sentence. Reconciliation closes that gap
when the conversation is on disk, copied by a hook or by `ws chats import`.

```text
ws reconcile                        list user messages that no row accounts for yet
ws reconcile m3fa91c02e --ids R4,P2 the message is recorded by these rows
ws reconcile m77b0e1d4a --reason "chat: thanks"
ws reconcile all --reason "duplicate: pasted twice"
```

A reason starts with `question`, `chat`, `duplicate`, `superseded`, `out-of-scope` or `secret`.
Short continuation messages such as "继续" or "ok" are skipped automatically. Each answer is a row
in `docs/logs/RECONCILE_LOG.md`, so a later session can see why a message produced no record.
The brief, the per-turn hook and the checkpoint report how many messages are still open.
READY is refused while any saved message is open: answer each one with row IDs or a reason, then checkpoint again.
A host with no hook and no import saves no messages, so READY cannot check them; checkpoint prints a notice.

## Credentials

How a project keeps passwords, keys and tokens is the user's decision. The agent asks the first time
one appears and records the answer twice: as a preference in the user's words, and as the WORKSPACE
`"credentials"` setting in ARCHITECTURE.md, which the tool follows.

| Setting | Meaning | What the tool does |
| --- | --- | --- |
| `"ask"` (default) | Not decided yet | Redacts as below, and the prompt hook tells the agent to ask before writing a credential anywhere |
| `"plain"` | Keep credentials as written, where the user said | Writes every value as given, in rows, cards, notes, evidence and transcripts; `ws check` does not report them |
| `"redact"` | Keep credentials out of the workspace files | Redacts as below; the agent names the variable or file that holds each one |

The preference says where a credential goes when it is kept as written, for example
"server passwords go in docs/guides/server.md". Changing the answer later is a `ws set` on the
preference and an edit of the setting.

With `"ask"` and `"redact"`, values that look like credentials are replaced with `[REDACTED]` wherever
the tool writes text:
rows and card fields from `add`, `set` and `card`, the goal, stop point and next step, sources,
reasons, verify labels, notes, and both copies of a transcript. User messages also lose unlabeled
random tokens of 24 or more mixed-case letters and digits.

A password of letters only is removed after `password:`, `password =`, `password is`, `密码：` or
`密码是`. After a bare label, as in "my password hunterhunter", it is removed unless it is a common
English word, as in "password manager". Names that hold no secret, such as `primary_key`,
`public_key` and `csrf_token`, are left alone.
`ws check` scans `docs/` and `ops/` for credentials written by hand and names the file and line.

Recognized forms include `password: ...`, `"password": "..."`, `secret_key = ...`, `密码：...`,
`| 密码 | ... |`, `user:password@host` and `?token=...` in URLs, and key formats such as `sk-`,
`ghp_`, `github_pat_`, `AKIA`, JWTs and private key headers. Environment variable names such as
`LITGW_API_KEY`, placeholders such as `<your password>`, versions, counts and plain words are not
reported. A credential split by invisible characters (zero-width space or joiner, soft hyphen, BOM)
is found and redacted with them removed.

The raw transcript copy never keeps a host's `encrypted_content` fields, even with `"plain"`: Codex
stores compaction and reasoning there as blobs the host can replay, and they hold no user text.

## Recovery

What to do for each error and interruption is in one place: `.agents/skills/maintain-project-state/SKILL.md`,
"Resume" for a new session that finds unfinished work and "Recover" for each message `ws` prints. When `ws`
cannot run at all, edit the tables by hand in the formats above and run `ws check` when it can run again.

## Limits

- The lock is cooperative. A process that edits files without `ws` bypasses it.
- Hashes detect accidental change, not deliberate forgery by someone who can edit the evidence.
- The validator checks structure and references. It cannot judge whether a requirement is right or a test is sufficient.
- `ws verify` proves that the recorded acceptance ran and passed. It does not stop anyone from changing the test or
  the code until it passes.
- READY means the workspace is saved, released and consistent. It does not mean the product works or meets every
  requirement.
- Coverage checks catch an empty requirement table and untracked code. They cannot tell whether
  one requirement out of several was missed.
- The credential scan matches common patterns. A secret in an unusual form can pass it.
- Hooks capture transcripts only for hosts where `ws hooks enable` has been run and tested.

## Autosave

Set `"autosave": true` in the WORKSPACE block to save an intermediate checkpoint whenever a Stop
hook fires and the state is valid. A refused autosave changes nothing. It is off by default because
each autosave adds a checkpoint manifest.

## Stop nudge

Set `"stop_nudge": true` in the WORKSPACE block to have the Stop hook ask once when a turn ended
without any record. The per-turn hook notes the revision when a user message arrives. If the turn
ends with the same revision and no new `ws note`, the Stop hook tells the agent to record the message
or write `ws note "no record: <reason>"`. The marker is removed before the hook answers, so the next
stop always passes.

| Host | Stop output |
| --- | --- |
| Claude Code, Codex | `{"decision": "block", "reason": ...}` |
| Cursor | `{"followup_message": ...}` |
| Gemini | `{"decision": "deny", "reason": ...}` |
| Antigravity | `{"decision": "continue", "reason": ...}` |
| Kiro | none; its Stop hook cannot block |
| Copilot, Grok | none; the hooks written here have no per-turn hook to note the message |

The hook passes without asking when the host reports a repeated stop (`stop_hook_active`,
`stopHookActive` or `loop_count` above 0) or a stop for another reason than the end of a turn. It is
off by default: a blocked stop costs one more model turn, and a turn with nothing to record still
needs the note.
