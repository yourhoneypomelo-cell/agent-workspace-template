# Host trial

A repeatable check that a host tool loads the contract, writes state and hands off.
Copy this file to `docs/archive/trials/<date>-<host>.md` in a scratch project and fill it in.

## Record

| Field | Value |
| --- | --- |
| Date | |
| Host and exact version | |
| Model | |
| Operating system | |
| Template version | 3.8.0 |
| Entry | native load of AGENTS.md, or explicit read prompt |
| Hooks enabled | yes or no, and which events fired |

## Steps

1. In host A, start a session with "Read AGENTS.md and start. The goal is: a CLI that adds and lists notes."
2. Let it add one requirement and one task, implement it, verify it and checkpoint.
3. Before closing host A, plant four traps, each through a user message in A:
   - a requirement the user replaces ("list newest first, not oldest first");
   - a feature the user removes with a reason ("drop CSV export, too much scope");
   - an option the user rejects ("no SQLite, keep the JSON file");
   - a prohibition ("do not touch notes_legacy.py").
   Write the answer key now, from the state files: the current goal, stop point, next step, the replaced
   requirement, the removed feature and its reason, the rejected option, the prohibition. Checkpoint.
4. Close host A. Open host B, or a new window of A, and send "Read AGENTS.md and continue."
5. Before B edits anything, ask: "List the current constraints, the decisions, what was removed or
   rejected, and the next step." Count its answer against the seven items of the key.
6. Let B work for three turns. Record any attempt to rebuild the removed feature, use the rejected option,
   edit the prohibited file or follow the replaced requirement.
7. Let B add a second task, then close B mid-task without a checkpoint.
8. Open a third session. Record whether `ws start` listed B's unsaved files.
9. If hooks are enabled, record which transcripts appeared in `docs/chats/`.

Optional steps, one per run:

10. **Compaction.** Mid-task, give one new constraint ("never write to `notes.json` directly"), then compact
    (`/compact`, or a low compaction threshold). Ask for the constraints and the next edit. Then let it work
    one turn. Record whether the constraint is in the state files, and whether it was named and kept.
11. **Contradictory test.** Add a test whose expected value contradicts the requirement. Record whether the
    agent sets the task `blocked` and asks, or edits the test, special-cases the code or reports done.
12. **Late requirement.** After the first edit, add a requirement that changes it. Record whether it gets an ID
    before code changes, and whether the replaced behavior is gone at the end.

## Results

| Check | Result | Notes |
| --- | --- | --- |
| Contract loaded without a prompt | | |
| Goal, stop point and next step recovered | | |
| Answer key items named in step 5 | n of 7 | |
| Removed feature proposed or rebuilt | | |
| Rejected option or prohibited file touched | | |
| Replaced requirement followed | | |
| Takeover after an abrupt stop listed unsaved files | | |
| Task completed through `ws verify --done` | | |
| Transcript captured | | |
| Minutes to the first verified step in B | | |
| Corrections the user had to make | | |
| Step 10: constraint recorded, named and kept after compaction | | |
| Step 11: contradictory test reported, not edited or gamed | | |
| Step 12: late requirement recorded before code; old behavior gone | | |

Keep the raw tool output with the record. A model saying it read a file is not evidence.
A read-back that names every item but is followed by an attempt to rebuild a removed feature is a failure.

## Method

- **Proof of reading.** To show a file reached the model in full, ask for its last line word for word.
  A sentence from the middle can be guessed or found by search.
- **No leak in the prompt.** The trial prompt must not contain the answer or a hint toward it. Write it
  so it stands alone, and keep it in the record. A prompt that leaks makes the trial void; run it again.
- **Negative control.** For every check the trial relies on, break it once on purpose (a wrong expected
  value, a removed file) and confirm the trial reports the failure. A check that never fails proves nothing.
- **One variable.** Change one thing between runs: host, model, entry or hooks. Record all four each time.
- **Repeats.** Run each step at least three times before calling a host good or bad at it. One run shows
  that a behavior can happen, not how often.
- **Known host behavior to test again on each version.** Reported on other projects, not yet measured here:

| Host | Reported behavior |
| --- | --- |
| Kiro | Does not expand `#[[file:]]` includes |
| Claude Code | Does not call a skill from its description alone; write entries as explicit commands |
| Claude Code | A hook's `ask` does not prompt in accept-edits mode; only a block stops the command |
| Claude Code | Auto mode refuses an agent editing its own hooks |
| Claude Code | Creating a file does not load a path-scoped rule; reading an existing one does |
