# Short-term context: per-repo recent-session briefs

Status: draft for review (2026-10-01). Not yet approved for planning.

Companion spec: `2026-10-02-user-wing-ideas-design.md`. Its Phase B extends this sweeper to pull ideas out of the user's prompts and write them, with the digest's open items, to the user wing. Its Phase C adds idea clusters to the SessionStart brief.

## Summary

After each human Claude Code session goes idle, a background job on the host reduces the transcript to its useful text. Haiku writes a 3–6 line digest from that text, and the job stores the digest in a new palace wing, `recent`, tagged with the repo. When a new session starts, a SessionStart hook prints the last 5 digests for that session's repo. Any repo's digests can be read on demand through an MCP tool and `mems recent <repo>`.

Expected load is about 3 sessions a day at about 8k input tokens each. On the subscription this is negligible.

## What the user asked for

- A "what we've been working on recently" brief covering the last N sessions.
- A cheap summarizer. Haiku is confirmed.
- Scoped per repo, so a new session gets its own repo's brief automatically.
- Other repos' briefs queryable when needed.

## Facts that shape the design

From the research pass on 2026-10-01:

| Fact | Consequence |
|---|---|
| All SessionEnd hooks share a 1.5 s budget and block shutdown. | The Haiku call cannot run inside SessionEnd. |
| Desktop-app sessions often never "end". They sit idle or get resumed days later. | A hook-driven trigger misses sessions. A sweeper that looks for idle transcripts catches them all. |
| `claude -p --bare` skips hooks, MCP and CLAUDE.md, but needs `ANTHROPIC_API_KEY`. It cannot use the subscription login. | The summarizer runs non-bare and needs its own recursion guards (see Recursion). |
| Every transcript record has `cwd`, `gitBranch`, `timestamp` and `entrypoint`. | Repo, branch and time come straight from the JSONL. No folder-name decoding. |
| `entrypoint` is `claude-desktop` for human sessions, and `sdk-py` or `sdk-cli` for orchestrator and `claude -p` runs. | Filtering out `sdk-*` drops automated sessions and the summarizer's own runs. |
| Subagent transcripts live in `<session>/subagents/**.jsonl` with `isSidechain: true`. | Reading only top-level `*.jsonl` excludes them. |
| Useful text (user prompts + assistant text) is under 1% of transcript bytes. p50 is 6.5k tokens and p90 16k for real sessions. | Extract before summarizing. Cap at 30k tokens, keeping head and tail. |
| 67% of sessions have fewer than 3 prompts. | Skip when there are fewer than 3 prompts and under 1k useful tokens. |
| `claude_imports` drawers carry no repo, cwd, branch or real timestamp. | Read raw JSONL, not the existing palace imports. |
| Upstream `diary_write` and `diary_read` store timestamped entries per wing, but use `add` (not upsert), naive local time, and no structured fields. | Not a good fit. See Rejected alternatives. |
| `UserWing` dedup merges entries whose text is similar. `summary()` reads `limit=5` with no ordering. Phase A of the companion spec fixes both. | `recent` copies the class pattern, but uses session-id keys and sorts by time explicitly. |
| `guess_wing` in `pretooluse_fs_gate.py` slugs the cwd basename, so worktrees resolve to the wrong wing. | We need a real resolver based on `git --git-common-dir`. |

## Design

### 1. Sweeper (host, launchd, every 15 min)

`mems recent sweep` runs on the host because it needs the `claude` CLI and the subscription login, which the Docker container doesn't have.

1. List top-level `~/.claude/projects/*/*.jsonl` modified in the last 7 days.
2. Skip a transcript if any of these hold:
   - it was modified less than 30 min ago (the session may still be active)
   - its `mtime` is unchanged since the last digest (tracked in a state file, `~/.mempalace/recent-state.json`)
   - the first record's `entrypoint` starts with `sdk`
   - `cwd` is under `/private/tmp` or `/private/var`
   - it fails the triviality rule
3. Resolve the repo wing, extract, summarize and store. Advance the state file only after the store succeeds. If the server is down, the next run retries.

A resumed session keeps its session id. When it grows, the sweeper re-digests it and replaces the old entry. The state file also records the uuid of the last prompt already used for ideas, so a re-digest extracts ideas only from new prompts.

The `sdk-*` filter means orch's work never reaches this sweeper. orch writes its answers and outcomes back to the user wing on its own, through MCP (companion spec, Phase B).

### 2. Extractor (pure Python, no LLM)

Input is one JSONL file. The output has two parts.

Mechanical facts, which Haiku never invents:
- session id
- repo wing and cwd
- branches seen
- start and end time
- files edited (`file_path` of Edit/Write tool uses)
- commits (`git commit` Bash calls with their exit status)
- PR links (`pr-link` records)
- session title (`custom-title`, else `ai-title`)

The text sent to Haiku is the user prompts (excluding `isMeta` and tool results) plus assistant text blocks (excluding thinking and tool input). Each block is labelled `[user]` or `[assistant]`, so Haiku can take ideas from user text only. It is capped at 30k tokens. User prompts are kept whole, and assistant text is trimmed first, keeping its first 20% and last 80%. Obvious secrets are redacted by regex first: `sk-…`, `ghp_…`, AWS keys, and `KEY=value` lines.

### 3. Summarizer

```
MEMS_DIGEST=1 claude -p --model haiku \
  --no-session-persistence \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --tools "" --max-turns 1 --output-format json
```

The prompt asks for JSON only:

```
{"did": [<=3 short lines], "state": "<one line>", "open": [<=2], "next": "<one line or empty>",
 "ideas": [<=5 {"text", "kind", "personal", "topic", "quote"}]}
```

The rules are plain lines, no adjectives, and no secrets. The transcript is passed as quoted data, not as instructions. Malformed output is retried once, then skipped and logged.

`ideas` comes only from `[user]` blocks. Each idea's `quote` must appear in the user prompt text, or the sweeper drops it. The companion spec's Phase B defines the fields and rules.

### 4. Store: `recent` wing

`src/recent_wing.py` follows the `UserWing` pattern, in the same Chroma collection with `wing="recent"`. The document text is the rendered digest, so it is semantically searchable.

- ID: `recent-<session_id>`, written with upsert.
- Metadata: `repo_wing`, `session_id`, `cwd`, `branch`, `started_at`, `ended_at` (UTC ISO), `title`, `files_n`, `commits` (joined string), `pr`.
- Retention: on each write, keep the newest 10 per `repo_wing` and drop anything older than 30 days.

Exposed by the MCP server:
- `mempalace_recent(wing=None, n=5, days=None)` is a read tool. With no wing, it returns the newest across all repos.
- `POST /recent` is internal and used by the sweeper. Its body carries the digest, the extracted ideas and the open items. The server stores the digest here and writes the ideas and open items to the user wing with origin `prompt` and status `open`, in a worker thread.
- `GET /recent?wing=&n=` is a plain HTTP endpoint next to `/health` that returns raw digests.
- `GET /brief?wing=` renders the SessionStart block (section 5) on the server, so the hook can read it with `curl` without speaking MCP.

The digest itself never goes to the user wing. Its open items and the extracted ideas do, because those are the ideas that get lost today. A digest is pruned after 30 days. An idea has to stay until the user marks it done.

### 5. Injection: SessionStart hook

`integration/claude_code/sessionstart_recent.py` runs with matcher `startup|clear`.

- If `agent_type` is present (a subagent) or `MEMS_DIGEST` is set, it does nothing.
- It resolves the repo wing from `cwd` and calls `GET /brief?wing=<w>` with a 2 s timeout. Any failure prints nothing, and it always exits 0.
- Output goes through `additionalContext`. The whole block stays under about 400 tokens. It holds the last 5 digests, then up to 5 open ideas for this repo touched in the last 14 days, then (once the companion spec's Phase C ships) the base statements of the 3 most active idea clusters. Personal entries are left out. Over budget, clusters are cut first, then ideas.

```
Recent sessions in edens-zac (reference data, may be stale; current branch: X @ abc123):
- 2026-09-30, branch feat/foo, PR 231: did …; open: …; next: …
- …
Open ideas in edens-zac, last 14 days:
- [goal] … (2026-09-29, seen 3 times)
Active idea clusters:
- c-3f2a91c0d4e2 <label>: <base statement> (last touched 2026-10-01)
Other repos: mempalace_recent(wing=...) or `mems recent <repo>`. All ideas: `mems ideas`.
```

On `clear`, the existing `handoff-inject.sh` still runs. The two hooks don't conflict. The handoff is deliberate and one-shot, while the brief is automatic and rolling.

### 6. Repo resolver (shared)

`src/repo_resolve.py`, used by the sweeper, the SessionStart hook and later by `pretooluse_fs_gate.guess_wing`:

1. Run `git -C <cwd> rev-parse --path-format=absolute --git-common-dir`. Take the parent dir's basename. This handles `.claude/worktrees/*` and `~/.orch-worktrees/*`.
2. Map the basename to a wing using a host-path table. Add a `host_path` field to `config/repos.json` entries so there is one source of truth instead of the separate override file.
3. Fallback: match `git remote get-url origin` against the table (this covers `~/.cache/orch-*` clones). Otherwise return `None` and skip the session.

### 7. CLI

- `mems recent [repo] [-n 5] [--all]` prints digests.
- `mems recent sweep [--since 7d] [--dry-run]` is what launchd runs. `--since 30d` doubles as a rebuild.
- `mems standup` gains a "Recent sessions" section.

### Recursion

The summarizer is itself a Claude Code session. Three independent guards stop it from summarizing itself or triggering the palace hooks:

1. `--no-session-persistence` means no transcript is written for the sweeper to find.
2. Even if a transcript is written, its `entrypoint` is `sdk-cli`, and the sweeper filters that out.
3. `MEMS_DIGEST=1` is checked first by our hooks (`pretooluse_fs_gate.py`, `pretooluse_agent_orientation.py`, `sessionstart_recent.py`). The upstream `mempal_save_hook.sh` sees no transcript to mine.

Phase 0 must confirm guards 1 and 3 on the real CLI.

## Critical review

| Risk | Assessment and mitigation |
|---|---|
| A stale or wrong brief misleads the agent. | This is the main risk. Facts like branch, commits, PR and files are extracted mechanically. Haiku writes only the "did / open / next" lines. The brief is labelled reference data with dates and the current HEAD, matching how `handoff-inject.sh` frames its text. |
| Overlap with `user_summary` and the handoff. | Each answers a different question. `wing_user` holds durable thoughts, decisions and open ideas. `recent` holds what happened in the last few sessions. The handoff is a one-shot note the user chooses to write. Digests stay in `recent`. Only their open items and the extracted ideas go to `wing_user`, where dedup bumps an existing entry instead of copying it. |
| Context cost on every session start. | Capped at about 400 tokens. Skipped for subagents and for repos with no digests. |
| Prompt injection from transcript text. | Haiku runs with no tools and one turn, and its output is restricted to a fixed JSON schema. The worst case is a misleading digest, which the framing already covers. |
| Secrets in transcripts. | They already go to Anthropic in the original session. Regex redaction runs before the Haiku call. Digests are stored in the local palace only. |
| Orchestrator noise (75 sessions a month, mostly SDK). | Filtered by `entrypoint`. Human orchestrator sessions still get digests. orch's own results reach the palace through its MCP write-back instead. |
| The sweeper fails silently (launchd not loaded, server down). | `mems doctor` checks the launchd job is loaded, reports the age of the last successful run from the state file, and shows the count of digests from the last 7 days. |
| Losing the wing. | Digests can be rebuilt from transcripts with `mems recent sweep --since 30d`, as long as Claude Code keeps transcripts (30 days by default). No snapshot or restore needed. |
| Brief lag. | The newest session shows up 30–45 min after going idle. Acceptable. The handoff covers "I'm about to /clear and continue". |
| The transcript format is internal and may change. | The extractor reads only a few stable fields and tolerates unknown record types. A fixture test catches breakage on upgrade. |

## Rejected alternatives

- **Trigger from SessionEnd or Stop.** The 1.5 s budget is too short, desktop sessions never end, and Stop fires every turn. The sweeper is simpler and complete.
- **Upstream diary tools.** They can't upsert (a resumed session would duplicate its digest), use naive local timestamps, and split long entries into chunks. Adapting them means patching upstream.
- **Plain files under `~/.mempalace/recent/`.** Faster to read, but not searchable, and a second store would sit beside the palace. Rejected, though it is the fallback if the HTTP read proves slow.
- **Storing digests in `wing_user`.** Different lifecycle: rolling and pruned versus durable and deduped. Mixing them would corrupt `user_summary`. Open items and extracted ideas are the exception, and they go in as separate entries.
- **Ollama or no-LLM extraction.** The user chose Haiku.

## Build order

| Phase | Work | Depends on |
|---|---|---|
| 0 | Spike (throwaway): run the summarizer command on the subscription. Confirm no transcript is written, no user hooks fire with `MEMS_DIGEST=1`, `--tools ""` is accepted, and record latency. Confirm `additionalContext` renders in the desktop app. | — |
| 1 | `repo_resolve.py` + `host_path` in `config/repos.json` + tests. | — |
| 2 | Extractor + redaction + fixture tests. | — |
| 3 | `RecentWing`, MCP tool, `GET`/`POST /recent`, retention + tests. | — |
| 4 | Summarizer wrapper + prompt + schema check. | 0 |
| 5 | `mems recent` and `mems recent sweep`, state file, launchd plist, `doctor` check. | 1–4 |
| 6 | SessionStart hook + `hooks_install.py` entry + `MEMS_DIGEST` guard in existing hooks. | 1, 3 |
| 7 | Docs: README, CONTEXT.md, one line in the CLAUDE.md protocol, `standup` section. | 5, 6 |

Phases 1, 2 and 3 are independent and can run as parallel subagents.

The companion spec's Phase B extends phases 2, 3, 4 and 6 here (labels and prompt handling in the extractor, `ideas` in the schema, user-wing writes from `POST /recent`, `GET /brief`). Its build order table lists those steps and their dependencies.

## Found during research, out of scope

- Two palaces. The Stop hook mines into the host palace (`~/.mempalace/palace`, `wing_api` with 252k drawers), which the MCP server never reads. Session mining is invisible to search.
- Docs say the backup is named `wing_user_backup.YYYYMMDD.json` and live in a `wing_user_backups/` dir. The real name uses `_` and there is no such dir. Affects `restore_wing_user.py:10` and `README.md:177`.
- `wing_user_snapshot.main()` and `restore_wing_user.main()` defaults disagree with `entrypoint.sh` (paths and env var names).

## Decisions for the user

1. Retention and injection counts: keep 10 per repo and 30 days, inject 5. Change?
2. Inject on `resume` too? Proposed: no, because a resumed session already has its history.
3. Read via a new `GET /brief` HTTP endpoint rendered on the server (proposed), or have the hook speak MCP?
4. Fold the `guess_wing` fix into phase 1 (proposed), or leave the fs-gate alone?
