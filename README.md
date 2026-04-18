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
  Snapshotted daily; auto-restored on empty boot.
- **`mems` CLI** — single `pip install` surface for repo registry, palace
  ops, search, publishing, ticket lookup, and hybrid Jira + palace queries.

See [`CONTEXT.md`](CONTEXT.md) for the full target-state spec.

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
| `mems repo list` | Show registered repos with last-sync timestamp. |
| `mems repo add <name> <path>` | Register a local git repo as a wing. |
| `mems repo remove <name>` | Unregister a wing (does not delete palace data). |
| `mems repo show <name>` | Dump the JSON entry for one wing. |

### Palace lifecycle

| Command | Purpose |
|---------|---------|
| `mems status` | Sync ledger digest (per-wing last sync, file count, status). |
| `mems sync [--wing W] [--full]` | Run `memory_sync` — incremental by default. |
| `mems resync [--wing W] [--full]` | Call `mempalace_resync` directly. |
| `mems wings` | List every wing with drawer counts. |
| `mems rooms <wing>` | List rooms inside a wing. |
| `mems logs [--limit N] [--wing W]` | Recent drawer log entries. |
| `mems export <wing> [--output PATH]` | Export a wing as a `.wingpack` bundle. |

### Search & user context

| Command | Purpose |
|---------|---------|
| `mems search <query> [--wing W] [--room R] [--limit N] [--json]` | Semantic search across wings. |
| `mems user-search <query> [--hall H] [--limit N]` | Search the personal User Wing. |
| `mems user-summary [--json]` | Compact session-start digest of user context. |
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
- **Claude Code** — wire the MCP server into `~/.claude/settings.json`:
  ```json
  {
    "mcpServers": {
      "mempalace": { "url": "http://localhost:8787/mcp" }
    }
  }
  ```
  The session-end stop hook lives at `integration/stop-hook.sh`.

Cursor-flavored session rules are also shipped as `.mdc` files under
`integration/` (`mempalace-discovery.mdc`, `user-wing.mdc`).

## Docker runtime

The container is defined by `Dockerfile` + `docker-compose.yml`. Nothing
else is required on the host except Docker and Python for the CLI.

**Volumes:**

- `mempalace-data:/data` — named volume holding `palace/`, `exports/`,
  `sync_ledger.json`, and `exports/wing_user_backups/`.
- `./config:/config:ro` — your taxonomy + `repos.json` (read-only inside).
- `~/Code/<repo>:/repos/<repo>:ro` — one bind-mount per wing you want
  indexed. Add these to `docker-compose.yml` (examples are commented in).

**Env vars that matter:**

| Var | Default | Purpose |
|-----|---------|---------|
| `MEMORY_PORT` | `8080` (host `8787`) | MCP listen port inside the container. |
| `PALACE_PATH` | `/data/palace` | Chroma persistence dir. |
| `EXPORTS_PATH` | `/data/exports` | Wingpack + wing_user snapshots. |
| `CONFIG_PATH` | `/config` | Mounted taxonomy + `repos.json`. |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Pre-downloaded at build time. |
| `WING_USER_RETENTION_DAYS` | `7` | Snapshot pruning threshold. |

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

## Configuration

- **`~/.config/mems/repos.json`** — wing name → repo path:
  ```json
  {
    "my-project": {
      "path": "/Users/you/Code/my-project",
      "wing": "my-project",
      "default_hall": "general"
    }
  }
  ```
  Edited via `mems repo {add,remove}` or by hand. `setup.sh` writes a
  skeleton there on first run.
- **`config/mempalace.yaml`** — taxonomy: wings → rooms → keywords. Drives
  the priority-ordered room detector in `src/filters.py`. Mounted into the
  container read-only at `/config/mempalace.yaml`.

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for the common
failure modes (container won't start, search returns no results, wingpack
publish refused, IDE doesn't see tools, etc.).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest tests/                      # full test suite
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
