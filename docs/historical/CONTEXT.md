# mems — Full Repo Context (All-In-One)

> ⚠️ **Status: DRIFTED target-state spec.** Most of this document was written
> *before* implementation and has not been kept in sync. Significant portions
> are aspirational, vaporware, or wrong (taxonomy claims, CLI command names,
> wings list, line-32 Python version, multiple gibberish paragraphs in §9).
>
> **For current state, use these instead:**
>
> - **What's shipped + how to use it:** [`README.md`](README.md)
> - **Taxonomy (the source of truth):** [`config/mempalace.yaml`](config/mempalace.yaml) — the YAML is canonical; if a description here disagrees, the YAML wins.
> - **What works vs what's pending:** [`docs/2026-05-06-handoff.md`](docs/2026-05-06-handoff.md)
> - **Live wing list + drawer counts:** call `mempalace_status` (the `## 11. Current Wings` section below is wrong — those wings are not registered).
>
> This file is scheduled to be merged into `ARCHITECTURE.md` or deleted entirely
> in a follow-up cleanup. **Do not treat anything below as canonical.** Inline
> `(planned — not implemented)` markers have been added to the most actively
> misleading command references; the rest of the body is left untouched
> pending the merge/delete decision.

---

## 1. What This Repo Is

`mems` wraps the open-source `mempalace` PyPI package and adds:

- **bash helpers** (`sync_all.sh`, etc.) — indexes N sibling repos into separate wings
- **HTTP MCP server** (`mcp_http_server.py`) — StreamableHTTP wrapper on port `8787` (internal `8080`)
- **Wingpack sharing** (`wing_pack.py`, `wing_publish.py`) — portable `.wingpack` bundles re-exported into each source repo after sync
- **Snapshot / disaster recovery** (`wing_user_snapshot.py` + `restore_wing_user.py`) — daily sqlite backup + auto-restore on wipe
- **Custom mount volume** — persistent palace data, survives container teardown
- **`mems` CLI** (`mems_cli/`) — unified shell for repo registry, publishing, palace ops, palace search, user-context capture, Jira, hybrid commands
- **Cursor / Codex / Claude Code integration** (`scripts/setup.sh`) — one-command install of MCP config, rules, and stop hooks
- **Palace primitives:** Wing (one per repo + `wing_user`) → Hall (personal/social, `wing_user` only) → Room (domain/topic) → Drawer (content chunk with embedding). Tunnels bridge like-named rooms across wings. Drawer IDs are deterministic — re-imports are idempotent.

---

## 2. Requirements / Dependencies / Versions

| Thing                 | Value                                                                                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Host OS               | macOS/Linux with Docker Desktop + bash/zsh                                                                                                                                |
| Container base        | `docker`, `python3` (for setup scripts + CLI)                                                                                                                             |
| Python                | 3.12 – 3.14                                                                                                                                                               |
| Core deps (Docker)    | `mempalace>=0.3.4`, `mcp[cli]`, `uvicorn`, `starlette`, `pyyaml>=6.0`, `h2`                                                                                               |
| Core deps (pyproject) | `mempalace>=0.3.4`, `mcp[cli]`, `uvicorn`, `starlette`, `sentence-transformers`, `pyyaml>=6.0`, `h2`, `chromadb>=0.5.0`                                                   |
| Dev deps              | `pytest>=7.0`, `ruff>=0.4.0`                                                                                                                                              |
| Python style          | `ruff` (B,L,P,W), line-length 100, double-quote, target py39                                                                                                              |
| Build backend         | `hatchling`; `packages = ["src", "mems_cli"]`                                                                                                                             |
| Console script        | `mems = mems_cli.main:main`                                                                                                                                               |
| Upstream policy       | `mempalace` is installed from PyPI, never vendored. Align version pins to upstream in `requirements.txt`. Docs explicit installs of transitives upstream doesn't declare. |
| Repos cloned as       | Siblings of `mems/` (default: `~/Code`). Dirs aren't paths — wings registered via `mems_cli` add `~/Code/<repo>` to PATH.                                                 |

---

## 3. Install / Setup / Rebuild

### One-shot Install (new machine)

```bash
cd ~/Code/Data/mems
python3 scripts/setup.sh
# or: ./scripts/setup.sh --ide cursor   (codex|both)
```

### What `setup.sh` does (all idempotent, safe to re-run)

1. **Pre-flight:** check `docker` + `python3` on PATH
2. **`pip install --user -e .`** — drops the `mems` console script into `$(python3 -m site --user-site)/bin`; appends to PATH if missing
3. **IDE selection** (prompt or `--ide <cursor|codex|both>`):
   - Cursor: appends to `~/.cursor/mcp.json` (via `mempalace_mcp_cursor.json`) with a marker comment (`# mempalace`) — existing entries, if present, are left alone
   - Codex: appends to `~/.codex/config.toml` (via `mempalace_codex_append.toml`) with the same marker guard
4. **Stop hook install** (prompt or `--setup-hook`): drops `mempalace-stop-hook.sh` into `$HOME/.config/claude/stop-hooks/` with marker comment; re-runs skip duplicates
5. **Repo discovery** (skip via `--skip-discovery`): scans `~/Code` for sibling repos, writes `config/repos.json` for each repo found
6. **For each wing selected**, sync via `palace.py`: backs-up-then-rebuilds wing
7. **Cursor install** (if selected): write pipeline to `~/.cursor/mcp.json`, merge with markers
8. **Codex install** (if selected): write pipeline to `~/.codex/config.toml`, copy `mempalace_codex.toml` block
9. `docker compose up --build` then `docker compose up --wait`
10. **Final check:** `mems doctor` *(planned — not implemented)* (mempalace check, validates compose/health)

### CLI fallback install

```bash
pip install --user -e .
python3 -m mems_cli --help    # same surface, no GUI fiddling
```

### Rebuild modes

| Command                                                 | What it does                                           | KG / wing_user                                 |
| ------------------------------------------------------- | ------------------------------------------------------ | ---------------------------------------------- |
| `docker compose up --build`                             | Incremental sync (git diff + hash scan)                | Kept                                           |
| `MEMPALACE_FULL_REFRESH=true docker compose up --build` | Re-embed all source-owned wings; `wing_user` preserved | `wing_user` kept                               |
| `mems make` *(planned — not implemented)*                                             | Snapshot `wing_user` + `down -v` + `up --build`        | Palace volume wiped; `wing_user` auto-restores |
| `mems doctor` *(planned — not implemented)*                                           | Same as `mems make` *(planned — not implemented)* + freshness guard on snapshot      | Serves as nuke-but-safe                        |
| `docker compose down -v && docker compose up -d`        | Raw nuke (entrypoint auto-restore saves `wing_user`)   | Freshness guard kicks in                       |
| `docker compose up --wait -d`                           | Rebuild image only                                     | —                                              |

### Upgrade mempalace

```bash
# update pin in Dockerfile + pip install mempalace=<new> or shared requirements.txt
docker compose up --build
```

**Post-upgrade smoke (when the storage/index engine changed).** A version bump
can ship stricter HNSW vector-index integrity checks that the *existing* index
(written by the old version) fails on first boot — mempalace then quarantines
the segment (`<uuid>.corrupt-<ts>` / `.drift-<ts>` under the palace dir). The
tell is that wing-filtered `mempalace_search` throws
`Error executing plan: Internal error: Error finding id` while `search_all`,
`wing_user` search, writes, and `/health` all keep working and report every
drawer present. Fix by rebuilding the HNSW index from the intact
`chroma.sqlite3`:

```bash
docker compose stop mempalace                      # repair wants the server down
docker run --rm -v memory_mempalace-data:/data memory-mempalace:latest \
    mempalace --palace /data/palace repair --yes   # legacy mode; rebuilds index from sqlite
docker compose up -d --wait mempalace
# verify: run a REAL wing-filtered search (e.g. mempalace_search wing=memory)
```

The source data (`chroma.sqlite3`) is never at risk here — only the derived
vector index is rebuilt. Always finish an engine-touching upgrade with a smoke
that runs an actual wing-filtered search against the *existing* index; a
fresh-empty-volume boot does **not** exercise this code path, so a clean smoke
can pass while prod is broken.

---

## 4. File Layout

```
mems/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── mcp_http_server.py       # FastMCP StreamableHTTP entry
│   ├── sync_engine.py           # Multi-repo git-diff orchestrator
│   ├── user_wing.py             # wing_user halls / rooms
│   ├── tools.py                 # MCP tool handlers
│   ├── filters.py               # Room detection (priority-ordered)
│   ├── wing_pack.py             # .wingpack bundle author
│   ├── wing_publish.py          # Publish bundle back into source repos
│   ├── wing_user_snapshot.py    # Daily sqlite backup of wing_user
│   ├── restore_wing_user.py     # Auto-restore on empty wing_user
│   └── auto_publish.py          # Post-sync re-publish hook
├── mems_cli/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py                  # Console script entry
│   ├── repo_registry.py         # list/add/scaffold/unlist/remove
│   ├── publishing.py            # publish/tags
│   ├── palace_ops.py            # sync/make/restore/doctor
│   ├── search.py                # search / my-context commands
│   ├── tickets.py               # Jira integration (utils-only)
│   └── hybrid.py                # standup / context
├── scripts/
│   ├── setup.sh                 # One-shot installer
│   ├── mempalace-discovery.md   # Cursor rule (search-first)
│   ├── operations.md            # Cursor rule (palace ops)
│   └── user-wing.mdc            # Cursor rule (thought capture)
├── integration/
│   ├── mempalace_mcp_cursor.json
│   ├── mempalace_codex_append.toml
│   └── mempalace-stop-hook.sh
├── config/
│   ├── repos.json               # wing → path map (gitignored per-user)
│   └── mempalace.yaml           # Taxonomy: wings → rooms → keywords
├── exports/                     # wing_user snapshots (gitignored)
├── tests/
├── docs/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── pyproject.toml
├── requirements.txt
└── CONTEXT.md                   # this file
```

---

## 5. Docker Runtime (what happens on boot)

### Container layout (from `Dockerfile`)

- Base `python:3.12-slim` + `curl`
- Install deps (see §2). Pre-downloads the embedding model (warmup collection) so cold starts wait ~80s once, not every boot
- Copies `src/` + all top-level scripts + `entrypoint.sh` to `/app/`
- ENV:
  - `MEMPALACE_REPOS_ROOT=/repos`
  - `MEMPALACE_STATIC_DIRS=/config` (each repo mounted R/O)
  - `MEMPALACE_PORT=8080`
  - `MEMPALACE_EXPORTS_RETENTION=7` (days)
- Exposes `8080` (host-mapped to `8787`)
- `HEALTHCHECK curl -f /health` every 30s, start-period 300s. Bumps to 3 retries once mining >5 min

### `entrypoint.sh` flow

1. `source /app/common/lib/sync_session.sh`
2. Install deps if missing (idempotent)
3. If `MEMPALACE_FULL_REFRESH=true`, skip drawers-preserved path (throwaway caches, re-mine from scratch)
4. Run `wing_user_snapshot.py` (write today's backup, prune older than retention)
5. Run `restore_wing_user.py` (if `wing_user` is empty, re-insert from newest backup using deterministic IDs)
6. Start `mcp_http_server.py` on `MEMPALACE_PORT`

### Order-of-operations (guaranteed)

```
docker compose up
  └─ entrypoint.sh
       ├─ snapshot  (always)
       ├─ restore   (only if wing_user empty)
       ├─ sync      (git diff → hash scan → full refresh, cheapest first)
       └─ serve     (FastMCP on :8080)
```

---

## 6. Sync + Room Detection + Wingpacks

### Sync strategy (cheapest first, per wing)

1. **`git diff`** — if manifest has synced SHA and repo is a checkout, `git diff --name-status` gives exact changed files
2. **SHA-256 hash scan** — fallback: hash every readable file, compare to manifest
3. **Full refresh** — purge + re-mine. Triggered by `MEMPALACE_FULL_REFRESH`, missing/corrupt manifest, `sync:full=true` in config, or explicit request

### Room detection (priority order)

1. **`rooms.json` explicit** — blocks override, wildcard listed last, plus keyword lists
2. **Path prefix** — wing path segment substring-matches a room name or keyword (applies to files goody, on short)
3. **Keyword match** — bag-of-words against room keywords, highest score wins
4. **Unrouted** — goes to `general` room (per wing); warned on import

### Wingpack bundle (`.wingpack` = zip)

Default filename: `{YYYYMMDD-HHMMSS}.wingpack`

Contents:

- `manifest.json` — schema, counts, embedding model + dim, source_digest (for future validation)
- `wingpack.yaml` — this wing's slice of `mempalace.yaml`
- `keywords.json` — per-room keyword lists
- `rooms.json` — per-room metadata + tags
- `prompts.json` — explicit tunnels touching this wing
- `sync_manifest.json` (optional) — static git-diff sync from bundle's SHA

**Static publish modes:**

- `default` (dict-suspect merge, refuses conflicts)
- `force` (overwrites wing YAML)
- `keep` (ignores YAML)
- **Compatibility gates** (refuse before writing): wing name blocked, embedding dim + model mismatch → refuse

**Read-what-lasts:** `wing_palace` scans every mounted repo for `.mempalace/wingpacks/*.wingpack`. Any bundle whose wing name matches the folder is ingested first — turns a 10-min re-embed into a sub-second row insert. Already-present wings skip import and fall back to live sync (rare).

---

## 7. `wing_user` (Personal Context + Disaster Recovery)

`wing_user` is a dedicated MCP-only wing — populated exclusively via `mempalace_user_write`.

### Halls (built-in)

| Hall              | Purpose                            |
| ----------------- | ---------------------------------- |
| `my_questions`    | Things the user is wondering about |
| `my_discoveries`  | Things the user learned            |
| `my_frustrations` | Blockers and pain points           |
| `my_goals`        | Short/long-term objectives         |
| `my_decisions`    | Choices made with reasoning        |
| `my_observations` | Patterns and insights              |

### Rooms (examples)

`debugging`, `architecture`, `mcp_pipelines`, `tooling`, `solutions`, `insights`, `blockers`, `recurring_issues`, `near_adjacent`, `long_term`, `technical_decisions`, `process_decisions`, `general`

### Recovery flow (the only wing with its own boot-time path)

1. `wing_user_snapshot.py` runs on every boot — split-brain read of `chroma.sqlite3` → writes `exports/wing_user_backup.YYYYMMDD.json` (one per day), prunes older than retention (default 7d)
2. `restore_wing_user.py` runs right after — if `wing_user` is empty, re-inserts from newest backup using the canonical open-palace API with deterministic IDs
3. `mems doctor` *(planned — not implemented)* forces a fresh snapshot BEFORE `down -v` if newest backup is >6h old (override with `--force`), then rebuilds and polls `/health`

If `mems my rooms` comes back empty after a rebuild:

```bash
ls -t exports/wing_user_backup_*.json | head -1    # if present, restore re-fires on next up
# if absent: re-capture manually via `mems my note "..."`
```

---

## 8. `mems` CLI Reference

All commands default to `MEMPALACE_URL=http://localhost:8787`. Run from anywhere (CLI resolves paths via `MEMS_ROOT` + `Path(__file__).resolve().parent.parent`).

### Repo Registry

| Command                          | Purpose                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------ |
| `mems list`                      | Show `repos.json` entries                                                                  |
| `mems add <path> [--goto]`       | Register a repo — if `.mempalace/wingpacks/*.wingpack` exists → force-install its YAML too |
| `mems scaffold <repo> [--setup]` | Generate starter wing YAML from directory structure                                        |
| `mems unlist <slug>`             | Unregister (prompt to also remove wing). Regen compose → prompt to restart                 |
| `mems remove <name>`             | Delete wing entirely (drops drawers, optionally keeps snapshot)                            |

### Wings & Publishing

| Command                           | Purpose                                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------------------- |
| `mems publish <repo> [--dry-run]` | Export + stage wing(s) into source repo (`.mempalace/wings/<wingpack>`); one MCP request per wing |
| `mems tags`                       | List wings with drawer counts (via `mempalace_list_wings`)                                        |

### Palace Ops

| Command              | Purpose                                                                |
| -------------------- | ---------------------------------------------------------------------- |
| `mems sync [--full]` | One-shot `/sync` call. Exits non-zero if `/status` is not ok           |
| `mems restart`       | `docker compose restart mempalace`                                     |
| `mems make [--full]` | Snapshot + `down -v` + `up --build` + poll `/health`                   |
| `mems doctor` *(planned — not implemented)*        | Same as `make` + aborts if newest backup is >6h old (unless `--force`) |

### Palace Search (wing_user)

| Command                                                            | Default behavior                                                                                                                    |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `mems search <query> [--wing W] [--room R] [--list N] [--json]`    | JSON search                                                                                                                         |
| `mems my frustrations [--topic T]`                                 | unresolved-only by default                                                                                                          |
| `mems my questions [--unresolved-only] [--list N]`                 | unresolved-only by default                                                                                                          |
| `mems my goals [--unresolved-only] [--list N]`                     | unresolved-only by default                                                                                                          |
| `mems my todo [--list N]`                                          | shortcut for topic=todos                                                                                                            |
| `mems my tools [--list N]`                                         | list tools                                                                                                                          |
| `mems my recent [--days 7] [--type T] [--topic T] [--list 20]`     | `mempalace_user_summary` output (unresolved_questions, unresolved_frustrations, active_goals, recent_decisions, recent_discoveries) |
| `mems my <hall> --type T [--topic R] [--resolved] [--sentiment S]` | Quick-capture: `--type = question \| discovery \| frustration \| goal \| decision \| observation`                                   |
| `mems my note "<content>"`                                         | Sets metadata via `mempalace_update_drawer`                                                                                         |

### Tickets (Jira) — stdlib-only, no third-party deps

Requires `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`. Auto-loaded from `~/.config/atlassian.env` (same file the `mcp-atlassian` server uses).

| Command                                                   | Purpose                                                   |
| --------------------------------------------------------- | --------------------------------------------------------- |
| `mems tickets [--mine] [--open] [--branch] [--project P]` | JQL search                                                |
| `mems todo`                                               | alias: `tickets --mine --open`                            |
| `mems backlog [--project P]`                              | unassigned, not-Done                                      |
| `mems ticket <key>`                                       | summary                                                   |
| `mems ticket <key> description\|comments`                 | full body / all comments (ADF flattened)                  |
| `mems ticket <key> comment "<msg>"`                       | post comment                                              |
| `mems ticket <key> link "<other>" [relates\|blocks]`      | list / move                                               |
| `mems ticket <key> transition "<to>"`                     | transition `In Progress` → `git checkout -b <key>-<slug>` |

### Hybrid

| Command                   | Purpose                                                                                                                                                   |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mems standup [--days 5]` | Compose drift: Jira (assigned, updated<=1h) + palace (ease_recently=0-N decisions/discoveries) + git commits (date/summary) — per repo in current context |
| `mems context <title>`    | Palace drawers + wing_user thoughts related to a ticket (search on ticket summary)                                                                        |

---

## 9. MCP Tools (exposed by `mcp_http_server.py` at `/mcp`)

All prefixed `mempalace_`. Served as StreamableHTTP (FastMCP + uvicorn). Clients: Cursor via `~/.cursor/mcp.json`, Codex via `~/.codex/config.toml`.

| Group           | Tools                                                                                                                                                              |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Navigation      | `status`, `list_wings`, `list_rooms(wing?)`, `check_logs(content, threshold=0.65)`, `get_logs_recent`                                                              |
| Search          | `search(query, slug?, wing?, room?)`, `search_all`                                                                                                                 |
| KG              | `kg_query(entity, as_of?, direction?)`, `kg_add(subject, predicate, object, valid_from?, source_time?)`, `kg_time(entity?)`, `kg_time_kv(entry?, ...)`, `kg_stats` |
| Graph traversal | `traverse(start_room, max_hops?)`, `find_tunnels(max_hops?, root)`, `kg_stats`                                                                                     |
| Drawers         | `kg_drawer`, `delete_drawer`, `list_drawers(wing?)`, `update_drawer(wing_id?, content?, metadata?)`                                                                |
| Tunnels         | `create_tunnel(tunnel_name, source, target)`, `delete_tunnel`, `list_tunnels(wing?)`, `tunnel_read(...)`                                                           |
| Diary           | `diary_write(entry, drawer?)`, `diary_read(term_name?, content?)`, `diary_read_time(topic?)`                                                                       |
| User context    | `user_write(entry, targets?, keep_settings?)`, `user_summary`, `user_search(query, hall?, topic?)`                                                                 |
| Ops             | `sync_status`, `resync(true\|false, output_dir?)`                                                                                                                  |
| Wing sharing    | `export_wing(slug, output_dir?)`                                                                                                                                   |

HTTP endpoints also include `/health` (JSON status, `fix_blob_ids`, `full_refresh`, timestamp).

**Summary of PalaceClient in `mems_cli/common.py` does the JSON-RPC handshake, authorization, reason, HTTP_retry, timestamps.** `mems <cmd>` → `tools/call` with session id ($200, server is up) and Cursor's registration sees stale (reload window when done). Meanwhile, fall back to JSON-RPC over `./cursor/hooks/user-commands.sh` when the interactive window doesn't declare.

**MCP-enabled fallback:** if Cursor's roster loses `mempalace_*` probe `curl -sf http://localhost:8787/health`. If 200, server is up and Cursor's registration went stale (reload window when done). Meanwhile, fall back to JSON-RPC over `/cursor/hooks/user-commands.sh`.

---

## 10. Conventions, QA, and Known Gotchas

| Area                  | Convention                                                                                                       |
| --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Python style          | `snake_case` functions, `PascalCase` classes                                                                     |
| Linter                | `ruff check src/ mems_cli/ tests/`, fix all — `ruff --fix`, no helpers                                           |
| Formatter             | `ruff format` — double-quote, line-length 100                                                                    |
| Commits               | Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `cli:`)                                                 |
| No `print` for status | Use `print()` only for error/debug; user messages go via helpers                                                 |
| Upstream patches      | Tier-3 (e.g. `exact_stem_match`, `fix_blob_id_ids` open pattern, `protected_wings`) belong upstream, not here    |
| Tier-2 candidates     | `config/repos.json`, `docker-compose.yml`, `src/_static_dirs_`, `_static/_dirs_ids_`, `palace/.todo/`            |
| Gitignored per-user   | `config/repos.json`, `docker-compose.yml` override, `.env`, `exports/*` (except `.gitkeep`), `palace/`, `.todo/` |

### Docker CLI gotchas

- `docker compose ps --filter` is NOT supported (docker-py limitation). Use `docker compose ps | awk/grep` — `mems doctor` *(planned — not implemented)* does this
- On `2.38+` releases UID-mismatched bind-mounts with "dubious ownership" throw. `safe.directory=*` in git config handles it — don't patch `.gitconfig`
- Repo-mounts must be **r/o** for `auto_publish` (safety; ensures we never write back into source repos by accident)
- Inter-repo KG triples — auto-extraction is shallow; use cross-repo relations manually
- Wingpack-hijack: sync skips source-code work when `.wingpack` exists with no SHA-shift check (wing can stale)

---

## 11. Current Wings (from `mempalace.yaml`)

> ⚠️ **The list previously here was wrong** — those wing names came from a
> different project's spec. For the actual registered wings, run
> `mempalace_status` or check `config/repos.json`. As of 2026-05-06 they are:
> `wing_user`, `edens-zac`, `edens-zac-backend`, `edens-zac-backend-go`,
> `edens-zac-ml`, `lightroom-export`, `job-search`, `running`, `memory`.

---

## 12. Troubleshooting (quick lookup)

| Symptom                                    | First action                                                                                                                                                                   |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `/health` says degraded                    | Read `sync_reason`: `mempalace.yaml not mounted` → check `~/.config/mcp`; `SIGSEGV on teardown` → usually benign, run `mempalace_resync`; `sync exited non-zero` → `mems logs` |
| Files in wrong room                        | Confirm `exact_stem_patch` archive; rename file to match room OR add specific keywords. Avoid short generic keywords                                                           |
| Wingpack import refuses embedding mismatch | Align mempalace version both sides (`>=0.3.4`); inspect bundle: `unzip -p bundle.wingpack manifest.json \| jq .`                                                               |
| `git pull` rejects `.wingpack`             | `git check-ignore -v .mempalace/wings/*.wingpack` — if matched, fix `.gitignore` (add `!.mempalace/wings/*.wingpack` exception)                                                |
| Container can't write under mount          | Compose entry must be `rw`. Dubious-ownership errors → already handled by `-c safe.directory=*`, don't patch `.gitconfig`                                                      |
| `wing_user` empty after rebuild            | `ls -t exports/wing_user_backup_*.json \| head -1`. If present, `docker compose down && docker compose up -d` — restore re-fires. If aged out, re-capture via `mems my note`   |
| MCP tools missing in Cursor                | `curl -sf http://localhost:8787/health`. If 200, Cursor roster is stale — reload window; meanwhile curl-fallback JSON-RPC per `./cursor/hooks/user-commands.sh`                |
| `SIGSEGV-139` mid-sync (not teardown)      | `docker compose restart mempalace`; if persists, `MEMPALACE_FULL_REFRESH=true`; last resort `down -v && up --build` (KG lost, re-import wingpacks)                             |

---

## 13. Quick Reference (most-used commands)

```bash
# Lifecycle
docker compose up -d --build
mems make
mems publish --all
curl http://localhost:8787/health
MEMPALACE_FULL_REFRESH=true docker compose up -d --build

# Day-by-day
mems list | mems add <path> | mems remove <wing>
mems publish --all
mems sync
mems search "<query>" --wing databricks-ett
mems my recent --days 7
mems my note "<wrapper code only — deposit investigation>" --type discovery --topic mcp_pipelines
mems doctor

# Lint/format (wrapper code only, src/ + mems_cli/)
ruff check mcp_http_server.py mems_cli/*.py wing_publish.py sync_engine.py auto_publish.py --fix
ruff format mcp_http_server.py mems_cli/**/*.py sync_engine.py wing_publish.py auto_publish.py

# Tests
pytest               # see tests/ dir
```
