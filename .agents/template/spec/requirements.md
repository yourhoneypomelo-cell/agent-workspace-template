# Requirement detail: <name>

Detail for one requirement that does not fit in a table row.
Link it from the Detail column of the requirement in `docs/state/REQUIREMENTS.md`.

## Context

Requirement IDs: R<n>.
Why the user wants it, in two or three sentences.

## Acceptance criteria

| ID | When | Then | Verified by |
| --- | --- | --- | --- |
| AC1 | The user runs `app export` with three tasks | `export.json` lists the three tasks | `tests/test_export.py::test_three` |
| AC2 | The output path is not writable | The command exits 1 and writes nothing | `tests/test_export.py::test_readonly` |

Replace the example rows. Cover the normal case, failures and limits.

## Out of scope

- Behavior that a reader might assume is included but is not.

## Open points

- Assumptions not yet confirmed. Register each one that needs the user with `ws add question`.
