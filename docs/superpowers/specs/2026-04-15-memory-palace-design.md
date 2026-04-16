# Memory Palace — Design Specification

**Date:** 2026-04-15
**Status:** Approved
**Approach:** Plugin Architecture (Approach C)

## Overview

A dockerized container that indexes local code repos into a searchable, semantically connected knowledge store, served as an MCP server. Agents get tools to search code, traverse cross-repo connections, and capture/recall user context across sessions.

Built on top of the `mempalace` PyPI package (v3.3.0), which provides ChromaDB storage, temporal knowledge graph, 29 MCP tools, mining primitives, and room detection. This repo adds three layers: multi-repo sync orchestration, a User Wing for persistent user context, and a streamableHTTP transport in a Docker container.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Docker Container                │
│                                                  │
│  ┌─────────────┐  ┌────────────┐  ┌───────────┐ │
│  │ sync_engine  │  │ user_wing  │  │  tools    │ │
│  │ .py          │  │ .py        │  │  .py      │ │
│  └──────┬───────┘  └─────┬──────┘  └─────┬─────┘ │
│         │                │               │       │
│  ┌──────▼────────────────▼───────────────▼─────┐ │
│  │           mcp_http_server.py                 │ │
│  │        (StreamableHTTP on :8787)             │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │                            │
│  ┌──────────────────▼──────────────────────────┐ │
│  │          mempalace (pip package)             │ │
│  │   ChromaDB · KG · 29 tools · mining · CLI   │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  /data (Docker volume)     /repos (read-only)    │
│  ├── chroma/               ├── edens.zac/        │
│  ├── mempalace.db          ├── edens.zac.backend/ │
│  └── sync_ledger.json      └── ...               │
└─────────────────────────────────────────────────┘
```

## Repository Structure

```
Memory/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── pyproject.toml
│
├── config/
│   ├── mempalace.yaml          # Taxonomy: wings, halls, rooms, keywords
│   ├── repos.json              # Repo registry: paths, wing mappings
│   └── entities.json           # Entity registry seed data
│
├── src/
│   ├── __init__.py
│   ├── sync_engine.py          # Multi-repo git-diff sync orchestrator
│   ├── user_wing.py            # User Wing: halls, tools, summary synthesizer
│   ├── mcp_http_server.py      # StreamableHTTP MCP server (ASGI)
│   └── tools.py                # Custom tool definitions beyond mempalace's 29
│
├── integration/
│   ├── user-wing.mdc           # AlwaysApply rule for Cursor
│   ├── mempalace-discovery.mdc # AlwaysApply rule for Cursor
│   └── stop-hook.sh            # Stop hook backstop
│
├── tests/
│   ├── test_sync_engine.py
│   ├── test_user_wing.py
│   ├── test_mcp_server.py
│   └── test_tools.py
│
└── docs/
    └── superpowers/
        └── specs/
```

## Wing Taxonomy

Each repo maps to its own wing. Rooms are semantic (by concern), not structural (by folder).

### Wing: `edens-zac`

**Source:** `edens.zac` — Next.js 15 photography portfolio frontend

| Room | What it covers |
|------|---------------|
| `landing` | Home page, hero section, navigation, site-wide layout |
| `collections` | Collection cards, detail views, image grids, parallax effects |
| `admin` | Collection manager, image browser, drag-and-drop, metadata editing |
| `layout-engine` | BoxTree algorithm, responsive breakpoints, rating-based row composition |
| `media` | Image rendering, CDN URLs, WebP/AVIF, responsive image usage |
| `api-client` | Typed API client layer, proxy routes to Spring Boot |
| `styling` | SCSS modules, theme variables, global styles |
| `types` | TypeScript definitions — Collection, Content, enums |

### Wing: `edens-zac-backend`

**Source:** `edens.zac.backend` — Java 23 / Spring Boot 3.4 portfolio API

| Room | What it covers |
|------|---------------|
| `image-processing` | Upload pipeline, thumbnail generation, WebP conversion, EXIF extraction, GIF/MP4 handling |
| `collections` | Collection CRUD, types (Blog/Portfolio/Art/Client), ordering, pagination, nesting |
| `search` | Multi-dimensional filtering — tags, people, camera, lens, location, rating, date range |
| `client-galleries` | Password protection, SHA-256 hashing, access tokens |
| `storage` | S3 integration, CloudFront CDN config, presigned URLs |
| `database` | Flyway migrations, schema, JDBC/NamedParameterJdbcTemplate patterns |
| `config` | Spring profiles (dev/prod), exception handling, web config |

### Wing: `edens-zac-backend-go`

**Source:** `edens.zac.backend.go` — Go 1.26 backend rewrite (PoC)

| Room | What it covers |
|------|---------------|
| `collections` | Read endpoints, pagination, slug lookup |
| `database` | Repository layer, raw SQL, migrations |
| `server` | HTTP routing, middleware (CORS, logging, auth), config |

### Wing: `edens-zac-ml`

**Source:** `edens.zac.ml` — Python/FastAPI ML image tagging service

| Room | What it covers |
|------|---------------|
| `classification` | CLIP inference, zero-shot tagging, tag taxonomy (99 tags, 8 categories) |
| `face-recognition` | InsightFace detection/matching, face database (SQLite), correction tracking |
| `pipeline` | Orchestration: analyze -> CLIP -> face detect -> EXIF enrich |
| `lightroom-plugin` | Lua plugin, keyword sync, tagging workflow UI |
| `api` | FastAPI routes, Pydantic schemas |

### Wing: `lightroom-export`

**Source:** `lightroom-portfolio-export` — Lua Lightroom export plugin

| Room | What it covers |
|------|---------------|
| `export` | Image upload to Portfolio Backend API during Lightroom export |

### Wing: `job-search`

**Source:** `job-search` — Claude Code career ops pipeline

| Room | What it covers |
|------|---------------|
| `evaluation` | A-F scoring system, 10 weighted dimensions, batch processing |
| `resume` | CV tailoring, HTML templates, PDF generation (Playwright) |
| `scanning` | Portal scanning, Greenhouse/Ashby/Lever integrations |
| `tracking` | Application status, pipeline data, merge/dedup/normalize |
| `interview-prep` | Story bank (STAR+Reflection), negotiation scripts |
| `dashboard` | Go TUI (Bubble Tea), pipeline visualization |

### Wing: `running`

**Source:** `running` — Python Strava activity dashboard

| Room | What it covers |
|------|---------------|
| `sync` | Strava API integration, activity fetching |
| `visualization` | Heatmaps, dashboard, GitHub Actions automation |

### Wing: `memory`

**Source:** `Memory` — this repo

| Room | What it covers |
|------|---------------|
| `sync-engine` | Multi-repo git-diff orchestration |
| `mcp-server` | StreamableHTTP transport, tool registry |
| `user-wing` | User Wing module, halls, summary synthesizer |
| `integration` | IDE rules, stop hooks, discovery rules |

### Wing: `user`

**Source:** None (MCP-only — populated through tool calls, not file sync)

**Halls:**

| Hall | Purpose | Example thoughts |
|------|---------|-----------------|
| `questions` | Things the user is wondering about | "How does CloudFront invalidation work with S3 versioning?" |
| `discoveries` | Things the user learned | "CLIP ViT-L/14 works better than B/32 for photography tags" |
| `frustrations` | Pain points and blockers | "Spring Boot JDBC template error messages are useless" |
| `goals` | Short and long-term objectives | "Get portfolio site production-ready by end of Q2" |
| `decisions` | Choices made and their reasoning | "Chose Go over Rust for backend rewrite because of learning curve" |
| `observations` | Patterns, insights, notes | "The BoxTree algorithm gets slow above 200 images per collection" |

No rooms — the User Wing is organized by hall (thought type), not by code area. Cross-referencing to code wings happens via search and tunnels.

### Cross-Wing Tunnels

| From | To | Connection |
|------|----|-----------|
| `edens-zac` | `edens-zac-backend` | API contracts — frontend calls backend |
| `edens-zac` | `edens-zac-backend-go` | Same API, different implementation |
| `edens-zac-backend` | `edens-zac-backend-go` | Java vs Go comparison |
| `edens-zac-ml` | `lightroom-export` | Tagging pipeline — ML tags flow through Lightroom |

## Sync Engine

### State Tracking

A `sync_ledger.json` persisted at `/data/sync_ledger.json`:

```json
{
  "edens-zac": {
    "repo_path": "/repos/edens.zac",
    "last_commit_sha": "abc123f",
    "last_sync_ts": "2026-04-15T10:30:00Z",
    "files_indexed": 342,
    "status": "synced"
  }
}
```

### Initial Sync

1. Read `repos.json` — list of repos with paths and wing name mappings
2. For each repo: call `mempalace.mine(repo_path)` with the wing/room taxonomy from `mempalace.yaml`
3. Record the HEAD commit SHA in the ledger
4. Mark status as `synced`

### Incremental Sync

Triggered via MCP tool call (`memory_sync`):

1. Agent calls `memory_sync` tool (optionally with a specific wing name)
2. For each repo (or the specified one): run `git log {last_sha}..HEAD --name-status` to get changed files
3. For deleted files: remove their drawers from ChromaDB
4. For added/modified files: call `mempalace.process_file()` on each (upserts into ChromaDB)
5. Update ledger with new HEAD SHA

### Room Assignment

Files are assigned to rooms based on semantic pattern matching defined in `mempalace.yaml`, not folder structure:

```yaml
wings:
  edens-zac-backend:
    rooms:
      image-processing:
        patterns:
          - "**/ImageService*"
          - "**/Thumbnail*"
          - "**/WebP*"
          - "**/Exif*"
      collections:
        patterns:
          - "**/Collection*"
          - "**/collection*"
```

### Error Handling

If a repo path doesn't exist or git fails, that repo gets `status: "error"` in the ledger with a message. Other repos continue independently.

## User Wing

### Data Model

Each user thought is a mempalace drawer with structured metadata:

```python
{
    "id": "user-{uuid}",
    "content": "CLIP ViT-L/14 works better than B/32 for photography tags",
    "metadata": {
        "wing": "user",
        "hall": "discoveries",
        "topic": "ml-tagging",
        "source_wing": "edens-zac-ml",
        "timestamp": "2026-04-15T10:30:00Z",
        "session_id": "abc-123",
        "confidence": 0.9
    }
}
```

### Custom MCP Tools (6)

| Tool | Purpose | Key Params |
|------|---------|-----------|
| `mempalace_user_write` | File a thought into a hall | `hall`, `content`, `topic`, `source_wing` (optional) |
| `mempalace_user_search` | Semantic search across user wing | `query`, `hall` (optional), `topic` (optional), `n_results` |
| `mempalace_user_summary` | Synthesize compact user context for agent wake-up | none (returns ~300-500 token summary) |
| `mempalace_user_status` | Hall counts, recent topics, protocol guidance | none |
| `mempalace_user_merge_topics` | Merge drifted topics — rewrite metadata, deduplicate | `source_topic`, `target_topic`, `hall` (optional) |
| `mempalace_user_prune` | Remove stale/low-value thoughts by age, similarity, or cluster | `hall`, `topic`, `older_than_days`, `dry_run` |

### Summary Synthesizer

`mempalace_user_summary` queries each hall for recent high-relevance drawers and assembles a structured summary (~300-500 tokens):

```
## User Context
**Goals:** Get portfolio production-ready by Q2; evaluate Go vs Java backend
**Recent decisions:** Chose semantic rooms over folder-based rooms for mempalace taxonomy
**Active frustrations:** Spring Boot JDBC error messages; BoxTree perf above 200 images
**Recent discoveries:** CLIP ViT-L/14 outperforms B/32 for photography tags
**Open questions:** How does CloudFront invalidation work with S3 versioning?
**Observations:** BoxTree algorithm slows above 200 images per collection
```

### Deduplication

Before writing, `mempalace_user_write` checks cosine similarity against recent drawers in the same hall. If distance < 0.15, it updates the existing drawer rather than creating a duplicate.

### Topic Merging

`mempalace_user_merge_topics(source_topic, target_topic, hall=None)`:

1. Find all drawers where `topic == source_topic` (optionally scoped to a hall)
2. Update metadata to `target_topic`
3. Run dedup pass — near-duplicates (cosine < 0.15) collapsed, keeping the richer entry
4. Return: `{ merged: N, deduped: N, remaining: N }`

### Pruning

`mempalace_user_prune(hall=None, topic=None, older_than_days=90, dry_run=True)`:

1. Find candidates matching filters
2. Cluster by similarity — if N thoughts say roughly the same thing, keep the best one
3. If `dry_run`: return what would be pruned. If not: delete and return count.

## MCP HTTP Server

### Transport

StreamableHTTP using the `mcp` Python SDK's server utilities (`mcp[server]` extras). The SDK handles JSON-RPC framing, SSE streaming, and protocol compliance. We configure it with our tool registry and serve via uvicorn.

### Tool Registry

```python
TOOLS = {}

# mempalace's 29 tools
from mempalace.mcp_server import get_tools
TOOLS.update(get_tools())

# User Wing tools (6)
TOOLS["mempalace_user_write"] = user_wing.handle_write
TOOLS["mempalace_user_search"] = user_wing.handle_search
TOOLS["mempalace_user_summary"] = user_wing.handle_summary
TOOLS["mempalace_user_status"] = user_wing.handle_status
TOOLS["mempalace_user_merge_topics"] = user_wing.handle_merge_topics
TOOLS["mempalace_user_prune"] = user_wing.handle_prune

# Sync tools (2)
TOOLS["memory_sync"] = sync_engine.handle_sync
TOOLS["memory_sync_status"] = sync_engine.handle_sync_status
```

**Total: ~37 tools** (29 mempalace + 6 user wing + 2 sync)

### Endpoints

- `POST /mcp` — StreamableHTTP MCP protocol (JSON-RPC)
- `GET /health` — Returns status, tool count, last sync timestamp

### Port

`8787` (configurable via `MEMORY_PORT` env var)

## Docker Container

### Dockerfile

- Base: `python:3.12-slim`
- Install `git` (needed for diff-based sync)
- `pip install mempalace` + this package
- Copy `src/`, `config/`, `entrypoint.sh`
- Expose 8787

### docker-compose.yml

```yaml
services:
  memory:
    build: .
    ports:
      - "8787:8787"
    volumes:
      - palace_data:/data
      - ~/Code/edens.zac:/repos/edens.zac:ro
      - ~/Code/edens.zac.backend:/repos/edens.zac.backend:ro
      - ~/Code/edens.zac.backend.go:/repos/edens.zac.backend.go:ro
      - ~/Code/edens.zac.ml:/repos/edens.zac.ml:ro
      - ~/Code/lightroom-portfolio-export:/repos/lightroom-portfolio-export:ro
      - ~/Code/job-search:/repos/job-search:ro
      - ~/Code/running:/repos/running:ro
      - ~/Code/Memory:/repos/Memory:ro
    environment:
      - MEMORY_PORT=8787
      - PALACE_PATH=/data
      - CONFIG_PATH=/config

volumes:
  palace_data:
```

### entrypoint.sh

1. Check if `/data/sync_ledger.json` exists
2. If not (first boot): run full sync across all repos
3. If yes (subsequent boot): skip sync, validate ledger
4. Start uvicorn on `0.0.0.0:8787`

## IDE Integration

### Primary: Claude Code

**MCP server config** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "mempalace": {
      "url": "http://localhost:8787/mcp"
    }
  }
}
```

**Stop hook** (`~/.claude/settings.json` hooks section):
On agent stop, nudge to capture user context via `mempalace_user_write` if it hasn't already.

**Discovery:** Instructions in `~/.claude/CLAUDE.md` or project-level CLAUDE.md files telling agents to call `mempalace_user_summary` at session start and `mempalace_search` when investigating code.

### Secondary: Cursor

**`.mdc` rule files** installed to `~/.cursor/rules/`:

- `user-wing.mdc` — alwaysApply, tells agents to capture user thoughts at session end
- `mempalace-discovery.mdc` — alwaysApply, tells agents to search palace at session start

### Three Automation Layers

1. **Protocol injection** — `mempalace_user_status` returns "capture user context" guidance + tip to call `mempalace_user_summary`
2. **Rule files** — Tell agents at session end to call `mempalace_user_write` once per distinct user thought with correct `hall`/`topic`
3. **Stop hook** — System backstop: when an agent tries to stop, followup nudges context capture if it hasn't happened

## Testing Strategy

- `test_sync_engine.py` — Test ledger CRUD, git-diff parsing, incremental sync logic (mock git + mempalace)
- `test_user_wing.py` — Test all 6 tools: write/search/summary/status/merge/prune, dedup logic, hall validation
- `test_mcp_server.py` — Test JSON-RPC routing, tool registry, health endpoint, error responses
- `test_tools.py` — Test room assignment pattern matching, repos.json parsing

## Dependencies

```
mempalace>=3.3.0
mcp[server]>=1.0.0
uvicorn>=0.30.0
pyyaml>=6.0,<7
```

Uses the `mcp` SDK for protocol-compliant StreamableHTTP transport. No FastAPI/Starlette needed.

## Excluded Repos

The following repos under `~/Code/` are excluded from indexing:

| Repo | Reason |
|------|--------|
| `coding_challenges` | Notes/links, not a codebase |
| `interviewprep` | Stale CRA app |
| `python` | Interview prep docs + utility scripts |
| `python_tests` | Test data, not a project |
| `learning` | Algorithms learning materials |
| `test-bitch` | Test/throwaway project |
| `themancalledzac` | Obsidian vault — personal notes, not code |
| `settings` | System config files |
| `job-search-backup` | Backup of job-search |
| `jobs` | Stale/related to job-search |
| `Keys` | Credentials — never index |
| `ExampleRepos`, `old_computer`, `mysql_bootcamp` | Archives/learning |
