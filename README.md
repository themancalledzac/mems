# Memory Palace (`mems`)

`mems` is a multi-repo semantic memory system for AI coding assistants. It
wraps the open-source [mempalace](https://pypi.org/project/mempalace/)
Python package and layers on portable `.wingpack` bundles, daily disaster
recovery for personal context, a unified `mems` CLI, and ready-made IDE
integrations for Cursor, Codex, and Claude Code. A single MCP server on
`localhost:8787` indexes every repo you register into a shared ChromaDB-
backed vector store, so every AI session starts with the same memory.

## Architecture

- **Wings → Rooms → Drawers** — each repo becomes a *wing*; files inside
  are routed into *rooms* (topic areas) and stored as *drawers* (embedded
  chunks). Cross-wing connections are expressed as *tunnels*.
- **MCP server** — FastMCP / StreamableHTTP on host port `8787` (internal
  `8080`). Speaks the MCP tool protocol to any compliant client.
- **`.wingpack` bundles** — portable zip archives (manifest + per-room
  metadata + embedding info) that can be published back into the source
  repo so any teammate or fresh machine can reconstitute a wing without
  re-embedding.
- **`wing_user`** — a dedicated MCP-only wing for personal context
  (questions, discoveries, frustrations, goals, decisions, observations).
  Each entry tracks `last_seen`, `seen_count` and, for goals and questions,
  a status that starts `open`. A repeated thought keeps its original text and
  gains a revision line. `mempalace_user_search` ranks recent entries higher,
  `mempalace_user_recent` lists what was touched lately, and
  `mempalace_user_set_status` marks an entry done or parked.
  Snapshotted daily; auto-restored on empty boot.
- **`mems` CLI** — single `pip install` surface for repo registry, palace
  ops, search, publishing, ticket lookup, and hybrid Jira + palace queries.

See [`CONTEXT.md`](docs/historical/CONTEXT.md) for the original target-state spec.

## Tech Stack

Python 3.12, `mempalace==3.6.0`, FastMCP (via `mcp[cli]`), uvicorn+starlette, chromadb 1.5.4+ (embeds with its bundled ONNX MiniLM model), hatchling, ruff, pytest. uv for the local venv. Docker Compose for runtime.

## Quickstart

```bash
git clone <repo-url> ~/Code/Memory
cd ~/Code/Memory
./scripts/setup.sh            # preflight, docker build + up, pip install --user, prompts for Cursor/Codex
mems status                   # confirm server is up and a wing is visible
```

`setup.sh` is idempotent — rerun any time. Use `--yes` for a non-interactive
install that skips repo prompts and IDE integration.

## CLI reference

All `mems` subcommands hit the MCP server at `MEMORY_SERVER_URL`
(default `http://localhost:8787`). Run `mems <cmd> --help` for flags.

### Server health

| Command | Purpose |
|---------|---------|
| `mems health` | GET `/health`; confirms server + lists wings. |
| `mems tools`  | List MCP tools the server advertises. |

### Repo registry (local `repos.json`)

| Command | Purpose |
|---------|---------|
| `mems repo list` | Show registered repos. The last-sync column comes from the server and shows `-` when it is down. |
| `mems repo add <name> <path>` | Register a local git repo as a wing. |
| `mems repo remove <name>` | Unregister a wing (does not delete palace data). |
| `mems repo show <name>` | Dump the JSON entry for one wing. |

### Palace lifecycle

| Command | Purpose |
|---------|---------|
| `mems status` | Sync ledger digest: per-wing last sync, file count, status, and last prune (`ok -N`, `blocked N`, `error`, `skipped`). |
| `mems sync [--wing W] [--full] [--allow-large-prune]` | Run `memory_sync`, incremental by default. Exits 1 when any wing errored or a prune was blocked or failed. |
| `mems resync [--full] [--allow-large-prune]` | Call `mempalace_resync` for every wing. Same exit code as `mems sync`. |
| `mems wings` | List every wing with drawer counts. |
| `mems rooms <wing>` | List rooms inside a wing. |
| `mems logs [--limit N] [--wing W]` | Recent drawer log entries. |
| `mems export <wing> [--output PATH]` | Export a wing as a `.wingpack` bundle. |

To check or clean drawers for files a repo no longer has, run
`python -m src.sync_engine prune [--wing W] [--apply] [--force]` in the container. It reads
`PALACE_PATH` and `CONFIG_PATH` like the server. It is a dry run by default and prints one
JSON line per wing with `would_remove` and `top_sources`. `--apply` deletes, and `--force`
allows a prune that would remove most of a wing. It only touches wings in `repos.json`.
Before `--apply`, run `docker compose stop`, then
`docker compose run --rm --no-deps mempalace python -m src.sync_engine prune --apply`.

### Search & user context

| Command | Purpose |
|---------|---------|
| `mems search <query> [--wing W] [--room R] [--limit N] [--json]` | Semantic search across wings. |
| `mems user-search <query> [--hall H] [--limit N]` | Search the personal User Wing. |
| `mems user-summary [--json]` | Compact session-start digest of user context. |
| `mems my recent [--days N] [-n N] [--json]` | User Wing entries touched in the last N days, newest first. |
| `mems user-write <hall> "<content>" [--topic T] [--source-wing W]` | File a thought; `hall ∈ {questions,discoveries,frustrations,goals,decisions,observations}`. |

### Publishing (`.wingpack` sharing)

| Command | Purpose |
|---------|---------|
| `mems publish <wing> [--mode ask\|overwrite\|skip] [--dry-run]` | Export + stage a wingpack into the source repo. |
| `mems publish-all [--mode ...] [--dry-run]` | Same, for every registered wing. |

### Jira tickets (stdlib-only client)

Requires `JIRA_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` in the environment.

| Command | Purpose |
|---------|---------|
| `mems ticket list [--assignee ME] [--status S] [--limit N]` | List tickets via JQL. |
| `mems ticket show <KEY>` | Show one ticket (ADF description flattened). |
| `mems ticket search "<JQL>"` | Raw JQL search. |

### Hybrid (Jira + palace)

| Command | Purpose |
|---------|---------|
| `mems hybrid <TICKET> [--limit N]` | Look up a ticket and surface the top palace drawers related to its summary + description. |

## IDE integration

Artifacts live under `integration/` and the installers under `scripts/`:

- **Cursor** — `scripts/install_cursor.sh` merges
  `integration/mempalace_mcp_cursor.json` into `~/.cursor/mcp.json` and
  copies `scripts/cursor_rules/mempalace.mdc` into `~/.cursor/rules/`.
- **Codex** — `scripts/install_codex.sh` appends
  `integration/mempalace_codex_append.toml` to `~/.config/codex/config.toml`
  (guarded by a `[mcp_servers.mempalace]` marker so reruns skip).
- **Claude Code** — `scripts/install_claude_code.sh` installs three hooks
  (`PreToolUse: Agent`, `PreToolUse: Bash|Grep|Glob|Read`, `Stop`, `PreCompact`) idempotently into
  `~/.claude/settings.json`. See the **Claude Code Setup** section below
  for the full flow. Register the MCP server globally with
  `claude mcp add --transport http mempalace --scope user http://localhost:8787/mcp`.

Cursor-flavored session rules are also shipped as `.mdc` files under
`integration/` (`mempalace-discovery.mdc`, `user-wing.mdc`). Claude Code
does not read `.mdc` files; equivalent guidance for Claude Code lives in
`~/.claude/CLAUDE.md`.

## Docker runtime

The container is defined by `Dockerfile` + `docker-compose.yml`. Nothing
else is required on the host except Docker and Python for the CLI.

**Volumes:**

- `mempalace-data:/data` — named volume holding `palace/`, `exports/`,
  `sync_ledger.json`, and `exports/wing_user_backups/`.
- `./config:/config:ro` — your taxonomy + `repos.json` (read-only inside).
- `~/Code/<repo>:/repos/<repo>:ro` — one bind-mount per wing you want
  indexed. Put these in a user-local `docker-compose.override.yml`
  (gitignored); `docker-compose.yml` has examples commented in.

**Env vars that matter:**

| Var | Default | Purpose |
|-----|---------|---------|
| `MEMORY_PORT` | `8080` (host `8787`) | MCP listen port inside the container. |
| `PALACE_PATH` | `/data/palace` | Chroma persistence dir. |
| `EXPORTS_PATH` | `/data/exports` | Wingpack + wing_user snapshots. |
| `CONFIG_PATH` | `/config` | Mounted taxonomy + `repos.json`. |
| `MEMPALACE_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Pre-downloaded at build time (upstream reads the `MEMPALACE_`-prefixed name). |
| `WING_USER_RETENTION_DAYS` | `7` | Snapshot pruning threshold. |
| `MEMPALACE_HOOKS_AUTO_SAVE` | `true` | Toggle upstream's auto-save hooks (upstream 3.3.6 #711). |
| `MEMPALACE_EAGER_WARMUP` | `1` | Warm the embedder at startup for predictable cold-start latency (upstream 3.3.6 #1530). |
| `MEMPALACE_TOPIC_TUNNEL_MIN_COUNT` | `2` | Co-occurrence threshold for promoting topic tunnels (default upstream is `1`; wrapper tunes to `2` for dense corpora). |
| `MEMPALACE_ENTITY_LANGUAGES` | `en` | Comma-list of entity-extraction languages. Override via compose env file. |

**Common operations:**

```bash
docker compose up -d --build      # build + start
docker compose logs -f mempalace  # follow logs
docker compose restart mempalace  # restart without rebuild
docker compose down               # stop (volumes kept)
docker compose down -v            # stop + wipe palace volume (wing_user restores)
```

## Disaster recovery

`wing_user` is the one wing you cannot re-derive from source code — it
holds the user's personal context. Every container boot runs, in order:

1. `src/wing_user_snapshot.py` — writes today's snapshot to
   `/data/exports/wing_user_backups/wing_user_backup.YYYYMMDD.json`
   and prunes any older than `WING_USER_RETENTION_DAYS` (7 by default).
2. `src/restore_wing_user.py` — if the `wing_user` collection is empty,
   replays the newest snapshot with deterministic drawer IDs.

You can test it end-to-end: `docker compose down -v && docker compose up -d`
— the wing_user drawers should reappear on boot from the newest snapshot.
Snapshots live inside the named volume, so they survive container
rebuilds; they are wiped only by `docker compose down -v`.

## Claude Code Setup

The wrapper installs four Claude Code hooks via `scripts/install_claude_code.sh`:

| Hook | Purpose |
|---|---|
| `PreToolUse: Agent` | Block sub-agent dispatch that omits the mempalace orientation block |
| `PreToolUse: Bash\|Grep\|Glob\|Read` | Remind the main agent when filesystem discovery runs without a mempalace search |
| `Stop` | Auto-mine the active transcript every 15 user messages |
| `PreCompact` | Emergency save before context compaction |

### The filesystem gate

`pretooluse_fs_gate.py` enforces CLAUDE.md Hard Rule #1 for the main agent — the
case procedural rules alone did not cover. Before the gate existed, 82% of
filesystem batches (244 of 297, across 86 sessions) ran to 3+ calls with no
mempalace search.

It reads the transcript Claude Code passes on stdin and counts discovery calls
since the last palace search. Only `mempalace_search`, `mempalace_search_all` and
`mempalace_user_search` end a run. A Read of a file already edited in the session
does not count. Inside a subagent (the payload carries `agent_id`) it reads that
subagent's own transcript, and stays silent if it cannot find it.

It only fires when a target path belongs to a wing. `integration/claude_code/repo_scope.py`
maps the path to a wing using `$MEMORY_CONFIG_DIR/repos.json` (default
`~/.config/mems/repos.json`), with git fallbacks for worktrees and clones. The
reminder names that wing.

| Variable | Default | Effect |
|---|---|---|
| `MEMPALACE_FS_GATE_MODE` | `warn` | `warn` injects a reminder; `block` denies the call; `off` disables |
| `MEMPALACE_FS_GATE_THRESHOLD` | `3` | Consecutive discovery calls before it fires (then every multiple) |
| `MEMPALACE_FS_GATE_TAIL_BYTES` | `524288` | Transcript tail window to scan |
| `MEMPALACE_FS_GATE_HOLDOUT` | unset | Fraction of sessions (by `sha1(session_id)`) that stay silent, for measurement |
| `MEMS_DIGEST` | unset | Any non-empty value silences the gate |

Only `Bash` commands that lead a segment with a discovery verb (`grep`, `rg`,
`find`, `ls`, `cat`, `sed`, `awk`, `wc`, `tree`, `fd`) count — `git commit`,
`pytest`, and `git log | head` do not.

Measure compliance at any time:

```bash
mems doctor --protocol
```

Add `--days N` to change the window, `--json` for machine-readable output.

The `Stop` and `PreCompact` scripts live in `~/Code/mempalace/hooks/` — install
upstream mempalace there alongside this repo:

```bash
git clone https://github.com/MemPalace/mempalace.git ~/Code/mempalace
```

Then run the installer (idempotent):

```bash
bash scripts/install_claude_code.sh
```

**Important:** Claude Code retains JSONL transcripts for only **30 days**.
Without these hooks wired, conversation history is lost permanently after
auto-deletion. Back up `~/.claude/projects/` and run the one-shot backfill:

```bash
rsync -av ~/.claude/projects/ ~/Documents/Claude_JSONL_Backup/
bash scripts/backfill_claude_sessions.sh
```

## Configuration

- **`~/.config/mems/repos.json`** — wing name → repo path. The key is the
  wing name; there is no separate `wing` field.
  ```json
  {
    "my-project": {
      "path": "/Users/you/Code/my-project",
      "default_hall": "general"
    }
  }
  ```
  Edited via `mems repo {add,remove}` or by hand. `setup.sh` writes a
  skeleton there on first run.
- **`config/mempalace.yaml`** — taxonomy: `wings.<name>.halls.<hall>.rooms[]`
  where each room has `name`, optional `description`, and `keywords[]`.
  `src/sync_engine.py` flattens halls into a single room list before handing
  off to `mempalace.miner.process_file`, which routes files to rooms by
  path/keyword scoring. Mounted into the container read-only at
  `/config/mempalace.yaml`.

## Troubleshooting

See [`docs/historical/TROUBLESHOOTING.md`](docs/historical/TROUBLESHOOTING.md) for the common
failure modes (container won't start, search returns no results,
wing-filtered search failing with "Error finding id" after a version bump,
wingpack publish refused, IDE doesn't see tools, etc.).

## Development

```bash
uv sync --extra dev                # builds .venv from uv.lock

.venv/bin/python -m pytest -q      # full test suite (bare pytest picks up the wrong tests package)
ruff check src/ mems_cli/ tests/   # lint
ruff format src/ mems_cli/ tests/  # format (check with --check)
```

The CLI package (`mems_cli/`) is standard argparse dispatch; add a new
subcommand by writing a `register(subparsers)` function in
`mems_cli/commands/` and wiring it into `mems_cli/main.py`.

Contributions follow conventional commit prefixes (`feat:`, `fix:`,
`docs:`, `test:`, `chore:`, `style:`). Run ruff + pytest before pushing.

## License

TBD — no `LICENSE` file in the repo yet.
