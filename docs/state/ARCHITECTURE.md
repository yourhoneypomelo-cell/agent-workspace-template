# Architecture

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
