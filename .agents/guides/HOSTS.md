# Hosts

How each agent tool finds AGENTS.md and which hooks `ws hooks enable` writes.
Documentation was checked on 2026-10-31.

## Entry files

### Tried

A trial ran these hosts end to end with the version named; "Trials" below has the runs.

| Host and version tried | Loads the contract through | Notes |
| --- | --- | --- |
| Kimi Code 2.4.1 | `AGENTS.md` | Skills from `.agents/skills/` |
| OpenAI Codex 0.166.0 | `AGENTS.md` | Project instruction cap is 32 KiB by default |
| Antigravity CLI `agy` 1.4.12 | `AGENTS.md` and `.agents/skills/` | 24,000 bytes per rule file |

### Entry files only

These rows come from each host's documentation. They stay documented claims until a trial confirms them.

| Host | Loads the contract through | Notes |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` with the line `@AGENTS.md` | Reads AGENTS.md natively only when no CLAUDE.md exists. The trial of 2.1.316 did not run: the model provider returned 403 |
| Cursor | `AGENTS.md` | Nested AGENTS.md files apply to their folders |
| Gemini CLI | `.gemini/settings.json`, `context.fileName` | Default is GEMINI.md, so the setting lists both. Not tried: individual Code Assist accounts are no longer served |
| GitHub Copilot | `AGENTS.md` | Also reads `.github/copilot-instructions.md` if present |
| Kiro | `AGENTS.md` and `.kiro/steering/workspace.md` | Steering file uses `inclusion: always`. The trial of Kiro CLI 2.37.0 stopped at the device login |
| Grok CLI | `AGENTS.md` after the folder is trusted | Skills from `.grok/skills/` and `~/.agents/skills/`. Also runs `.claude/settings.json` hooks unless `compat.claude.hooks=false`. The trial of 1.0.70 did not run: the endpoint returned HTTP 530 |
| DeepSeek Harness | `AGENTS.md` and `.agents/skills/` | 65,536 bytes per instruction chain |
| CodeBuddy and WorkBuddy | `AGENTS.md` when no `CODEBUDDY.md` exists | Keep project rules in AGENTS.md, not CODEBUDDY.md. On Windows hooks run through Git Bash; edits made outside the app need approval in `/hooks` |
| Qwen Code | `AGENTS.md` and `.agents/skills/` | Project hooks load only in a trusted folder |
| Qoder | `AGENTS.md`, after the folder is trusted in the CLI | All active rules share 100,000 characters; `.qoder/rules` wins on conflict. The IDE needs a restart after a hook edit |
| Trae | `.trae/rules/workspace.md`, a pointer with `alwaysApply: true` | AGENTS.md is read only after "Include AGENTS.md in the context" is turned on under Rules & Memories |

If a host does not load the file, start the session with:

> Read AGENTS.md in the project root and follow "Start of every session".

Notes that apply across hosts:

- Open the project root, the folder that holds AGENTS.md. A host opened on a subfolder may load
  only a nested AGENTS.md, or none. `ws` still finds the root from its own location.
- Antigravity ID and other editions of a host use the same entry as the base host. Confirm with
  step 4 under "Confirming a hook" after any host update.
- Changing the model, for example to Gemini 3.8 Flash, changes nothing in the files. A smaller
  model benefits most from one task at a time with an acceptance command. No model-specific
  settings are recommended here, because no trial has measured them.
- If a project already has `CODEBUDDY.md`, CodeBuddy and WorkBuddy read it instead of AGENTS.md.
  Add the line `@AGENTS.md` to that file; `ws check` warns until it is there.
- Kimi Code reads hooks only from `~/.kimi-code/config.toml`. Never add a `ws.py` hook there: the
  relative command fails in every other folder, and Kimi treats exit code 2 as "block the prompt".
- Some host commands rewrite the contract or the task files: Kimi `/init` rewrites AGENTS.md, and
  Kiro "Sync Files" rewrites a spec's tasks.md and may renumber it. Do not run them in a workspace
  project. If one ran, compare with the last checkpoint and restore the rows by ID.
- Host memory is a second copy that `ws` cannot see: Claude auto memory, Codex memories, Kiro
  Memory, WorkBuddy MEMORY.md, Qwen auto-memory, Antigravity knowledge. AGENTS.md rule 3 puts
  `docs/state/` first. Record anything worth keeping there, not only in host memory.
- `AGENTS.override.md` makes Codex skip the AGENTS.md in the same folder, and Codex stops reading
  the AGENTS.md chain at 32 KiB. `ws check` warns about both.

Skills in `.agents/skills/` are discovered natively by Codex, Antigravity, Kimi Code, DeepSeek
Harness, Qwen Code, Trae and Grok. Other hosts reach them through the "Read before you act" table in AGENTS.md.

## Hooks

`python .agents/tools/ws.py hooks enable <host>` merges these entries into the host settings file.
Existing settings and hooks are kept. Running it twice adds nothing.

Hook commands use paths relative to the project root, except Antigravity's, which run from
`.agents/`. The tool finds the project from its own location, so either works. They start with the first of
`python`, `python3` and `py -3` that runs Python 3.10 or newer on this machine; `ws hooks enable <host> --python
<command>` writes another. An older Python prints which version ws.py needs, and a hook then exits quietly.
`ws hooks disable <host>` takes the tool's entries out again: the file gets its bytes from before the first
enable back when nothing else changed, and a file left with no hooks is removed.

`ws upgrade` rewrites the tool's entries in every settings file that holds them, so the hook changes of a
new version reach the project. `ws doctor` reports, each with the command that fixes it, a settings file
whose entries are missing or come from an older version, name an interpreter that does not run Python 3.10
here, or run the ws.py of another folder, as the absolute paths of a copied project do. It also reports
when the host it runs in has no hooks in this project.

| Host | Settings file | Session start | Every turn | Transcript copy |
| --- | --- | --- | --- | --- |
| `claude` | `.claude/settings.json` | SessionStart, also after compaction | UserPromptSubmit | PreCompact, Stop, SessionEnd |
| `codex` | `.codex/hooks.json` | SessionStart, also after compaction | UserPromptSubmit | PreCompact, Stop, SessionEnd |
| `cursor` | `.cursor/hooks.json` | sessionStart | beforeSubmitPrompt, also saves the prompt | afterAgentResponse saves the reply; preCompact, stop, sessionEnd |
| `gemini` | `.gemini/settings.json` | SessionStart | BeforeAgent | PreCompress, AfterAgent, SessionEnd |
| `copilot` | `.github/hooks/workspace.json` | sessionStart | not available | preCompact, agentStop, sessionEnd |
| `antigravity` | `.agents/hooks.json`, commands run from `.agents/` | SessionStart, as `injectSteps` | PreInvocation, first call only | Stop |
| `kiro` | `.kiro/hooks/workspace.json` | SessionStart | UserPromptSubmit, also saves the prompt | Stop; the full log is imported at `ws start` |
| `codebuddy`, `workbuddy` | `.codebuddy/settings.json` | SessionStart | UserPromptSubmit | PreCompact, Stop, SessionEnd |
| `qoder` | `.qoder/settings.json` | SessionStart | UserPromptSubmit | PreCompact, Stop, SessionEnd |
| `qwen` | `.qwen/settings.json`, loaded only in a trusted folder | SessionStart, also after compaction | UserPromptSubmit | PreCompact, Stop, SessionEnd |
| `grok` | `.grok/hooks/workspace.json` | none, stdout of passive events is ignored | not available | PreCompact, Stop, SessionEnd when a path is given |

These settings files are not watched, so enabling hooks leaves a READY workspace READY. The exception is
`.gemini/settings.json`, which is also the Gemini adapter: after `ws hooks enable gemini`, run `ws checkpoint`.

The session start hook runs `ws brief --hook <host>` and returns the brief in the field the host
injects into the model context. The per-turn hook runs `ws turn --hook <host>`: before each user
message is handled it reminds the agent to record new requirements, decisions and preferences
first, and adds the current task, open questions and any coverage problem. The other hooks run
`ws capture`, which reads the transcript path from the hook payload and writes
`docs/chats/<host>/<session>.md`. On Stop it also appends `last_assistant_message` when the
transcript file does not hold the final reply yet.

Kiro and Cursor hooks send no transcript file. Their per-turn hook saves the prompt from the
payload, one message at a time, and Cursor's afterAgentResponse saves the reply. Answers given
through a question tool (Claude AskUserQuestion, Kiro choices) are saved as user messages.

A hook problem is reported on stderr and never stops the host: hooks wait at most 3 s for a busy
workspace and print valid output even when the state files are broken. Saved user messages then
appear in `ws reconcile` until each is accounted for.

Copilot and Grok prompt hooks cannot add context, so those hosts get the rule from AGENTS.md only.
Cursor's public docs list no context field for beforeSubmitPrompt, but its installed code (2026-11,
`workbench.desktop.main.js`) lists the event among those whose `additional_context` reaches the
model, up to 10,000 characters. A live check with `cursor-agent` is still open: it needs a login.
Gemini, Antigravity and Cursor do not run their session start hook again after compaction.
Their compaction hook leaves a marker, and the next per-turn hook adds the brief once. The brief
injected at session start is cut at 9,000 characters, under Claude Code's 10,000-character limit.
PROTOCOL.md, "Stop nudge", describes the optional Stop hook that asks once when a turn recorded
nothing. Kiro also
reads `.kiro/steering/workspace.md` on every turn, a one-line pointer to AGENTS.md.

Codex asks you to review and trust project hooks once, with `/hooks`, before they run.

## Importing from host stores

Some chats never pass through a hook: Kimi Code keeps hooks only in its user config, Codex hooks
need trust, and Antigravity's Stop hook can fire before the final reply is written. `ws start`
therefore imports this project's sessions from the stores it can read in about a second. The
others are imported on request.

| Host | Store | Matched by | When |
| --- | --- | --- | --- |
| Kimi Code | `~/.kimi-code/session_index.jsonl` | working directory | `ws start` |
| Codex | `~/.codex/sessions/` | working directory in the first line | `ws start` |
| Kiro | `~/.kiro/sessions/*/sess_*/session.json` | workspace folders | `ws start` |
| WorkBuddy, CodeBuddy, Qoder, Qwen Code | `~/<host folder>/projects/*/` | `cwd` in the session lines | `ws start` |
| Cursor | `~/.cursor/projects/*/agent-transcripts/` | a mention of the project path | `ws chats import cursor` |
| Antigravity | `~/.gemini/antigravity*/brain/` | a mention of the project path | `ws chats import antigravity` |

Cursor and Antigravity stores must be read in full, which took 20 to 160 s on a machine with
thousands of sessions. Results are cached in `.agents/cache/session-scan.json`, so a second run is
faster. Set `WS_IMPORT=0` to skip the import at `ws start`. An import updates existing transcripts
in place.

DeepSeek Harness stores sessions in `~/.dsh/sessions/--<project key>--/`, compressed with zstd. `ws start`
imports them when the running Python can decompress zstd: Python 3.14 or newer, or the `backports.zstd`
package. `ws chats import dsh` also uses a Python 3.14 found by `py -0p` or at `~/.local/bin/python3.14.exe`.
Subagent sessions are skipped. Node is never called: looked up by name it could run a program from the
project folder.

Codex subagent and guardian threads (`thread_source` other than `user`) are not imported: their
user turns are prompts the parent agent wrote.

Without a hook or an import, `docs/chats/` stays empty and `ws reconcile` reports nothing to check,
which is not the same as every message being recorded. The brief says so in a "Hooks:" line.

## Subagents and workflow steps

Subagents load the same entry files as their parent, so they read "Run ws start" too. AGENTS.md
tells them not to, and `WS_ROLE=worker` makes the tool refuse their writes (PROTOCOL.md, "Subagents
and helper windows"). How to set it per host:

| Host | Subagent mechanism | What to do |
| --- | --- | --- |
| Claude Code | Agent tool, workflows | Start each prompt with "WS_ROLE=worker: run shell commands as `WS_ROLE=worker <command>`; never run ws writes or edit docs/state/" |
| Codex | Spawned threads share `CODEX_SESSION_ID` | The same prompt line; the parent records results |
| Cursor | Task subagents get their own `CURSOR_CONVERSATION_ID` | Their writes are refused even without `WS_ROLE`; still put the prompt line in each task, so they do not try |
| Kiro | Workflow steps are new sessions | Put the prompt line in every step; only the final step, or the orchestrator, runs ws writes |
| Any host | A second window for a side question | Set `WS_ROLE=readonly` in that terminal, or tell the agent it is read-only |

A worker that needs to save command output writes it under `.tmp/`; the owner runs `ws verify` with
the task's acceptance to create evidence.

## Confirming a hook

1. Enable the hook, run `python .agents/tools/ws.py doctor`, and start a new session in that host.
2. Ask one question, then end the session.
3. Check `docs/chats/INDEX.md` for a new row and open the transcript file.
4. For the session start hook, ask the agent what the brief said. It should name the stop point.

The transcript format of most hosts is not a stable interface. If a host changes it, the copy may
lose messages. The raw copy in `docs/chats/<host>/raw/` keeps the original.

## Trials

Unattended runs in scratch projects created from the release package, Windows 11, 2026-10-31.

| Host and version | Entry | Hooks | Result |
| --- | --- | --- | --- |
| Kimi Code 2.4.1, template 3.2.0 | Native AGENTS.md | none | Three turns modelled on the failed Kiro session. Requirements, a preference, a question, two decisions and three tasks were recorded in the turns they were stated. A pasted password stayed out of every file and reply, and the agent advised rotating it. READY |
| Antigravity CLI `agy` 1.4.12 | Native AGENTS.md | SessionStart and Stop fired after the 3.1.1 path fix | Session 1 recorded P1 and P2, built and verified R1, READY. Session 2 read the injected brief, skipped `ws brief` as told, took over and continued T2, then hit the account quota |
| Codex 0.166.0, second run | Native AGENTS.md | SessionStart fired in both sessions | Ran `ws init` and started recording, then hit the account usage limit. The init baseline let the next brief show the unsaved file |
| Kiro CLI 2.37.0 | not run | | Installed, but the device login was not completed |
| Codex 0.166.0 | Native AGENTS.md | SessionStart and Stop fired | Loaded the brief, ran `ws init` and `ws start`, recorded P1. Stopped at the account usage limit before checkpoint |
| Kimi Code 2.4.1 | Native AGENTS.md | none | Session 1 built and verified R1. Session 2 resumed from "继续上次的任务" alone and finished R2. READY both times |
| Kimi Code 2.4.1, after Codex | Native AGENTS.md | none | Took over the Codex session without a checkpoint, kept P1, finished the work, READY |
| Claude Code 2.1.316 | not run | | Model provider returned 403 in this environment |
| Gemini CLI 0.66.0 | not run | | Individual Code Assist accounts are no longer served; Google points to Antigravity |
| Grok 1.0.70 | not run | | The configured endpoint returned HTTP 530 |

Problems found in these trials and fixed in 3.1.0:

- Codex transcripts included its own system and AGENTS.md text. Capture now keeps only visible turns.
- Agents left `phase`, `risks` and `next_acceptance` at the init text. Checkpoint and brief now warn.
- Evidence went stale without naming the file. The error now lists the changed files.
- `--set source=...` on a requirement failed. It is now accepted as `--source`.

Problems found in the second round and fixed in 3.1.1:

- Antigravity ran hook commands from `.agents/`, so `.agents/tools/ws.py` was not found. The
  Antigravity hooks now use `tools/ws.py`, and the tool locates the project from its own path.
- Antigravity transcripts use their own record types. Capture now reads `USER_INPUT` and the text
  of `PLANNER_RESPONSE`, and `ws chats import antigravity` collects past conversations.
- Codex hook payloads with Chinese text were decoded with the console code page. Capture now
  reads the payload as UTF-8 bytes.
- A session that stopped before its first checkpoint left no baseline, so the next brief could not
  list its files. `ws init` now seals a first checkpoint.

Record new trials with `.agents/template/TOOL_TRIAL.md` and add a row here.
