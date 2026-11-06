# Quickstart

Install the template, run the first session and switch between tools.

## Requirements

- Python 3.10 or newer on the PATH as `python`. No packages are needed.
- An agent tool that can read files and run shell commands.
- Version control is recommended. The workspace works without it.

## Install

New project: unzip `dist/agent-workspace-<version>.zip` from the template folder into an empty
folder. The zip has no top-level folder, so the empty folder becomes the project root.
The package already contains the hidden folders `.agents`, `.gemini` and `.kiro`.

Existing project: preview first, then install from the template folder.

```text
python .agents/tools/ws.py install --target "D:/code/my-app" --dry-run
python .agents/tools/ws.py install --target "D:/code/my-app"
```

The installer never overwrites a file. An existing README.md is kept.
If the project already has an AGENTS.md, CLAUDE.md or `.gemini/settings.json`, add `--merge`.
The old AGENTS.md text is kept under a "Project rules" heading.

The installer also writes small `.gitignore` and `.gitattributes` files inside `.agents/` and
`docs/`. They keep the hash cache and raw transcripts out of version control and keep line endings
stable across Windows and Unix checkouts.

## First session

Open the project in an agent tool and send:

> Read AGENTS.md and start. The goal is: [one sentence].

The agent runs `ws init`, inspects the code, fills ARCHITECTURE.md, records the first requirements
and tasks, and checkpoints. Check the result with `python .agents/tools/ws.py brief`.

## Daily use

You talk to the agent as usual. The agent records requirements, decisions, questions and
preferences as they come up and verifies tasks before calling them done.
Useful requests:

| You say | The agent does |
| --- | --- |
| "Save now." | `ws checkpoint --keep --stop "..." --next "..."` |
| "I'm switching tools." | `ws checkpoint` and confirms READY |
| "What's open?" | `ws brief` |
| "Clean up the docs." | `ws compact` |

## Switching windows or tools

```text
window A: "I'm switching."  ->  ws checkpoint  ->  READY
window B: "Read AGENTS.md and continue."  ->  ws brief  ->  ws start  ->  next step
```

If window A died before saving, window B still works. `ws start` takes over and lists the files
window A changed after its last checkpoint, so nothing is lost silently.

If a tool does not load AGENTS.md by itself, send this first:

> Read AGENTS.md in the project root and follow "Start of every session".

## Automatic transcripts

Hooks copy each session's transcript into `docs/chats/` and inject `ws brief` at session start.

```text
python .agents/tools/ws.py hooks enable claude
python .agents/tools/ws.py hooks enable cursor
python .agents/tools/ws.py hooks enable gemini
python .agents/tools/ws.py hooks enable copilot
```

Run the line for each tool you use, then start a new session in that tool. HOSTS.md lists what
each host supports and how to confirm the hook ran.

## Upgrading within version 3

Replace the project's `.agents/` folder with the one from the new template and keep `docs/`.
Log files added by a newer version, such as `docs/logs/RECONCILE_LOG.md`, are created on their
first write. Merge the new AGENTS.md into yours, or copy it if you never edited it. The replaced
files show as unsaved changes until you run `ws start` and `ws checkpoint`.

## Upgrading from version 2

```text
python .agents/tools/ws.py migrate --target "D:/code/my-app" --dry-run
python .agents/tools/ws.py migrate --target "D:/code/my-app"
```

Run it from a version 3 template folder. If a v2 session still holds the workspace, close that
agent window and add `--force`; nothing it changed is discarded. The migration backs up
every replaced file to `docs/archive/v2-backup/`, converts the tables and card, moves closed rows
to CLOSED_ITEMS.md and marks completed tasks `unverified` so they are tested again.
Afterwards open the project and say "Read AGENTS.md and continue."
