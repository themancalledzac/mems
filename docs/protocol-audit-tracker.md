# Protocol-Audit Tracker

Single source for the status of the M1–M8 (Memory MCP) and N1–N6 (non-Memory) protocol-compliance issues identified in the original 2026-04-19 audit. Replaces `docs/superpowers/2026-04-19-protocol-audit.md` (deleted).

**Status legend**

- `FIXED-S` — addressed by **structural** enforcement (a hook, allowlist, or harness check that fires regardless of agent attention).
- `FIXED-P` — addressed by **procedural** enforcement only (a CLAUDE.md rule, snippet, or skill instruction that the agent must read and remember).
- `OPEN-P` — open, only a procedural fix is feasible today.
- `OPEN-U` — open and **structurally unprotectable** under current constraints; mitigation is human attention, not another layer. **Use this status sparingly and justify it** — it was applied wrongly to the parent-loop case for three months (see "Corrected verdicts" below).

**Pruning rule (per `~/.claude/CLAUDE.md` Memory Palace Protocol header).** Any procedural row with no observed trigger in 30 days is a candidate for deletion in the next sweep. "Fixed" without an observed trigger means a rule was written, not a failure prevented.

---

## M-series: Memory MCP protocol issues

| ID | Issue (one line) | Status | Mechanism | Last observed trigger |
|---|---|---|---|---|
| M1 | Filesystem queries ran before mempalace was checked | FIXED-S | Same gate as M2 — `pretooluse_fs_gate.py` | 2026-08-22 (see M2) |
| M2 | Multiple naked Grep/Glob/Read with no preceding mempalace_search | FIXED-S | `pretooluse_fs_gate.py` (parent loop) + `pretooluse_agent_orientation.py` (subagent dispatch) | 2026-08-22: **82% of batches ran to 3+ calls with no search** across 86 sessions (`mems doctor --protocol`); both hooks live-verified same day |
| M3 | Cross-wing signal present but `mempalace_find_tunnels` never called | OPEN-P | CLAUDE.md Hard Rule #2 mentions it; no structural gate | not tracked |
| M4 | `mempalace_search` coverage too narrow for planning | FIXED-P | CLAUDE.md "Before Invoking Skills" minimum-coverage list | not tracked |
| M5 | `mempalace_user_summary` called but output not cited | FIXED-P | CLAUDE.md Hard Rule #4 ("cite or dismiss") | not tracked |
| M6 | `mempalace_user_write` deferred to session end (not continuous) | FIXED-P | CLAUDE.md Hard Rule #5 + `src/user_wing.py` `status()` guidance string | not tracked |
| M7 | `mempalace_user_search` skipped in favor of summary only | FIXED-P | CLAUDE.md "Before Invoking Skills" requires both | not tracked |
| M8 | Opaque `mempalace_user_write` calls (no inline announcement) | FIXED-P | CLAUDE.md Hard Rule #3 ("announce inline") | not tracked |

## N-series: non-Memory protocol issues

| ID | Issue (one line) | Status | Mechanism | Last observed trigger |
|---|---|---|---|---|
| N1 | `@spec` auto-loaded but never acknowledged | FIXED-P | CLAUDE.md Hard Rule #6 + `superpowers:writing-plans` override #1 | not tracked |
| N2 | Spec content in context but agent never demonstrated reading | FIXED-P | Same as N1 | not tracked |
| N3 | Backend cross-repo context ignored at planning level | OPEN-P | CLAUDE.md Hard Rule #2 covers signals; no structural gate when user mentions backend mid-plan | not tracked |
| N4 | Agent Teams evaluation skipped | FIXED-P | CLAUDE.md `## Agent Teams` + `superpowers:writing-plans` override #3 | not tracked |
| N5 | Plan presented "complete" without spec-coverage check | FIXED-P | `superpowers:writing-plans` override #4 (spec-coverage table required) | not tracked |
| N6 | Dead-code patterns in touched files not flagged | FIXED-P | `superpowers:writing-plans` override #5 (dead-code flagging) | not tracked |

---

## Cross-cutting open items

- **Parent-loop violation — CLOSED 2026-08-22, verdict was wrong.** See "Corrected verdicts" below.
- **Hook paraphrase weakness (Phase 1.4 fix, 2026-05-06).** The PreToolUse hook previously accepted bare `mempalace_*` token mentions as evidence of orientation. Strengthened to require the literal `"Memory Palace orientation"` marker (with `# skip-mempalace-orientation` opt-out for one-off non-protocol cases). This was a false-negative surface that survived initial deployment.

## Corrected verdicts

**Parent-loop violation was marked `OPEN-U` on faulty reasoning (≈2026-05-26 → 2026-08-22).**

The prior entry read: *"A PreToolUse hook on `Read`/`Glob`/`Bash` that checked recent mempalace activity would create a doom-loop (the check itself either calls mempalace or reads a ledger that gets stale). Documented unfixable... Mitigation: human attention."*

That is a false dilemma. It enumerated two implementations and missed the one that works: **read the session transcript**. Claude Code passes `transcript_path` on stdin to `PreToolUse` hooks (confirmed against the hook reference on 2026-08-22). The gate parses that JSONL, counts consecutive filesystem calls since the last `mempalace_*` call, and decides from it — calling no MCP tool (no recursion) and keeping no state file (nothing to go stale). The warn cadence fires on exact multiples of the threshold, so even "have I warned yet?" needs no bookkeeping.

The capability was already in the repo: `mempal_save_hook.sh` has read `transcript_path` since the upstream migration.

Cost of the wrong verdict: it also concluded "Do not add another procedural layer for this" and assigned mitigation to human attention, so the user personally caught this same failure on 2026-04-20, 04-28, 04-29 (×2), and 08-22. The first measurement, taken the day it was finally fixed, found **82% of filesystem batches (244 of 297) ran to 3+ calls with no mempalace search** — Hard Rule #1's own stated bright line. The live gate would have emitted 950 reminders over that window. The protocol was failing four times in five while every tracker row read "not tracked".

Two lessons, both now enforced above:

1. **`OPEN-U` requires a justification that survives review.** An unfixable verdict freezes work; it earns more scrutiny than an open bug, not less.
2. **"not tracked" is not a neutral value.** It hid an 82% failure rate for months. A row with no measurement is a row with no evidence — `mems doctor --protocol` now supplies it for M1/M2, and any future row claiming FIXED should say how it would be observed failing.

---

## Pruning candidates (next sweep)

Rows that are FIXED-P with `not tracked` last-trigger and where the procedural rule has been in CLAUDE.md for >30 days without observable triggering are candidates for **deletion**, not strengthening, per the pruning rule.

Instrumentation now exists for the M1/M2 class: `mems doctor --protocol` measures mempalace-before-filesystem compliance from session transcripts, so those rows carry real numbers. It does not generalize to the N-series (spec acknowledgment, Agent Teams evaluation), which remain qualitative.

The next pruning sweep should ask: of M1, M4–M8 and N1, N2, N4, N5, N6 (all FIXED-P), how many CLAUDE.md lines could be cut without observably regressing behavior? This is the question Phase 2.6 of the 2026-05-06 plan asks.

---

*This tracker replaces the 282-line prose audit doc. One source of truth. If a row is added, it should also be deleted from somewhere — the protocol's failure mode is accretion, not gaps.*
