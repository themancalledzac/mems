# mems Troubleshooting

Common failure modes for the Memory Palace runtime, CLI, and IDE integrations.
Every section lists a one-shot diagnostic first, then the fix.

## Diagnostics first

Before anything destructive:

```bash
curl -sf http://localhost:8787/health    # is the server up?
docker compose ps                        # is the container running?
docker compose logs -f mempalace         # what is it complaining about?
mems health                               # same thing, via the CLI
```

---

## Container won't start / health check fails

**Symptoms:** `docker compose up` exits non-zero, or the container enters a
`restarting` loop, or `curl localhost:8787/health` never responds.

**Diagnose:**

```bash
docker compose logs --tail=100 mempalace
docker compose ps                     # STATUS column tells you if it's restarting
lsof -iTCP:8787 -sTCP:LISTEN          # port conflict?
```

**Common causes:**

- **Port 8787 already in use.** Another Memory Palace run, or another
  service, is bound to the host port. Kill it, or change the host port
  in `docker-compose.yml` (`"8787:8080"` → `"9787:8080"`).
- **Volume permission.** The named `mempalace-data` volume is owned by
  Docker; if you manually bind-mounted a host path instead, make sure
  the container user can write it.
- **First-boot model download.** The `sentence-transformers` embedding
  model is pre-baked into the image at build time (see Dockerfile), so
  a fresh container should not need to download it. If you see
  `HTTPSConnectionPool(host='huggingface.co', ...)` in the logs, you've
  hit a stale image — run `docker compose build --no-cache`.
- **Healthcheck grace period.** Compose considers the container healthy
  once `/health` returns 200; first boot does a full sync, which can take
  several minutes on a large repo. Watch logs instead of waiting on
  `healthy` status.

---

## `mems health` returns connection refused

**Symptoms:** `mems health` prints `server error: connection failed` or
`Connection refused`.

**Diagnose:**

```bash
echo "${MEMORY_SERVER_URL:-http://localhost:8787}"
docker compose ps
curl -v http://localhost:8787/health
```

**Common causes:**

- **Container not running.** `docker compose up -d`.
- **Wrong URL.** The CLI honors `MEMORY_SERVER_URL`. If you set it to a
  remote host or a non-standard port, it will happily fail against the
  wrong address. `unset MEMORY_SERVER_URL` and retry.
- **Firewall / VPN.** Some corporate networks block loopback on custom
  ports. Test with `curl --interface lo0 http://localhost:8787/health`.

---

## Search returns no results

**Symptoms:** `mems search "<query>"` prints nothing, or `mems wings` shows
no wings despite registered repos.

**Diagnose:**

```bash
mems status                           # any wings synced?
mems wings                            # drawers per wing
mems repo list                        # is the repo registered?
docker compose logs mempalace | grep -iE "sync|error"
```

**Common causes:**

- **Sync never ran.** A fresh install registers repos in `repos.json`
  but doesn't index them until the first boot sync completes. Run
  `mems sync` to force an incremental pass.
- **Wrong wing name.** Wing slugs are derived from the directory name
  (with dots replaced by hyphens). `mems wings` shows the canonical list.
- **Repo not bind-mounted into the container.** `config/repos.json` only
  tells the CLI *about* the repo; the container needs a read-only
  bind-mount at the same logical path (see `docker-compose.yml` volume
  examples). Without it, sync skips the wing.
- **Ledger stale after a volume wipe.** `docker compose down -v` wipes
  `sync_ledger.json`. Next boot triggers a full sync — give it time
  before querying.

---

## Wing-filtered search fails with "Error finding id" (but `search_all` works)

**Symptoms:** `mems search "<query>" --wing <wing>` (and MCP
`mempalace_search` with a wing filter) errors with
`Error executing plan: Internal error: Error finding id`, while
`mempalace_search_all`, `wing_user` search, writes, and `/health` all
succeed and report every drawer present. Typically appears right after a
mempalace version bump that tightened HNSW vector-index integrity checks:
the existing index (written by the old version) fails the new check on
first boot and the segment gets quarantined.

**Diagnose:**

```bash
docker exec mempalace mempalace --palace /data/palace repair-status   # read-only: sqlite vs HNSW counts
docker exec mempalace sh -c 'ls -d /data/palace/*.corrupt-* /data/palace/*.drift-* 2>/dev/null'   # quarantined segments?
```

**Fix:**

```bash
docker compose stop mempalace                       # repair needs the server down
docker run --rm -v memory_mempalace-data:/data memory-mempalace:latest \
    mempalace --palace /data/palace repair --yes    # legacy mode; rebuilds HNSW from chroma.sqlite3
docker compose up -d --wait mempalace
```

`mems restore` delegates to the same repair path if you prefer the CLI.
The source data in `chroma.sqlite3` is intact — only the derived vector
index is rebuilt — so no drawers are lost. Verify by re-running an actual
wing-filtered search and confirming results come back.

---

## Wing sync fails repeatedly

**Symptoms:** `mems status` shows a wing with `status: error`, or
`docker compose logs` shows `fail <wing>: ...` on every boot.

**Diagnose:**

```bash
mems status --json | python -m json.tool
docker compose exec mempalace bash -lc 'ls /repos/ && git -C /repos/<wing> status'
```

**Common causes:**

- **Not a git repo.** `sync_engine.py` expects a `.git/` directory.
  Either init the repo or remove it from `repos.json`.
- **HEAD detached / no commits.** `git rev-parse HEAD` must succeed. Land
  at least one commit.
- **Bind mount missing inside the container.** `repos.json` lists the
  path, but `docker-compose.yml` does not mount it at
  `/repos/<wing>`. Add the volume line and `docker compose up -d`.

---

## Wingpack publish refused

**Symptoms:** `mems publish <wing>` exits with
`publish refused for <wing>: <reason>`.

**Common reasons:**

- **Embedding dim / model mismatch.** The bundle's manifest records the
  embedding model (`all-MiniLM-L6-v2`) and its dimension (384). Publishing
  into a repo whose existing `.mempalace/wings/*.wingpack` was made with a
  different model is refused. Either upgrade the other side or re-export
  fresh bundles everywhere.
- **Blocked wing name.** `wing_user` is personal context and is never
  publishable. The publisher refuses explicitly.
- **No `.git/` in the target repo.** The target of a publish must be a
  real checkout so the staged bundle lives under a tracked path.

---

## `wing_user` empty after restart

**Symptoms:** `mems user-summary` returns nothing and `mems user-search`
finds zero hits after a container rebuild.

**Diagnose:**

```bash
docker compose exec mempalace bash -lc 'ls -t /data/exports/wing_user_backups/ | head'
docker compose logs mempalace | grep -iE "restore|snapshot"
```

**How it works:** the entrypoint always runs
`src/wing_user_snapshot.py` (writes today's backup, prunes older than
`WING_USER_RETENTION_DAYS`, default 7) and `src/restore_wing_user.py`
(if `wing_user` is empty, replays the newest backup with deterministic
IDs so it is idempotent).

**Recovery:**

- If snapshots exist but restore did not fire, restart the container —
  the restore hook runs at boot.
- If snapshots were wiped (`docker compose down -v` with nothing outside
  the named volume), data is gone; re-capture via `mems user-write`.
- To force a manual restore: `docker compose exec mempalace python -m
  src.restore_wing_user /data/palace /data/exports`.

---

## Cursor / Codex doesn't see mempalace tools

**Symptoms:** AI assistant says "I don't have a tool called
`mempalace_search`" even though the server is healthy.

**Diagnose:**

```bash
curl -sf http://localhost:8787/health      # server up?
cat ~/.cursor/mcp.json | python -m json.tool
cat ~/.config/codex/config.toml | head
```

**Common causes:**

- **Config path wrong.** Cursor reads `~/.cursor/mcp.json`; Codex reads
  `~/.config/codex/config.toml`. If you installed to the wrong place,
  rerun `scripts/install_cursor.sh` / `scripts/install_codex.sh`.
- **Client not restarted.** Both clients only scan MCP configs on
  launch. After editing config, fully quit and relaunch the app.
- **URL mismatch.** The shipped Cursor config points at
  `http://localhost:8787/mcp`. If you changed the host port, update the
  config too.

---

## Jira commands error

**Symptoms:** `mems ticket list` prints
`error: Jira not configured. Set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN`
or `jira error: HTTP 401 Unauthorized`.

**Diagnose:**

```bash
env | grep -i jira
curl -u "$JIRA_EMAIL:$JIRA_API_TOKEN" "$JIRA_URL/rest/api/3/myself"
```

**Common causes:**

- **Missing env vars.** All three of `JIRA_URL`, `JIRA_EMAIL`,
  `JIRA_API_TOKEN` must be set. Put them in your shell rc or an
  auto-loaded `.env`.
- **Wrong URL.** Must be the tenant root (`https://<tenant>.atlassian.net`),
  no trailing path.
- **Token scope.** Tokens from
  [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens)
  must have access to the projects you are querying. 401 means the email
  + token pair doesn't authenticate; 403 means auth succeeded but the
  account can't see that resource.

---

## `memory_sync` from MCP hangs

**Symptoms:** an AI agent calls `memory_sync` and the response never
returns, or `mems sync` hangs on large repos.

**Diagnose:**

```bash
docker compose logs -f mempalace        # watch for "full-sync: <wing>" lines
docker stats mempalace                  # CPU + memory usage
```

**Common causes:**

- **Large repo, first-time embedding.** A full sync embeds every file.
  Expect single-digit minutes per thousand files the first time; after
  that, git-diff incremental sync is sub-second.
- **Embedding model cold start.** Even with the pre-baked image, the
  first call after container boot warms the model into memory (~80s). The
  healthcheck start-period accounts for this.
- **Stuck on a huge file.** The sync engine skips binaries, but an
  oversized checked-in log can stall. Tail the logs; if a specific file
  is named, add it to the repo's `.gitignore` or the taxonomy's skip
  list.

To watch progress live while an MCP call is in flight:
`docker compose logs -f mempalace | grep -E "full-sync|ok|fail"`.

---

## See also

- `README.md` — CLI reference and Docker volumes.
- `CONTEXT.md` — full architecture spec (source of truth).
- `docs/plans/2026-04-17-mems-full-implementation.md` — implementation
  plan, phase-by-phase.
