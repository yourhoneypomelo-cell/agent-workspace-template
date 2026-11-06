# Host trial: CLI scenarios 10-12

## Record

| Field | Value |
| --- | --- |
| Date | 2026-11-06 |
| Host and exact version | CLI only (no host tool; ws.py direct) |
| Model | N/A (scripted) |
| Operating system | Windows 11, Python 3.11 |
| Template version | 3.6.5 |
| Entry | Direct `ws.py` commands |
| Hooks enabled | no |

## Steps and results

### Step 10: Compaction constraint

Recorded a preference (P1: "Never write to notes.json directly") and a decision (D1: "Use JSON file storage, not SQLite")
through `ws add preference` and `ws add decision`, then checkpointed.

**Result: PASS.** Both P1 and D1 are in `docs/state/PREFERENCES.md` and `docs/state/DESIGN.md`. A new session
reads them from the state files. The constraint survives any compaction because it is on disk, not in context.

### Step 11: Contradictory test

Added T2 with acceptance "notes list returns oldest first", then wrote a test asserting the opposite and made it
fail. Ran `ws verify T2 --done -- python -m unittest test_notes`.

**Result: PASS.** Verify refused to mark T2 as done. The failed test output is recorded in evidence. T2 stays
"ready next" in the brief. The tool does not allow editing a test to pass; the acceptance command's exit code
is the only gate.

### Step 12: Late requirement

Added R2 ("newest first") and replaced R1 ("oldest first") with `ws set R1 --set status=replaced`.

**Result: PASS.** The tool immediately listed impacted rows (T2, F1) and gave the fix command. After updating
both rows to point at R2, verify passed and checkpoint sealed.

## Summary

| Check | Result |
| --- | --- |
| Constraint recorded in state files, survives compaction | PASS |
| Contradictory test refused by verify | PASS |
| Late requirement impact detected with fix commands | PASS |
| Impacted rows updated, verify passes, checkpoint seals | PASS |
