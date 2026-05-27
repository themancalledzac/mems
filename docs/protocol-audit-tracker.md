# Protocol-Audit Tracker

Single source for the status of the M1–M8 (Memory MCP) and N1–N6 (non-Memory) protocol-compliance issues identified in the original 2026-04-19 audit. Replaces `docs/superpowers/2026-04-19-protocol-audit.md` (deleted).

**Status legend**

- `FIXED-S` — addressed by **structural** enforcement (a hook, allowlist, or harness check that fires regardless of agent attention).
- `FIXED-P` — addressed by **procedural** enforcement only (a CLAUDE.md rule, snippet, or skill instruction that the agent must read and remember).
- `OPEN-P` — open, only a procedural fix is feasible today (e.g., parent-loop violations — see [`feedback_mempalace_hook_doom_loop.md`](../../.claude/projects/-Users-themancalledzac-Code-Memory/memory/feedback_mempalace_hook_doom_loop.md)).
- `OPEN-U` — open and **structurally unprotectable** under current constraints; mitigation is human attention, not another layer.

**Pruning rule (per `~/.claude/CLAUDE.md` Memory Palace Protocol header).** Any procedural row with no observed trigger in 30 days is a candidate for deletion in the next sweep. "Fixed" without an observed trigger means a rule was written, not a failure prevented.

---

## M-series: Memory MCP protocol issues

| ID | Issue (one line) | Status | Mechanism | Last observed trigger |
|---|---|---|---|---|
| M1 | Filesystem queries ran before mempalace was checked | FIXED-P | CLAUDE.md Hard Rule #1 (per-batch) | not tracked |
| M2 | Multiple naked Grep/Glob/Read with no preceding mempalace_search | FIXED-P + FIXED-S (subagent only) | CLAUDE.md Hard Rule #1 (parent) + PreToolUse hook (subagent dispatch) | hook: 2026-05-06 (verified, deliberate-omission test); parent: still failing per handoff §3b |
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

- **Parent-loop violation (handoff §3b).** The parent agent skipping mempalace before its own filesystem batches is **OPEN-U**. A PreToolUse hook on `Read`/`Glob`/`Bash` that checked recent mempalace activity would create a doom-loop (the check itself either calls mempalace or reads a ledger that gets stale). Documented unfixable under current constraints. **Mitigation: human attention** — when the user notices the parent skipping mempalace, they call it out, and the agent re-orients. Do not add another procedural layer for this.
- **Hook paraphrase weakness (Phase 1.4 fix, 2026-05-06).** The PreToolUse hook previously accepted bare `mempalace_*` token mentions as evidence of orientation. Strengthened to require the literal `"Memory Palace orientation"` marker (with `# skip-mempalace-orientation` opt-out for one-off non-protocol cases). This was a false-negative surface that survived initial deployment.

## Pruning candidates (next sweep)

Rows that are FIXED-P with `not tracked` last-trigger and where the procedural rule has been in CLAUDE.md for >30 days without observable triggering are candidates for **deletion**, not strengthening, per the pruning rule. Trackable triggering requires an instrumentation or convention this repo doesn't have yet — until then, `not tracked` is the honest answer for every procedural row, and pruning decisions remain qualitative ("has the user noticed this failing recently?").

The next pruning sweep should ask: of M1, M4–M8 and N1, N2, N4, N5, N6 (all FIXED-P), how many CLAUDE.md lines could be cut without observably regressing behavior? This is the question Phase 2.6 of the 2026-05-06 plan asks.

---

*This tracker replaces the 282-line prose audit doc. One source of truth. If a row is added, it should also be deleted from somewhere — the protocol's failure mode is accretion, not gaps.*
