# Repowise review: what mems should take

**Date:** 2026-10-12
**Subject:** [repowise-dev/repowise](https://github.com/repowise-dev/repowise), AGPL-3.0. Ideas only. No code is copied.
**Prior review:** graphify, 2026-08-21 (user wing topics `graphify-borrow-list`, `mems-gaps-exposed-2026-08-21`).

## Verdict

Repowise is a code-intelligence tool, not a memory tool. It has a call graph across 26 languages, git-history mining, code-health scoring and a decisions layer, all served over MCP. Most of it is too large for our needs, or doesn't apply to a solo developer. Its value to us comes from how carefully it measures itself. Several of its findings apply directly to mems, and reading it closely turned up three bugs in our own sync.

## Bugs found in mems during this review (verified)

1. **72% of the palace is gitignored output.** 152,703 of about 211,000 drawers come from `lightroom-portfolio-export/scripts/output/`. That folder is in `.gitignore`, and the repo tracks only 35 files. The 2026-06-23 `full_sync` mined the working tree through `scan_project`, not through `git ls-files`. This is most of the "80% of drawers in `general`" problem: the cause is what we index, not the room keywords.
2. **The prune fails silently.** `src/sync_engine.py:211-218` runs `mempalace sync --apply` with `check=False` and throws away its output. A failed prune leaves no trace.
3. **Renames are dropped.** `get_changed_files` (`src/sync_engine.py:65-86`) has no branch for `R` or `C` status lines. A renamed file's new path is never indexed, and the old path's drawers stay.

Also: the `agent-orchestrator` wing is 100% `general` because it has no taxonomy entry. `running` is 49% `general`.

## Ranked ideas

### Tier 1: do first (small, high value)

| # | Idea | Repowise evidence | Lands in | Size |
|---|---|---|---|---|
| 1 | Sync only `git ls-files`. Prune drawers whose source isn't tracked. Report prune failures. Handle `R`/`C` lines. Count modified files in `files_indexed`. | `core/pipeline/incremental.py:262-268` | `src/sync_engine.py` | S |
| 2 | `mems eval`: 30–50 questions with correct files labelled by hand. Score hit@1, recall@5, MRR and precision. Commit a baseline and fail on any drop over 0.03. Hold out 20% of the questions until tuning is done. | `tests/unit/server/mcp/test_retrieval_guard.py:1-75` | `tests/fixtures/retrieval_corpus.json`, `mems_cli/commands/eval.py` | S |
| 3 | Hybrid search. First pass: send `candidate_strategy="union"` to upstream. Later: merge the vector, BM25 and filename results by rank (RRF, k=60) and report which ones ran. | `mcp/_answer_pipeline.py:96-110, 147-200, 340-412` | `src/tools.py` `handle_search` | S, then M |

Do #2 before or alongside #3. Without it, we can't tell whether hybrid search helped.

### Tier 2: change how agents get context

| # | Idea | Repowise evidence | Lands in | Size |
|---|---|---|---|---|
| 4 | Measure whether a hook changes what the agent does in its next ~40 calls, compared with a base rate. Make the fs gate silent for paths outside synced repos. Repowise measured its own nudges at 11.4% follow-through against an 11.9% base rate and deleted them. It also removed every PreToolUse context hook as noise. | `core/sessions/efficacy.py:1-81`; `augment_cmd/command.py:83-87` | `mems_cli/protocol_audit.py`, `integration/claude_code/pretooluse_fs_gate.py` | S–M |
| 5 | SessionStart hook that pushes user-wing entries ranked against the session's dirty files, branch name and wing. 400-token cap, relevance floor, and nothing at all when nothing clears the floor. It also covers a brief after compaction. | `augment_cmd/decision_inject.py:1-84`; `session_start.py:49-123` | New `integration/claude_code/sessionstart_context.py`; relevance mode on `UserWing.summary` | M |
| 6 | Lean search responses. Dedupe identical text, drop diagnostic fields by default, cap total characters, and add `retrieval_quality` computed from the gap between the top hit and the second. | `mcp/_meta.py:43-63`; `tool_answer/confidence.py:485-496` | `src/tools.py` | S–M |
| 7 | Rescue after a zero-result Grep/Glob by appending the top palace hit. Repowise measured a 44% action rate, its best. On a not-found path, name the single indexed file with that basename. | `augment_cmd/search.py:46-61`; `efficacy.py:43-48` | New PostToolUse hook | M |
| 8 | Stale-index warning only when a file this response served has changed since sync. | `mcp/_meta.py:447-580` | `src/tools.py` + sync ledger | S–M |
| 9 | Advertise a default set of tools and make the rest opt-in. We advertise all 34. Repowise registers 18, advertises 10, and has a 6-tool lean profile. | `_tool_selection.py:1-15` | `src/mcp_http_server.py` | S |

### Tier 3: tie memory to code

| # | Idea | Repowise evidence | Lands in | Size |
|---|---|---|---|---|
| 10 | A `paths` field on user-wing decisions. Staleness is the fraction of those files committed since the entry, computed on read and never stored. The Phase B sweeper fills `paths` from the Edit/Write calls near each mined quote. | `analysis/decisions/staleness.py:31-67`; `lifecycle.py:271-305` | `src/user_wing.py` write + `_format_entry` | M |
| 11 | One deterministic file-card drawer per file: path, symbols, imports, importers, co-change partners, identifier list. | `generation/templates/file_page.j2:40-229` | New `src/file_cards.py` | M |
| 12 | Regex import edges for Python, TS, Java and Go, stored as KG triples with origin and confidence. Search expands 1 hop (hub cutoff, 0.7 damping, at most 3 added). This is the first producer for our empty KG, and it makes `mempalace_traverse` a real graph walk. | `ingestion/lightweight_imports/`; `_answer_pipeline.py:898-1010` | New `src/import_graph.py` | M |
| 13 | HTTP route matching to create tunnels. Spring and Go handlers in the two backends are matched to `fetch`/axios callers in edens-zac. These are the first real tunnels, which makes Hard Rule #2 return something. | `workspace/extractors/http/`; `workspace/matching/http.py:23-272` | New `src/contracts.py` → `mempalace_create_tunnel` | M |
| 14 | Fallback rooms from directory structure, bounded in size and stable across commits. This fixes agent-orchestrator and running. | `generation/concept_tree/grouping.py:1-104` | Synthetic rooms fed to upstream `detect_room` | M |
| 15 | `mems doctor --docs` (path references that resolve to nothing) and `--orphans` (drawers whose source file is gone). A 40-line prototype found 54 dead path references, including real broken links in `docs/protocol-audit-tracker.md:3` and `README.md:146`. | `analysis/doc_drift/resolver.py:323-333` | `mems_cli/commands/palace_ops.py` | S |

## What not to take

- **Savings ledger.** It estimates tokens "saved" from guessed costs, such as 400 tokens per search hit. Their own data shows an MCP call came before about 1% of edits.
- **LLM-written wiki**, the 39-type call resolver (still about 14% wrong), and the stacked ranking tweaks tuned to their own question set.
- **Session-decision mining as shipped.** Repowise turned it off: 139 records, none with context. Take only its rules: verbatim quote checks, file lists limited to files actually touched, and promotion after 2 sessions.
- **Similarity-based supersession.** Repowise disabled it because entries from one repo all look alike. This is a warning for Phase C clustering thresholds: measure the baseline distance between unrelated entries first.
- **Inline `WHY:` markers.** They conflict with our no-inline-comments rule.
- **Change risk, ownership, bus factor, bug history.** These are team code intelligence, not memory.
- **Distill** (rewrites the agent's shell commands, auto-allowed by default) and **Lens** (UI mod).

## Claims to discount

- **"−31.6% agent output":** counts only the agent's own output tokens. `get_answer` writes its answer with a hosted model whose tokens aren't counted. Answer quality didn't change. One repo (django). On reruns, Claude Code called the tool 3–4 times out of 15. The table says 44/44 against n=43.
- **"0.876 retrieval coverage":** measured without a fixed result count. It served 19.2 files against a competitor's 14.0.
- **"58,924 files in 120 min":** run with a stand-in embedder. A one-file commit still takes 469 s to update. Our per-changed-file sync is the better model.
- **The call-graph precision method is sound:** graded against compiler output, with losses published.

## Overlap with the graphify borrow list

Graphify item 1 (tiered, staleness-aware hooks) is still right. Repowise adds evidence for it: measure the hook's effect, and stay silent when there's nothing to add. Item 8 (learning sidecar) is the same idea as repowise's follow/contradict check, which we should defer until decisions carry paths. The synthesis "embeddings for entry, graph for expansion" holds. Tier 3 #12 is the cheapest version of the graph part.
