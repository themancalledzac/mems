# User wing ideas: closed items and old session log

Archive for `2026-10-02-user-wing-ideas-design.md`. Open work is never here. Each section is a closed item's write-up, newest first.

## A1 and A2 outcome (2026-10-02): Phase A shipped, live store repaired

### What shipped

Branch `feat/user-wing-recency` was cut from a40d413 in a worktree, because `feat/mempalace-fs-gate` had uncommitted WIP in the same files. It was merged into `feat/mempalace-fs-gate` at f6ea120, and that branch fast-forwarded main to eda101c. The worktree is removed. The branch refs are kept.

| Commit | Subject |
|---|---|
| 1a1122e | feat(user-wing): recency metadata, non-destructive dedup, recent and set_status |
| 780f5cb | feat(mcp): expose user-wing recency params, recent and set_status tools |
| cda87cb | feat(cli): mems my recent reads mempalace_user_recent |
| d58c5f7 | feat(mcp): pass session_id through mempalace_user_write |
| 1684161 | feat(scripts): repair_user_wing strips leaked tool-call markup |
| 0deb17b | feat(user-wing): machine-readable error codes; pin legacy open-status matching |
| e93c9d1 | docs: describe user-wing recency tools and the new dedup behaviour |
| 87a45bc | fix(scripts): repair_user_wing also reads the `<source_wing>X</source_wing>` leak form |

Follow-ups on the way to main:

| Commit | Subject |
|---|---|
| 91ed597 | build(deps): cap mcp below 2 |
| 7e9bfa7 | refactor(server): move health-route notes into docblocks |
| 968d796 | feat(scripts): add tag_personal.py to mark personal user-wing entries |
| 5ec1263 | feat(user-wing): keep summary items readable, drop whole items to fit |
| 96f4c3f | fix(user-wing): summary skips entries already listed under open ideas |
| b9a2a08 | chore(config): register agent-orchestrator wing |
| 6093513 | feat(scripts): tag_personal --ids tags only the named user-wing drawers |
| 1e7f193 | test(user-wing): orch-style scoped reads never return personal entries |
| eda101c | docs(user-wing): spell out orch's calls and the personal-flag safeguard |

### Size

A1 was not sized before it started.
- A1, measured with `git diff --shortstat a40d413 87a45bc`: code +560/−175 across 4 files, tests +689/−48 across 4 files.
- Follow-ups, measured with `git diff --shortstat 7e9bfa7 eda101c`: code +266/−25, tests +314/−6.
- Tests outweighed code both times. That is now a rule in the tracker: size items including tests.
- The suite went from 222 tests to 292.

### Where the contract changed during the build

- Error dicts gained a `code` field: `malformed`, `invalid_hall`, `invalid_origin`, `invalid_status`, `not_found`. orch asked for it so it can tell a markup rejection from a server error. A rejected write is a normal result, not an MCP error.
- The rejected markup strings live in `MALFORMED_MARKERS` in `src/user_wing.py`.
- A `status="open"` filter also matches goals and questions that have no `status` key, so entries written before Phase A count as open. Results still show `status: None` for them.
- `mempalace_user_write` gained `session_id`. Phase B's sweeper needs it.
- `last_seen_epoch` is a float, not an int.
- The summary section first called "Open questions" became "Recent questions", because it is not filtered by status.

### A2: repair

- The dry run found 114 entries with markup. 108 would get a `source_wing` from the leaked tag.
- It was applied after a snapshot (`/data/exports/wing_user_prerepair_20261002.json`, 3,193 entries).
- A second dry run found 0. The entry count did not change.
- The live data had a leak form the spec didn't mention: `<source_wing>X</source_wing>`. The script reads it.

### Personal audit

- Rule 1 of `tag_personal.py` tags by `source_wing` in `job-search` or `running`. Rule 2 matches unscoped entries by keyword. Together they tagged 13 entries. Snapshot: `wing_user_pretag_20261002.json`.
- A later audit tagged 5 more by id with `--ids`. Snapshot: `wing_user_preaudit_20261002.json`. The total is 18.
- All 18 are job-search or interview prep. Each was read before tagging.
- Trap: the keyword list first hit "resume" (as in resuming a session) and "savings" (cost savings). Both were removed. Matching is whole-word, and hyphens count as word breaks.
- Trap: 4 of the 5 audited entries had a code repo's `source_wing`. Filtering by repo alone would have let them through to orch.

### Summary readability

- Before: each item was cut to about 75 characters to fit the budget, which made it unreadable.
- After: items run up to 220 characters, and the summary drops whole items from the end to stay under 2,400 characters. Goals and questions skip entries already listed under open ideas.
- What it did not fix: discoveries still don't fit. Filed as A3.

### Deploys

- The first rebuild committed the fs-gate WIP: an O(1) `/health`, `/health/deep`, a loop watchdog, tini as init, and the mempalace 3.6.0 pin.
- Trap: `mcp[cli]>=1.0.0` had no upper bound. A fresh install resolves mcp 2.x, which removes `FastMCP`. The cap is now `>=1.27,<2`. The container runs mcp 1.30.0.
- Both rebuilds went healthy within 10 seconds. No rollback was needed.

### What held (do not re-investigate)

- The fs-gate WIP diff applied cleanly on top of Phase A, and the merge had no conflicts.
- `search()` adds no scan beyond one vector query of up to 100 candidates, about 40 ms. `recent()`, `summary()` and `status()` each do one metadata-only user-wing read, about 75 ms. None scans the whole palace.
- orch-style calls return no personal entry. `TestOrchCallsSkipPersonal` covers search and recent, with `include_unscoped` true and false.
- The planner pack's three calls take about 0.35 s from orch's runner, measured by orch's Task 1 (agent-orchestrator 06bac91).

## Session log (older entries)

None yet.
