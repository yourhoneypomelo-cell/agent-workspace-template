# Record forms

Fill-in forms for the facts agents write most often. Each field holds one fact.
Leave out a field that does not apply. Write `unknown` for a field that applies but is not known.

## Component

For ARCHITECTURE.md, "Components". One block per service, module or job.

```text
### <name>

- Code: <path>
- Runs: <where it runs, port, process>
- Start: <command or script>
- Interface: <endpoints, CLI, or functions others call>
- Config: <settings; credentials as the project's credential rule says>
- Check: <command that proves it works>
- Limits: <known limits, with the requirement or task ID>
```

## Decision

For DESIGN.md, "Decisions", through `ws add decision`. One row per decision.

```text
decision: <what was chosen, one sentence>
reason:   <the fact that decided it, with a number or an observed failure>
source:   <user and date, or the task ID that produced the evidence>
```

A decision that replaces an earlier one sets the old row to `superseded` with a reason.

## Finding

For a result that changes later work, such as a test against an external system.
Put it in the Evidence column of the task, or in a table when several items share the same fields.

| Item | Result | Evidence | Next |
| --- | --- | --- | --- |
| <thing tested> | works, fails, blocked | <command, status code, size> | <task ID or none> |

## Procedure

For `docs/guides/<topic>.md`.

```text
# <Topic>

<One sentence: what this controls.>

## Use it
<numbered steps with exact commands>

## Conventions
<bullets: rules that every agent must follow>

## When it fails
| Symptom | Cause | Fix |
```

## Report

For `docs/reports/<topic>.md`: an audit, a measurement campaign or an investigation whose full
detail is too long for a state row. The state row that cites it keeps the conclusion.

```text
# <Topic>

<One sentence: what was examined and the verdict.>

## Verdict
<the decision or result, open items with their task IDs>

## Evidence
| Item | Result | Evidence | Next |

## Method
<what was run, where, with which limits>
```

## Term

For ARCHITECTURE.md, "Terms". One row per project code that a state row uses.

| Term | Meaning | Detail |
| --- | --- | --- |
| ME-02 | Audit finding: QC tracks unbounded dictionaries on a 48 KB fixture | docs/reports/nexus-qc.md |

## What not to write

| Instead of | Write |
| --- | --- |
| A dated heading per work session in a state file | The changed fact in its form; the tool logs when it changed |
| Hashes, byte counts and probe results in a decision or feature cell | The verdict and the evidence path |
| A feature cell that lists v3.2, v3.3 and v3.4 changes | The current behavior; history goes to CHANGE_LOG |
| `BLUE5`, `ME-02` with no definition | A Terms row, or the plain meaning |
| A shorter row made by dropping a number or a user's words | The detail moved to a spec or report, with its path in the row |
| "Not yet done: run-on-boot, HTTPS, Wiley" in prose | One task row for each |
| The same address or port in three sections | One component field; other places name the component |
| A paragraph that mixes how, why, results and plans | Component, decision, finding and task rows |
