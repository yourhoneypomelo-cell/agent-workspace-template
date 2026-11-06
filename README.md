# Agent workspace template

A file-based memory system for AI coding agents. It gives any agent tool — Claude Code, Codex,
Cursor, Kimi Code, Kiro, DeepSeek Harness, and others — a shared, persistent memory that survives
window switches, context compaction, and tool changes.

Every project fact lives in plain Markdown files under `docs/`. A new session reads them and picks
up exactly where the last one stopped. No database, no server, no lock-in: standard-library Python,
plain text, and a CLI tool.

## Why

AI agents lose track of long projects. They forget requirements, re-do finished work, propose
features the user already rejected, and claim tasks are done without proof. This template prevents
that by making the agent record every requirement, decision, task and piece of evidence in files
that the next session reads before doing anything.

## Quick start

1. **Download** the latest release ZIP from
   [Releases](https://github.com/yourhoneypomelo-cell/agent-workspace-template/releases)
   and unzip it into an empty project folder.

2. **Open the project** in your agent tool and say:

   > Read AGENTS.md and start.

3. **State your goal** in one sentence when the agent asks. It will create the state files, record
   your goal as a requirement, and begin working.

4. **Optional: enable hooks** so the tool saves chat transcripts and injects the workspace brief
   at session start:

   ```bash
   python .agents/tools/ws.py hooks enable claude
   ```

   Replace `claude` with `codex`, `cursor`, `gemini`, `copilot`, `kiro`, `grok`, `qwen`, or
   `codebuddy` for your tool.

## How it works

```text
Session start:  brief → read state → start → work and record → verify → checkpoint
Next session:     ↑                                                              |
                  └──────────────────────────────────────────────────────────────┘
```

- **AGENTS.md** is the root contract every agent reads. It defines the session protocol, the
  state file format, and the rules that keep the workspace consistent.
- **`docs/state/`** holds seven Markdown files: the handoff card, requirements, preferences,
  features, tasks, architecture, and design decisions. These are the source of truth.
- **`docs/logs/`** records what happened: session history, requirement changes, feature changes.
- **`docs/chats/`** saves chat transcripts so no user message is lost.
- **`ws.py`** is the CLI tool that validates writes, assigns IDs, runs acceptance tests, and seals
  checkpoints. It is the only thing the agent needs to run.

## Key features

- **Record first, act second.** Every user message is checked for new requirements, decisions
  and preferences before any work begins.
- **Verified completion.** A task is done only when its acceptance command passes in the current
  session. The tool runs the test, stores the evidence, and marks it done.
- **Parallel sessions.** Multiple agent windows can work on the same project. Task claims use
  file paths and resource names to prevent conflicts. A stale lock is reclaimed by generation
  number, not by guessing whether a process is alive.
- **Credential safety.** The tool asks how the project handles credentials (keep, redact, or
  ask each time) and follows that rule in every write.
- **Host adapters.** AGENTS.md is the single contract. Adapters for Claude Code, Codex, Cursor,
  Gemini, Kiro, Kimi Code, Grok, DeepSeek Harness, CodeBuddy and Qwen Code load it natively.
- **Compaction survival.** State files are on disk, not in the agent's context window. After
  compaction, the agent re-reads them and continues.

## Install into an existing project

```bash
# From the template folder:
python .agents/tools/ws.py install --target /path/to/your/project --merge

# Or unzip a release into the project root.
```

`--merge` preserves your existing AGENTS.md by appending it under "Project rules".

## Guides

| Guide | Use |
| --- | --- |
| [Quickstart](.agents/guides/QUICKSTART.md) | Installation, first session, daily use |
| [Protocol](.agents/guides/PROTOCOL.md) | Formats, ownership, evidence and recovery |
| [Structure](.agents/guides/STRUCTURE.md) | Folders, naming, document size and writing style |
| [Hosts](.agents/guides/HOSTS.md) | Per-tool entry files and hooks |

## Requirements

Python 3.10 or newer. No packages to install — standard library only.

## License

[MIT](LICENSE)
