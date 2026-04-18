# Taxonomy Refactor: Align with Native mempalace Format

**Status:** Ready for implementation
**Date:** 2026-04-15
**Context:** Our `config/mempalace.yaml` uses a custom glob-pattern format that is incompatible with mempalace's native data model. This refactor aligns our config with what `process_file()` and `detect_room()` actually expect.

---

## Problem

We pass `wing_rooms` (a dict of room-name → `{patterns: [...]}`) to `process_file()`, but mempalace expects `rooms` as a **list of dicts** with `name`, `description`, and `keywords` fields. Our glob patterns are never used by mempalace — `detect_room()` scores using keyword substring matching against content and filepath, not glob matching.

### Current flow (broken)

```
config/mempalace.yaml → SyncEngine loads as dict → passes dict to process_file(rooms=wing_rooms)
                                                     ↓
                                            process_file expects list[dict] with "name"/"keywords"
                                            detect_room() ignores our patterns entirely
```

### Target flow (aligned)

```
config/mempalace.yaml → SyncEngine loads rooms as list[dict] → passes to process_file(rooms=rooms_list)
                                                                  ↓
                                                         detect_room() uses keywords for routing
```

---

## What mempalace Actually Expects

Source: `mempalace` v3.3.0 installed at `.venv/lib/python3.13/site-packages/mempalace/`

### `process_file()` signature (miner.py:559)

```python
def process_file(
    filepath: Path,
    project_path: Path,
    collection,
    wing: str,
    rooms: list,          # <-- list of dicts, NOT our nested dict
    agent: str,
    dry_run: bool,
    closets_col=None,
) -> tuple:
```

### `detect_room()` routing (miner.py:286-325)

Priority order:
1. **Folder path match** — checks if any folder in filepath matches a room name or keyword
2. **Filename match** — checks if filename stem matches a room name
3. **Content keyword scoring** — counts keyword occurrences in first 2000 chars (case-insensitive)
4. **Fallback** — returns `"general"`

### `detect_hall()` (miner.py:453-474)

Halls are detected automatically from content using global `DEFAULT_HALL_KEYWORDS` in `config.py`. They categorize content TYPE (emotional, technical, creative, etc.) orthogonally to rooms which categorize TOPIC. Hall detection is not configurable per-room — it uses global config.

### Room dict structure expected

```python
{"name": "frontend", "description": "UI components and pages", "keywords": ["component", "page", "layout"]}
```

---

## Files to Change

### 1. `config/mempalace.yaml` — Full rewrite

**Before** (custom glob format):
```yaml
wings:
  edens-zac:
    rooms:
      landing:
        patterns:
          - "**/page.tsx"
          - "**/Hero*"
```

**After** (native mempalace format):
```yaml
wings:
  edens-zac:
    rooms:
      - name: landing
        description: "Landing page, hero sections, navigation, and site layout"
        keywords: [page, hero, nav, header, footer, layout, landing]
      - name: collections
        description: "Photo collection browsing, parallax effects, and image grids"
        keywords: [collection, parallax, imagegrid, gallery, grid]
      - name: admin
        description: "Admin panel, collection management, image browser, drag-drop, metadata editing"
        keywords: [admin, collectionmanager, imagebrowser, dragdrop, metadata, edit]
      - name: layout-engine
        description: "BoxTree layout engine, breakpoint logic, responsive layout calculations"
        keywords: [boxtree, layout, breakpoint, responsive, box, tree]
      - name: media
        description: "Image handling, CDN integration, WebP conversion, responsive images"
        keywords: [image, cdn, webp, responsive, optimize, thumbnail]
      - name: api-client
        description: "API client, proxy layer, data fetching"
        keywords: [api, proxy, client, fetch, request, endpoint]
      - name: styling
        description: "SCSS/CSS styles, theming, design tokens"
        keywords: [scss, css, theme, style, color, font, spacing]
      - name: types
        description: "TypeScript type definitions, interfaces, and enums"
        keywords: [type, interface, enum, model, dto]

  edens-zac-backend:
    rooms:
      - name: image-processing
        description: "Image upload, thumbnail generation, WebP conversion, EXIF extraction, GIF processing"
        keywords: [imageservice, thumbnail, webp, exif, gif, upload, convert, resize]
      - name: collections
        description: "Collection CRUD operations and data models"
        keywords: [collection, album, organize, group]
      - name: search
        description: "Search and filtering across images and collections"
        keywords: [search, filter, query, find, index]
      - name: client-galleries
        description: "Password-protected client galleries and access control"
        keywords: [clientgallery, password, access, share, client, protect]
      - name: storage
        description: "S3 storage, CloudFront CDN integration"
        keywords: [s3, cloudfront, storage, bucket, cdn, aws]
      - name: database
        description: "Database migrations, Flyway, JDBC repositories"
        keywords: [migration, flyway, repository, jdbc, sql, schema]
      - name: config
        description: "Application configuration, exception handling, web config"
        keywords: [config, application, exception, webconfig, cors, security]

  edens-zac-backend-go:
    rooms:
      - name: collections
        description: "Collection handlers and data models in Go"
        keywords: [collection, handler, model]
      - name: database
        description: "Repository layer, migrations, SQL queries"
        keywords: [repository, migration, sql, database, query]
      - name: server
        description: "HTTP router, middleware, server config, entrypoint"
        keywords: [router, middleware, server, config, main, http, handler]

  edens-zac-ml:
    rooms:
      - name: classification
        description: "CLIP-based image classification, tagging, taxonomy, zero-shot labeling"
        keywords: [clip, tag, taxonomy, zero_shot, classify, label, embedding]
      - name: face-recognition
        description: "Face detection and recognition using InsightFace"
        keywords: [face, insightface, recognition, detect, identity]
      - name: pipeline
        description: "ML pipeline orchestration and analysis workflows"
        keywords: [pipeline, orchestrate, analyze, workflow, batch]
      - name: lightroom-plugin
        description: "Lightroom Lua plugin for keyword sync"
        keywords: [lua, lightroom, keyword, plugin, export]
      - name: api
        description: "FastAPI routes, Pydantic schemas, application entrypoint"
        keywords: [route, schema, fastapi, endpoint, app, main]

  lightroom-export:
    rooms:
      - name: export
        description: "Lightroom export plugin scripts"
        keywords: [lua, lightroom, export, plugin]

  job-search:
    rooms:
      - name: evaluation
        description: "Job posting evaluation and scoring"
        keywords: [eval, score, grade, rank, assess]
      - name: resume
        description: "Resume generation, templates, PDF output"
        keywords: [resume, cv, template, pdf, generate]
      - name: scanning
        description: "Job board scraping from Greenhouse, Ashby, Lever, etc."
        keywords: [scan, greenhouse, ashby, lever, portal, scrape, crawl]
      - name: tracking
        description: "Application pipeline tracking and status management"
        keywords: [track, pipeline, status, merge, application, progress]
      - name: interview-prep
        description: "Interview stories, STAR format, negotiation prep"
        keywords: [interview, story, star, negotiation, prep, behavioral]
      - name: dashboard
        description: "TUI dashboard using Bubble Tea"
        keywords: [tui, dashboard, bubble, view, render, terminal]

  running:
    rooms:
      - name: sync
        description: "Strava API sync and data fetching"
        keywords: [strava, fetch, sync, api, activity, run]
      - name: visualization
        description: "Heatmaps, dashboards, plotting, GitHub Actions publishing"
        keywords: [heatmap, dashboard, plot, github_actions, visualize, chart]

  memory:
    rooms:
      - name: sync-engine
        description: "Multi-repo git-diff sync orchestrator"
        keywords: [sync, engine, ledger, diff, incremental, repo]
      - name: mcp-server
        description: "FastMCP HTTP server and tool definitions"
        keywords: [mcp, server, tool, http, fastmcp]
      - name: user-wing
        description: "User conversation wing management"
        keywords: [user, wing, conversation, session]
      - name: integration
        description: "IDE integration rules, hooks, and Cursor/Claude config"
        keywords: [integration, mdc, hook, cursor, claude, ide]
```

### 2. `src/sync_engine.py` — Fix room loading

The `rooms` parameter passed to `process_file()` must change from a nested dict to a list of dicts.

**Lines 111-112, current:**
```python
wing_rooms = self.taxonomy.get("wings", {}).get(name, {}).get("rooms", {})
```

**Change to:**
```python
wing_config = self.taxonomy.get("wings", {}).get(name, {})
wing_rooms = wing_config.get("rooms", [])
```

This is a minimal change because the new YAML already stores rooms as a list of dicts under each wing — the only difference is that it's now a list instead of a dict, which is exactly what `process_file()` expects.

**Same fix at line 159** (in `incremental_sync`):
```python
wing_rooms = self.taxonomy.get("wings", {}).get(name, {}).get("rooms", {})
```
Change to:
```python
wing_config = self.taxonomy.get("wings", {}).get(name, {})
wing_rooms = wing_config.get("rooms", [])
```

### 3. `tests/conftest.py` — Update `tmp_config` fixture (lines 32-43)

**Current:**
```python
taxonomy = {
    "wings": {
        "test-wing": {
            "rooms": {
                "general": {
                    "patterns": ["*"],
                }
            }
        }
    }
}
```

**Change to:**
```python
taxonomy = {
    "wings": {
        "test-wing": {
            "rooms": [
                {
                    "name": "general",
                    "description": "All project files",
                    "keywords": [],
                }
            ]
        }
    }
}
```

### 4. `src/tools.py` — No changes needed

Confirmed: `tools.py` does not reference the taxonomy config, `detect_room`, or rooms. No changes required.

---

## What NOT to Change

- **`config/repos.json`** — stays the same, it maps wing names to repo paths
- **`SyncLedger`** — unchanged, it tracks sync state not taxonomy
- **`get_head_sha()` / `get_changed_files()`** — pure git ops, unrelated
- **Hall configuration** — `detect_hall()` uses global defaults from `mempalace.config`. We could add custom hall_keywords later but it's not part of this refactor.

---

## Verification Checklist

1. `pytest tests/` passes with updated config and fixtures
2. `SyncEngine.full_sync()` calls `process_file()` with a `list[dict]` rooms arg
3. `detect_room()` successfully routes files using keywords (test with a real repo if possible)
4. No references to `patterns` remain in `config/mempalace.yaml`
5. `python -c "import yaml; print(yaml.safe_load(open('config/mempalace.yaml')))"` parses cleanly

---

## Design Decisions

**Why keywords over glob patterns:** `detect_room()` uses keyword substring matching — it literally does `content.lower().count(kw.lower())`. Glob patterns were our invention that mempalace never consumed. Keywords align with the actual routing logic.

**Why keep the multi-wing wrapper:** mempalace's per-repo format uses a flat `wing: name` + `rooms: [...]`. Our central config wraps multiple wings under `wings:` because we manage many repos from one config. The SyncEngine extracts per-wing room lists before passing to `process_file()`, so this is fine.

**Why no halls in this refactor:** Hall detection is automatic from content keywords via global config. Adding per-wing hall customization would require extending `MempalaceConfig`, which is a separate effort.

**Keyword selection strategy:** Keywords were derived from the original glob patterns by extracting the meaningful stems. E.g., `**/Hero*` → `hero`, `**/ImageService*` → `imageservice`. Folder-based routing in `detect_room()` handles cases like `**/admin/**` naturally since it checks folder names.
