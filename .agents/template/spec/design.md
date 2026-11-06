# Design: <name>

How the requirement in `requirements.md` of this folder is built.

## Approach

Entry points, data flow and the main components, in a few sentences.
Add a plain text diagram only if a flow is hard to follow in prose.

## Interfaces and data

| Item | Shape | Owner |
| --- | --- | --- |
| `export(tasks, path)` | list of task dicts to file path | `app/export.py` |

## Failure and recovery

- How a partial result is detected.
- Whether a retry is safe.
- What a rollback keeps.

## Decisions

Register each decision with `ws add decision` and list its ID here: D<n>.
Rejected options belong there too, so they are not proposed again.
