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

Run the tool of the new template folder against the project, first to see the plan:

```text
python .agents/tools/ws.py upgrade --target "D:/code/my-app" --dry-run
python .agents/tools/ws.py upgrade --target "D:/code/my-app"
```

Run it while no session works in the project. A template file the project never edited is replaced. An
edited guide, skill or adapter is kept, and the new version goes to `docs/archive/upgrades/<folder>/new/`
for a hand merge; the command then exits with 1. The rules under "## Project rules" in AGENTS.md are kept
under the new contract. Tool code the project changed stops the upgrade before anything is written, so the
tool never mixes two versions. `docs/` and `.agents/hooks.json` are not touched, and hook settings get this
version's entries while the user's own stay. The checkpoint takes in the new files, so a READY workspace
stays READY.

Every replaced file is backed up in the upgrade folder. `--rollback <folder>` puts them back, and
`ws doctor` checks hooks and tool files afterwards. A project without `.agents/template/MANIFEST.json`
needs `--assume-base <the release zip or folder it came from>`; otherwise every file that differs from the
new version counts as edited. `--scan <folder>` lists the workspaces under a folder with their versions.

Before 3.7.0 there was no upgrade command: the four folders `.agents/tools`, `.agents/guides`,
`.agents/skills` and `.agents/template` were copied over, followed by `ws start` and `ws checkpoint`.

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

## Compatibility between versions

A stored format changes only together with its version mark. A tool reads every older mark it knows and
refuses a newer one with a message to upgrade, so an older tool never misreads newer data.

| Part | Mark | In 3.8.0 | Older forms |
| --- | --- | --- | --- |
| State line in HANDOFF.md | `schema` | continuity.v3, unchanged | continuity.v2 is converted once by `ws migrate` |
| Evidence in `docs/archive/checks/` | `rules` | Summary rules 2 since 3.7.0; evidence without the field is rules 1 | Read again with the rules it records, so it stays valid |
| Checkpoint manifests | optional keys | `rebaselined` and `upgraded` after an upgrade (3.7.0); `after_upgrade` in the first session after one (3.8.0) | Older tools ignore them |
| Template manifest | optional keys | `maintainer_files`, `source_modified` (3.7.0) | 3.6.x ignores them |
| WORKSPACE block | optional keys | `stale_evidence`, block by default (3.8.0) | Older tools ignore it |
| Task Scope | words | `new:<path>`, `resource:<name>`, `tree:` (3.8.0) | A 3.7.x tool reads them as plain words |
| Lock `.agents/cache/ws.lock` | none | Unchanged since 3.6.7 | |
| Message IDs in RECONCILE_LOG | none | Unchanged | |

Nothing is retired in 3.8.0. A later version that stops reading an older mark says so here first, one
release ahead.

Rules 2 reads two kinds of output differently from rules 1: a unittest run whose program prints an "OK"
or "FAILED" line of its own, and a log line such as "FAILED to connect". To go back to 3.6.x, run
`ws upgrade --rollback` from the newer template: it lists the evidence 3.6.x would refuse, and
`ws verify` runs those tasks again.
