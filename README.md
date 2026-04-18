# Memory Palace

A multi-repo memory system built on [mempalace](https://pypi.org/project/mempalace/). It indexes code across multiple repositories into a shared ChromaDB vector store organized by wings (repos) and rooms (topics), and provides a User Wing for capturing persistent user context across AI coding sessions.

Exposes everything via an MCP (Model Context Protocol) server so AI agents in Cursor, Claude Code, etc. can query and write to the palace.

## Architecture

```
config/
  repos.json          # Maps wing names to local repo paths
  mempalace.yaml      # Taxonomy: wings → rooms with keyword routing

src/
  mcp_http_server.py  # FastMCP server (8 tools, StreamableHTTP on :8787)
  sync_engine.py      # Multi-repo git-diff sync orchestrator
  user_wing.py        # User thought storage organized by halls
  tools.py            # Sync tool handlers
  __main__.py         # python -m src entry point

integration/
  mempalace-discovery.mdc  # Cursor rule: query palace at session start
  user-wing.mdc            # Cursor rule: capture thoughts at session end
  stop-hook.sh             # Claude Code stop hook for thought capture
```

## Setup

**Requirements:** Python 3.12+, git

```bash
# Clone and install
git clone <repo-url> && cd Memory
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure repos

Edit `config/repos.json` to point wings at your local repo paths:

```json
{
  "my-project": {
    "path": "/Users/you/Code/my-project",
    "wing": "my-project"
  }
}
```

### Configure taxonomy

Edit `config/mempalace.yaml` to define rooms and keywords for each wing. Keywords drive `detect_room()` routing — files are matched by folder name, filename, then content keyword scoring:

```yaml
wings:
  my-project:
    rooms:
      - name: api
        description: "REST API routes and handlers"
        keywords: [route, handler, endpoint, request, response]
      - name: database
        description: "Models, migrations, queries"
        keywords: [model, migration, schema, query, repository]
```

## Usage

### Run the MCP server locally

```bash
# Direct
python -m src

# Or explicitly
python -m src.mcp_http_server
```

The server starts on `http://localhost:8787` (override with `MEMORY_PORT` env var).

### Run with Docker

```bash
docker compose up --build
```

Docker mounts your repos read-only under `/repos/` and persists palace data in a named volume. On first boot, it runs a full sync automatically.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_PORT` | `8787` | MCP server port |
| `PALACE_PATH` | `/data` | ChromaDB storage directory |
| `CONFIG_PATH` | `/config` | Directory containing `repos.json` and `mempalace.yaml` |

## MCP Tools

### Sync tools

| Tool | Description |
|------|-------------|
| `memory_sync(wing?, full?)` | Sync repos into the palace. Incremental by default — only processes files changed since last sync. Pass `full=True` to re-index everything. |
| `memory_sync_status()` | Show per-wing sync state: last commit SHA, file count, timestamp, errors. |

### User Wing tools

The User Wing captures persistent user context — goals, decisions, frustrations, discoveries — organized into halls rather than by code area.

| Tool | Description |
|------|-------------|
| `mempalace_user_write(hall, content, topic, source_wing?)` | File a thought into a hall. Auto-deduplicates near-identical entries. |
| `mempalace_user_search(query, hall?, topic?, n_results?)` | Semantic search across user thoughts. Filter by hall or topic. |
| `mempalace_user_summary()` | Compact user context digest (~300-500 tokens) for agent session startup. |
| `mempalace_user_status()` | Hall counts, recent topics, and protocol guidance. |
| `mempalace_user_merge_topics(source_topic, target_topic, hall?)` | Merge drifted topic slugs and deduplicate. |
| `mempalace_user_prune(hall?, topic?, older_than_days?, dry_run?)` | Remove stale thoughts by age. Defaults to dry run. |

### Halls

| Hall | When to use |
|------|-------------|
| `questions` | User is wondering about something |
| `discoveries` | User learned something new |
| `frustrations` | User hit a blocker or pain point |
| `goals` | User stated a short or long-term objective |
| `decisions` | User made a choice and explained reasoning |
| `observations` | User noted a pattern, insight, or factoid |

## IDE Integration

### Cursor

Copy the `.mdc` rules into your project:

```bash
cp integration/mempalace-discovery.mdc /path/to/project/.cursor/rules/
cp integration/user-wing.mdc /path/to/project/.cursor/rules/
```

These rules instruct the AI to query the palace at session start and capture user thoughts at session end.

### Claude Code

Add the stop hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "command": "/path/to/Memory/integration/stop-hook.sh"
      }
    ]
  }
}
```

Connect the MCP server:

```json
{
  "mcpServers": {
    "memory-palace": {
      "url": "http://localhost:8787/mcp"
    }
  }
}
```

## Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_sync_engine.py -v
```

## Project Structure

The palace stores data in ChromaDB with this hierarchy:

- **Wing** — maps to a repository (e.g., `edens-zac`, `edens-zac-backend`)
- **Room** — a topic area within a wing, assigned by keyword routing (e.g., `api-client`, `database`)
- **Hall** — the *type* of content, detected automatically from content keywords (e.g., `technical`, `creative`). For the User Wing, halls are explicit categories (`questions`, `goals`, etc.)
- **Drawer** — an individual chunk of indexed content (~800 chars)
