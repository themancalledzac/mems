# Structural gate for mempalace-before-filesystem

**Branch:** `feat/mempalace-fs-gate` → `feat/mems-full-implementation`
**Commit:** `a40d413` · 10 files, +1383/−38 · 224 tests pass, ruff clean

## The problem

Hard Rule #1 — search mempalace before each batch of filesystem discovery — was
enforced only by a CLAUDE.md rule the agent had to remember. Measured across 86
sessions of real transcripts, that rule held for 18% of batches:

```
filesystem batches (2+)    : 297
violations (runs of 3+)    : 244  (82%)
gate reminders it'd emit   : 950
longest run, no mempalace  : 64
```

The palace was healthy throughout. A wing-filtered search on `edens-zac` for
`"GalleryFilter LensType filter state gallery view"` returns `contentFilter.ts`,
`filterToolbarUtils.ts`, and `CollectionFilterContext.tsx` in under a second —
including the exact doc comments one session was extracting by hand with
`sed -n '1,30p'`. This was never a data or index problem. The palace simply was
not being asked.

## Why it stayed broken

`docs/protocol-audit-tracker.md` had ruled this class of fix impossible, marking
it `OPEN-U` ("structurally unprotectable"):

> A PreToolUse hook on `Read`/`Glob`/`Bash` that checked recent mempalace
> activity would create a doom-loop (the check itself either calls mempalace or
> reads a ledger that gets stale).

That is a false dilemma. It enumerates two implementations and misses the one
that works: **read the session transcript**. Claude Code passes `transcript_path`
on stdin to `PreToolUse` hooks (verified against the hook reference). The gate
parses that JSONL, counts consecutive discovery calls since the last
`mempalace_*` call, and decides from it — calling no MCP tool (no recursion) and
keeping no state file (nothing to go stale). The warn cadence fires on exact
multiples of the threshold, so even "have I warned yet?" needs no bookkeeping.

`mempal_save_hook.sh` has read `transcript_path` since the upstream migration.
The capability was in the repo the whole time the gap was documented as unfixable.

Because the verdict also said "do not add another procedural layer for this" and
assigned mitigation to human attention, the same failure was caught by hand on
2026-04-20, 04-28, 04-29 (×2), and 08-22.

## What's in the diff

**`integration/claude_code/pretooluse_fs_gate.py`** (new, 344 lines)
Registered on `PreToolUse: Bash|Grep|Glob|Read`. Warn-only by default: it injects
a reminder naming the likely wing, and the tool call proceeds.

| Variable | Default | Effect |
|---|---|---|
| `MEMPALACE_FS_GATE_MODE` | `warn` | `block` denies the call, `off` disables |
| `MEMPALACE_FS_GATE_THRESHOLD` | `3` | Calls before firing, then every multiple |
| `MEMPALACE_FS_GATE_TAIL_BYTES` | `524288` | Transcript tail window |

Only `Bash` commands leading a segment with a discovery verb count, so
`git commit` and `git log | head` do not trip it, while the multi-line
`cd` → `echo` → `sed` → `grep` probe does. Fails open on every error path.
42 ms per invocation on a 1.2 MB transcript.

**`mems_cli/protocol_audit.py`** (new, 231 lines) — `mems doctor --protocol`.
Imports its classifier from the gate rather than reimplementing it, so the audit
cannot grade against a standard the gate does not enforce.
`test_audit_shares_classifier_with_gate` guards that contract.

**`docs/protocol-audit-tracker.md`** — M1/M2 move to `FIXED-S` with real numbers.
New "Corrected verdicts" section records why `OPEN-U` was wrong and what it cost.
`OPEN-U` now carries a warning to justify its use. Fixes a dead link to a memory
file deleted in May.

## Reviewer notes

**The metric definition is the load-bearing decision.** Three candidates, and two
are indefensible:

| Definition | Rate | Verdict |
|---|---|---|
| Any run of 2+ calls | 83% | Too strict — penalizes a legitimate pair after a search |
| Run not immediately preceded by a search | 4% | Badly broken (see below) |
| **Run reaching 3+ with no search between** | **82%** | **Shipped** |

The second is the trap. Runs are delimited *by* mempalace calls, so "preceded by
a search" is true by construction for every run but the first — the test measures
nothing, and one search licensed an unbounded 64-call streak. It would have
reported "96% compliant" the same week the protocol was visibly failing.

The shipped definition uses Hard Rule #1's own stated bright line ("3+ Greps
without a mempalace call between them") and matches what the gate enforces at its
default threshold, so audit and enforcement report one standard.

**Two pre-existing bugs fixed on the way:**
- `cmd_doctor`/`cmd_make`/`cmd_restore` returned dicts where the dispatcher
  expected exit codes, so `SystemExit(dict)` dumped the dict to stderr and exited
  1 on success.
- `hooks_install.py` deduped on command alone, so two `PreToolUse` entries with
  different matchers collided. Now keyed on `(matcher, command)`. Caught by the
  installer test, not by inspection.

**Verification:** 224 tests pass in-tree, 222 on the committed state in isolation
(the 2 extra are your uncommitted `test_mcp_server.py` additions). Ruff clean.
Both hooks live-tested: the agent gate blocked a deliberately un-oriented
dispatch, and the fs gate fired repeatedly while this work was being done.

**Out of scope / not committed:** `~/.claude/CLAUDE.md` is not version-controlled.
Its Memory Palace Protocol section was pruned 75 → 60 lines (file 186 → 171) by
cutting three sections that restated Hard Rules #1/#3/#4/#5/#6 verbatim — a net
removal even after adding the hook line, per that section's own pruning policy.
Backup at `/tmp/CLAUDE.md.bak.<ts>`.

## Follow-up

The gate ships in `warn` mode against a 950-reminder backlog. Re-run
`mems doctor --protocol` in a week; if the reminders are being ignored the way
the CLAUDE.md rule was, `MEMPALACE_FS_GATE_MODE=block` is the escalation.
