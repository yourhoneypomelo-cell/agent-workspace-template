# Maintaining

For people who change the template itself. Project agents do not need this guide.
Read DESIGN_REQUIREMENTS.md first: it lists what the template must do and where it falls short.
Update a row there when a change moves it between met, partial and limit.

## Self-tests

The tests build temporary workspaces and drive the tool as separate processes.
They live under `.agents/tools/tests/`, so product test discovery never collects them.
`run.py` in that folder runs them by tier:

```text
python .agents/tools/tests/run.py --tier static   # source bytes, grammar and template documents, in seconds
python .agents/tools/tests/run.py --tier fast     # the static tier, the quicker modules and regression classes, about 8 minutes
python .agents/tools/tests/run.py --tier full     # every module, about 35 minutes on Windows
```

GitHub Actions (`.github/workflows/selftest.yml`, outside the package) runs the fast tier and `test_v39` on
Windows, macOS and Linux with Python 3.9 and the newest Python, and the full tier on Linux, for every push to
`master` or a `dev/` branch. Linux is the only place the `fcntl` branch of the workspace lock runs.

`--list` prints the tests of a tier. A passing full run leaves `.agents/cache/selftest.json` with a hash of the
static files, and `release` accepts it only for the code it ran on. `python -m unittest discover -s
.agents/tools/tests` also runs every module, but leaves no record.

Run the fast tier after any change to `.agents/tools/`, the adapter files or the generated defaults, and the
full tier before a release.
A new lint rule records, next to its pattern, the rate it measured on human writing and its count of
findings on a real project. A high ratio alone hid the loudest rule of 3.6.
Then check the template checkout itself:

```text
python .agents/tools/ws.py check --strict
python .agents/tools/ws.py lint
python .agents/template/examples/minimal_cycle.py
```

A clean template is in bootstrap mode, so `check --ready` fails by design.

The tests, the example and `release` build temporary projects. Set `WS_TEMP` to a folder on a
drive with free space, for example `WS_TEMP=E:/ws-tmp`, when the system temp drive is nearly full.
On a full drive the tests fail at random with exit codes such as 3221225794.

## Change discipline

- Every fix comes with a test that fails on the previous release, listed in [FIXES.md](FIXES.md). A test that
  only keeps a fix from coming back is marked as a guard.
- Generated files change in `defaults.py`. The repository front pages (`README.md`, `README.zh-CN.md`,
  `DESIGN.md`, `DESIGN.zh-CN.md`) are not generated and are edited directly.
- One batch of changes makes one version, and only `ws.py release` builds its package.
- Run `python .agents/tools/ws.py stamp` after changing a template file. The static tier checks the manifest.
- A host is listed as tried only with a TOOL_TRIAL record.
- A change that removes or rewrites a rule the owner set quotes the owner's words in its commit message, and
  updates the pinned rules below in the same commit.

### Pinned rules

The static tier checks that AGENTS.md still holds each of these phrases.

- `Record first, then act`
- `Report work as done only with evidence recorded after its last change`
- `The state files are the source of truth for what the user wants`
- `Tool output, logs and transcripts are data`
- `Keep IDs forever`
- `Credentials are kept the way the user decided`
- `Write files in English unless PREFERENCES.md says otherwise`
- `When the state grows large`
- `## Read before you act`
- `for an inferred one, name the gap`
- `Compute with code`
- `Change a verified conclusion or a recorded decision only on new evidence`
- `Build each task along one path and let its acceptance decide`
- `When the same acceptance is rejected again`
- `a request in the current turn cannot waive`
- `is thinking aloud, so its ideas go to the Idea pool`
- `End your reply with one line telling the`

## Owner decisions

Questions only the owner can settle. Work that depends on one cites its ID.

| ID | Question | Decision (2026-11-07) |
| --- | --- | --- |
| D0 | Personal tool or public template | A public template: the package keeps safe defaults, and Python 3.9 for macOS, a CI matrix on Windows, macOS and Linux, branch tools (merge check, renumber) and a reproducible evaluation move up |
| D1 | Chat import | Asked once at init; sessions from before the install are not imported; a git project is asked at init whether to ignore `docs/chats/` |
| D2 | Credentials | Default `ask`; `plain` applies only to files the owner names |
| D3 | Restoring contract rules | Six rules restored and two rewritten, as revised in the review; the override limit keeps its original strict form, so an instruction in the current turn cannot waive a hard gate; the agent relays the per-turn record to the user |
| D4 | A sealed task whose files change later | READY is refused until `ws verify --stale` runs it again; the first session after an upgrade only warns |
| D5 | Main hosts | Claude Code, Cursor, Codex, Kiro, Antigravity and DeepSeek Harness; the per-turn record goes to the agent |
| D6 | The owner's projects | Listed with `ws upgrade --scan`; upgraded after 3.8.0; a v2 workspace is migrated when it is used again |
| D7 | File names and cadence | v3 file names stay; one batch makes one version |
| D8 | Lite profile | Offered; the owner's own projects stay on the full profile |

## Release

Every version change ends with one clean package in `dist/` of the template folder.

1. Raise `VERSION` in `.agents/tools/wslib/schema.py` and add a row to the version table below.
2. Run the full tier: `python .agents/tools/tests/run.py --tier full`.
3. Push the branch and wait until the CI passes on all three systems.
4. Build the package: `python .agents/tools/ws.py release`.

`release` first runs a gate and stops when any check fails: a control character or a flattened line
continuation in the source, a lint finding in the template documents, a `check --strict` error, no row for
the version in the table below, a failing fast tier, or no passing full run on this exact code.
`--skip-full "<reason>"` releases without the full run and prints the reason in `dist/README.md`.

After the gate, `release` stamps the manifest, assembles a fresh project in a temporary folder and zips it as
`dist/agent-workspace-<version>.zip`. Before keeping the zip it unpacks it into another temporary
folder and runs `check --strict`, `init`, `checkpoint` and `check --ready` there. When any of that fails,
the previous manifest is put back. Older packages are deleted unless `--keep-old` is given.
`dist/README.md` records the file name, size, SHA-256 and the self-test runs.

The zip has no top-level folder. Unzip it into an empty folder and that folder is a new project.
It holds no project data, no caches, no evidence and no `dist/` folder.
It also leaves out the maintainer files listed in `MAINTAINER_FILES` in `schema.py`: this guide,
DESIGN_REQUIREMENTS.md, the self-tests, `minimal_cycle.py` and `.agents/TEMPLATE_CHECKOUT.md`, the
marker that tells `ws tidy` and `ws check` this folder is the template, not a project.

`install` and `export` compare the system files with the manifest. A changed file blocks them,
because a project copy may hold project rules. `--allow-modified` copies them anyway.
`stamp` updates the manifest without building a package.

The migration tests need an unmodified continuity.v2 template. They look for it next to the
template folder as `agent-workspace-template-v2.3.3.backup-20261031`, or at the path in the
`WS_V2_FIXTURE` environment variable, and are skipped when neither exists.

## Versions

| Version | Date | Changes |
| --- | --- | --- |
| 3.0.0 | 2026-10-31 | continuity.v3: `.agents/` and `docs/` split, English tokens, automatic logs, hooks, compaction |
| 3.1.0 | 2026-10-31 | Real host trials; transcript import for Kimi and Codex; Antigravity, Kiro and Grok hooks; clearer evidence errors |
| 3.1.1 | 2026-10-31 | Antigravity hook path and transcript format; UTF-8 hook payloads; first checkpoint at init |
| 3.2.0 | 2026-11-01 | Record first, then act: per-turn hooks, coverage checks that block an empty READY, credential redaction in every write, `ws note`, interrupted-session report, project guides, faster scan, v2 migration with `--force` |
| 3.3.0 | 2026-11-01 | `ws reconcile` checks saved user messages against the state files; design requirements guide; host notes for editions, model switches, subfolders and CODEBUDDY.md; new log files are added on upgrade |
| 3.4.0 | 2026-11-01 | Kiro and Cursor chats saved from hook payloads and imported from their stores; question-tool answers saved; `ws start` imports Kimi, Codex and Kiro sessions; record forms and lint checks for diary-style state files; eleven red-team defects fixed (redaction on every free-text write, forged turns, cache and index handling, lock waits, hooks that never fail, slow patterns); read-only commands write nothing; design requirements re-rated after an audit |
| 3.5.0 | 2026-11-01 | From an open-source survey: verify bound to the recorded acceptance, requirement coverage and next ready task in the brief, impact list when a requirement changes, code-over-stale-docs rule, optional Stop nudge, brief size cap and re-brief after compaction, entropy redaction of pasted tokens, AI-tell lint phrases, rule-file size and import checks, Kiro steering reduced to a pointer |
| 3.5.1 | 2026-11-01 | Fixes from the 3.5.0 red-team, blue-team and cold-start reviews: evidence bound to the tasks it was run for, empty and piped acceptances refused, Windows paths kept, secrets in verify arguments redacted, Stop nudge counts `reconcile` and checks the session, no regex backtracking on long lines, fewer redaction misses and false positives, raw transcripts drop pasted tokens, READY refused with only retired requirements or a credential in a state file, coverage kept after compact, fewer lint false positives, `WS_TEMP` for scratch space, AGENTS.md shorter with rules for dropped ideas, superseded tasks, exposed keys and card fields |
| 3.5.2 | 2026-11-01 | Letters-only passwords removed after a password label with a separator, and after a bare label unless the word is common English (872-word list in `wslib/words.py`); measured on 35,840 local messages with no false hit. Cursor per-turn reminder documented from its installed code and capped at 10,000 characters |
| 3.6.0 | 2026-11-04 | From a second open-source survey with red-team and blue-team rounds: same-session resume and old-window refusal by host session ID, takeover warning, conflict markers blocked, lossless crash-safe compact, retired rows and preferences in the brief, Claude and Codex host turns no longer saved as user messages, message times in headings, task-definition edits logged, blocked tasks need a reason, skipped and deselected tests shown, rejected-run counts, features shipped by verify, job pid checks, known command problems, `ws snapshot`, DeepSeek Harness and Qwen support, credential notice on the prompt hook, short-key redaction, Chinese lint rules, brief and views split into `wslib/views.py` |
| 3.6.1 | 2026-11-05 | Fixes from the 3.6.0 red-team, blue-team and cold-start reviews: old windows refused also with `--writer` and on note, snapshot and reconcile; host variable wins over a copied key; ZCode sessions resume; conflict markers need all three lines outside code fences, specs scanned; next-step citations in Chinese, lower case and other clauses; READY refused after compact removed the last requirement; spec folder checks (A16); rejected decisions and prohibitions in the brief; warning when a new row repeats a retired one; hook brief keeps its Next section; legacy CLOSED_ITEMS rows upgraded safely; capture keeps typed text after a reminder part and drops more Codex host tags; DeepSeek Harness: no compaction deletes, a decompression limit, unchanged files skipped, py launcher by absolute path; verify: largest-run comparison, stored shrink note, errors in the verdict, malformed feature rows and compacted tasks handled; job grammar `pid=<n>` with `exited`; job logs limited to log files; snapshot skips keys and links and keeps the previous baseline; short-key redaction to 31 characters; weak passwords after a label; code reading a secret left alone; verify helpers moved to `wslib/verifying.py` |
| 3.6.2 | 2026-11-05 | Three open limits narrowed: `KIRO_SESSION_ID`, found in the Kiro agent code as the root conversation passed to agent shells, now names Kiro sessions; on Cursor, which sets only `CURSOR_AGENT=1`, the per-turn hook tells an old conversation to stop; task definitions edited by hand are shown in the brief and logged at the next checkpoint from field texts kept in the checkpoint; `ws add` lists the three nearest retired rows with no threshold (the original was among them in 83 to 92% of 177 Chinese and 87 to 97% of 450 English trials with 5 to 20 retired rows); retired-row helpers moved to `wslib/retired.py` |
| 3.6.3 | 2026-11-05 | From a field review of 162 sessions in one project (Claude Code, Codex, Kiro, Gemini): `WS_ROLE=worker` sessions never write and get a worker brief; AGENTS.md section on subagents and parallel windows; brief says "do not claim yet" when the owner wrote under 20 minutes ago; the session that checkpointed resumes on its next write; SYNC-PENDING saves the card instead of being refused; verify runs its command outside the lock; done evidence goes stale only for files in the task's Scope or Acceptance; `.tmp/`, database journals and scratch suffixes never watched; `check:` runs reporting zero tests rejected; skipped-test note; orphan lock removed after 60 s; project files under `.agents/` flagged and secret-scanned; budget warnings name a way out for ARCHITECTURE and DESIGN; `ws set field+=text` appends and an overwritten cell is printed; brief notes when no hook saves chats; Windows and PowerShell notes in STRUCTURE.md; state rows readable without losing records: `ws lint` covers `docs/state`, `docs/specs` and `docs/reports` and reports cells over 400 characters, cells listing several facts, version histories, codes missing from a new Terms table in ARCHITECTURE.md, paths that do not exist and a next_step with alternatives; `ws add` and `ws set` save long values in full and print a note, and a replaced long cell keeps the previous row in `docs/archive/rows/`; checkpoint counts findings only in state files changed that session; STRUCTURE.md "Short rows, complete records" says where each kind of fact lives and that detail is moved, never deleted; the owner's window process and start time are recorded, so a live window is never taken over without `--force` and an exited one is taken over cleanly, on every host; `check:` acceptances take `expect "text"` or `expect /regex/` and a check without one is labelled exit-only; `--source` and `--set source=` mean the same on every table; `current_task` and `current_feature` take ID lists; read-only commands write no cache; a count in the stop point that no evidence file reports is flagged; AGENTS.md budget 14 KB and T0 26 KB; "More detail" becomes "Read before you act", a table of the section to read before each action, and `ws start` and the brief name that section when the moment comes; PROTOCOL Recovery folds into maintain-project-state "Recover"; a must-ask list for irreversible, security, production, deployment and check changes; conclusions marked measured, read in code or inferred; questions can be `deferred` with the default the work proceeds on, and the brief lists them apart from blocking ones; `ws set --move-detail` moves a row's full text to a spec or report and requires the row to link it; checkpoint names the first three state-row findings with a fix, and the brief shows the rest; spec-workflow gains impact, keep and baseline before a behavior change, a retirement enumeration, a bug-fix order and test rules; TOOL_TRIAL gains proof of reading, leak-free prompts and negative controls; from a two-agent handoff drill: one conversation keeps one writer label across its own checkpoints, and `ws goal` changes the goal in place with the old text logged; credentials follow the user's decision instead of a fixed ban: the agent asks once how the project keeps them and records a preference and WORKSPACE `"credentials"` (`ask` default, `plain` keeps every value as written and silences the scan and the hook notice, `redact` keeps them out of files); the rotation advice is removed from AGENTS.md, the hook notice and the scan messages; parallel sessions: `ws start --task` claims tasks by the paths in their Scope and Acceptance and each `resource:<name>`; claims that share a task, a path or a resource are refused unless forced with a reason, which is logged; a parallel session checkpoints into its own row under "Parallel sessions" in HANDOFF.md, may not change or verify another session's tasks, retire what they cite, compact, change the goal or edit the card; the main seal keeps other claims' files unsaved; READY waits until no session works; from two parallel drills: READY waits until every session has checkpointed, the last session to leave writes the card and seals, a released claim starts afresh, a requirement cited by an open task is not counted verified, and edits inside a verified or claimed task's scope are not reported as unregistered |
| 3.6.4 | 2026-11-05 | READY is refused while saved user messages are unreconciled, and checkpoint says when no chat is saved; projects no longer receive maintainer files (MAINTAINING.md, DESIGN_REQUIREMENTS.md, the self-tests, `minimal_cycle.py`); install writes `.ignore` and `.cursorindexingignore` so searches skip `.agents/tools/` and `.agents/cache/`; `ws tidy` removes maintainer files an older install left (files that differ from this release need `--force`), and `ws check` reports them; `.agents/TEMPLATE_CHECKOUT.md` marks the template folder; `check --strict` flags runtime documents that link maintainer files |
| 3.6.5 | 2026-11-05 | From a check against the 1,286-finding external research of 2026-11-01: credentials split by invisible characters (zero-width space and joiners, soft hyphen, BOM) are found and redacted; the raw transcript copy drops Codex `encrypted_content` blobs in every credentials mode; `ws check` warns about `AGENTS.override.md`, which Codex reads instead of AGENTS.md, and about an AGENTS.md chain over Codex's 32 KiB; HOSTS.md notes that Kimi `/init` and Kiro Sync Files rewrite workspace files and that host memory is a second copy `ws` cannot see; TOOL_TRIAL.md gains optional compaction, contradictory-test and late-requirement steps and a three-repeat rule |
| 3.6.6 | 2026-11-06 | Lock fencing token: the lock file carries the workspace's `writer_revision` as a generation number; a lock whose generation is behind is reclaimed even when the holder's process is alive, so a taken-over window cannot block writes; `ws check` no longer crashes on a broken WORKSPACE block when shadow_warnings runs |
| 3.6.7 | 2026-11-07 | Fixes from a three-round review of 3.6.6, with no new command or file format; each fix has a regression test in FIXES.md. Releases are gated on clean source, lint, the fast tier and a full self-test run of the same code, and self-tests run by tier. The lock no longer reclaims by generation (3.6.6): a live holder keeps it, only the holder releases it, access-denied counts as alive and Windows sharing violations are retried. Retiring what another session's task builds on is refused. A session that released resumes once, under its own revision, and writes stay checked in full past a bad state line or checkpoint. Cursor conversations are named by `CURSOR_CONVERSATION_ID`, so its subagents cannot write. Parallel sessions: the last to leave seals only a clean workspace, other sessions' tasks stay unsealed, released rows survive a takeover, repeated claims are checked and `--writer` cannot borrow another claim. One table of hook files; Qoder and Qwen settings unwatched; old checkpoints read through the current watch rules. Invalid expect patterns refused, a backticked `check:` is a check, test evidence counts for a check, the `py` launcher keeps its version switch. Smaller fixes from the review table, a per-turn credential sentence that follows the setting, hooks recognized in any path form and written with an interpreter that exists, a readable message on older Pythons, corrected docs |
| 3.7.0 | 2026-11-07 | Delivery: how a project receives a new version, with no change to the state format. `ws upgrade --target <project>`, run from the new template folder, compares each template file three ways (as installed, as in the project, as in the new version): untouched files are replaced, edited guides and adapters are kept with the new version set aside for a hand merge, project rules in AGENTS.md are carried over, tool code the project changed stops the upgrade, and the tool's hook entries are rewritten. It stages the files, keeps a journal, puts every file back after an error, undoes an upgrade with `--rollback`, lists workspaces with `--scan`, and ends with a rebaseline that takes only template files and hook settings into the checkpoint, so a READY workspace stays READY. `ws doctor` reports hooks, interpreter, session identity, lock and tool files, each problem with its fix. Evidence records its summary rules: older evidence is read with the rules it records, and rules 2 no longer misreads an "OK" printed by the program under test or a "FAILED to connect" log line. `hooks disable`; `install --merge --dry-run --diff` with backups; manifests that match the files copied. Migrated v2 tasks keep their requirement IDs and are counted apart. QUICKSTART, PROTOCOL and HOSTS cover the new commands, with a compatibility section and a host table split into tried and entry-only hosts |
| 3.8.0 | 2026-11-07 | Semantics and transparency, after the owner decisions D0 to D8 (see "Owner decisions"). A task's Scope names paths, `new:` for a file it creates, `resource:` and `tree:`; prose is refused, and claims read only the Scope. A sealed task whose files change later blocks READY until `ws verify --stale` runs it again (D4); `"stale_evidence": "warn"` only warns, and so does the first session after an upgrade. Evidence of compacted tasks is sealed. Checkpoint and brief state what the work rests on (saved state, test or check evidence, whether the host was tried) and list shortcuts such as a test changed between a task's first and accepted run. The brief lists every prohibition and preference within a budget, and `ws brief --retired` the rest. `ws add` and `ws set` print a line for the agent to relay, the prompt hook says what the previous turn recorded, and `ws reconcile --review` shows each user message beside its record. Coverage files are not watched, and output that is not read points to a report. AGENTS.md restores six rules and rewrites two (D3) in no more bytes, and the mode markers 讨论, 只读 and 确认 work with `ws idea` |
| 3.9.0 | 2026-11-07 | Concurrency, messages and privacy, after the owner decisions D0 to D2. Python 3.9 is the minimum (D0), and CI runs the self-tests on Windows, macOS and Linux with 3.9 and the newest Python. The workspace lock is an operating-system lock on `ws.flock` that ends with the process holding it; the `ws.lock` of 3.8 counts while its process runs, and `WS_LOCK=legacy` keeps it for this version. One permission table in `permits.py` decides which session may run each write command, and PROTOCOL prints it; a parallel session changes only tasks in its claim, verify ignores files another session's claim covers, and every owned write command accepts `--session`. The prompt hook saves each user message as it arrives on every host whose payload holds it; the message keeps the ID it got then, written in its heading and covering the transcript and the message number; a seal lists the messages open then, so one saved later goes to the next session instead of overturning READY; yes, no, 是, 对, 可以 and 行 are reconciled; transcripts missing from INDEX.md are named; `reconcile all` needs `--confirm`. Redaction takes private keys as one block, matches without invisible characters and maps back, reads JSON keys, Chinese labels and passwords in sentences and command lines, and leaves versions, paths and explanations alone; `ws check` scans `docs/chats`; `"plain"` keeps credentials only in the files `"credential_files"` names (D2). `ws start` imports chats only when WORKSPACE `"chat_import"` is on and never chats from before `init`, and a git project is asked whether to ignore `docs/chats/` (D1). `hooks enable --absolute` writes absolute paths. The lock, compact, message identity and redaction have modules of their own |

## Reviews

Each version gets a red-team test of the tool and a blue-team audit of DESIGN_REQUIREMENTS.md
against the code, both by agents that did not write the change. Fix each reproduced finding with a
regression test, and change a status in DESIGN_REQUIREMENTS.md only with evidence.

| Version | Red team | Blue team |
| --- | --- | --- |
| 3.6.1 | Four red teams and a cold-start relay on the 3.6.0 package. 11 ownership findings, 3 high: ZCode sessions had no identity, an old window passed with `--writer <new owner>`, a copied key resumed another session. 14 verify, job and snapshot findings, among them a verify that stopped half-way on a malformed feature row and snapshots that followed junctions and zipped keys. Capture: typed text after a reminder part dropped, DeepSeek compaction deleting history, a decompression bomb, `py.exe` run from the project folder. The relay scored 7 of 7 recovered items, two only through DESIGN.md or a hand copy, which led to prohibitions and rejected decisions in the brief | Statuses of U6 and U36 lowered to partial; U35 and U43 rewritten; 9 doc mismatches fixed; survey figures given their caveats |
| 3.6.0 | Run inside the survey: 17 defects reproduced in scratch copies (old window still writing after a takeover, same-session start treated as a takeover, conflict markers invisible, compact truncating rows, host text saved as user messages, Codex subagent threads imported, empty-cwd sessions matched to any project). Red teams also overturned four wave-1 designs: a Claude filter that dropped 98.6% of typed messages, a heading time that changed message IDs, a semicolon rule that fired 7,452 times on lists, and account-pair redaction | Statuses changed only where a test now proves them; see DESIGN_REQUIREMENTS.md |
| 3.5.0 | 13 defects: verify accepted another run's evidence, empty and piped acceptances; Stop nudge blocked after `reconcile`, missed session scope and string loop counts; a regex stalled hooks for minutes; redaction misses and over-redaction; READY with only retired requirements. All fixed in 3.5.1 with tests in `test_review.py` | Cited tests checked; 8 statuses lowered, survey figures given their caveats, 9 doc mismatches fixed |
| 3.4.0 | 11 defects: 3 high (secrets on 7 write paths, forged turns hiding requirements, corrupt cache), 4 medium, 4 low. All fixed with tests | 12 statuses lowered; chat saving for 6 of 10 tools found untested or missing. Kiro, Cursor and start-time import now tested |

## Open-source survey for 3.6.0

Eighteen agents searched in English, Chinese, Japanese and Korean and read the source of 156 projects.
Among them: handoff skills and the Anthropic harness, compaction code of Codex, Gemini CLI, OpenHands,
Goose, Cline, Roo and Kimi, task trackers (Backlog.md, beads, shrimp, vibe-kanban, pueue), spec kits
(GSD, Agent OS, spec-workflow-mcp, AI-DLC, Tessl), memory systems (basic-memory, Serena, MemOS, memobase,
cognee, Supermemory), secret scanners (trufflehog, noseyparker, betterleaks, CredSweeper, ggshield,
ai-guardian), writing linters (vale-ai-tells, humanizer, shuorenhua), host sources (Qwen Code, Kimi Code,
DeepSeek Harness, Qoder, Trae) and 2025 to 2026 papers. Five red teams then reproduced each defect and
attacked each strategy on the owner's real projects and local chats; five blue teams built and tested
each design. Notes, scripts and prototypes are outside the template, in the maintainer's scratch folder.

| Adopted | Evidence |
| --- | --- |
| Session identity from the host variable or the brief-hook key | Reproduced: a same-session `start` voided its own evidence; an old window wrote on with no error |
| Takeover warning, not refusal | 31 takeovers in 4 days in the owner's Kiro project, 17 within 20 minutes |
| Lossless, archive-first compact; retired rows in the brief | Reproduced: a 231-character requirement and its spec link existed in no file after compact; a probe test found removed features invisible after compact |
| Host-text and subagent filters in capture | 37.7% of saved Claude "user" messages were host text; about three in four of 1,352 local Codex rollouts were subagent or guardian threads (1,004 to 1,026 by two counts) |
| Process rules and prohibitions named in the turn reminder | arXiv 2610.31778, 44 sessions with an LLM judge: process instructions dropped 35.9% and scope exclusions 36.8% at compaction, against 6.2% for features. It does not test whether a reminder gets them recorded |
| Code-without-task warning on the turn it fires, only when no task is doing | clew #10 and #11: a hook that fired rarely worked, the same hook firing every call was ignored |
| Skipped and deselected counts; a note when a run tests less | Reproduced: a skip and a `-k` filter were invisible; a notice on any test change would fire in 17 to 96% of work sessions in five repositories, so no refusal |
| Rejected-run counts, known command problems, job pid checks, card history | A single-author study of 505 Codex sessions on Windows (its author warns it may not generalize): 81.6% of retries needed a changed run condition and the fix was rarely reused; Claude Code #84625 and #104019 on lost background jobs |
| `ws snapshot` | The owner's agents made 12 baselines in 3 days with the 2.x command; 8 of 132 project folders have git |
| DeepSeek Harness import through Python 3.14 or `backports.zstd` | 1,612 local session files decoded; pure-Python decoders were wrong on most frames |
| Credential notice on the prompt hook | ggshield runs a prompt hook on the same events but blocks; this one only warns. It fired on 0.85% of 10,284 local messages |
| Chinese lint rules, narrowed | Bold density 122 times more common in agent docs than human Chinese docs; the semicolon rule limited to prose |

Rejected strategies are listed in DESIGN_REQUIREMENTS.md, "Rejected proposals".

## Open-source survey for 3.5.0

Eight agents read the source of about 40 projects: task trackers (beads, Task Master, spec-kit,
SWE-agent, OpenHands, Aider), memory tools (Cline and Roo memory banks, mem0, Letta, Graphiti),
spec kits (OpenSpec, Kiro, cc-sdd, BMAD), hook collections (claude-mem, MemPalace), rule syncers
(ruler, rulesync), transcript exporters (SpecStory, claude-code-log, ccusage) and secret scanners
(gitleaks, detect-secrets). A strategy was adopted only with evidence and a fit to plain files.

| Adopted | Evidence |
| --- | --- |
| Verify runs only the recorded acceptance | ImpossibleBench: models pass contradictory tests by editing them; SWE-agent reverts test edits |
| Requirement coverage line and next ready task in the brief | spec-kit #3752: "done" claims without denominators missed a gap; Anthropic's long-running harness |
| Changing a requirement lists the work that cites it | BMAD replan, OpenSpec verify, spec-kit #4164 duplicates |
| "Code shows current behavior" rule for ARCHITECTURE and FEATURES | arXiv 2610.30571: agents followed stale docs 90.1% of the time; one sentence raised code-following to 91.4%. Tested only in the user-level instruction file |
| Block on spec conflict; replace a row only on explicit staleness | cc-sdd kiro-impl; Graphiti contradiction rules; Letta PR #4097 reports 90 to 110 of 120, unconfirmed because its harness is not public |
| Turn reminder names corrections and requirements inside questions | Claude Code memory triggers, mem0 extraction rules |
| Optional Stop nudge, once per unrecorded turn | Stop block and follow-up schemas of six hosts; loop guards from MemPalace, andylizf/nonstop and the hosts' payload fields |
| Brief cut at 9,000 characters; brief after compaction on hosts without a compact start hook | Claude Code 10,000-character hook limit; the marker pattern claude-mem uses for Codex |
| Entropy rule on user text; gitleaks names that hold no secret | Our own measurement in this session on 5,191 user messages from local Claude, Codex and Kiro stores: 18 hits, 12 already caught by the label rules; gitleaks generic-key allowlist |
| Phrase-level AI-tell lint rules | sloptrim: 0 to 6.7% false positives on the Human Detectors set |
| AGENTS.md size and CLAUDE.md or CODEBUDDY.md import checks | Antigravity truncation at 24,000 bytes; CodeBuddy skips AGENTS.md when CODEBUDDY.md exists |

Rejected strategies are listed in DESIGN_REQUIREMENTS.md, "Rejected proposals".

## Where things are generated

| Content | Source |
| --- | --- |
| Clean `docs/` files and the template README | `.agents/tools/wslib/defaults.py` |
| Table columns, statuses, budgets, watch skips | `.agents/tools/wslib/schema.py` |
| Hook settings per host | `hook_settings` in `.agents/tools/ws.py` |
| Transcript parsing | `.agents/tools/wslib/capture.py` |

Change the generator, not a generated copy. The self-tests compare the two.

## Host trials

A host counts as supported only after a recorded trial. Copy `.agents/template/TOOL_TRIAL.md` to
`docs/archive/trials/<date>-<host>.md`, follow it in a scratch project and add a summary row to
the trial table in HOSTS.md.
