# Design requirements

What the owner of this template asked for, and how far each request is met.
Maintainers read this before changing the template. Project facts never go here.

Sources:

- The Codex conversation that built versions 2.x: 38 user messages, 2026-10-28 to 10-31.
- Its summary in the owner's server project.
- The conversation that built 3.x.

Repeated requests are merged, and the later wording wins. Checked against 3.6.2 on 2026-11-05,
including an independent audit that downgraded twelve claims from 3.3.0.

| Status | Meaning |
| --- | --- |
| met | Built and covered by a self-test, and by a host trial where a host is involved |
| partial | Built, but some hosts, cases or proofs are missing; the row names them |
| limit | Files and a tool cannot guarantee it; the row names the mitigation |

## Continuity

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U1 | A long project resumes in any new window or tool without the old chat | partial | `ws brief`, T0 files, `ws start`. Kimi resumed from "继续上次的任务" alone and took over a Codex session. Codex and Antigravity trials stopped at account limits. No relay between two different hosts has passed end to end |
| U2 | Context compaction loses nothing | limit | Claude re-injects the brief after compaction and copies the transcript first; untested on a live Claude. Work never written down is lost from the model; the copied transcript and `ws reconcile` let it be recovered |
| U3 | Switch at any time between Antigravity, Antigravity ID, Codex, Kimi, Claude Code, Cursor, DeepSeek Harness, Kiro, Grok CLI and WorkBuddy | partial | Every host has an entry path (HOSTS.md). Trials: Kimi, Codex, Antigravity. Blocked by accounts: Claude, Gemini, Grok, Kiro. Untested: Cursor, DeepSeek Harness, WorkBuddy, Antigravity ID |
| U4 | A window that closes or crashes leaves work recoverable | met | Takeover lists unsaved files, notes and the stop point. `test_solo_takeover_after_abrupt_stop_lists_unsaved_files` |
| U5 | No quality drop after a switch: no repeated questions, forgotten constraints or rebuilt removed features | limit | Every model gets the same facts and rules; following them depends on the model. Removed IDs cannot return (`test_retired_id_cannot_return`). Gemini 3.8 Flash has no trial |
| U6 | Long operations record purpose, command, state and recovery | partial | `pid=<n> log=<path>` in `recovery_notes` gets its start time when written, and the brief reports running or exited with the last log line (`test_a_recorded_job_is_checked_by_the_brief`). The Git Bash pid conversion and the reused-pid branch were checked by hand only |

## Records kept from the conversation

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U7 | Every user message is checked for requirements and recorded before acting | partial | AGENTS.md step 1, per-turn hooks for Claude, Codex, Gemini, Antigravity, Kiro and Cursor naming corrections and requirements inside questions, `ws reconcile`, the optional Stop nudge (`test_turn_with_no_record_is_nudged_once`). The tool cannot judge meaning; Kimi recorded six requirements in-turn in one trial |
| U8 | Requirements maintained in the style of Kiro specs | met | REQUIREMENTS.md rows, `docs/specs/<slug>/` from `.agents/template/spec/`. `ws check` and `ws start` warn about a spec folder no row links, a "Requirement IDs:" line that misses the linking row or names an unknown ID, and an unfilled template; links of compacted rows are read from `docs/archive/closed/` (`test_spec_folders_are_checked_against_their_rows`) |
| U9 | Revision log and requirement change log | partial | REQUIREMENT_LOG and CHANGE_LOG, written by `ws add` and `ws set`. `test_add_assigns_ids_and_writes_log` covers REQUIREMENT_LOG only |
| U10 | Framework and feature documents | met | ARCHITECTURE.md with component forms, FEATURES.md with a lifecycle. A planned or building feature ships when verify finishes its last task (`test_feature_ships_when_its_last_task_is_verified`) |
| U11 | User preferences, with the user's words told apart from inference | partial | PREFERENCES.md with Source and Confidence. The brief lists active requirements whose log never names the user as source (`Not stated by the user`). It is a reminder; nothing blocks |
| U12 | Todos and the exact stop point | met | TASKS.md and the HANDOFF card, checked by `ws checkpoint`. A blocked task needs a reason, shown in the brief. `test_stale_init_card_is_flagged` |
| U13 | Project, maintenance and session logs | partial | SESSION_LOG and MAINTENANCE_LOG. No separate log for milestones and incidents; they go to SESSION_LOG |
| U14 | Vague ideas mature; vague parts never hold back confirmed ones | partial | The rule and the Idea pool section exist. No command writes the Idea pool and no test covers it |
| U15 | Frequent additions and removals; a removed feature is not rebuilt by accident | partial | Retired rows keep IDs and reasons; compact archives full rows; the brief lists the last five retired rows; `ws add` warns on an exact repeat and lists the three nearest retired rows (`test_a_reworded_retired_row_is_listed_for_the_agent`). With 5 to 20 retired rows a rewrite's original was among the three in 83 to 92% of Chinese trials. The agent judges the meaning; the tool cannot |
| U16 | The latest explicit instruction wins over older chat | met | `ws set Rn --set status=replaced` with a reason. The change lists the open tasks and features that cite it (`test_retiring_a_requirement_names_the_open_work_that_cites_it`) |

## Chat history

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U17 | The chat is saved automatically to a fixed folder with fixed names | partial | See the table below. Hooks must be enabled once per host with `ws hooks enable`. Codex subagent threads and Claude host-inserted turns are no longer saved as user messages |
| U18 | Answers given through a host's question tool are saved as user messages | partial | `test_claude_question_answers_become_user_messages`, `test_kiro_session_log_keeps_typed_text_spoken_replies_and_answers`. Codex keeps answers as a user turn already |
| U19 | Each saved message carries its source, time and delivery state | partial | Session, host, order and the UTC time in each heading, a compaction mark after a summary (`test_messages`). The sent state of the last reply is not kept |
| U20 | Credentials are kept the way the user decided | partial | The agent asks once and records the answer as a preference and as WORKSPACE `"credentials"`: `plain` keeps every value as written (`test_plain_credentials_are_kept_as_written`), `ask` and `redact` redact on every write path and the prompt hook tells the agent to ask before writing one (`test_ask_rule_redacts_and_tells_the_agent_to_ask`). With `ask` or `redact`, a bare password with no label and no login context is a limit: such rules hit 88 to 583 of 10,140 local messages, nearly all false |

How each tool's chat reaches `docs/chats/`:

| Tool | Path | Test |
| --- | --- | --- |
| Claude Code | Hooks with the transcript file | `test_capture_copies_transcript_and_never_fails` |
| Codex | Hooks with the transcript file after `/hooks` trust; also imported at `ws start` | parser and payload tests |
| Kimi | Imported at `ws start` from its session index | parser test |
| Kiro | Prompt saved by the per-turn hook; full log imported at `ws start` | `test_prompt_hooks_write_a_journal_and_return_host_json`, `test_start_imports_sessions_of_hosts_without_hooks` |
| Cursor | Prompt and reply saved by hooks; `ws chats import cursor` by hand | `test_prompt_hooks_write_a_journal_and_return_host_json`, `test_import_finds_kiro_and_cursor_sessions_of_this_project` |
| Antigravity, Antigravity ID | Stop hook; `ws chats import antigravity` by hand | parser test |
| Grok CLI | Hooks when the payload names a file | `test_grok_synthetic_turns_and_cursor_wrappers_are_dropped` |
| DeepSeek Harness | Imported at `ws start` with Python 3.14 or `backports.zstd`; `ws chats import dsh` also finds an installed Python 3.14 | `test_messages_keep_typed_turns_and_apply_replacements` |
| WorkBuddy, CodeBuddy, Qoder, Qwen Code | Claude-shaped hooks; store imported at `ws start` by `cwd` | parser tests |

## Documents

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U21 | Copying the template into a folder is enough to start | met | Release zip, `ws install`, bootstrap mode. `test_release_builds_one_verified_clean_package` |
| U22 | Naming and folders good enough to serve as a model | partial | Fixed file sets, extra files in state and log folders rejected. No test covers the rejection. The owner's 2.x file names (TODO, LOG_INDEX, CURRENT, TRANSCRIPT) became HANDOFF, the brief and `docs/chats/` |
| U23 | AGENTS.md and system documents in English, replies in the user's language | partial | Rule 7 in AGENTS.md; a rule, not checked |
| U24 | Simple diagrams where they help | met | Text diagrams in STRUCTURE.md and this file; the session diagram left AGENTS.md because its steps say the same |
| U25 | Orderly writing with no AI flavor and no excess punctuation | partial | `ws lint` flags filler words, dashes, emoji and repeated punctuation. Tone needs a human reader |
| U26 | Documents stay concise as the project grows, without dropping content, preferably by fill-in templates | partial | Record forms, lint (now with Chinese rules), size budgets, `ws compact` that keeps every full row in `docs/archive/closed/` and survives a crash midway (`test_crash_after_archive_loses_nothing`). Forms are advice; an agent can still write prose |

## Delivery

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U27 | Nothing is reported done without evidence from this session | met | `ws verify` runs the task's recorded acceptance only; zero tests is not a pass. Skipped and deselected tests are shown, and a run that tests less than the previous accepted one is noted (`test_skips_are_shown_and_a_shrinking_run_is_noted`). A `check:` run that reports zero tests is rejected (`test_check_that_ran_zero_tests_is_rejected`). A check of behavior names its output with `expect`, and a run without it is rejected (`test_check_with_expect_fails_when_the_output_is_wrong`); a check with no expect clause is labelled exit-only (`test_check_without_expect_is_named_exit_only`). The agent still chooses what to expect |
| U28 | Each version ships a clean zip in `dist/` that starts a new project when unpacked | met | `ws release` unpacks and tests the zip before keeping it |
| U29 | Each version gets a red-team and blue-team review | partial | Done for 3.2.0 to 3.4.0; findings are summarized in MAINTAINING.md. No review file is required by the release command |
| U30 | Installing into an existing project overwrites nothing | met | `ws install --dry-run`, `--merge`. `test_install_keeps_existing_files_and_reports_conflicts` |
| U31 | Projects on older versions can upgrade | partial | `ws migrate` for version 2, skipped in tests without the v2 fixture. Within version 3, new optional logs are created on first write (`test_older_project_without_the_log_reads_and_writes`) |
| U32 | The contract works with no shell or no Python | partial | AGENTS.md gives the manual path. No trial on such a host |
| U33 | Parallel work on separate copies merges cleanly | partial | One writer per copy is enforced. Git conflict markers in state or log files block writes and READY (`test_conflict_markers_block_writes_and_ready`). Merging copies, including ID collisions, is left to version control |

## Further requirements from the 2.x summary

| ID | Requirement | Status | Evidence, and what is missing |
| --- | --- | --- | --- |
| U34 | Tell the template folder, a clean starter and a project apart | met | Bootstrap mode, `release` refuses to run in a project, manifest check on install. `test_project_folder_cannot_release` |
| U35 | Confirm the old session stopped before a takeover | partial | Every host is identified by its window process and start time. While the owner's window runs, another window's `ws start` and writes are refused and the brief says "do not claim"; `start --force --reason` takes over and logs it; an exited window is taken over without a warning (`test_a_live_window_is_not_taken_over_and_an_exited_one_is`). Session variables separate conversations on Claude Code, Codex, Qwen and Kiro (`test_kiro_conversations_are_told_apart`); on Cursor the per-turn hook stops an old conversation (`test_cursor_old_conversation_is_told_by_the_turn_hook`). `WS_ROLE=worker` sessions cannot claim or write (`test_worker_role_never_claims_or_writes`). Limit: two chats in one application window share a process, so on a host with no variable and no hook they are not told apart Parallel sessions claim tasks by path and resource; overlaps are refused unless forced with a logged reason (`test_overlapping_paths_or_a_shared_resource_are_refused`, `test_separate_tasks_run_in_parallel_and_both_save`) |
| U36 | After compaction in one session, re-check ownership and unsaved work | partial | The same session resumes on `ws start` through a host variable or the key the brief hook prints, also for ZCode (`test_same_session_start_after_compaction_keeps_its_evidence`, `test_zcode_restart_resumes_and_its_subagents_may_write`). No live host trial yet |
| U37 | Record failed attempts and dead ends | met | Rejected verify runs are counted per task in the brief (`test_rejected_runs_are_counted_in_the_brief`); a "Known command problems" table reaches the brief; replaced `risks` and `recovery_notes` are logged; blocked tasks need a reason |
| U38 | Before deleting a feature, check callers, tests, config and data | limit | A rule in AGENTS.md ("check FEATURES.md and CLOSED_ITEMS.md"); the tool cannot see callers |
| U39 | One-off instructions such as "review only" keep their scope | limit | Host permission modes; the files hold stable preferences only |
| U40 | Save the original before a large reorganization | met | `ws snapshot --label before-<what>` zips the documents and named paths with size and disk checks and sets the card baseline (`test_snapshot_zips_the_documents_and_sets_the_baseline`). No restore command, on purpose |
| U41 | Each saved message has an ID, a raw-or-summary marker and marked gaps; re-import is idempotent | partial | IDs come from the text hash and do not change when a time is added to the heading; re-import rewrites the same file; compaction boundaries are marked. Sequence gaps are not marked; none was seen in 1,465 DeepSeek Harness session files |
| U42 | Product tests stay separate from the template self-tests | met | Self-tests live under `.agents/tools/tests/`; verify runs only the task's command |
| U43 | A changed task definition needs new evidence | met | The definition digest check refuses old evidence after an edit (`test_source_change_after_evidence_requires_reverify`); `ws set` logs the old value of each edited field, and an edit made by hand is shown in the brief and logged at the next checkpoint (`test_an_acceptance_edited_by_hand_is_logged_at_the_next_checkpoint`) |
| U44 | Structured test reports (JSON, JUnit) | met | `test_structured_json_report` |
| U45 | A clean re-export carries no chats or state from another project | met | `test_export_writes_clean_zip`, the package check in `release` |
| U46 | Handoff quality is measured: time, re-explanations, missed constraints | partial | Offline probe test of what a fresh agent can read before and after compact (`test_probes`); TOOL_TRIAL.md with four planted traps and a seven-item answer key. Behavior after a switch is still measured by hand |

## Limits

These cannot be fully met by any document template. Each has a mitigation in place.

```text
user message --> agent records it? --no--> missing from the state files
                        |                            |
                       yes                   saved in docs/chats/?
                        |                     |              |
                    ws add/set               yes             no
                                              |              |
                                        ws reconcile    not recoverable
```

1. No file can force a model to record. The per-turn hook repeats the rule on every message, and
   a goal with no requirement rows blocks READY.
2. The tool cannot tell which sentence was a requirement. Reconciliation turns saved messages into
   a checklist; it relies on the agent answering it truthfully.
3. Hosts with no hook and no readable store save no chat. On those hosts the transcript exists only
   if the user exports it into `docs/chats/`.
4. Quality after a model switch depends on the model. Small tasks with acceptance commands limit
   the damage a weaker model can do.
5. Pattern-based redaction misses a secret that has no label and no login context, such as a bare
   word on its own line. Every scanner read in the 3.6 survey requires a label for passwords, and the
   shape rules tried hit 88 to 583 of 10,140 local messages, nearly all false. Until the user sets a
   credential rule, the prompt hook tells the agent to ask before writing a credential anywhere.

## Rejected proposals

Reviewers proposed these; the owner did not adopt them as rules.

| Proposal | Reason |
| --- | --- |
| A hard 8 KB limit on AGENTS.md | Size budgets warn instead; the content needed for safety is larger |
| A whitelist of allowed commands | Hosts already have permission systems |
| Judging handoff quality by sentence length | Not a measure of whether facts are present |
| Taking over without a lock | Two writers corrupt the state |
| Removing every completed row automatically | `ws compact` moves closed rows only when asked |
| A fixed matrix of three tools by three scenarios | Trials follow the tools the owner actually uses |
| Reading every host store at each session start | Cursor and Antigravity stores took 20 to 160 s here; they are imported on request |
| Memory-bank files updated on agent judgment (Cline, Roo) | In 39 public repos the always-read file trailed the code by a median of 15 commits |
| Change folders with delta specs merged on archive (OpenSpec) | A second copy of each requirement and a merge step that agents skip or get wrong (OpenSpec #799, #1387) |
| Automatic fact extraction with a model (mem0, Letta) | Needs a model call the tool cannot make; measured failures are overwritten or duplicated facts |
| A Stop hook that blocks every N messages | MemPalace dropped it after users found it noisy; the nudge here fires only when a turn wrote nothing |
| Hash IDs or IDs with a branch suffix (beads, git-bug) | They do not stop Markdown tables from conflicting (two branches adding R7 and R9 still conflicted), users of three trackers asked for numbers back, and no ws project of the owner is under git |
| `ws merge`, a union merge driver or a custom git merge driver | No ws project is under git; parallel copies are folders never merged back. beads shipped a merge driver and removed it. GitHub web merges ignore `.gitattributes` |
| Refusing a takeover when the owner wrote recently | It would have refused 17 of 31 real takeovers, mostly sub-sessions that cannot ask the user, and agents already forced writes with `ws start | Out-Null`. `start` warns instead |
| A similarity hint for new rows against retired ones | 0 to 8.5% recall on Chinese rewrites and 18 to 31% false hints on templated ops rows. The brief lists retired rows instead |
| Checking that backticked paths in state files exist | 315 unresolved paths in 7 real projects, none a stale repository path; they were remote server paths, image names and routes |
| Warning when a state section shrinks sharply | 6 of 12 real restructures and all 33 section flags in 49 snapshot pairs were deliberate |
| A notice whenever a run's test files changed | In five repositories it would fire in 17 to 96% of work sessions (author and day, last 400 commits); only removed tests and changed runner config are reported |
| A keyword filter that ranks reconcile messages | 0.44 to 0.70 held-out recall on 6,090 local messages; every message needs an answer anyway |
| Blocking a prompt that holds a credential | Claude Code keeps a blocked prompt on disk, the Kiro IDE ignores the block, and the owner shares keys on purpose. The hook warns instead |
| Account-pair redaction (`email|value`) | 7 of 11 ordinary lines such as tab-separated rosters were redacted, against 2 real hits |
| Calling Node to read DeepSeek Harness sessions | Looked up by name on Windows it ran a program from the current folder; Python 3.14 and `backports.zstd` read the store |
| A vendored pure-Python zstd decoder | The three found decoded 41%, 4% and 4% of real frames correctly, two of them silently |
