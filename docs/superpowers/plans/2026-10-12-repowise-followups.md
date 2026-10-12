# Repowise follow-ups: sync fixes, eval, search, hooks, session brief

> **For agentic workers:** This is a roadmap plan. It fixes the decisions, the MR split, the order and each MR's tasks, files, interfaces and tests. Before an MR is built, write its step plan with full code in `docs/superpowers/plans/` using superpowers:writing-plans, then run it with superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three sync bugs that left 76% of the palace as junk or orphans, then add a retrieval eval, gated hybrid search, a fixed and measured fs-gate hook, and a SessionStart brief.

**Architecture:** Sync moves from "mine the working tree, diff by commit" to "reconcile each wing against `git ls-files`". It runs our own in-process cleanup and reports every result. Retrieval changes are gated by a hand-labelled eval run over HTTP. Hook changes share one host-side repo resolver.

**Tech Stack:** Python 3.12, mempalace 3.6.0 (container), ChromaDB, FastMCP, stdlib-only hooks, pytest.

**Source documents:**
- `docs/research/2026-10-12-repowise-review.md`: the repowise review and the ideas list.
- Eight per-item reviews done on 2026-10-12, folded into the sections below: B1, B2, B3, I2, I3, I4, I5, I6.
- Specs amended by MR-7: `docs/superpowers/specs/2026-10-01-short-term-context-design.md`, `docs/superpowers/specs/2026-10-02-user-wing-ideas-design.md`.

## Global constraints

- Repowise is AGPL-3.0. Borrow ideas only. Copy no code.
- The container runs mempalace 3.6.0. The local `.venv` runs 3.3.6 (spec item A4). Any test that touches upstream search or miner code must run against 3.6.0. Any live measurement goes over HTTP to `localhost:8787`.
- Never write to the live palace from a second process while the server runs. One-off data steps use `docker compose stop` then `docker compose run --rm --no-deps`.
- The user wing (`wing=user`), `claude_imports` and the planned `recent` wing are never pruned. Cleanup touches only wings in `repos.json`, and only drawers whose `source_file` is under that repo's path.
- orch's contract stays stable: `mempalace_search`, `mempalace_user_search`, `mempalace_user_recent` and `mempalace_user_write` keep their names, parameters and hit fields. Changes are additive only.
- No inline comments in any file touched. Delete existing ones in touched files. Docblocks of 3 sentences or fewer.
- Hooks are stdlib-only, fail open (exit 0, no output) and never block more than about 2 s.

## Verified findings

All of these were checked against live state on 2026-10-12.

| # | Finding | Evidence |
|---|---|---|
| F1 | 164,086 of 214,614 drawers (76%) belong to files that are not in `git ls-files --cached --others --exclude-standard`. lightroom `scripts/output/` accounts for 152,704. `.claude/worktrees/` copies in edens-zac-backend account for about 7.9k. | B1, B2 |
| F2 | lightroom's `scripts/output/` was not gitignored when it was mined on 2026-06-23. It was ignored from 2026-07-15 (commit `64646af`). `scan_project` behaved correctly. The real gap is that nothing ever cleans up. | B1, B2 |
| F3 | `mempalace sync --apply` with no `--wing` always exits 2 (upstream `sync.py:224`). The cleanup has never deleted a drawer. Upstream would also take the mine lock and open a second Chroma client. | B2 |
| F4 | Upstream's ignore matcher reads `.gitignore` only, not `.git/info/exclude` or the global ignore file. | B1 |
| F5 | `get_changed_files` drops `R` lines. Range diffs pair unrelated deletes and adds into `R` lines, so real deletes and adds are lost too. Example: `manageUtils.test.ts` left 109 drawers, and `collectionEditUtils.test.ts` has 0. In all, 273 drawers are lost and 5 new paths were never indexed. | B3 |
| F6 | An unreachable `since_sha` returns an empty diff, and the ledger advances anyway. | B3 |
| F7 | Incremental sync skips `scan_project`'s filters. `package-lock.json` has 671 drawers, `config/mempalace.yaml` has 51, plus `.scss`, `.svg` and `.tf` files. | B3 |
| F8 | Nothing syncs on a schedule. The memory wing was last synced 2026-06-23 at `6647f51`, 25+ commits behind. Most wings are weeks to months stale. | B2, B3, I2 |
| F9 | `handle_sync` always returns `"status": "ok"` and reports errors from every ledger entry. `mems sync` exits 0 on errors. `memory_sync` and `mempalace_resync` are plain `def` tools, so they run on the event loop. A long sync can trip the 90 s liveness watchdog. | B1, B2 |
| F10 | `mems search` prints `?` paths and empty snippets. `mems_cli/commands/search.py:56-89` reads `hit["metadata"]` and `hit["document"]`, but hits carry top-level `source_path` and `text`. | I2, I3 |
| F11 | BM25 today only re-sorts the final 10 vector hits. Upstream `"union"` adds lexical candidates. With a wing filter it adds 1.5–2.4 s to prose queries and changes nothing. Unscoped, it moved 3 identifier misses to rank 1. | I3 |
| F12 | `UserWing.search` filters by `source_wing` after Chroma has already picked the top 30–100 hits from the whole user wing. Scoped searches for small wings (memory is 5% of entries) return 0. This affects orch now. | I5 |
| F13 | The fs gate works in the main loop. It raises searches within 10 calls to 31%, against an 11% pre-gate base and a 13% in-era control. It has three defects. In subagents it reads the parent's transcript (the count matches only 4% of the time). 22% of firings target paths no wing covers. The reminder says the repo "has already been indexed", which is false. | I4 |
| F14 | Staleness labels on decisions would flag 300 of 321. The median gap from a decision to the next commit on its files is 2 h, because that commit is the decision being built. | I6 |
| F15 | The palace's own ONNX embedder is downloaded at runtime into the container layer. `Dockerfile:34` bakes the wrong model. `repair rebuild-index` in a fresh container needs network. | B1 |

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The files to keep for a wing are `git ls-files -z --cached --others --exclude-standard`, filtered by upstream's `READABLE_EXTENSIONS`, `SKIP_FILENAMES`, symlink, regular-file and size checks, plus a `sync.exclude` list in `config/mempalace.yaml`. | Tracked-only would wipe `edens-zac-backend-go` (no commits) and job-search's `modes/`. `--exclude-standard` reads `.git/info/exclude`, which fixes F4. |
| D2 | Replace `_post_ingest_prune` and `_delete_drawers_for_file` with our own in-process `prune_wing`. | F3. Upstream cannot be called safely from the server. |
| D3 | Incremental sync becomes a reconcile: per wing, list the files to keep, prune, then call `process_file` on every kept file. `process_file` skips unchanged files by mtime. Delete `get_changed_files`. | This one path fixes F5, F6, F7 and untracked files. MR-1 Task 1.4 measured it at 7 s for the largest wing. Owner question Q1. |
| D4 | Mass-removal guard: refuse when a prune would remove more than 50% of a wing **and** more than 200 drawers, or when the keep list is empty, unless `allow_large_prune=True`. | Protects against a bad mount or a broken git call. |
| D5 | `memory_sync` and `mempalace_resync` run their work through `anyio.to_thread.run_sync`. | F9 watchdog risk. |
| D6 | Search strategy is chosen per call. `mempalace_search` and `mempalace_search_all` gain an optional `candidate_strategy: "auto" \| "vector" \| "union" = "auto"`. `auto` picks `union` only for identifier-shaped queries. No env var. | Additive for orch. `mems eval --arg candidate_strategy=...` can A/B without a restart (I2 and I3 agreed on the need; this picks I2's form). |
| D7 | I3 stage 2 (our own FTS5 leg, filename leg and RRF) is deferred until the eval shows misses that stage 1 leaves. | F11. Stage 1 is 2–3 h. Stage 2 is 1–1.5 days and ties us to Chroma's sqlite schema. |
| D8 | I6 (decision paths and staleness) is dropped as its own MR. An optional `paths` write field may be added later inside MR-7, or in Phase B's sweeper. | F14. |
| D9 | One host-side repo resolver, `integration/claude_code/repo_scope.py` (stdlib). MR-5 builds it. MR-7 and the 2026-10-01 spec's `src/repo_resolve.py` use it instead of a second one. | I4 and I5 each designed one. |
| D10 | Keep the fs gate. Fix it and measure it with a session holdout. Keep the orientation hook as is. | F13. Oriented subagents searched 94% of the time, against 1% for opted-out ones. |
| D11 | The SessionStart brief is an amendment to the 2026-10-01 spec (phase 6 split into 6a and 6b). It is not a parallel design. v1 matcher is `startup\|clear`, with no `compact`. | Repowise leaves out `compact` on purpose. The open-ideas section needs only Phase A data. |

## MR breakdown and order

| MR | Content | Items | Size | Depends on | Status |
|---|---|---|---|---|---|
| MR-0 | Bake chroma's ONNX MiniLM into the image | F15 | S, about 1 h | none | Done |
| MR-1 | Sync correctness: file list, prune, reconcile, reporting, threading | B1, B2, B3 | M–L, 10–14 h | none | Done |
| OP-1 | One-off cleanup of about 164k drawers, then resync every wing | B1 migration | 1 h window | MR-0, MR-1 deployed | Done |
| MR-2 | `mems eval` harness, question set, and the `mems search` printer fix | I2, F10 | M, 4–5 h + about 2 h owner review | none for the code; baseline after OP-1 | Tasks 2.1–2.4 done; Task 2.5 open |
| MR-3 | `UserWing.search` scoping fix | F12 | S, about 1.5 h | none | Done |
| MR-4 | Hybrid search stage 1: identifier-gated union, `candidate_strategy` param | I3 | S, 2–3 h | MR-2 baseline, OP-1 | Open |
| MR-5 | fs gate fixes and the shared `repo_scope.py` resolver | I4 part 1 | M, 4–5 h | none | Done |
| MR-6 | `mems doctor --protocol --efficacy` report | I4 part 2 | M, about 3 h | MR-5 deployed for two weeks of holdout data | Open |
| MR-7 | SessionStart brief: `/brief` route, `src/brief.py`, hook, installer, spec edits | I5 | M, 5–6 h | MR-3, MR-5 | Open |

**Waves:** waves 1 and 2 are done, except the MR-2 baseline (Task 2.5).
1. **In parallel:** MR-0, MR-1, MR-2 (code and question set), MR-3, MR-5. They touch separate files, except that MR-1 and MR-5 both touch `config/` reads. MR-5 reads `~/.config/mems/repos.json` and MR-1 reads `config/repos.json`, so they don't conflict.
2. **Then:** OP-1, then commit the MR-2 baseline.
3. **Then:** MR-4 and MR-7. MR-6 starts two weeks after MR-5 is deployed.

**Agent Teams:** wave 1 has five independent branches. It is a good fit for `/agent-teams`, or for parallel subagents with one worktree per branch. Remove the worktrees when the wave closes, per CLAUDE.md.

---

## MR-0: Bake the embedding model into the image

**Status:** Done. The image bakes chroma's ONNX MiniLM model, so the palace embeds with no network.

**Files:** Modify `Dockerfile:34`.

- [x] **Task 0.1.** Replace the sentence-transformers bake with a build step that loads chroma's `ONNXMiniLM_L6_V2` once, so `~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/` ships in the image.
  - Verify by building the image and running `docker run --rm --network none <image> python -c "<embed one string with chroma's default embedding function>"`. It must succeed with no network.
  - Check whether the old sentence-transformers model is used anywhere (`grep -rn sentence_transformers src mems_cli scripts`). Remove the bake if nothing uses it.

---

## MR-1: Sync correctness (B1 + B2 + B3)

**Status:** Done. Sync reconciles each wing against `git ls-files`, prunes drawers for files that are gone, and reports per-wing results. A file that fails to index is recorded and skipped; it never fails its wing. `sync.extra_extensions` and `sync.extra_filenames` add `.tf`, `Dockerfile` and `pom.xml`.

**Files:**
- Modify: `src/sync_engine.py` (most of the file), `src/tools.py` (`handle_sync`, `handle_resync`), `src/mcp_http_server.py` (`memory_sync`, `mempalace_resync`), `config/mempalace.yaml` (new `sync:` block and header docs), `mems_cli/commands/palace_ops.py` (`cmd_sync`, `cmd_status`), `mems_cli/commands/repo_registry.py:50`.
- Test: `tests/test_sync_engine.py`, `tests/test_tools.py`, `tests/test_mems_commands.py`, `tests/conftest.py`.

**Interfaces produced:**
```python
class SyncSourceError(Exception): ...

def list_indexable_files(repo_path: str, sync_cfg: dict) -> list[Path]:
    """Files to keep for a wing: git ls-files -z --cached --others --exclude-standard, filtered."""

def prune_wing(collection, wing: str, repo_path: str, keep: set[str], *,
               dry_run: bool = False, allow_large: bool = False) -> dict:
    """Returns {"status": "ok"|"skipped"|"blocked"|"error", "scanned", "removed",
    "kept", "no_source", "out_of_scope", "top_sources", "reason"}."""

SyncEngine.full_sync(wing_name: str | None = None, allow_large_prune: bool = False) -> list[str]
SyncEngine.incremental_sync(wing_name: str | None = None, allow_large_prune: bool = False) -> list[str]
```
Both sync methods return the wing names they processed. Ledger entries gain `prune` (the `prune_wing` result plus a timestamp) and `last_run: {indexed, skipped, removed}`.

### Task 1.1: `list_indexable_files`

Behaviour:
- Runs `git -C repo ls-files -z --cached --others --exclude-standard`. A non-zero exit raises `SyncSourceError` with stderr.
- Drops entries ending in `/`. These are nested repos and worktrees.
- Keeps a path only if all of these hold:
  - `is_file()` and not a symlink.
  - Suffix in `mempalace.miner.READABLE_EXTENSIONS`.
  - Name not in `SKIP_FILENAMES`.
  - No path segment matched by `should_skip_dir`.
  - Size `<= MAX_FILE_SIZE`.
  - Not matched by `sync.exclude`. Use upstream `GitignoreMatcher.from_patterns`; confirm the name exists in 3.6.0 first.
  - If `sync.max_data_file_bytes` is set, data files (`sync.data_extensions`) are under it.
- Returns `Path(repo_path) / rel` and never calls `resolve()`. This keeps the existing `source_file` string format.
- Works on a repo with no commits.

Add the `sync:` block to `config/mempalace.yaml`:
```yaml
sync:
  exclude: ["**/.claude/settings.local.json", "**/.claude/.cc-writes/**"]
  max_data_file_bytes: null
  data_extensions: [.json, .jsonl, .csv]
```
The size cap stays off until the owner answers Q6.

Tests:
- `test_indexable_excludes_gitignored_dir`
- `test_indexable_includes_untracked_not_ignored`
- `test_indexable_honors_git_info_exclude`
- `test_indexable_skips_nested_repo_dir`
- `test_indexable_applies_upstream_filters` (`package-lock.json`, `.png` and symlinks are dropped)
- `test_indexable_unborn_head_lists_files`
- `test_indexable_drops_tracked_file_deleted_from_disk`
- `test_indexable_unquoted_paths` (`café.md`, `sp ace.md`)
- `test_indexable_config_exclude_patterns`
- `test_indexable_data_size_cap_only_hits_data_extensions`
- `test_indexable_raises_on_non_git_dir`

### Task 1.2: `prune_wing`

Behaviour:
- Pages `collection.get(where={"wing": wing}, include=["metadatas"], limit=1000, offset=...)`. Collects ids first, then deletes in batches of 1,000.
- Removes a drawer only when all of these hold:
  - It has `source_file`.
  - `source_file` starts with `normpath(repo_path) + "/"`.
  - It is not a registry row (`room == "_registry"`, or the id starts with `_reg_`).
  - It is not in `keep`.
- Counts and keeps drawers with no source, and drawers outside the repo.
- Purges closets by `source_file $in` when that collection is available.
- Guards:
  - Repo path missing: `skipped`.
  - `keep` empty while the wing has drawers: `blocked`.
  - D4 threshold exceeded and `allow_large` false: `blocked`, with the count and the override command.
  - Any exception: `error`. It never raises.
- `dry_run=True` deletes nothing and returns the same report.

Tests:
- `test_prune_removes_untracked_source`
- `test_prune_removes_drawers_for_deleted_files`
- `test_prune_keeps_drawers_without_source_file`
- `test_prune_never_touches_other_wings` (`wing=user` and `wing=claude_imports` with sources under the repo path both survive)
- `test_prune_keeps_source_outside_repo_path`
- `test_prune_skips_registry_rows`
- `test_prune_dry_run_deletes_nothing`
- `test_prune_pages_past_1000` (1,500 drawers)
- `test_prune_blocked_above_threshold`
- `test_prune_blocked_when_keep_empty`
- `test_prune_allow_large_applies`
- `test_prune_error_never_raises`

All of these use a real Chroma collection in `tmp_palace`.

### Task 1.3: Reconcile sync and the ledger

Behaviour:
- Split the per-wing body into `_sync_one(name, repo_config, collection, allow_large_prune) -> dict`. The steps:
  1. `keep = list_indexable_files(...)`.
  2. `prune_wing(...)`.
  3. `process_file` for each kept file.
  4. Update the ledger with `last_commit_sha` (display only), `last_sync_ts`, `files_indexed = len(keep)`, `prune` and `last_run`.
- `full_sync` and `incremental_sync` both call `_sync_one`.
- `incremental_sync` skips a wing only when HEAD is unchanged **and** the last prune was `ok` **and** `git status --porcelain` reports no untracked or modified files.
- Call `get_collection` once per run, not once per wing (`:115`).
- Delete `get_changed_files`, `_post_ingest_prune` and `_delete_drawers_for_file`.
- `SyncSourceError` marks only that wing as errored.

Rewrite the docblocks of `full_sync` and `incremental_sync`. Indexing covers committed and untracked-but-not-ignored files, as they are on disk.

Tests:
- `test_full_sync_records_prune_in_ledger`
- `test_sync_never_invokes_mempalace_cli` (replaces `test_full_sync_calls_mempalace_sync_after_ingest`)
- `test_reconcile_rename_purges_old_and_indexes_new`
- `test_reconcile_unrelated_delete_and_add` (the `manageUtils` regression)
- `test_reconcile_skips_non_indexable` (`package-lock.json`)
- `test_reconcile_modified_to_symlink_purges_drawers`
- `test_incremental_skips_wing_when_clean_and_unchanged`
- `test_incremental_runs_when_untracked_file_added`
- `test_files_indexed_counts_kept_files`
- `test_sync_source_error_marks_only_that_wing`

Update the existing tests:
- `test_full_sync_indexes_repo`, `test_full_sync_handles_bad_repo` and `test_full_sync_specific_wing` patch `list_indexable_files` instead of `scan_project`.
- `tests/conftest.py` `tmp_config`: move to the current nested taxonomy shape, so `_flatten_rooms` returns rooms.

### Task 1.4: Measure reconcile cost (gate for D3)

- [x] `incremental_sync(wing_name="edens-zac-backend")` with no changes, the worst case at about 1.4k kept files, took 7 s against a copy of the palace. That is under the 30 s limit, so reconcile is kept and no git-diff path was added.

### Task 1.5: Reporting and threading

Behaviour:
- `handle_sync(..., allow_large_prune=False)` reports only the wings it touched. Shape: `{"status": "ok"|"partial"|"error", "synced": [...], "errors": [{"wing", "error"}], "prune": {wing: result}}`. Status is `partial` when any wing errored, or any prune is `error` or `blocked`.
- `handle_resync` passes the flag through. Delete its unused `output_dir` parameter.
- `memory_sync(wing, full, allow_large_prune=False)` and `mempalace_resync` run their work through `anyio.to_thread.run_sync`.
- `mems sync --allow-large-prune`. `cmd_sync` exits 1 when status is not `ok` and prints errors and blocked prunes to stderr.
- `cmd_status` adds a prune column: `ok -N`, `blocked N`, `error` or `skipped`.
- Fix `mems_cli/commands/repo_registry.py:50` `_load_ledger`. It reads a path that doesn't exist, so `mems repo list` always shows `-`. Read `last_sync` from `memory_sync_status` over HTTP instead.

Tests:
- `test_sync_status_partial_on_prune_error`
- `test_sync_reports_only_touched_wings`
- `test_memory_sync_runs_in_worker_thread` (monkeypatch `anyio.to_thread.run_sync`)
- `test_sync_exits_nonzero_on_partial`
- `test_status_shows_prune_column`
- `test_repo_list_shows_last_sync`

### Task 1.6: Prune command for OP-1 and orphan checks

`python -m src.sync_engine prune [--wing W] [--apply] [--force]`. It is a dry run by default. It prints each wing's report as JSON lines.

Tests:
- `test_prune_cli_dry_run_by_default`
- `test_prune_cli_apply_force`

**Rot to clean in MR-1 files:**
- Inline comments in `src/sync_engine.py`, `src/tools.py` and `mems_cli/commands/palace_ops.py`.
- The `docs/2026-05-06-handoff.md:26` claim that sync is "working".
- The `docker-compose.yml` comment examples (`edens-zac` vs `edens.zac`).
- `repos.json`'s unused `"wing"` field. Document that the key is the wing.

---

## OP-1: One-off cleanup (after MR-0 and MR-1 are deployed)

**Status:** Done on 2026-10-12. The prune removed 165,235 stale drawers. A full sync then ran with 9 wings ok and 0 failed files. The user wing kept all 3,291 drawers. Backups are in `~/mempalace-backups/2026-10-12/`: `palace-volume.tar.gz` (the whole volume, taken with the server stopped) and `wing_user.json`.

This needs a 15–20 minute window. MCP tools are down for the whole window.

- [x] **Dry run against live.** `docker exec mempalace python -m src.sync_engine prune`. This is read-only. Expect about 164k removals, with `user` (3,282) and `claude_imports` (23,669) untouched. Stop if the numbers differ by more than 5%.
- [x] **Stop and back up.**
  ```bash
  docker compose stop mempalace
  ```
  ```bash
  docker run --rm -v memory_mempalace-data:/data alpine cp -a /data/palace /data/palace.pre-op1-20261012
  ```
  Use the actual date in the backup name.
- [x] **Prune** (about 2.5 min).
  ```bash
  docker compose run --rm --no-deps --entrypoint python mempalace -m src.sync_engine prune --apply --force
  ```
- [x] **Rebuild the vector index** (about 11.5 min). The palace drops from 1.6 GB to about 380 MB.
  ```bash
  docker compose run --rm --no-deps --entrypoint mempalace mempalace --palace /data/palace repair rebuild-index --yes
  ```
- [x] **Start and verify.** `docker compose up -d`. Then check:
  - `/health` is ok.
  - `/health/deep` shows `user=3282`, `claude_imports=23669`, `lightroom-export` about 323, total about 50.5k.
  - There are 104 `personal` flags.
- [x] **Resync each wing in turn.** `mems sync --wing <w>` for every wing in `repos.json`. Every prune should report `ok`.
- [ ] **Rollback, if needed.** Stop the container, move `/data/palace` aside, copy the backup back, then start.

---

## MR-2: `mems eval` (I2) and the search printer fix

**Status:** Tasks 2.1–2.4 are done: `mems eval`, the fixed `mems search` printer, the query sampler `scripts/sample_eval_queries.py`, and 35 drafted questions in `tests/fixtures/retrieval_corpus.draft.json`. Open: the owner's review of those questions (Task 2.4 step 3), then the baseline (Task 2.5).

**Files:**
- Create: `mems_cli/eval_scoring.py`, `mems_cli/commands/eval.py`, `tests/fixtures/retrieval_corpus.json`, `tests/fixtures/retrieval_baseline.json` (after OP-1), `tests/test_eval.py`, `tests/test_retrieval_live.py`.
- Modify: `mems_cli/main.py` (register `eval`), `mems_cli/commands/search.py:56-89`, `mems_cli/common.py` (shared exit codes).

**Interfaces produced:**
```python
def normalize_hit(hit: dict) -> tuple[str, str]
    """(repo-relative path, text). Strips ^/repos/[^/]+/. Falls back to metadata.source_path and document."""
def served_files(hits: list[dict]) -> list[str]
def score_question(served: list[str], gold_groups: list[list[str]], chunk_paths: list[str]) -> dict
    """keys: ranks, hit1, recall3, recall5, rr, file_precision, chunk_precision"""
def aggregate(rows: list[dict]) -> dict
def compare(run: dict, base: dict, tol: float | None = None) -> dict
```

**Question set format:**
```json
{"version": 1,
 "wings": {"memory": {"repo_dir": "Memory"}},
 "questions": [{"id": "mem-01", "wing": "memory", "split": "dev",
   "style": "prose", "query": "...", "gold": ["src/sync_engine.py"], "basis": "..."}]}
```
- A `gold` item is either a string or a list of equivalent copies (any one counts).
- For user-wing questions, `gold` holds drawer ids.

### Task 2.1: Scoring functions

Behaviour:
- Gate on hit@1, MRR and recall@3, with tolerance `max(0.03, 1.5 / n_scored)`.
- Report chunk precision and p50/p95 latency without gating. Warn when p95 doubles.
- Only exact paths match, so a `.claude/worktrees/x/<gold>` copy never counts.

Tests:
- `test_normalize_hit_strips_container_prefix`
- `test_served_files_dedupes_in_first_seen_order`
- `test_worktree_copy_does_not_match_gold`
- `test_hit1_true_only_when_top_file_is_gold`
- `test_recall_at_k_divides_by_min_k_and_groups`
- `test_any_of_group_counts_once`
- `test_reciprocal_rank_zero_when_gold_absent`
- `test_chunk_precision_counts_chunks_not_files`
- `test_compare_one_flip_passes_two_flips_fail`

### Task 2.2: `mems eval` command

Flags: `--holdout`, `--wing`, `--n 10`, `--arg k=v` (repeatable), `--out`, `--compare`, `--update-baseline`, `--allow-drift`, `--json`.

Flow:
1. Load the question set.
2. Read each wing's SHA from `memory_sync_status`.
3. Precheck gold with `git -C $MEMS_CODE_ROOT/<repo_dir> cat-file -e <sha>:<path>`. `MEMS_CODE_ROOT` defaults to `~/Code`. Mark a question `stale` and exclude it if its gold isn't present at that SHA.
4. Call `mempalace_search`, or `mempalace_user_search` for user-wing questions.
5. Score, compare and print.

Exit codes: 0 pass, 1 regression, 2 server error, 3 SHA drift without `--allow-drift`. User-wing questions are reported and never gated.

Tests:
- `test_stale_question_excluded_from_means_and_counted`
- `test_compare_refuses_on_sha_drift_exit_3`
- `test_user_wing_questions_reported_not_gated`
- `test_cmd_eval_calls_search_with_extra_args` (the `_Factory` pattern, `tests/test_mems_commands.py:53`)
- `test_corpus_schema_valid`
- `test_corpus_gold_paths_exist_at_head` (skips if the repo is missing)
- `test_retrieval_live.py::test_no_regression_against_baseline` (skips unless `MEMS_EVAL_LIVE=1`)

### Task 2.3: Fix the search printer

`mems search` uses `normalize_hit`. Remove the dead `drawers`/`closets` key lookups. Move the `EXIT_*` constants into `mems_cli/common.py`; they are duplicated in `main.py`, `search.py` and `hybrid.py`.

Test: `test_search_human_output_shows_path_and_snippet`.

### Task 2.4: Question set

1. A script samples real `mempalace_search` query strings per wing from `~/.claude/projects/*/*.jsonl`. It reuses the transcript walker in `mems_cli/protocol_audit.py`. Only query strings leave the transcripts.
2. A drafting subagent with **no palace tools** reads the code with `git show <sha>:<path>` at the synced SHA. It writes the gold and a basis that cites line numbers.
3. The owner accepts, edits or drops each row. Expect 2–3 minutes per question.

Size and mix:
- 40 questions: edens-zac 12, edens-zac-backend 10, agent-orchestrator 8, memory 5, user 5 (report-only).
- Half identifier lists, half prose. At least 2 questions whose answer is a filename.
- 8 held out, split evenly across wings.
- Seed with the five drafted examples: `mem-01`, `ez-01`, `ezb-01`, `ezb-02`, `usr-01` (from the I2 review).

### Task 2.5: Baseline (after OP-1 and resync)

- [ ] `mems eval --update-baseline`, then commit `tests/fixtures/retrieval_baseline.json`.
- [ ] If the question set is ready before OP-1, also save `mems eval --allow-drift --out pre-op1.json` and quote the before/after in the OP-1 notes. This run is for information only, not a gate.

**Rot:** the stale "Phase 6/Phase 7" docblock and the inline comments in `mems_cli/main.py`.

---

## MR-3: `UserWing.search` scoping fix

**Status:** Done. Scoped user-wing search filters by `source_wing` inside Chroma.

**Files:** Modify `src/user_wing.py` (`search`, about `:268-335`). Test in `tests/test_user_wing.py`.

- [x] **Task 3.1. Check how unscoped entries are stored.** Is the `source_wing` key missing, or `""`? Look in a copy of the live palace, read-only.
- [x] **Task 3.2. Push the filter into Chroma.** When `source_wing` is set and `include_unscoped=False`, add `{"source_wing": source_wing}` to the Chroma `where`. When `include_unscoped=True`, run two queries (scoped, plus unscoped as stored per Task 3.1) and merge them by `effective_distance`. Hit fields stay the same.

Tests:
- `test_search_scoped_finds_minority_wing_entries`: 40 similar entries in wing A and 2 in wing B. A scoped search for B returns both B entries. This fails today.
- `test_search_scoped_with_unscoped_returns_both`
- `TestOrchCallsSkipPersonal` stays green, unchanged.

**Rot in `src/user_wing.py`:**
- The `prune` docblock claims similarity and cluster pruning. It only prunes by age, and filters on `timestamp`, not `last_seen`.
- `merge_topics` has a dead assignment, `remaining = merged`.
- `_find_duplicate_in_topic` duplicates `_find_duplicate`.

---

## MR-4: Hybrid search stage 1 (I3)

**Files:** Modify `src/tools.py` (`handle_search`, `handle_search_all`, module docblock `:3-56`) and `src/mcp_http_server.py` (`mempalace_search`, `mempalace_search_all`). Test in `tests/test_tools.py`.

**Interfaces:**
```python
def _looks_like_identifier(query: str) -> bool
def _candidate_strategy(query: str, requested: str = "auto") -> str   # "union" | "vector"
```
- `mempalace_search(..., candidate_strategy: str = "auto")` and the same on `mempalace_search_all`.
- Results gain `"retrieval": {"strategy": "union"|"vector"|"vector-fallback"}`. This is additive.

Tasks:
- [ ] **4.1.** Write `_looks_like_identifier`. True if any token has `_`, an inner capital, `.`, `::` or `/`. Also true if the query has at most 2 tokens and one is 3 or more characters. Otherwise false.
- [ ] **4.2.** Thread `candidate_strategy` through `handle_search` and `handle_search_all`. If the result has an `error` key, retry once with `vector` and report `vector-fallback`.
- [ ] **4.3.** Align the local `.venv` to mempalace 3.6.0 (spec item A4), so the integration test runs the same union code as the container.
- [ ] **4.4.** Run the eval three ways: `--arg candidate_strategy=vector`, `=union` and `=auto`. Ship only if all three hold:
  - `auto` beats `vector` on identifier questions (hit@1 and MRR).
  - Prose questions drop by no more than 0.03.
  - Scoped prose p95 stays within +100 ms of `vector`.

  Put the table in the MR description.

Tests:
- `test_looks_like_identifier_snake_camel_dotted`
- `test_looks_like_identifier_prose_false`
- `test_looks_like_identifier_short_tokens`
- `test_handle_search_passes_union_for_identifier`
- `test_handle_search_passes_vector_for_prose`
- `test_handle_search_all_uses_same_gate`
- `test_explicit_strategy_overrides_gate`
- `test_retrieval_field_reports_strategy`
- `test_union_error_falls_back_to_vector`
- `test_union_finds_vector_distant_identifier` (real Chroma; skip below 3.6)

**Rot:** check the `handle_search` docblock's "hybrid (drawers + closets)" claim against the code. Sync has created closets since MR-1 (1,090 on 2026-10-12). Closet-boosted hits used to repeat one chunk many times; `_search_distinct` in `src/tools.py` now drops the repeats (commit `fe3a678`).

**Follow-up, not in this MR:** file an upstream issue. `_lexical_search_via_sqlite` has no `ORDER BY rank`, and the filtered path has no `LIMIT`.

---

## MR-5: fs gate fixes and the shared resolver (I4 part 1)

**Status:** Done. The fs gate resolves the wing from target paths (worktrees and orch clones included), reads the subagent's own transcript, and makes at most one `git` call per run.

**Files:**
- Create: `integration/claude_code/repo_scope.py`, `tests/test_repo_scope.py`.
- Modify: `integration/claude_code/pretooluse_fs_gate.py`, `mems_cli/protocol_audit.py` (the shared classifier), `tests/test_pretooluse_fs_gate.py`, `tests/test_protocol_audit.py`.

**Interfaces produced** (stdlib only):
```python
def load_repo_roots() -> list[tuple[str, str]]          # (host_root, wing), longest first
def wing_for_path(path: str) -> str | None
def target_paths(tool_name: str, tool_input: dict, cwd: str) -> list[str]
```

**`repo_scope.py` behaviour:**
- `load_repo_roots` reads `$MEMORY_CONFIG_DIR/repos.json` (default `~/.config/mems/repos.json`). Owner question Q7 picks the single source.
- `wing_for_path` tries a prefix match first. It falls back to the basename of the parent of `git rev-parse --path-format=absolute --git-common-dir`, then to matching the origin URL, with a 1 s timeout. That covers `~/.cache/orch*` clones and `.claude/worktrees`.

**Gate changes, in `evaluate()` order:**
1. Return immediately if `MEMS_DIGEST` is set.
2. Collect the wings for every target path. If none has a wing, stay silent.
3. If the payload has `agent_id`, use `<transcript without .jsonl>/subagents/agent-<agent_id>.jsonl`. If the payload is from a subagent but that file is missing, stay silent.
4. Only `mempalace_search`, `mempalace_search_all` and `mempalace_user_search` reset the run. This also changes `classify_tool` for the audit; document it.
5. A Read of a file already edited or written in this session doesn't count toward the run.
6. Holdout: with `MEMPALACE_FS_GATE_HOLDOUT=<fraction>`, a session is held out when `int(sha1(session_id)[:8], 16) % 100 < fraction * 100`.
7. The reminder names the wing from the target path. It drops "has already indexed this repo" and shrinks to about 300 characters.

**Tests:**
- `test_repo_scope.py`:
  - `test_path_under_registered_root_maps_to_wing`
  - `test_path_outside_all_roots_is_none`
  - `test_worktree_resolves_via_git_common_dir`
  - `test_orch_style_clone_resolves_via_origin`
  - `test_missing_repos_json_returns_no_roots`
  - `test_bash_target_paths_ignore_dev_null_and_use_cwd_for_relative`
- `test_pretooluse_fs_gate.py`:
  - `test_silent_when_target_outside_any_wing`
  - `test_fires_when_one_of_several_targets_is_in_wing`
  - `test_subagent_payload_uses_subagent_transcript`
  - `test_subagent_payload_without_transcript_is_silent`
  - `test_only_search_tools_reset_run`
  - `test_read_of_already_edited_file_not_counted`
  - `test_holdout_session_is_silent_and_deterministic`
  - `test_reminder_names_wing_from_target_not_cwd`
  - `test_reminder_does_not_claim_indexed`
  - `test_digest_env_silences_gate`
- `test_protocol_audit.py`: update `test_mempalace_call_splits_runs` for the search-only reset.

**Step 0 (Q8):** settled. A real PreToolUse payload from a subagent, captured on 2026-10-12, carries `agent_id` and `agent_type`, and its `transcript_path` points at the parent session's transcript. Step 3's path rule is correct as written.

**Rot:**
- In `pretooluse_fs_gate.py`: the history-narrating module docblock (cut to 3 sentences), the inline comments, and `LS` and `NotebookRead` in `FS_TOOLS`. Those two never reach the hook because the matcher is `Bash|Grep|Glob|Read`.
- In `pretooluse_agent_orientation.py`: the docblock names a `mems setup install-hooks` command that doesn't exist. Add `claude` to `GATED_SUBAGENT_TYPES`.

---

## MR-6: Efficacy report (I4 part 2)

Start after MR-5 has run with `MEMPALACE_FS_GATE_HOLDOUT=0.2` for two weeks.

**Files:** Modify `mems_cli/protocol_audit.py` and `mems_cli/commands/palace_ops.py`. Create `tests/test_protocol_efficacy.py`.

**Interfaces:**
```python
def iter_firings(path: Path) -> Iterator[dict]   # hook_success attachments whose command contains pretooluse_fs_gate
def follow_through(calls: list[dict], i: int, windows=(5, 10, 40)) -> dict
def efficacy(projects_dir: Path, days: int) -> dict
```

**Report:**
- Groups are main/sub × fired/holdout/no-fire × first/later × in-wing/no-wing.
- Each group shows n, the search rate per window, and the rate at which a hit was used within 20 calls. `/repos/<dir>` maps to the host root.
- Subagent transcripts are included (`*/*/subagents/*.jsonl`) and labelled.
- It also shows orientation blocks and the retry outcomes.
- CLI: `mems doctor --protocol --efficacy [--json]`.

**Tests:**
- `test_firing_followed_by_search_within_window`
- `test_firing_without_search_counts_as_not_followed`
- `test_firing_dedupe_counts_hook_success_only`
- `test_holdout_virtual_triggers_form_base_rate`
- `test_hit_used_when_later_read_matches_source_path`
- `test_subagent_transcripts_included_and_labelled`
- `test_orientation_block_retry_classification`

**Rot:** `_iter_tool_calls` duplicates the gate's version, and `gate_mode()` duplicates `_mode()`. Share one of each. The `analyze_session` docblock describes a "covered" check the code doesn't make.

**Decision rule at the end:**
- If fired in-wing searches don't beat the holdout base rate by at least 5 points within 10 calls, soften the gate to fire once per session.
- If hits are used no more often than after voluntary searches, report that plainly.

---

## MR-7: SessionStart brief (I5)

**Files:**
- Create: `src/brief.py`, `integration/claude_code/sessionstart_brief.py`, `tests/test_brief.py`, `tests/test_sessionstart_brief.py`.
- Modify: `src/mcp_http_server.py` (the `/brief` route), `integration/claude_code/hooks_install.py` (a 5th entry, plus the docblock), `scripts/install_claude_code.sh` (`HOOK_SESSIONSTART_CMD`), `src/user_wing.py` (`status()` guidance string), and both specs.
- Test: `tests/test_mcp_server.py`, `tests/test_install_claude_code.py`.

**Interfaces:**
```python
def render_brief(user_wing, repos_config: dict, repo: str, branch: str, head: str,
                 q: str, recent=None) -> dict   # {"text": str, "ids": list[str], "wing": str | None}
def resolve_wing(repo: str, repos_config: dict) -> str | None   # match Path(entry["path"]).name == repo
```
`GET /brief?repo=&branch=&head=&q=` returns that dict as JSON. It runs through `anyio.to_thread.run_sync`.

**Brief sections:**
- Each section has its own character budget. A line that doesn't fit is skipped, not cut off mid-section. Items are capped at 160 characters.
- B, open ideas: `recent(days=14, scoped, status="open", no personal, n=5)`, 450 characters.
- C, related to this branch: `search(q, scoped plus unscoped, no personal, n=3)`, keeping only hits with `distance <= 0.50` that aren't already in B. 300 characters.
- A (recent sessions) and D (clusters) are added later by the 2026-10-01 spec's phase 3 and by C5.
- When every section is empty, the text is `""`, with no header.

**Hook steps:**
1. Return silently if `MEMS_DIGEST` is set, the `CLAUDE_CODE_ENTRYPOINT` starts with `sdk`, or `agent_type` is present.
2. Get the repo from `repo_scope`. Run `git status --porcelain --branch`. If the branch isn't main or master, also run `git diff --name-only main...HEAD`. Cap at 30 files, with a 1 s timeout per git call.
3. Build `working_terms`: drop generic, short and digit-only tokens, and cap at 20.
4. `GET /brief` with a 1.5 s timeout.
5. Print `hookSpecificOutput.additionalContext` only when the text is non-empty.
6. Append a line to `~/.mempalace/hook_state/brief.jsonl` for MR-6.

The matcher is `startup|clear` and the settings timeout is 5.

**Tests:**
- `test_brief.py`:
  - `test_empty_when_wing_has_nothing`
  - `test_unknown_repo_returns_empty`
  - `test_resolve_wing_by_path_basename`
  - `test_open_ideas_scoped_excludes_unscoped_personal_and_old`
  - `test_related_respects_floor`
  - `test_related_skips_ids_in_open_ideas`
  - `test_section_budgets_independent`
  - `test_long_item_skipped_not_truncating_section`
  - `test_header_has_branch_and_head_and_reference_label`
  - `test_ids_returned_match_rendered_items`
- `test_mcp_server.py`:
  - `test_brief_route_returns_json`
  - `test_brief_route_unknown_repo_empty`
  - `test_brief_route_runs_in_thread`
- `test_sessionstart_brief.py`:
  - `test_branch_tokens_drop_generic_short_numeric` (`docs/next-2026-10-02` gives `["next"]`)
  - `test_file_terms_from_porcelain_handles_rename_and_untracked_dir`
  - `test_skips_on_mems_digest`
  - `test_skips_on_sdk_entrypoint`
  - `test_skips_on_agent_type`
  - `test_not_git_repo_silent`
  - `test_server_down_silent_exit0`
  - `test_slow_server_times_out_silent`
  - `test_empty_brief_prints_nothing`
  - `test_emits_additional_context_json`
  - `test_writes_ledger_line`
- `test_install_claude_code.py`:
  - `test_installs_sessionstart_brief_idempotent`
  - `test_coexists_with_handoff_clear_entry`

**Spec edits in the same MR:**
- `2026-10-01-short-term-context-design.md`:
  - Section 5: rename the hook to `sessionstart_brief.py`, add section C, and the silence rule.
  - Section 1: drop `host_path` and use `repo_scope`.
  - Phase 6: split into 6a (now) and 6b (needs phase 3).
  - Decision #2: cover `compact` and `fork`.
- `2026-10-02-user-wing-ideas-design.md`: B5b becomes part of 6a and is no longer blocked on B1.

**Owner edit, not done by an agent:** CLAUDE.md Hard Rule #4 becomes "If the session opened with a Memory palace brief, cite or dismiss it. Call `mempalace_user_summary` only when no brief appeared and the task needs global context." (Q5).

**Rot:** `hooks_install.py`'s "Adds four entries" docblock and inline comment. The `guess_wing` in `pretooluse_fs_gate.py` is replaced by `repo_scope` in MR-5.

---

## Deferred

| Item | Revisit when |
|---|---|
| I3 stage 2: own FTS5 leg, filename leg, RRF | MR-4's eval still misses identifier or filename questions that a rank-sorted FTS query finds |
| I6: `paths` field on user-wing writes | MR-7 is live and the owner wants "decisions about files I'm touching". Fill it from orch and the Phase B sweeper only, and never show a staleness label. |
| Retag 30 user-wing entries with mismatched `source_wing` (`lightroom-portfolio-export`, `edens.zac`, `edens.zac.backend`) | Any time. Take a snapshot first and do a dry run. |
| Delete `/data/palace.backup` (June, 612 MB) and `/data/palace.pre-rebuild-20260623-000314` | After OP-1 is verified |
| Upstream issue for the lexical search's missing `ORDER BY rank` and `LIMIT` | With MR-4 |
| Remove the stale worktree `.claude/worktrees/text-component-padding-cd1216` | Check who created it first |

## Open questions for the owner

| # | Question | Recommendation | Blocks |
|---|---|---|---|
| Q1 | Reconcile sync (D3), or keep a git diff plus a prune on every sync? | Reconcile, gated by the Task 1.4 timing | MR-1 |
| Q2 | Is a 15–20 minute downtime for OP-1 OK, including the index rebuild? | Yes. It frees about 1.2 GB and fixes search scores. | OP-1 |
| Q3 | Should sync run on a schedule? Wings have been stale for 3–16 weeks. | Yes. A launchd job runs `mems sync` every 30 min. Add it as Task 1.7 if approved. | MR-1 scope |
| Q4 | Run a 20% fs-gate holdout for two weeks, even though CLAUDE.md mandates the protocol? Only the reminder is withheld; the rule stays. | Yes | MR-6 |
| Q5 | Change CLAUDE.md Rule #4 once the brief ships? | Yes, with the wording above | MR-7 |
| Q6 | Turn on a data-file size cap? At 256 KB it drops about 1.5k drawers of `running` JSON. | Leave it off | MR-1 |
| Q7 | Which file is the one host-side repo list the hooks read: `~/.config/mems/repos.json`, or `config/repos.json` with `host_path`? | `~/.config/mems/repos.json`. It already holds host paths. | MR-5 |
| Q8 | Does a subagent's PreToolUse payload carry `agent_id`? | Settled on 2026-10-12 from a real capture. It carries `agent_id` and `agent_type`. `transcript_path` points at the parent session's transcript. The subagent's transcript is `<session transcript without .jsonl>/subagents/agent-<agent_id>.jsonl`, which `integration/claude_code/pretooluse_fs_gate.py` already derives. | none |
| Q9 | Index repos at their checked-out branch, or always at the default branch? | Checked-out branch, as today | none |
| Q10 | Should `mempalace_search_all` leave out personal user-wing entries? It returns them today. | Yes, as a small add to MR-4 | MR-4 |

## Coverage check

| Source item | Covered by | Notes |
|---|---|---|
| B1: untracked and gitignored files indexed | MR-1 Tasks 1.1, 1.2, 1.6; OP-1 | Keep list widened per D1 |
| B2: silent prune | MR-1 Tasks 1.2, 1.5 | Upstream call removed (D2) |
| B3: renames dropped | MR-1 Tasks 1.3, 1.4 | Reconcile; the git-diff fallback was not needed |
| B3 extra: incremental skips filters, unreachable SHA | MR-1 Tasks 1.1, 1.3 | Fixed by reconcile |
| Review idea 1: fix sync scope | MR-1 | Same as B1–B3 |
| Idea 2 / I2: `mems eval` | MR-2 | Live palace pinned to synced SHAs |
| Idea 3 / I3: hybrid search | MR-4 | Stage 1 only (D7) |
| Idea 4 / I4: hook efficacy and silence outside synced repos | MR-5, MR-6 | The gate stays (D10) |
| Idea 5 / I5: SessionStart push | MR-3, MR-7 | Amends existing specs (D11) |
| Idea 6 / I6: decision paths and staleness | Deferred | Dropped as its own MR (D8, F14) |
| F9: sync blocks the event loop | MR-1 Task 1.5 | Found during review |
| F10: `mems search` printer | MR-2 Task 2.3 | Found during review |
| F12: scoped user search | MR-3 | Found during review; affects orch |
| F15: embedding model not baked | MR-0 | Found during review |
| Q3: scheduled sync | Not yet planned | Needs an owner answer |
