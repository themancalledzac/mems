# User wing: recency, idea capture and the idea tree

Status: draft for review (2026-10-02). Phase A is being built on `feat/user-wing-recency`. Phases B and C are not yet approved for planning.

Companion spec: `2026-10-01-short-term-context-design.md` (the `recent` wing, the sweeper and the SessionStart brief). Phase B extends that sweeper. The two specs have been edited to agree.

## Summary

The user wing stops losing ideas in three phases.

- Phase A makes the user wing favor recent entries. It adds `last_seen`, `seen_count`, `origin`, `status` and `personal` metadata, stops dedup from overwriting text, adds recency weighting to search, and adds `mempalace_user_recent` and `mempalace_user_set_status`. orch's context plan depends on it.
- Phase B captures ideas without relying on agents. The short-term sweeper already reads every human session. Its Haiku call also pulls ideas out of the user's own prompts and writes them to the user wing with status `open`. orch writes its answers and outcomes back on its own.
- Phase C groups ideas into a tree. A SQLite file in the palace volume holds clusters, their members and a 2–3 line "base statement" per cluster that Haiku keeps current. New entries join the nearest cluster on write. A nightly pass nests close clusters under larger ones, which is how the tree grows. The user sees open ideas and active clusters at session start and in `mems ideas`.

## What the user asked for

- "I type a lot of ideas, and often they get lost or otherwise overwritten or backlogged and never seen again."
- User context handed to any agent should favor what was said recently.
- "A structure of sorts where maybe we have Ideas, similar ideas being categorized as similar or otherwise creating a 'base model' as our idea tree grows."
- It has to work across many agents, including orch, which runs Claude jobs headlessly through the SDK.

## The problem, measured on 2026-10-01

Live store figures, out of 3,184 user entries:

| Fact | Effect |
|---|---|
| `summary()` calls `get(limit=5)` with no ordering. | It returns the oldest entries. The goals sample was all from 2026-04-16 and 2026-04-18. |
| `status().recent_topics` takes the first 10 entries per hall and sorts them alphabetically. | "Recent topics" are neither recent nor ordered by time. |
| 2,592 distinct topics. 2,383 are used once. There are 62 variants of "mems/mempalace". | Topic acts as a title, not a group. It cannot be the grouping for ideas. |
| `write()` on a near-duplicate (distance < 0.15) replaces the old text and keeps the old topic and source_wing. | Restating an idea overwrites it. The fact that it came up again is lost. |
| 113 entries contain leaked tool-call markup (`</content><parameter name="source_wing">...`). 222 have no source_wing. | Junk text pollutes search and embeddings. Unscoped entries can't be filtered by repo. |
| `user_search` ranks by plain vector distance. Only 113 entries (3.5%) are from the last 7 days. | Old entries crowd out new ones in every search. |
| There is no open/done status. The questions hall has 37 entries. | Nothing separates live ideas from finished ones. |
| Capture depends on agents remembering to call `user_write`. They often don't. | Ideas typed in a prompt never reach the store. |
| The palace has personal, non-code wings (`running`, `job-search`). The user wing mixes personal entries with code ones. | Personal entries can leak into orch packs. |

## Decisions already made

1. Phase A ships first. orch's context plan depends on it.
2. The short-term sweeper auto-extracts ideas from the user's own prompts with Haiku. Personal, non-code ideas are tagged `personal` and kept out of orch packs.
3. Idea clusters live in a SQLite side table in the palace volume, not in upstream's KG.

## Phase A: recency (contract)

Being built now on `feat/user-wing-recency`. This section is the contract Phases B and C and orch build on.

### New metadata

Missing keys read as defaults, so no migration is needed.

| Key | Type | Default when missing |
|---|---|---|
| `last_seen` | ISO UTC string | the entry's `timestamp` |
| `last_seen_epoch` | int (seconds) | from `timestamp` |
| `seen_count` | int, starts at 1 | 1 |
| `origin` | `agent` \| `prompt` \| `orch` | `agent` |
| `status` | `open` \| `active` \| `parked` \| `done` \| `superseded` | `open` for `goals` and `questions`, absent for other halls |
| `personal` | bool | False |

### Write behavior

- A write whose content contains tool-call markup is rejected.
- Dedup no longer overwrites. On a near-duplicate it keeps the original text and metadata, sets `last_seen` to now, increments `seen_count`, and appends a `[revised YYYY-MM-DD] <new text>` line. At most 3 revised lines are kept.

### Search

`mempalace_user_search` gains these parameters:

- `since_days`
- `source_wing` and `include_unscoped`
- `status`
- `include_personal`
- `recency_weight`, default 0.1

Results are ranked by `effective_distance = distance + recency_weight * min(age_days / 30, 1)`. An entry 30 or more days old is pushed back by 0.1.

### New tools

- `mempalace_user_recent(days=7, source_wing, include_unscoped, hall, status, include_personal, n=20)` lists entries by `last_seen`, newest first.
- `mempalace_user_set_status(drawer_id, status)` changes one entry's status.

### Summary and status

- `summary(source_wing)` returns the newest 3 entries per hall. It excludes personal entries, caps each item at 300 characters, and starts with an "Open ideas" section.
- `status().recent_topics` returns the topics of the 30 newest entries, newest first.

### Repair and CLI

- `scripts/repair_user_wing.py` strips leaked markup and recovers `source_wing` from it. It is a dry run unless told otherwise.
- `mems my recent` calls `mempalace_user_recent`.

## Phase B: capture

### Idea extraction in the sweeper

The sweeper from the 2026-10-01 spec already reads every human session's prompts and makes one Haiku call per session. Phase B adds ideas to that same call. There is no second LLM call and no new hook.

The extractor labels each block of text sent to Haiku as `[user]` or `[assistant]`. The digest JSON gains one field:

```
{"did": [...], "state": "...", "open": [...], "next": "...",
 "ideas": [{"text": "<one or two sentences>",
            "kind": "idea" | "question" | "todo",
            "personal": true | false,
            "topic": "<short-slug>",
            "quote": "<5-15 words copied exactly from a [user] block>"}]}
```

Rules in the prompt:

- Take ideas only from `[user]` blocks. Never from assistant text.
- An idea is something the user wants to build, change, find out or remember. Instructions for the current task ("fix the test", "run it again") are not ideas.
- Skip text the user pasted in, such as logs or earlier Claude output.
- At most 5 ideas per session.
- `personal` is true when the idea is not about code or this repo's work.

The sweeper checks every idea mechanically before writing it:

- `quote` must appear in the user prompt text after whitespace is normalized. If it doesn't, the idea is dropped and logged. This is what keeps assistant text out.
- `kind` must be one of the three values, and `text` must be under 400 characters.

The extractor change: when a session is over the 30k-token cap, user prompts are kept whole and assistant text is trimmed first. Prompts are small, and they are the source of ideas.

### Resumed sessions

A resumed session keeps its session id and gets re-digested. Without care, its ideas would be extracted again and bump `seen_count` falsely. To prevent that, the state file (`~/.mempalace/recent-state.json`) records the uuid of the last prompt already processed for ideas. On a re-digest, prompts up to that uuid are marked `[user, already processed]`, and Haiku takes ideas only from the new ones. The digest itself still covers the whole session.

### Writing ideas to the user wing

`POST /recent` carries the digest, the ideas and the open items in one request. The server stores the digest in the `recent` wing, then calls `UserWing.write` for each idea and open item, in a worker thread.

Each idea becomes one user-wing write:

| Field | Value |
|---|---|
| content | the idea's `text` |
| hall | `goals` for `idea` and `todo`, `questions` for `question` |
| status | `open` |
| origin | `prompt` |
| topic | Haiku's slug. In Phase C, clusters replace topic as the grouping. |
| source_wing | the repo wing, or omitted when `personal` is true |
| personal | from Haiku, forced true when the repo is marked personal |
| session_id | the session's id |
| quote | the verified quote, kept in metadata |

A repo is marked personal by `personal: true` on its entry in `config/repos.json`. `running` and `job-search` get that flag.

The digest's `open` items are promoted the same way. An item ending in `?` goes to `questions`, anything else to `goals`. They are never personal unless the repo is.

Phase A dedup does the rest. When the user states an idea again in a later session, the existing entry gets a newer `last_seen` and a higher `seen_count` instead of a second copy. `seen_count` is the signal that an idea keeps coming back, and Phase C uses it to rank clusters.

`mempalace_user_write` gains optional `origin`, `personal` and `session_id` parameters so orch and agents can set them. If Phase A ships them, this step is already done.

Expected volume is about 3 sessions a day, so at most about 20 writes a day.

### Change to the 2026-10-01 spec

That draft said "Don't feed digests into wing_user". It now says this: digests stay in the `recent` wing, but their open items and the extracted ideas go to the user wing. Those are exactly the ideas that get lost today. A digest is a rolling record of a session and gets pruned after 30 days. An idea needs to stay until the user marks it done.

### orch write-back

The sweeper skips every `sdk-*` transcript, so nothing orch does reaches Mempalace. That filter stays for transcripts. orch transcripts are long, automated and mostly tool calls, and their useful facts already exist as files in the request directory.

Instead, orch's engine writes back through the MCP client it already has (see the orch plan below):

| When | hall | origin | topic | source_wing | content |
|---|---|---|---|---|---|
| After the owner's answers ask resolves | `decisions` | `orch` | `orch-<request_id>` | the repo's wing | the owner's `answers.md`, capped at 2,000 characters |
| When a request finishes | `observations` | `orch` | `orch-<request_id>` | the repo's wing | one line: request id, goal's first line, outcome (merged PR, failed stage, cancelled) |

orch writes are never personal. Once `POST /recent` exists, orch may also post a digest with session id `orch-<request_id>`. That is optional.

## Phase C: the idea tree

### Storage

`/data/ideas.sqlite`, in the `mempalace-data` volume next to the palace. Chroma keeps the entries and their embeddings. SQLite keeps clusters and membership.

```
clusters(
  cluster_id     TEXT PRIMARY KEY,
  label          TEXT,
  base_statement TEXT,
  parent_id      TEXT NULL,
  status         TEXT,
  created_at     TEXT,
  updated_at     TEXT,
  last_touched   TEXT,
  statement_at   TEXT NULL,
  member_count   INTEGER,
  centroid       BLOB,
  personal       INTEGER,
  locked         INTEGER DEFAULT 0
)
members(
  drawer_id   TEXT PRIMARY KEY,
  cluster_id  TEXT,
  joined_at   TEXT,
  distance    REAL,
  source_wing TEXT NULL,
  personal    INTEGER,
  locked      INTEGER DEFAULT 0
)
status_history(drawer_id TEXT, status TEXT, at TEXT)
meta(key TEXT PRIMARY KEY, value TEXT)
```

- `cluster_id` is `c-` plus 12 hex characters.
- Cluster `status` is `open`, `active`, `parked` or `done`.
- `updated_at` is the last membership change. `last_touched` is the newest member's `last_seen`. `statement_at` is when `base_statement` was last written.
- `centroid` is a normalized float32 vector.
- `meta` holds the schema version, the embedding model name and the thresholds.

The columns beyond the ones first proposed are `last_touched`, `statement_at`, `personal` and `locked` on clusters, `source_wing`, `personal` and `locked` on members, and the `meta` table. Each is used below.

`status_history` is written by `mempalace_user_set_status`. It lets a base statement say when something was finished.

The cluster id is also mirrored into each entry's Chroma metadata as `cluster_id`, so search can filter on it. SQLite is the source of truth. The mirror is repaired nightly.

The embedding model name (MiniLM by default, 384 dimensions) is stored in `meta`. If the palace's model changes, centroids are meaningless. Assignment stops and `mems doctor` says to run a rebuild.

### Where the work runs

The host sweeper drives all cluster work and runs every Haiku call. The vector math and SQLite writes run inside the container, for two reasons:

- `/data` is the named volume `mempalace-data`. The host can't open it.
- One process writing `ideas.sqlite` avoids SQLite locking across the Docker file share, which is the main way SQLite and Chroma would drift apart.

None of it runs on the event loop. FastMCP calls sync tool functions directly on the loop (`mcp/server/fastmcp/utilities/func_metadata.py`), so today every user-wing tool blocks it while Chroma works. Phase C turns the user-wing tools into async functions that run their work through `anyio.to_thread.run_sync`, as `/health/deep` already does. The nightly job, backfill and rebuild run in a worker thread behind a `CapacityLimiter(1)`. The 2026-07 outage was a synchronous palace scan on the loop, and this keeps that from happening again.

### Assignment on write

`UserWing.write` embeds the content once with the collection's embedding function. It passes that vector to the dedup query, the upsert and the assignment, so nothing is embedded twice.

1. A dedup hit keeps its cluster. The cluster's `last_touched` moves to now.
2. For a new entry, compute cosine distance to every centroid with the same `personal` flag. This is one matrix-vector product against centroids held in memory, under a few milliseconds at a few thousand clusters.
3. If the nearest is within `T_join`, join it. Update the centroid incrementally: `c = normalize(c * n + e)`, `n = n + 1`.
4. Otherwise start a new cluster with the entry's topic as label, the entry's vector as centroid, and the entry's text as its base statement.
5. Write the `members` row and the `cluster_id` metadata.

Personal and non-personal entries never share a cluster. That keeps a personal idea out of a cluster orch might read.

`T_join` starts at a cosine distance set by the spike (step C0 below).

### Nightly job

The sweeper runs this once a day, the first time it fires after `last_nightly` in its state file is 24 hours old. launchd fires the sweeper every 15 minutes, so a laptop that slept through the night still gets the run. It calls `POST /ideas/nightly`, which returns a JSON report.

1. Re-cluster. Load entries whose `last_seen` is in the last 30 days, with their embeddings. Move an entry to another cluster only if that cluster is closer than its current one by more than 0.05. The margin stops entries flapping between two clusters. Locked members are not moved. Recompute centroids of changed clusters from their members.
2. Clean up. Delete `members` rows whose drawer no longer exists (pruned or deleted). Delete empty clusters and move their children to their parent.
3. Nest (the merge step). For each changed cluster, find clusters whose centroids are within `T_nest`, a tighter threshold than `T_join`. The smaller cluster takes the larger as `parent_id`. Members are never moved or deleted by this step. A nest is skipped if it would create a cycle, if the result would be deeper than 3 levels, or if the smaller cluster is locked. Repeated nesting is how the tree grows.
4. Set cluster status:
   - `done` when the cluster has goal or question members and all of them are `done` or `superseded`
   - `active` when any member was touched in the last 14 days
   - `open` when any member is `open`
   - `parked` otherwise
5. Fix the `cluster_id` mirror in Chroma wherever it disagrees with `members`.
6. Return the clusters that need a new base statement: 2 or more members, and membership changed since `statement_at`.

### Base statements

The base statement is the user's "base model" of an idea. It is 2–3 plain lines:

1. What the idea is.
2. Where it stands: open and done counts, and the latest decision.
3. Its open sub-ideas, from open members and child clusters.

Code appends "last touched YYYY-MM-DD" from `last_touched`. Haiku never writes dates or counts.

The sweeper gets the pending clusters from the nightly report, with each cluster's label, child labels and its 20 newest members (hall, status, date, text capped at 300 characters). It sends up to 10 clusters per Haiku call, using the same `claude -p` command and recursion guards as the digest. Haiku returns `{"cluster_id": {"label": "<6 words or fewer>", "statement": "<2-3 lines>"}}`. The sweeper posts the results to `POST /ideas/statements`. A single-member cluster uses its entry's text and needs no Haiku call.

Cost: a few dozen Haiku calls a day at most, on the subscription.

### Backfill

`mems ideas backfill` runs once, after Phase A's repair script has cleaned the leaked markup.

1. `POST /ideas/backfill` assigns all 3,184 entries in timestamp order, oldest first, so clusters form in the order the ideas came up.
2. One re-cluster pass over all entries, not just the last 30 days, to reduce order effects. Then one nesting pass.
3. The sweeper writes base statements for every cluster with 3 or more members, 10 per Haiku call.

### Topic and `merge_topics`

Free-text topic stays as a label on each entry. Clusters do the grouping. `mempalace_user_merge_topics` is no longer needed and can be retired once backfill has run.

### Tools and search

- `mempalace_idea_clusters(source_wing=None, status=None, n=20, include_personal=False)` lists clusters by `last_touched`, newest first. Each has its id, label, base statement, status, member count, parent and child count. A cluster matches `source_wing` when any member has that wing. `include_personal` is an addition to the first proposal, so orch can never get personal clusters by default.
- `mempalace_idea_cluster(cluster_id)` returns the cluster, its parent, its children (id, label, status), and its members (id, hall, status, text capped at 300 characters, `last_seen`, `seen_count`).
- `mempalace_user_search` and `mempalace_user_recent` results gain `cluster_id`. `mempalace_user_search` also takes `cluster_id` as a filter.

### Where the user sees it

SessionStart. The hook from the 2026-10-01 spec calls `GET /brief?wing=<w>`, which the server renders in one response. The whole block stays under about 400 tokens:

```
Recent sessions in Memory (reference data, may be stale; current branch: X @ abc123):
- 2026-09-30, branch feat/foo, PR 231: did …; open: …; next: …
Open ideas in Memory, last 14 days:
- [goal] Show stale open ideas in mems standup (2026-09-29, seen 3 times)
Active idea clusters:
- c-3f2a91c0d4e2 Recency in user context: <base statement, one line> (last touched 2026-10-01)
Other repos: mempalace_recent(wing=...) or `mems recent <repo>`. All ideas: `mems ideas`.
```

The sections are recent sessions, then up to 5 open ideas for this repo touched in the last 14 days, then the base statements of the 3 most active clusters for this repo. Personal entries are left out. When the block is over budget, clusters are cut first, then ideas. The open-ideas section needs only Phase A data, so it can ship with the hook. The cluster section is added in Phase C.

`mems ideas`:

- `mems ideas` prints the tree. Root clusters are sorted by `last_touched`, with children indented. Each line has status, member count, date and the first line of the base statement.
- `mems ideas open [--repo R]` lists open ideas, newest first.
- `mems ideas stale` lists ideas that are open and untouched for 30 days or more. This is the lost backlog, meant to be reviewed weekly.
- `mems ideas show <cluster_id>` prints one cluster with members and children.
- `mems ideas set <drawer_id> <status>` calls `mempalace_user_set_status`.
- `mems ideas move <drawer_id> <cluster_id>` and `mems ideas unnest <cluster_id>` fix wrong groupings by hand and set `locked`, so the nightly job leaves them alone.
- `mems ideas backfill` and `mems ideas rebuild`.
- `mems standup` gains one line: the count of stale open ideas.

`open` and `stale` need only Phase A data and ship in Phase B.

orch. The planner pack reads the base statements of clusters that match the request's goal. See the next section.

## How orch uses this

orch's engine is its only Mempalace client. The plan for its context packs is `/Users/themancalledzac/Code/agent-orchestrator/docs/plans/2026-10-02-mempalace-context.md`, which is being rewritten against the Phase A API. In short:

- Phase A. Pack queries use `mempalace_user_search` with `source_wing`, `include_unscoped`, `status` and `since_days`, and `mempalace_user_recent` for what changed lately. orch always passes `include_personal=False` explicitly rather than relying on a default.
- Phase B. orch writes the owner's answers and each request's outcome back to the user wing, as described in "orch write-back".
- Phase C. The planner runs `mempalace_user_search` on the goal, takes the `cluster_id` of the top hits, and reads those clusters through `mempalace_idea_cluster`. The base statements go into the planner pack. No new orch-specific tool is needed.

## Build order

| Step | Work | Depends on |
|---|---|---|
| A1 | Phase A on `feat/user-wing-recency`: metadata, write behavior, search parameters, `user_recent`, `user_set_status`, `summary`, `status`, repair script, `mems my recent`. | — |
| A2 | Run `scripts/repair_user_wing.py` on the live store, dry run first. | A1 |
| B0 | The 2026-10-01 spec's phase 0 spike, plus an extraction check: run the extended prompt on 20 real transcripts in dry run and read every idea it returns. | 2026-10-01 phase 0 |
| B1 | The 2026-10-01 spec's phases 1–6 (resolver, extractor, `recent` wing, summarizer, sweeper, hook). | 2026-10-01 spec |
| B2 | `mempalace_user_write` gains `origin`, `personal`, `session_id` (skip if A1 has them). `personal: true` in `config/repos.json`. | A1 |
| B3 | Extractor: `[user]`/`[assistant]` labels, prompts kept whole under the cap, last-processed prompt uuid in the state file. | B1 |
| B4 | `ideas` in the digest schema, the quote check, `POST /recent` writing ideas and open items. Writes go to a log file instead of the palace for the first week. | B0, B2, B3 |
| B5 | `mems ideas open`, `mems ideas stale`, the standup line, and the open-ideas section of `GET /brief`. | A1, B1 |
| B6 | orch write-back, in the orch repo. | A1, B2 |
| C0 | Spike on an export of the user wing: try `T_join` from 0.25 to 0.45 and a few `T_nest` values. Report cluster count, share of single-member clusters, largest cluster, and hand-check 20 random clusters. The 62 "mems/mempalace" variants should land in a handful of clusters, not 62 and not 1. | A2 |
| C1 | `src/idea_tree.py`, the SQLite schema, assignment on write, async user-wing tools. | A1, C0 |
| C2 | `POST /ideas/nightly`, `POST /ideas/statements`, the sweeper's nightly step and base-statement calls. | B1, C1 |
| C3 | Backfill and the one-time base statements. | A2, C1, C2 |
| C4 | `mempalace_idea_clusters`, `mempalace_idea_cluster`, `cluster_id` in search results and as a filter. | C1 |
| C5 | Cluster section of `GET /brief`, `mems ideas` tree and the rest of the CLI, `doctor` checks, rebuild, `ideas.sqlite` in the daily snapshot. | C2, C4 |
| C6 | Retire `mempalace_user_merge_topics`. | C3 |

B2, B5 and B6 can run in parallel once A1 lands. C1 and C4 can run in parallel after C0.

## Risks

| Risk | Mitigation |
|---|---|
| Wrong cluster merges. | Thresholds come from the C0 spike on real data, not a guess. The nesting step never moves or deletes members, so a wrong nest is undone by `mems ideas unnest`. The 0.05 margin stops entries flapping. Depth is capped at 3. Manual moves and unnests set `locked`, and the nightly job leaves locked rows alone. |
| Haiku extracts things the user didn't mean as ideas. | Ideas must carry a quote that appears in a user prompt. The prompt excludes task instructions and pasted text. At most 5 per session. B0 reads 20 real sessions' output before anything is written, and B4 logs to a file for the first week. A bad capture is fixed with `mems ideas set <id> superseded`. |
| Personal entries leak into orch. | Four layers. Haiku flags personal ideas. Repos marked `personal` in `config/repos.json` force the flag. Personal entries have no `source_wing`, so a repo-scoped query with `include_unscoped=False` never sees them. Personal and non-personal entries never share a cluster, and orch passes `include_personal=False` on every call. A test checks that orch-style calls return no personal entries. The remaining risk is Haiku marking a personal idea as code. |
| Event-loop blocking. The 2026-07 outage was a synchronous palace scan on the loop. | User-wing tools move off the loop with `anyio.to_thread.run_sync`. Write-time assignment is one matrix-vector product and one SQLite insert. The nightly job, backfill and rebuild run in one worker thread behind a limiter. Every Haiku call runs on the host in the sweeper. The existing watchdog keeps polling `/health`. |
| SQLite and Chroma drift apart. | Only the container process writes `ideas.sqlite`. SQLite owns membership, and the nightly job fixes the `cluster_id` mirror and removes members whose drawers are gone. `mems doctor` reports members with no drawer, entries with no member row, mirror mismatches and the age of the last nightly run. `mems ideas rebuild` (`POST /ideas/rebuild`) wipes the SQLite file and reruns backfill from Chroma. Base statements can't be rebuilt from Chroma without Haiku, so `ideas.sqlite` joins `src/wing_user_snapshot.py`'s daily snapshot. |
| A resumed session double-counts ideas. | Only prompts after the last processed uuid are used for ideas. |
| Old junk skews clusters. | Backfill runs only after the repair script (A2). |

## Rejected alternatives

- **Topic as the grouping.** 2,383 of 2,592 topics are used once. Agents invent a new topic for the same idea every time.
- **Full re-clustering every night (for example HDBSCAN over all entries).** Cluster ids would change from run to run, so base statements and anything orch or the user referenced would churn. Incremental assignment keeps ids stable.
- **A UserPromptSubmit hook that captures ideas live.** It would add latency to every prompt and a Haiku call per prompt. The sweeper already reads every prompt within 45 minutes.
- **Clusters in upstream's KG.** Decided against. Clusters need centroid vectors and frequent membership updates, and the KG would need upstream patches for both.

## Decisions for the user

Each item has a default that applies if nobody answers.

1. Restating a parked or done idea. Default: a `parked` idea goes back to `open`. A `done` idea stays `done` and only gets its `seen_count` bumped.
2. The first-week dry run for extracted ideas (B4). Default: yes, write to a log file for one week, then switch to the palace after the user reads the log.
3. Which halls are clustered. Default: all six, so a frustration and a goal about the same thing land together.
4. The orch `answers.md` cap. Default: 2,000 characters, one entry per request.
5. The weekly stale review. Default: `mems ideas stale` plus the count in `mems standup`, with no extra reminder at session start.
