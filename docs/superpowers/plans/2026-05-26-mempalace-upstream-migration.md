# Mempalace Upstream Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task = one commit.

**Goal:** Migrate the Memory wrapper (`~/Code/Memory`, branch `feat/mems-full-implementation`) from `mempalace==3.3.0` to `mempalace>=3.3.6`, wire Claude Code auto-save hooks before the 30-day JSONL retention deletes them, and replace every piece of wrapper code that duplicates upstream functionality — while preserving the two pieces of wrapper-unique IP: the **User Wing** (halls) and **wingpack** (portable per-repo bundles).

**Architecture:** The wrapper stays a thin orchestrator on top of `mempalace`. After this plan: wrapper-unique modules are [src/user_wing.py](../../../src/user_wing.py), [src/wing_pack.py](../../../src/wing_pack.py), [src/wing_publish.py](../../../src/wing_publish.py), [src/auto_publish.py](../../../src/auto_publish.py), [src/sync_engine.py](../../../src/sync_engine.py), [src/mcp_http_server.py](../../../src/mcp_http_server.py), [src/wing_user_snapshot.py](../../../src/wing_user_snapshot.py), the user-wing slice of [src/restore_wing_user.py](../../../src/restore_wing_user.py), and the `mems` CLI. Everything else delegates to upstream's `mempalace` CLI or imports.

**Tech Stack:** Python 3.12, `mempalace>=3.3.6`, FastMCP, hatchling, pytest, ruff. Docker Compose for runtime. Upstream cloned to `~/Code/mempalace` (reference only — not vendored).

---

## File Structure

**Files modified:**
- [pyproject.toml](../../../pyproject.toml) — bump pins (P0.1)
- [requirements.txt](../../../requirements.txt) — bump pins (P0.1)
- [Dockerfile](../../../Dockerfile) — env var rename + extras (P0.2, P4.5)
- [entrypoint.sh](../../../entrypoint.sh) — env var rename (P0.2)
- [src/tools.py](../../../src/tools.py) — diary wing forwarding (P0.3), KG comment cleanup (P0.4)
- [src/mcp_http_server.py](../../../src/mcp_http_server.py) — diary wing param exposure (P0.3)
- [src/restore_wing_user.py](../../../src/restore_wing_user.py) — narrow to user_wing only (P3.3)
- [src/sync_engine.py](../../../src/sync_engine.py) — add post-ingest `mempalace sync` prune (P3.5)
- [mems_cli/commands/palace_ops.py](../../../mems_cli/commands/palace_ops.py) — shell out to upstream CLI (P3.4)
- [scripts/install_claude_code.sh](../../../scripts/install_claude_code.sh) — wire Stop + PreCompact hooks (P2.5)
- [config/mempalace.yaml](../../../config/mempalace.yaml) — remove dead `filters` taxonomy reference (P3.1), wire upstream env knobs (P4.1)
- [README.md](../../../README.md) — document mempalace 3.3.6 baseline (P5.3)

**Files created:**
- [integration/claude_code/hooks_install.py](../../../integration/claude_code/hooks_install.py) — Python merge helper used by `install_claude_code.sh` (P2.5)
- [scripts/backfill_claude_sessions.sh](../../../scripts/backfill_claude_sessions.sh) — one-shot backfill of `~/.claude/projects` into `wing_claude_imports` (P2.6)
- [~/Documents/Claude_JSONL_Backup/](~/Documents/Claude_JSONL_Backup/) — out-of-tree, created by P2.1

**Files deleted:**
- [src/filters.py](../../../src/filters.py) (P3.1)
- [tests/test_filters.py](../../../tests/test_filters.py) (P3.1)
- [integration/stop-hook.sh](../../../integration/stop-hook.sh) (P3.2 — after P2 ships)
- [integration/mempalace-discovery.mdc](../../../integration/mempalace-discovery.mdc) (P3.7 — decision-gated)
- [integration/user-wing.mdc](../../../integration/user-wing.mdc) (P3.7 — decision-gated)

**Files installed out-of-tree (Claude Code config):**
- `~/.claude/settings.json` — Stop + PreCompact hook entries (P2.3, P2.4)
- `~/.claude/commands/save.md` — manual save slash command (P2.7)

**Files left untouched (wrapper-unique IP):**
- [src/user_wing.py](../../../src/user_wing.py)
- [src/wing_pack.py](../../../src/wing_pack.py)
- [src/wing_publish.py](../../../src/wing_publish.py)
- [src/auto_publish.py](../../../src/auto_publish.py)
- [src/wing_user_snapshot.py](../../../src/wing_user_snapshot.py)
- All `mems_cli/commands/{repo_registry,publishing,tickets,hybrid,search}.py`

---

## Phase 0 — Critical Fixes + Pin Bump

**Goal:** Bump the mempalace pin, rename dead env vars, fix the diary-wing forwarding gap, delete stale comments. ~1 hour total. No behavioral risk.

### Task 0.1: Bump `mempalace` to `>=3.3.6` and `chromadb` to `>=1.5.4`

**Files:**
- Modify: [pyproject.toml](../../../pyproject.toml)
- Modify: [requirements.txt](../../../requirements.txt)

- [ ] **Step 1: Update `pyproject.toml` dependencies**

Replace the `dependencies` block:

```toml
dependencies = [
    "mempalace>=3.3.6",
    "mcp[cli]>=1.0.0",
    "uvicorn>=0.30.0",
    "starlette>=0.38.0",
    "sentence-transformers>=2.7.0",
    "pyyaml>=6.0,<7",
    "h2>=4.1.0",
    "chromadb>=1.5.4",
]
```

- [ ] **Step 2: Update `requirements.txt`**

```text
mempalace>=3.3.6
mcp[cli]>=1.0.0
uvicorn>=0.30.0
starlette>=0.38.0
pyyaml>=6.0,<7
h2>=4.1.0
# chromadb + sentence-transformers arrive transitively via mempalace;
# listed explicitly here so Docker builds fail loudly if upstream drops them
chromadb>=1.5.4
sentence-transformers>=2.7.0
```

- [ ] **Step 3: Install new pins**

```bash
cd /Users/themancalledzac/Code/Memory
pip install -e ".[dev]"
```

Expected: `Successfully installed mempalace-3.3.6 chromadb-1.5.x ...`

- [ ] **Step 4: Verify installed version**

```bash
python3 -c "import mempalace, importlib.metadata; print(importlib.metadata.version('mempalace'))"
```

Expected: `3.3.6` or higher.

- [ ] **Step 5: Run packaging tests**

```bash
pytest tests/test_packaging.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "chore(deps): bump mempalace to >=3.3.6, chromadb floor to >=1.5.4"
```

---

### Task 0.2: Rename `EMBEDDING_MODEL` → `MEMPALACE_EMBEDDING_MODEL` (dead env var)

**Files:**
- Modify: [Dockerfile](../../../Dockerfile) (line 18)
- Modify: [entrypoint.sh](../../../entrypoint.sh)

**Context:** The wrapper's `EMBEDDING_MODEL` env var is not read by mempalace ([mempalace/config.py:538](../../../../mempalace/mempalace/config.py) reads `MEMPALACE_EMBEDDING_MODEL`). The wrapper's `DEFAULT_EMBEDDING_MODEL` constant in [src/tools.py:81](../../../src/tools.py:81) is only used for the manifest field — leave it.

- [ ] **Step 1: Edit Dockerfile line 18**

Replace:

```dockerfile
    EMBEDDING_MODEL=all-MiniLM-L6-v2 \
```

with:

```dockerfile
    MEMPALACE_EMBEDDING_MODEL=all-MiniLM-L6-v2 \
```

- [ ] **Step 2: Check entrypoint.sh propagates the new name**

```bash
grep -n 'EMBEDDING_MODEL' entrypoint.sh
```

If any line references the old name, replace it with `MEMPALACE_EMBEDDING_MODEL`. (Quick scan said no references — but verify.)

- [ ] **Step 3: Build and verify the container reads the new var**

```bash
docker build -t mems-test -f Dockerfile .
docker run --rm mems-test env | grep MEMPALACE_EMBEDDING_MODEL
```

Expected: `MEMPALACE_EMBEDDING_MODEL=all-MiniLM-L6-v2`

- [ ] **Step 4: Commit**

```bash
git add Dockerfile entrypoint.sh
git commit -m "fix(docker): rename EMBEDDING_MODEL → MEMPALACE_EMBEDDING_MODEL (dead env var; upstream reads the prefixed name)"
```

---

### Task 0.3: Forward `wing` param on `tool_diary_write` / `tool_diary_read`

**Files:**
- Modify: [src/tools.py:600-620](../../../src/tools.py:600)
- Modify: [src/mcp_http_server.py:378-405](../../../src/mcp_http_server.py:378)
- Test: [tests/test_tools.py](../../../tests/test_tools.py)

**Context:** Upstream 3.3.3 added `wing: str = ""` to `tool_diary_write/read` (#659, #1145). Empty-string means "all wings" per #1145. Wrapper currently drops the param.

- [ ] **Step 1: Write failing test**

Append to [tests/test_tools.py](../../../tests/test_tools.py):

```python
def test_handle_diary_write_forwards_wing(monkeypatch, tmp_path):
    from src import tools
    captured = {}

    def fake_tool_diary_write(agent_name, entry, topic, wing):
        captured["wing"] = wing
        return {"ok": True}

    monkeypatch.setattr(
        "mempalace.mcp_server.tool_diary_write",
        fake_tool_diary_write,
    )
    tools.handle_diary_write(
        palace_path=str(tmp_path),
        agent_name="claude",
        entry="test entry",
        topic="general",
        wing="wing_test",
    )
    assert captured["wing"] == "wing_test"


def test_handle_diary_read_forwards_wing(monkeypatch, tmp_path):
    from src import tools
    captured = {}

    def fake_tool_diary_read(agent_name, last_n, wing):
        captured["wing"] = wing
        return {"entries": []}

    monkeypatch.setattr(
        "mempalace.mcp_server.tool_diary_read",
        fake_tool_diary_read,
    )
    tools.handle_diary_read(
        palace_path=str(tmp_path),
        agent_name="claude",
        last_n=10,
        wing="wing_test",
    )
    assert captured["wing"] == "wing_test"
```

- [ ] **Step 2: Run test, expect failure**

```bash
pytest tests/test_tools.py::test_handle_diary_write_forwards_wing tests/test_tools.py::test_handle_diary_read_forwards_wing -v
```

Expected: FAIL — `handle_diary_write` / `handle_diary_read` do not accept `wing` kwarg.

- [ ] **Step 3: Update `src/tools.py`**

Find the diary handlers (around lines 600-620). Update signatures:

```python
def handle_diary_write(
    palace_path: str,
    agent_name: str,
    entry: str,
    topic: str = "general",
    wing: str = "",
) -> dict:
    """Append a diary entry for an agent. Optionally scope to a specific wing."""
    from mempalace.mcp_server import tool_diary_write

    _bind_palace(palace_path)
    return tool_diary_write(agent_name=agent_name, entry=entry, topic=topic, wing=wing)


def handle_diary_read(
    palace_path: str,
    agent_name: str,
    last_n: int = 10,
    wing: str = "",
) -> dict:
    """Read an agent's recent diary entries. Empty wing returns entries from every wing."""
    from mempalace.mcp_server import tool_diary_read

    _bind_palace(palace_path)
    return tool_diary_read(agent_name=agent_name, last_n=last_n, wing=wing)
```

- [ ] **Step 4: Update MCP tool signatures in `src/mcp_http_server.py`**

Find `mempalace_diary_write` and `mempalace_diary_read` (around lines 380-400). Update:

```python
@mcp.tool()
def mempalace_diary_write(
    agent_name: str,
    entry: str,
    topic: str = "general",
    wing: str = "",
) -> dict:
    """Append a diary entry for an agent. Optionally scope to a specific wing."""
    return handle_diary_write(
        palace_path=_palace_path(),
        agent_name=agent_name,
        entry=entry,
        topic=topic,
        wing=wing,
    )


@mcp.tool()
def mempalace_diary_read(agent_name: str, last_n: int = 10, wing: str = "") -> dict:
    """Read an agent's recent diary entries. Empty wing returns entries from every wing."""
    return handle_diary_read(
        palace_path=_palace_path(),
        agent_name=agent_name,
        last_n=last_n,
        wing=wing,
    )
```

- [ ] **Step 5: Run test, expect pass**

```bash
pytest tests/test_tools.py::test_handle_diary_write_forwards_wing tests/test_tools.py::test_handle_diary_read_forwards_wing -v
```

Expected: PASS.

- [ ] **Step 6: Run full tools test suite to catch regressions**

```bash
pytest tests/test_tools.py tests/test_mcp_server.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/tools.py src/mcp_http_server.py tests/test_tools.py
git commit -m "feat(diary): forward wing param on diary tools (upstream 3.3.3 #659/#1145)"
```

---

### Task 0.4: Remove obsolete "KG bound at import" caveat

**Files:**
- Modify: [src/tools.py](../../../src/tools.py) (docstrings + `_bind_palace` comment)

**Context:** Upstream 3.3.5 #1136 fixed the module-level `_kg` singleton. KG is now resolved per-call via lazy cache. Wrapper's caveats are obsolete.

- [ ] **Step 1: Locate the obsolete comments**

```bash
grep -n "KG is bound\|Runtime-only: KG\|NOT retargeted\|KG singleton" src/tools.py
```

- [ ] **Step 2: Edit `src/tools.py` to remove the caveats**

Three places (line numbers approximate — find by content):

Replace the `_bind_palace` block comment:

```python
def _bind_palace(palace_path: str):
    """Set MEMPALACE_PALACE_PATH so subsequent mempalace tool calls hit the right palace.

    Both chroma collections and the knowledge graph are resolved per-call from
    the env var (upstream 3.3.5 #1136 + #1383), so this is sufficient for
    multi-tenant hosts that rotate palaces between tool invocations.
    """
    os.environ["MEMPALACE_PALACE_PATH"] = palace_path
```

In `handle_kg_query`, `handle_kg_add`, `handle_kg_invalidate`, `handle_kg_timeline`, `handle_kg_stats` docstrings: remove any line containing "Runtime-only: KG is bound to the palace path at module import."

- [ ] **Step 3: Run tools test suite**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass (this is doc-only).

- [ ] **Step 4: Commit**

```bash
git add src/tools.py
git commit -m "docs(tools): remove obsolete 'KG bound at import' caveat (fixed upstream 3.3.5 #1136)"
```

---

## Phase 1 — Audits (no-change expected)

**Goal:** Verify four upstream behavior changes don't break wrapper paths. Each audit is a grep + decision; if a real issue is found, file it as a follow-up task rather than expanding this plan.

### Task 1.1: Audit collection-open paths for missing `embedding_function`

**Files (read-only audit):**
- [src/tools.py](../../../src/tools.py), [src/sync_engine.py](../../../src/sync_engine.py), [src/user_wing.py](../../../src/user_wing.py), [src/wing_user_snapshot.py](../../../src/wing_user_snapshot.py), [src/restore_wing_user.py](../../../src/restore_wing_user.py)

**Context:** Upstream 3.3.4 #1299 — `client.get_collection` / `client.create_collection` called without `embedding_function=` silently rebinds to ChromaDB's built-in default (potential SIGSEGV on Python 3.14 + Apple Silicon). All wrapper calls should route through `mempalace.palace.get_collection` (which uses `ChromaBackend.get_collection` and resolves the EF).

- [ ] **Step 1: Search for any direct chromadb collection open**

```bash
grep -RIn 'client\.get_collection\|client\.create_collection\|PersistentClient' src/ mems_cli/ 2>/dev/null
```

Expected: only matches inside `get_collection` import callers; no direct `client.*` calls.

- [ ] **Step 2: Confirm all wrapper collection opens go via `mempalace.palace.get_collection`**

```bash
grep -RIn 'from mempalace.palace import get_collection\|mempalace.palace.get_collection' src/ 2>/dev/null
```

Expected: matches in [src/tools.py](../../../src/tools.py), [src/sync_engine.py](../../../src/sync_engine.py), [src/user_wing.py](../../../src/user_wing.py), [src/wing_user_snapshot.py](../../../src/wing_user_snapshot.py), [src/restore_wing_user.py](../../../src/restore_wing_user.py). No direct chromadb-client calls.

- [ ] **Step 3: If any direct call found, file a follow-up issue**

Create a TODO in the executing agent's task list naming the file + line; do not expand this plan.

- [ ] **Step 4: Commit audit note (only if changes made)**

If no changes needed, skip the commit. If a fix was applied:

```bash
git add <files>
git commit -m "fix(chroma): route collection opens through ChromaBackend (upstream 3.3.4 #1299)"
```

---

### Task 1.2: Audit KG callers for partial-date strings

**Files (read-only audit):**
- [src/tools.py](../../../src/tools.py), [src/mcp_http_server.py](../../../src/mcp_http_server.py), wherever `valid_from`/`valid_to`/`as_of`/`ended` is forwarded

**Context:** Upstream 3.3.5 #1164 rejects `"2026"`, `"2026-05"`, `"yesterday"` with `ValueError`. The wrapper forwards strings as-is.

- [ ] **Step 1: Search for KG date string usage**

```bash
grep -RIn 'valid_from\|valid_to\|as_of\|ended' src/ mems_cli/ 2>/dev/null | grep -v '\.pyc' | head -30
```

- [ ] **Step 2: Inspect each result; flag any string-literal partial dates**

For each match: if the value is hardcoded, ensure it's full ISO (`YYYY-MM-DD` or full ISO timestamp). If it's user input, no change needed — `ValueError` from upstream is the right surface.

- [ ] **Step 3: If any test fixtures use partial dates, update them**

```bash
grep -RIn '"2026"\|"2026-[0-9]\{2\}"' tests/ 2>/dev/null
```

- [ ] **Step 4: Commit (only if changes made)**

If no changes needed, skip. Otherwise:

```bash
git add tests/<file>
git commit -m "test(kg): use full ISO dates (upstream 3.3.5 #1164 rejects partials)"
```

---

### Task 1.3: Audit tests for `create_tunnel` calls before mining

**Files (read-only audit):**
- [tests/test_palace_client.py](../../../tests/test_palace_client.py), [tests/test_mcp_server.py](../../../tests/test_mcp_server.py)

**Context:** Upstream 3.3.6 #1468 — `tool_create_tunnel` validates source/target rooms have ≥1 drawer. Pre-mining tunnel creation now raises `ValueError`.

- [ ] **Step 1: Grep for tunnel creation in tests**

```bash
grep -RIn 'create_tunnel\|tool_create_tunnel\|handle_create_tunnel' tests/ 2>/dev/null
```

- [ ] **Step 2: For each match, check fixture ordering**

If a test creates a tunnel before its endpoints have drawers, reorder: file a drawer first, then create the tunnel.

- [ ] **Step 3: Run affected test files**

```bash
pytest tests/test_palace_client.py tests/test_mcp_server.py -v
```

If any tests fail with `ValueError` about empty rooms, fix the fixture order.

- [ ] **Step 4: Commit (only if changes made)**

```bash
git add tests/<file>
git commit -m "test(tunnel): mine endpoints before creating tunnels (upstream 3.3.6 #1468)"
```

---

### Task 1.4: Audit `entity_registry.research` callers

**Files (read-only audit):**
- Anywhere `entity_registry.research` is referenced

**Context:** Upstream 3.3.1 #811 changed `research()` to local-only by default; outbound network requires `allow_network=True`.

- [ ] **Step 1: Search**

```bash
grep -RIn 'entity_registry\.research\|EntityRegistry.*research' src/ mems_cli/ tests/ 2>/dev/null
```

- [ ] **Step 2: If any matches, decide policy**

If the wrapper relies on network-enabled research, add `allow_network=True` explicitly. If not used, no action.

- [ ] **Step 3: Commit (only if changes made)**

```bash
git add <files>
git commit -m "fix(entity): explicit allow_network on research calls (upstream 3.3.1 #811)"
```

---

## Phase 2 — Claude Code Auto-Save (URGENT)

**Goal:** Wire transcript auto-mining hooks before the 30-day Claude Code JSONL retention deletes more data. 528 files / 156 MB currently sit in [~/.claude/projects/](~/.claude/projects/) unmined.

> **Decision: vendor or reference upstream hooks?** This plan **references** `~/Code/mempalace/hooks/*.sh` directly via absolute paths. Pros: zero drift, picks up upstream fixes. Cons: breaks if `~/Code/mempalace` moves. Mitigation: add a doctor check that pre-flights the path. Vendoring is documented as a follow-up alternative.

### Task 2.1: Back up `~/.claude/projects/` immediately

**Files:**
- Create: `~/Documents/Claude_JSONL_Backup/` (out-of-tree)

- [ ] **Step 1: Run the backup script**

```bash
mkdir -p ~/Documents/Claude_JSONL_Backup
rsync -av --info=stats2 ~/.claude/projects/ ~/Documents/Claude_JSONL_Backup/
```

Expected: `Number of files transferred: 528` (or close to it). Disk usage ~156 MB.

- [ ] **Step 2: Verify counts**

```bash
find ~/.claude/projects -name '*.jsonl' | wc -l
find ~/Documents/Claude_JSONL_Backup -name '*.jsonl' | wc -l
```

Both counts must match.

- [ ] **Step 3: No commit (out-of-tree)**

Skip — this backs up files outside the repo. Note in the next task's commit message that the backup landed.

---

### Task 2.2: Pre-flight upstream hook paths

**Files (verification only):**
- `~/Code/mempalace/hooks/mempal_save_hook.sh`
- `~/Code/mempalace/hooks/mempal_precompact_hook.sh`

- [ ] **Step 1: Confirm both files exist and are executable**

```bash
ls -l ~/Code/mempalace/hooks/mempal_save_hook.sh ~/Code/mempalace/hooks/mempal_precompact_hook.sh
chmod +x ~/Code/mempalace/hooks/mempal_save_hook.sh ~/Code/mempalace/hooks/mempal_precompact_hook.sh
```

Expected: both files exist; both have `x` bit after chmod.

- [ ] **Step 2: Smoke-test the save hook script on a dummy input**

```bash
echo '{"session_id":"test","stop_hook_active":true,"transcript_path":"/tmp/nonexistent.jsonl"}' | ~/Code/mempalace/hooks/mempal_save_hook.sh
```

Expected: exit code 0 (script handles missing transcript gracefully when `stop_hook_active=true`).

- [ ] **Step 3: No commit**

Verification only.

---

### Task 2.3: Add Stop hook to `~/.claude/settings.json`

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Back up current settings**

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak.$(date -u +%Y%m%dT%H%M%SZ)
```

- [ ] **Step 2: Merge the Stop hook entry**

Run this Python one-liner (handles existing PreToolUse entry, idempotent):

```bash
python3 - <<'PY'
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
settings = json.loads(settings_path.read_text())
settings.setdefault("hooks", {})

hook_cmd = str(Path.home() / "Code" / "mempalace" / "hooks" / "mempal_save_hook.sh")

stop_entries = settings["hooks"].setdefault("Stop", [])
if any(
    h.get("command") == hook_cmd
    for entry in stop_entries
    for h in entry.get("hooks", [])
):
    print("skip — Stop hook already present")
else:
    stop_entries.append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}],
    })
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"installed Stop hook → {hook_cmd}")
PY
```

Expected: `installed Stop hook → /Users/themancalledzac/Code/mempalace/hooks/mempal_save_hook.sh`

- [ ] **Step 3: Verify the JSON**

```bash
python3 -c "import json; print(json.dumps(json.load(open('/Users/themancalledzac/.claude/settings.json')), indent=2))"
```

Expected output contains both the existing `PreToolUse: Agent` block and the new `Stop` block.

- [ ] **Step 4: No commit (out-of-tree)**

Skip — settings.json is per-user, not in the repo.

---

### Task 2.4: Add PreCompact hook to `~/.claude/settings.json`

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Merge the PreCompact entry**

```bash
python3 - <<'PY'
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
settings = json.loads(settings_path.read_text())
settings.setdefault("hooks", {})

hook_cmd = str(Path.home() / "Code" / "mempalace" / "hooks" / "mempal_precompact_hook.sh")

pc_entries = settings["hooks"].setdefault("PreCompact", [])
if any(
    h.get("command") == hook_cmd
    for entry in pc_entries
    for h in entry.get("hooks", [])
):
    print("skip — PreCompact hook already present")
else:
    pc_entries.append({
        "hooks": [{"type": "command", "command": hook_cmd, "timeout": 30}],
    })
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"installed PreCompact hook → {hook_cmd}")
PY
```

- [ ] **Step 2: Verify**

```bash
python3 -c "import json,sys; d=json.load(open('/Users/themancalledzac/.claude/settings.json')); print(list(d['hooks'].keys()))"
```

Expected: `['PreToolUse', 'Stop', 'PreCompact']`

- [ ] **Step 3: No commit (out-of-tree)**

---

### Task 2.5: Generalize `scripts/install_claude_code.sh` to install all three hooks

**Files:**
- Modify: [scripts/install_claude_code.sh](../../../scripts/install_claude_code.sh)
- Create: [integration/claude_code/hooks_install.py](../../../integration/claude_code/hooks_install.py)
- Test: [tests/test_install_claude_code.py](../../../tests/test_install_claude_code.py) (new)

**Context:** Today `install_claude_code.sh` only knows about the `PreToolUse: Agent` hook. Generalize so the same script installs Stop + PreCompact hooks pointing at upstream's mempalace scripts.

- [ ] **Step 1: Write the failing test**

Create [tests/test_install_claude_code.py](../../../tests/test_install_claude_code.py):

```python
"""Verify install_claude_code.sh wires all three hooks idempotently."""

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_claude_code.sh"


def test_script_installs_all_three_hooks(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    monkeypatch.setenv("HOME", str(fake_home))

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"HOME": str(fake_home), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr

    settings = json.loads((fake_home / ".claude" / "settings.json").read_text())
    hook_names = set(settings.get("hooks", {}).keys())
    assert {"PreToolUse", "Stop", "PreCompact"}.issubset(hook_names)


def test_script_is_idempotent(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    env = {"HOME": str(fake_home), "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)
    first = (fake_home / ".claude" / "settings.json").read_text()

    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)
    second = (fake_home / ".claude" / "settings.json").read_text()

    assert first == second, "second run mutated settings.json"
```

- [ ] **Step 2: Run test, expect failure**

```bash
pytest tests/test_install_claude_code.py -v
```

Expected: FAIL — the script only installs PreToolUse today.

- [ ] **Step 3: Create the shared Python merge helper**

Create [integration/claude_code/hooks_install.py](../../../integration/claude_code/hooks_install.py):

```python
"""Idempotent merge of Memory wrapper hooks into ~/.claude/settings.json.

Adds three entries:
  - PreToolUse: Agent → wrapper's pretooluse_agent_orientation.py
  - Stop → upstream mempalace's mempal_save_hook.sh
  - PreCompact → upstream mempalace's mempal_precompact_hook.sh

Designed to be invoked from scripts/install_claude_code.sh. Reads:
  HOOK_PRETOOLUSE_CMD, HOOK_STOP_CMD, HOOK_PRECOMPACT_CMD
  SETTINGS_PATH
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _already_present(entries, command):
    return any(
        h.get("command") == command
        for entry in entries
        if isinstance(entry, dict)
        for h in (entry.get("hooks") or [])
    )


def main() -> int:
    settings_path = Path(os.environ["SETTINGS_PATH"])
    pretool = os.environ["HOOK_PRETOOLUSE_CMD"]
    stop = os.environ["HOOK_STOP_CMD"]
    precompact = os.environ["HOOK_PRECOMPACT_CMD"]

    if settings_path.exists():
        original = settings_path.read_text()
        settings = json.loads(original) if original.strip() else {}
    else:
        original = ""
        settings = {}

    if not isinstance(settings, dict):
        print(f"error: {settings_path} is not a JSON object")
        return 1

    hooks = settings.setdefault("hooks", {})

    plan = [
        ("PreToolUse", pretool, {"matcher": "Agent", "hooks": [
            {"type": "command", "command": pretool}
        ]}),
        ("Stop", stop, {"matcher": "*", "hooks": [
            {"type": "command", "command": stop, "timeout": 30}
        ]}),
        ("PreCompact", precompact, {"hooks": [
            {"type": "command", "command": precompact, "timeout": 30}
        ]}),
    ]

    any_change = False
    for key, cmd, entry in plan:
        entries = hooks.setdefault(key, [])
        if not isinstance(entries, list):
            entries = []
            hooks[key] = entries
        if _already_present(entries, cmd):
            print(f"skip — {key} hook already present: {cmd}")
            continue
        entries.append(entry)
        any_change = True
        print(f"installed {key} hook → {cmd}")

    if any_change and original:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = settings_path.with_suffix(settings_path.suffix + f".bak.{ts}")
        backup.write_text(original)
        print(f"backup: {backup}")

    if any_change:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rewrite `scripts/install_claude_code.sh`**

Replace the existing content with:

```bash
#!/bin/bash
# Register Memory Palace Claude Code hooks in ~/.claude/settings.json.
# Three hooks installed idempotently:
#   - PreToolUse: Agent  → wrapper's pretooluse_agent_orientation.py
#   - Stop               → upstream's mempal_save_hook.sh (transcript auto-mine)
#   - PreCompact         → upstream's mempal_precompact_hook.sh (emergency save)
# Backs up settings.json to settings.json.bak.<UTC-ts> on first mutation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SETTINGS="${HOME}/.claude/settings.json"
PRETOOLUSE="$REPO_ROOT/integration/claude_code/pretooluse_agent_orientation.py"
STOP="${HOME}/Code/mempalace/hooks/mempal_save_hook.sh"
PRECOMPACT="${HOME}/Code/mempalace/hooks/mempal_precompact_hook.sh"

for f in "$PRETOOLUSE" "$STOP" "$PRECOMPACT"; do
    if [[ ! -f "$f" ]]; then
        echo "error: missing $f" >&2
        exit 1
    fi
done

chmod +x "$PRETOOLUSE" "$STOP" "$PRECOMPACT"
mkdir -p "$(dirname "$SETTINGS")"

HOOK_PRETOOLUSE_CMD="$PRETOOLUSE" \
HOOK_STOP_CMD="$STOP" \
HOOK_PRECOMPACT_CMD="$PRECOMPACT" \
SETTINGS_PATH="$SETTINGS" \
python3 "$REPO_ROOT/integration/claude_code/hooks_install.py"
```

- [ ] **Step 5: Run test, expect pass**

```bash
pytest tests/test_install_claude_code.py -v
```

Expected: PASS for both tests.

- [ ] **Step 6: Verify it's a no-op on real settings (already installed in P2.3/P2.4)**

```bash
bash scripts/install_claude_code.sh
```

Expected: three `skip — ... hook already present` lines, no backup written.

- [ ] **Step 7: Commit**

```bash
git add scripts/install_claude_code.sh integration/claude_code/hooks_install.py tests/test_install_claude_code.py
git commit -m "feat(install): wire Stop + PreCompact hooks alongside PreToolUse (idempotent)"
```

---

### Task 2.6: Backfill existing JSONLs into `wing_claude_imports`

**Files:**
- Create: [scripts/backfill_claude_sessions.sh](../../../scripts/backfill_claude_sessions.sh)

- [ ] **Step 1: Create the backfill script**

```bash
cat > scripts/backfill_claude_sessions.sh <<'EOF'
#!/bin/bash
# One-shot backfill of ~/.claude/projects/*.jsonl into the palace as wing_claude_imports.
# Idempotent — mempalace's drawer IDs are deterministic so re-runs are no-ops.
set -euo pipefail

PALACE_PATH="${MEMPALACE_PALACE_PATH:-$HOME/.mempalace/palace}"
SOURCE="${1:-$HOME/.claude/projects}"

echo "Backfilling Claude Code sessions"
echo "  source: $SOURCE"
echo "  palace: $PALACE_PATH"
echo "  wing:   claude_imports"
echo

MEMPALACE_PALACE_PATH="$PALACE_PATH" \
    mempalace mine "$SOURCE" --mode convos --wing claude_imports
EOF
chmod +x scripts/backfill_claude_sessions.sh
```

- [ ] **Step 2: Run the backfill against the real corpus**

```bash
bash scripts/backfill_claude_sessions.sh
```

Expected: `mempalace mine` walks 528 files, files them into `wing_claude_imports`. Wall time: 5-15 minutes depending on hardware.

- [ ] **Step 3: Verify in palace**

```bash
python3 -c "
import os
os.environ['MEMPALACE_PALACE_PATH'] = os.path.expanduser('~/.mempalace/palace')
from mempalace.mcp_server import tool_list_wings
print(tool_list_wings())
"
```

Expected: `claude_imports` appears in the wings list with >0 drawer count.

- [ ] **Step 4: Commit the script**

```bash
git add scripts/backfill_claude_sessions.sh
git commit -m "feat(scripts): one-shot backfill of Claude Code sessions into wing_claude_imports"
```

---

### Task 2.7: Add `/save` slash command

**Files:**
- Create: `~/.claude/commands/save.md` (out-of-tree)

- [ ] **Step 1: Pull the slash-command markdown from upstream's gist**

```bash
mkdir -p ~/.claude/commands
curl -fsSL https://gist.githubusercontent.com/milla-jovovich/25b9d43b3518674c80d6e7e54c499362/raw/save.md \
    -o ~/.claude/commands/save.md
```

- [ ] **Step 2: Verify it loaded**

```bash
test -f ~/.claude/commands/save.md && wc -l ~/.claude/commands/save.md
```

Expected: non-empty file.

- [ ] **Step 3: No commit (out-of-tree)**

---

## Phase 3 — Code Subtraction

**Goal:** Delete or narrow every wrapper module that duplicates upstream functionality. Keep user-wing + wingpack intact.

### Task 3.1: Delete `src/filters.py` + test + YAML reference

**Files:**
- Delete: [src/filters.py](../../../src/filters.py)
- Delete: [tests/test_filters.py](../../../tests/test_filters.py)
- Modify: [config/mempalace.yaml:508](../../../config/mempalace.yaml:508) (remove dead taxonomy entry)

**Context:** [src/filters.py](../../../src/filters.py) defines `detect_room_for_wing` with no callers in `src/` or `mems_cli/` — only [tests/test_filters.py](../../../tests/test_filters.py) imports it. The original plan (`docs/plans/2026-04-17-mems-full-implementation.md` Task 1.1) wired it into `sync_engine.py` for "drift-detection logging", but it was never integrated. Upstream's `miner.detect_room` (fixed in 3.3.5 #1004) handles room detection inside `process_file`.

- [ ] **Step 1: Confirm no production caller**

```bash
grep -RIn 'detect_room_for_wing\|from .*filters\|from src.filters' src/ mems_cli/ integration/ entrypoint.sh scripts/ 2>/dev/null
```

Expected: zero matches outside `src/filters.py` itself.

- [ ] **Step 2: Delete the files**

```bash
git rm src/filters.py tests/test_filters.py
```

- [ ] **Step 3: Remove the dead taxonomy entry from `config/mempalace.yaml`**

Find line 508 region (`grep -n 'detect_room_for_wing' config/mempalace.yaml`) and delete the surrounding `pack-author`-adjacent room block that references `filters`/`detect_room_for_wing`/`path_prefix_match`/`keyword_score`. Specifically, remove this entry from the `wingpack-pipeline.rooms` list if present, or whichever room block names those keywords.

Verify with:

```bash
grep -n 'detect_room_for_wing\|path_prefix_match\|keyword_score' config/mempalace.yaml
```

Expected: zero matches.

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/ -v 2>&1 | tail -30
```

Expected: all remaining tests pass; no import errors mentioning `src.filters`.

- [ ] **Step 5: Commit**

```bash
git add config/mempalace.yaml
git commit -m "refactor: delete unused src/filters.py — upstream miner.detect_room handles room routing"
```

---

### Task 3.2: Delete `integration/stop-hook.sh`

**Files:**
- Delete: [integration/stop-hook.sh](../../../integration/stop-hook.sh)

**Context:** 7-line echo reminder, no real save logic. Replaced by upstream's `mempal_save_hook.sh` (wired in P2.3).

**Precondition:** P2.3 must be complete.

- [ ] **Step 1: Confirm no references**

```bash
grep -RIn 'integration/stop-hook.sh\|stop-hook\.sh' . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules 2>/dev/null
```

Expected: no matches outside the file itself (or only in `docs/historical/` which is fine).

- [ ] **Step 2: Delete**

```bash
git rm integration/stop-hook.sh
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: delete integration/stop-hook.sh — replaced by upstream mempal_save_hook.sh"
```

---

### Task 3.3: Narrow `src/restore_wing_user.py` to user_wing only

**Files:**
- Modify: [src/restore_wing_user.py](../../../src/restore_wing_user.py)
- Test: [tests/test_restore_wing_user.py](../../../tests/test_restore_wing_user.py)

**Context:** Upstream 3.3.5 #1308 added `mempalace repair --mode from-sqlite` which reads drawers directly from `chroma.sqlite3` and re-upserts into a fresh palace — a strict superset of what `restore_wing_user.py` does for general drawers. The wrapper should only own the user_wing-specific recovery path (which IS unique — wing_user has no source repo to re-mine from).

- [ ] **Step 1: Read the current file**

```bash
wc -l src/restore_wing_user.py
grep -n '^def \|^class ' src/restore_wing_user.py
```

Note any function that handles non-user-wing recovery.

- [ ] **Step 2: Write failing test**

Append to [tests/test_restore_wing_user.py](../../../tests/test_restore_wing_user.py):

```python
def test_restore_only_touches_user_wing(tmp_path):
    """restore_wing_user must not import or re-upsert non-user-wing drawers."""
    from src import restore_wing_user
    import inspect

    src = inspect.getsource(restore_wing_user)
    # Sanity: the module should reference user_wing/halls but NOT
    # generic palace-wide recovery (that's `mempalace repair --mode from-sqlite`'s job now).
    assert "wing_user" in src or "user_wing" in src
    assert "from-sqlite" not in src, "restore_wing_user should not duplicate mempalace repair logic"
```

- [ ] **Step 3: Run test, expect pass or fail based on current state**

```bash
pytest tests/test_restore_wing_user.py::test_restore_only_touches_user_wing -v
```

If it passes, the file already narrow — proceed to step 5 (no-op narrow). If it fails because of generic-recovery code in the file, proceed to step 4.

- [ ] **Step 4: Edit `src/restore_wing_user.py` to remove any generic recovery branches**

Keep only:
- Snapshot loading from `exports/wing_user_backup.YYYYMMDD.json`
- Re-insertion of user_wing drawers using deterministic IDs
- Empty-check logic that gates restoration

Remove anything that walks all wings, calls `get_collection` for non-user collections, or rebuilds the palace generically.

- [ ] **Step 5: Run full restore tests**

```bash
pytest tests/test_restore_wing_user.py -v
```

Expected: all pass.

- [ ] **Step 6: Document the delegation in a module docstring**

Update the module docstring at the top of [src/restore_wing_user.py](../../../src/restore_wing_user.py):

```python
"""Auto-restore the user_wing slice from the most recent JSON backup on cold boot.

This module is intentionally narrow. For general palace recovery (HNSW corruption,
chromadb segment quarantine, drawer loss from source-file deletion), use upstream's
`mempalace repair --mode from-sqlite` instead — added in 3.3.5 #1308. That mode
reads (id, document, metadata) directly from chroma.sqlite3 and re-upserts into a
fresh palace, which is a strict superset of what we used to do here.

What this module owns:
  - Loading `exports/wing_user_backup.YYYYMMDD.json` (written by wing_user_snapshot.py)
  - Re-inserting user-wing drawers with deterministic IDs (idempotent)
  - The empty-wing-user precondition check that gates restoration

wing_user is a wrapper-unique concept (halls: questions / discoveries / frustrations /
goals / decisions / observations) with no source repo to re-mine from — that's why
this module exists separately from `mempalace repair`.
"""
```

- [ ] **Step 7: Commit**

```bash
git add src/restore_wing_user.py tests/test_restore_wing_user.py
git commit -m "refactor(restore): narrow restore_wing_user to user-wing slice (upstream 3.3.5 #1308 covers the rest)"
```

---

### Task 3.4: Refactor `mems_cli/commands/palace_ops.py` to shell out to upstream CLI

**Files:**
- Modify: [mems_cli/commands/palace_ops.py](../../../mems_cli/commands/palace_ops.py)
- Test: [tests/test_mems_commands.py](../../../tests/test_mems_commands.py)

**Context:** The wrapper's `palace_ops` reimplements semantics for init/mine/repair. Upstream now has stable CLI for all of these. Wrap, don't reimplement.

- [ ] **Step 1: Inventory current `palace_ops.py` subcommands**

```bash
grep -nE '^def |add_subparsers|subparsers\.add_parser\|def cmd_' mems_cli/commands/palace_ops.py | head -30
wc -l mems_cli/commands/palace_ops.py
```

Document each subcommand and what upstream `mempalace` CLI command would replace it:

| `mems ...` subcommand | Upstream replacement | Replace? |
|---|---|---|
| `mems sync` | (none — wrapper multi-repo, see Task 3.5) | NO — wrapper-unique |
| `mems make` (build palace) | `mempalace init --auto-mine <dir>` | YES |
| `mems restore` | `mempalace repair --mode from-sqlite` (general) + `restore_wing_user` (user slice) | YES (general path) |
| `mems doctor` | `mempalace repair --mode legacy` + status checks | YES (delegate diagnostic) |

- [ ] **Step 2: Write failing test for `mems make`**

Append to [tests/test_mems_commands.py](../../../tests/test_mems_commands.py):

```python
def test_mems_make_shells_out_to_mempalace_init(monkeypatch, tmp_path):
    """`mems make <dir>` should invoke `mempalace init --auto-mine <dir>` via subprocess."""
    captured = []

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        captured.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)

    from mems_cli.commands import palace_ops
    palace_ops.cmd_make(argparse_namespace_for(dir=str(tmp_path), yes=True))

    assert captured, "subprocess.run was not called"
    cmd = captured[0]
    assert "mempalace" in cmd[0] or cmd[0].endswith("mempalace")
    assert "init" in cmd
    assert "--auto-mine" in cmd
    assert str(tmp_path) in cmd
```

(Helper `argparse_namespace_for` lives in [tests/conftest.py](../../../tests/conftest.py) — add it there if absent: returns `argparse.Namespace(**kwargs)`.)

- [ ] **Step 3: Run test, expect failure**

```bash
pytest tests/test_mems_commands.py::test_mems_make_shells_out_to_mempalace_init -v
```

Expected: FAIL.

- [ ] **Step 4: Refactor `cmd_make` in `palace_ops.py`**

Replace whatever `cmd_make` currently does with:

```python
def cmd_make(args):
    """Build/initialize a palace from a directory. Delegates to `mempalace init --auto-mine`."""
    import subprocess
    cmd = ["mempalace", "init", "--auto-mine", str(args.dir)]
    if getattr(args, "yes", False):
        cmd.insert(2, "--yes")
    result = subprocess.run(cmd, check=False)
    return {"ok": result.returncode == 0, "returncode": result.returncode}
```

- [ ] **Step 5: Refactor `cmd_restore` in `palace_ops.py`**

```python
def cmd_restore(args):
    """Restore palace from backup. Routes user-wing slice to wing_user restore,
    general palace recovery to `mempalace repair --mode from-sqlite`.
    """
    import subprocess
    from src.restore_wing_user import restore_user_wing  # or whatever the real entry point is

    if getattr(args, "user_only", False):
        return restore_user_wing(args.palace_path)

    # General recovery → upstream
    cmd = ["mempalace", "repair", "--mode", "from-sqlite", "--palace", args.palace_path]
    if getattr(args, "source", None):
        cmd.extend(["--source", args.source])
    if getattr(args, "archive_existing", False):
        cmd.append("--archive-existing")
    result = subprocess.run(cmd, check=False)
    return {"ok": result.returncode == 0, "returncode": result.returncode}
```

- [ ] **Step 6: Refactor `cmd_doctor` in `palace_ops.py`**

```python
def cmd_doctor(args):
    """Diagnostic: pre-flight hook paths + delegate index health to mempalace repair."""
    import subprocess
    from pathlib import Path

    issues = []
    save_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_save_hook.sh"
    pc_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_precompact_hook.sh"
    for f in (save_hook, pc_hook):
        if not f.exists():
            issues.append(f"missing hook: {f}")

    # Delegate index health to upstream
    status = subprocess.run(
        ["mempalace", "status", "--palace", args.palace_path],
        capture_output=True, text=True, check=False,
    )
    if status.returncode != 0:
        issues.append(f"mempalace status failed: {status.stderr.strip()}")

    return {"ok": not issues, "issues": issues, "status_output": status.stdout}
```

- [ ] **Step 7: Run tests, expect pass**

```bash
pytest tests/test_mems_commands.py -v
```

Expected: all pass.

- [ ] **Step 8: Smoke test `mems doctor` against a real palace**

```bash
mems doctor --palace-path ~/.mempalace/palace
```

Expected: prints status, exits 0 if both hooks exist and palace is healthy.

- [ ] **Step 9: Commit**

```bash
git add mems_cli/commands/palace_ops.py tests/test_mems_commands.py tests/conftest.py
git commit -m "refactor(mems): palace_ops shells out to mempalace CLI (init/repair/status)"
```

---

### Task 3.5: Add post-ingest `mempalace sync` prune step in `sync_engine.py`

**Files:**
- Modify: [src/sync_engine.py](../../../src/sync_engine.py)
- Test: [tests/test_sync_engine.py](../../../tests/test_sync_engine.py)

**Context:** Upstream's `mempalace sync` (cmd_sync, tool_sync) is a gitignore-aware drawer prune — removes drawers whose source files were gitignored/deleted/moved (#1252). This is **complementary** to the wrapper's multi-repo git-diff ingest (which is wrapper-unique IP — KEEP). Add a post-ingest call.

- [ ] **Step 1: Write failing test**

Append to [tests/test_sync_engine.py](../../../tests/test_sync_engine.py):

```python
def test_full_sync_calls_mempalace_sync_after_ingest(monkeypatch, tmp_path):
    """SyncEngine.full_sync should invoke upstream `mempalace sync` after ingest to prune stale drawers."""
    calls = []

    def fake_subprocess_run(cmd, *args, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("src.sync_engine.scan_project", lambda *a, **k: [])
    monkeypatch.setattr("src.sync_engine.process_file", lambda *a, **k: None)

    from src.sync_engine import SyncEngine
    engine = SyncEngine(
        config_path=str(tmp_path / "config"),
        data_path=str(tmp_path / "data"),
    )
    engine.taxonomy = {"wings": {}}
    engine.repos = {}
    engine.ledger = type("L", (), {"entries": {}, "save": lambda self: None})()

    engine.full_sync()

    # Look for `mempalace sync` in subprocess calls
    sync_calls = [c for c in calls if any("sync" in str(p) for p in c) and any("mempalace" in str(p) for p in c)]
    assert sync_calls, f"expected `mempalace sync` post-ingest call; got {calls}"
```

- [ ] **Step 2: Run test, expect failure**

```bash
pytest tests/test_sync_engine.py::test_full_sync_calls_mempalace_sync_after_ingest -v
```

Expected: FAIL.

- [ ] **Step 3: Add post-ingest prune to `SyncEngine.full_sync` and `SyncEngine.incremental_sync`**

In [src/sync_engine.py](../../../src/sync_engine.py), at the end of both `full_sync` and `incremental_sync` (after the loop that calls `process_file`, before `self.ledger.save()`):

```python
        # Post-ingest: prune drawers whose source files were gitignored/deleted/moved.
        # Upstream cmd_sync handles this — runs against the same palace_path the
        # wrapper just wrote to (MEMPALACE_PALACE_PATH already set via _bind_palace).
        try:
            subprocess.run(
                ["mempalace", "sync", "--apply"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            # Non-fatal: ingest already succeeded. Log + continue.
            print(f"warning: post-ingest mempalace sync skipped: {exc}", flush=True)
```

(Adjust signature/import — `subprocess` is already imported per [src/sync_engine.py:4](../../../src/sync_engine.py:4).)

- [ ] **Step 4: Run test, expect pass**

```bash
pytest tests/test_sync_engine.py::test_full_sync_calls_mempalace_sync_after_ingest -v
```

Expected: PASS.

- [ ] **Step 5: Full sync_engine test suite**

```bash
pytest tests/test_sync_engine.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/sync_engine.py tests/test_sync_engine.py
git commit -m "feat(sync): post-ingest mempalace sync prune (upstream #1252) — wrapper retains git-diff orchestration"
```

---

### Task 3.6: Remove wrapper's `mempalace_diary_*` MCP forwarders (the wrapper-side ones)

**Files:**
- Modify: [src/mcp_http_server.py](../../../src/mcp_http_server.py)
- Modify: [src/tools.py](../../../src/tools.py)
- Test: [tests/test_mcp_server.py](../../../tests/test_mcp_server.py)

**Context:** With upstream's Stop hook wired (P2.3), diary writes happen via upstream's own path during transcript ingest. The wrapper's `mempalace_diary_write/read` MCP tools forward to upstream's `tool_diary_*` — but agents using the wrapper's HTTP MCP server still benefit from these endpoints existing. **Decision: KEEP the wrapper forwarders** (they're now correctly forwarding the `wing` param thanks to Task 0.3); skip this task. This entry is a placeholder for the eval — if you have not concluded otherwise, mark it complete-no-change.

- [ ] **Step 1: Verify the forwarders are wired correctly post-P0.3**

```bash
pytest tests/test_mcp_server.py -k diary -v
```

Expected: all pass.

- [ ] **Step 2: Decision: keep forwarders**

Reasoning: the wrapper's HTTP MCP server is the only transport some agents see (Cursor, custom integrations); removing the forwarders would force every consumer onto upstream's stdio mempalace-mcp. Forwarding is now correct after P0.3 — preserve it.

- [ ] **Step 3: No commit (no change)**

Skip the task.

---

### Task 3.7: Decide on Cursor-only `.mdc` files

**Files:**
- [integration/mempalace-discovery.mdc](../../../integration/mempalace-discovery.mdc)
- [integration/user-wing.mdc](../../../integration/user-wing.mdc)

**Context:** Prior memory confirms `.mdc` files are invisible to Claude Code. Decision: keep for Cursor users, document.

- [ ] **Step 1: Check git status of these files**

```bash
git log --oneline -5 -- integration/mempalace-discovery.mdc integration/user-wing.mdc
```

- [ ] **Step 2: Add a README to `integration/` documenting which file goes where**

Create or update [integration/README.md](../../../integration/README.md):

```markdown
# IDE Integrations

| File | Consumer | What it does |
|---|---|---|
| `claude_code/pretooluse_agent_orientation.py` | Claude Code | Injects mempalace orientation before Agent tool calls |
| `claude_code/hooks_install.py` | Claude Code | Helper for `scripts/install_claude_code.sh` |
| `mempalace_codex_append.toml` | Codex CLI | Append-block for Codex's hooks.toml |
| `mempalace_mcp_cursor.json` | Cursor | MCP server registration for Cursor |
| `mempalace-discovery.mdc` | Cursor | Cursor rule — search palace at session start (invisible to Claude Code) |
| `user-wing.mdc` | Cursor | Cursor rule — write user thoughts during session (invisible to Claude Code) |

Files ending in `.mdc` are Cursor-specific. Claude Code does not read them; for
Claude Code, the equivalent guidance lives in `~/.claude/CLAUDE.md` (Memory Palace
Protocol section).
```

- [ ] **Step 3: Commit**

```bash
git add integration/README.md
git commit -m "docs(integration): clarify .mdc files are Cursor-only (Claude Code reads CLAUDE.md)"
```

---

## Phase 4 — Config Adoption (Upstream Knobs)

**Goal:** Wire the easy upstream config knobs the wrapper hasn't yet exposed. Defers higher-effort adoption (embeddinggemma, office-document extract) to a follow-up plan with explicit user sign-off.

### Task 4.1: Add `MEMPALACE_HOOKS_AUTO_SAVE` toggle to Dockerfile

**Files:**
- Modify: [Dockerfile](../../../Dockerfile)

- [ ] **Step 1: Add the env var**

In [Dockerfile](../../../Dockerfile), append to the `ENV` block:

```dockerfile
    MEMPALACE_HOOKS_AUTO_SAVE=true \
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): expose MEMPALACE_HOOKS_AUTO_SAVE toggle (upstream 3.3.6 #711)"
```

---

### Task 4.2: Add `MEMPALACE_EAGER_WARMUP` toggle

**Files:**
- Modify: [Dockerfile](../../../Dockerfile)

- [ ] **Step 1: Append**

```dockerfile
    MEMPALACE_EAGER_WARMUP=1 \
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): enable MEMPALACE_EAGER_WARMUP for predictable cold-start (upstream 3.3.6 #1530)"
```

---

### Task 4.3: Add `MEMPALACE_TOPIC_TUNNEL_MIN_COUNT` knob

**Files:**
- Modify: [Dockerfile](../../../Dockerfile)
- Modify: [config/mempalace.yaml](../../../config/mempalace.yaml) (document the knob)

- [ ] **Step 1: Add to Dockerfile ENV**

```dockerfile
    MEMPALACE_TOPIC_TUNNEL_MIN_COUNT=2 \
```

(Default 1 is too eager for the wrapper's dense corpora. 2 = require two co-occurrences before promoting a topic tunnel.)

- [ ] **Step 2: Document in `config/mempalace.yaml` header comment**

Near the top of [config/mempalace.yaml](../../../config/mempalace.yaml), add or update the runtime-knobs comment block:

```yaml
# Runtime knobs (env vars consumed by upstream mempalace):
#   MEMPALACE_PALACE_PATH       — palace directory (set by entrypoint.sh)
#   MEMPALACE_EMBEDDING_MODEL   — minilm | embeddinggemma (default: minilm)
#   MEMPALACE_HOOKS_AUTO_SAVE   — true | false (default: true)
#   MEMPALACE_EAGER_WARMUP      — 1 = warm the embedder at startup (default: off)
#   MEMPALACE_TOPIC_TUNNEL_MIN_COUNT — co-occurrence threshold for topic tunnels (default: 1, wrapper sets 2)
#   MEMPALACE_ENTITY_LANGUAGES  — comma list, e.g. "en,pt-br" (default: en)
#   MEMPALACE_MAX_CHUNKS_PER_FILE — safety cap (default: upstream's tuned value)
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile config/mempalace.yaml
git commit -m "feat(config): tune MEMPALACE_TOPIC_TUNNEL_MIN_COUNT=2 + document upstream knobs"
```

---

### Task 4.4: Add `MEMPALACE_ENTITY_LANGUAGES` (default: en, configurable)

**Files:**
- Modify: [Dockerfile](../../../Dockerfile)

- [ ] **Step 1: Add the env var with English default**

```dockerfile
    MEMPALACE_ENTITY_LANGUAGES=en \
```

User can override to `en,pt-br,ru` etc. via docker-compose env file.

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): expose MEMPALACE_ENTITY_LANGUAGES (default en; user-configurable)"
```

---

### Task 4.5: Adopt office-document mining via `mempalace[extract]` (DEFERRED — gated)

**Files:**
- Would modify: [pyproject.toml](../../../pyproject.toml), [requirements.txt](../../../requirements.txt), [Dockerfile](../../../Dockerfile)

**Context:** Upstream 3.3.6 #1555 adds `mempalace mine --mode extract` for PDFs / docx / pptx / xlsx / RTF / EPUB. Adoption requires deciding whether to install the `[extract]` extra (~adds MarkItDown + striprtf, ~50MB), and whether [src/sync_engine.py](../../../src/sync_engine.py) should add a parallel extract path.

- [ ] **Step 1: Decision gate**

This task is **DEFERRED** to a follow-up plan. Trigger: the user confirms they have `.pdf` / `.docx` design docs to mine. Until then, do nothing.

- [ ] **Step 2: No commit**

Skip.

---

### Task 4.6: Adopt `embeddinggemma` multilingual (DEFERRED — gated)

**Context:** Upstream 3.3.6 #1483 — `embeddinggemma-300m` ONNX brings cross-lingual cosine from 0.35 to 0.88. Adoption requires:
1. Setting `MEMPALACE_EMBEDDING_MODEL=embeddinggemma`
2. Running `mempalace repair rebuild-index` on the existing 8,780-drawer palace (multi-minute wall time, one-shot)
3. ~300 MB lazy ONNX download on first use

- [ ] **Step 1: Decision gate**

DEFERRED. Trigger: confirmed need for multilingual content (Russian, Hindi, Korean, Italian, etc.) — minilm is fine for English-only.

- [ ] **Step 2: No commit**

Skip.

---

## Phase 5 — Verification + Docs

### Task 5.1: Run the full wrapper test suite

- [ ] **Step 1: Clean install**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Run pytest**

```bash
pytest tests/ -v 2>&1 | tee /tmp/test-output.log
```

Expected: all pass. If any fail, fix before continuing; do not commit failing tests.

- [ ] **Step 3: Ruff check**

```bash
ruff check .
ruff format --check .
```

Expected: clean.

- [ ] **Step 4: No commit (verification only)**

---

### Task 5.2: End-to-end smoke test

- [ ] **Step 1: Boot the wrapper container**

```bash
docker compose up --build -d
sleep 10
curl -fsS http://localhost:8080/health
```

Expected: `200 OK` with JSON body indicating palace is mounted.

- [ ] **Step 2: Smoke-test MCP tools via HTTP**

```bash
curl -fsS -X POST http://localhost:8080/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"mempalace_status"},"id":1}'
```

Expected: JSON response with `total_drawers > 0`.

- [ ] **Step 3: Smoke-test user-wing write/search**

```bash
curl -fsS -X POST http://localhost:8080/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"mempalace_user_write","arguments":{"hall":"observations","content":"upgrade-test","topic":"e2e_smoke"}},"id":2}'
```

Expected: `{"status":"created","id":"user-...","hall":"observations"}`.

- [ ] **Step 4: Verify the Claude Code hooks actually fire**

Open a new Claude Code session in a test directory. Run a trivial conversation. After ~15 user messages OR right before context compaction, watch:

```bash
tail -f ~/.mempalace/hook_state/*.log 2>/dev/null
ls -lt ~/.mempalace/palace/wal 2>/dev/null | head -5
```

Expected: hook log entries appear; WAL files written.

- [ ] **Step 5: Confirm wing_claude_imports populated**

```bash
python3 -c "
import os
os.environ['MEMPALACE_PALACE_PATH'] = os.path.expanduser('~/.mempalace/palace')
from mempalace.mcp_server import tool_status
print(tool_status())
"
```

Expected: includes `wing_claude_imports` (from P2.6) and recent drawers from the new Stop-hook-triggered ingest.

- [ ] **Step 6: No commit (verification only)**

---

### Task 5.3: Update top-level README + CONTEXT

**Files:**
- Modify: [README.md](../../../README.md)
- Modify: [docs/historical/CONTEXT.md](../../../docs/historical/CONTEXT.md) (only if it still represents current state — otherwise leave historical untouched)

- [ ] **Step 1: Update [README.md](../../../README.md) tech stack section**

Find the tech-stack block and update the mempalace pin:

```markdown
**Tech Stack:** Python 3.12, `mempalace>=3.3.6`, FastMCP (via `mcp[cli]`), uvicorn+starlette, chromadb 1.5.4+, sentence-transformers, hatchling, ruff, pytest. Docker Compose for runtime.
```

- [ ] **Step 2: Add a "Claude Code Setup" section to README**

After the existing setup instructions, append:

```markdown
## Claude Code Setup

The wrapper installs three Claude Code hooks via `scripts/install_claude_code.sh`:

| Hook | Purpose |
|---|---|
| `PreToolUse: Agent` | Inject mempalace orientation before sub-agent calls |
| `Stop` | Auto-mine the active transcript every 15 user messages |
| `PreCompact` | Emergency save before context compaction |

The `Stop` and `PreCompact` scripts live in `~/Code/mempalace/hooks/` — install
upstream mempalace there alongside this repo:

    git clone https://github.com/MemPalace/mempalace.git ~/Code/mempalace

Then run the installer (idempotent):

    bash scripts/install_claude_code.sh

**Important:** Claude Code retains JSONL transcripts for only **30 days**.
Without these hooks wired, conversation history is lost permanently after
auto-deletion. Back up `~/.claude/projects/` and run the one-shot backfill:

    rsync -av ~/.claude/projects/ ~/Documents/Claude_JSONL_Backup/
    bash scripts/backfill_claude_sessions.sh
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): mempalace 3.3.6 baseline + Claude Code hook setup"
```

---

## Parallelization Windows

The plan supports significant parallelization. Recommended execution order:

```
Phase 0 (sequential — small, ~1 hour):
  P0.1 → P0.2 → P0.3 → P0.4

After Phase 0 ships, the following run in parallel (independent files):
  Phase 1 audits (all 4 tasks)  ┐
  Phase 2 hooks (P2.1 → P2.7)   ├── three subagents simultaneously
  Phase 3 subtraction:           ┘
    P3.1 (filters) — independent
    P3.4 (palace_ops) — independent
    P3.5 (sync_engine) — independent
    P3.7 (.mdc README) — independent

Then sequentially:
  P3.2 (delete stop-hook) — requires P2.3 complete
  P3.3 (narrow restore_wing_user) — independent of others but touches `src/`
  P3.6 (diary forwarders eval) — no-op task

Phase 4 (parallel — Dockerfile edits collapse to one task in practice):
  P4.1 + P4.2 + P4.3 + P4.4 — all Dockerfile additions

Phase 5 (sequential, single-threaded):
  P5.1 → P5.2 → P5.3
```

**For `/agent-teams` execution:** good fit. The three independent streams (audits / hooks / subtraction) have zero shared files. Suggest one team per stream.

---

## Spec Coverage Checklist

| Plan Task | Spec Source | Notes |
|---|---|---|
| P0.1 | List 1 (F3) | chromadb floor + mempalace pin |
| P0.2 | List 1 (F1) | `EMBEDDING_MODEL` rename |
| P0.3 | List 1 (F2) | diary `wing` param |
| P0.4 | List 1 (F5) | KG caveat removal |
| P1.1 | List 1 (F4) | EF rebind audit |
| P1.2 | List 1 (F6) | KG partial-date audit |
| P1.3 | List 1 (F7) | create_tunnel pre-mine audit |
| P1.4 | List 1 (F8) | entity_registry.research audit |
| P2.1 | Task #5 + Discussion #1388 | JSONL backup |
| P2.2 | Task #7/#8 prep | Hook script pre-flight |
| P2.3 | Task #7 | Stop hook wiring |
| P2.4 | Task #8 | PreCompact hook wiring |
| P2.5 | Task #9 | Idempotent installer |
| P2.6 | Task #6 | Backfill into `wing_claude_imports` |
| P2.7 | Task #10 | `/save` slash command |
| P3.1 | Task #12 | Delete `filters.py` |
| P3.2 | Task #13 | Delete `stop-hook.sh` |
| P3.3 | Task #14 + List 3 (#6) | Narrow `restore_wing_user.py` to user slice |
| P3.4 | Task #15 | `palace_ops.py` shells out to upstream CLI |
| P3.5 | Task #16 (revised) | Post-ingest `mempalace sync` prune (additive, not replacement) |
| P3.6 | Task #17 | Diary forwarders evaluated → keep |
| P3.7 | Task #19 | Cursor `.mdc` documented |
| P4.1 | List 3 (#1) | `MEMPALACE_HOOKS_AUTO_SAVE` |
| P4.2 | List 3 (#2) | `MEMPALACE_EAGER_WARMUP` |
| P4.3 | List 3 (#3) | `MEMPALACE_TOPIC_TUNNEL_MIN_COUNT` |
| P4.4 | List 3 (#4) | `MEMPALACE_ENTITY_LANGUAGES` |
| P4.5 | List 3 (#12) | `[extract]` extra DEFERRED |
| P4.6 | List 3 (#11) | embeddinggemma DEFERRED |
| P5.1 | User constraint: "verification before completion" | pytest + ruff |
| P5.2 | User constraint: end-to-end correctness | docker smoke + hook fire |
| P5.3 | List 1 + User constraint: docs alignment | README + Claude Code setup section |

**Spec sections NOT addressed in this plan** (deliberate deferrals):

- List 3 #5 (bump mempalace>=3.3.6) — covered by P0.1
- List 3 #7 (`mempalace sweep` adoption) — DEFERRED; depends on JSONL volume growing, can be added when needed
- List 3 #8 (`init --auto-mine` / `--no-llm` / `--redetect-origin` passthrough) — covered by P3.4 (cmd_make delegates to upstream init)
- List 3 #9 (line ranges in search results) — DEFERRED; UX polish, no urgency
- List 3 #10 (drop KG bound-at-import) — covered by P0.4
- List 3 #13 (RFC 002 source adapter) — DEFERRED; RFC is Draft
- List 3 #14 (living-memory dynamics surfacing) — DEFERRED; UX
- List 3 #15 (spawn-method test pattern) — only fires on Python 3.13 multiprocessing test failures; reactive fix

**Wrapper-unique IP preserved (per user constraint):**

- [src/user_wing.py](../../../src/user_wing.py) — untouched
- [src/wing_pack.py](../../../src/wing_pack.py) — untouched
- [src/wing_publish.py](../../../src/wing_publish.py) — untouched
- [src/auto_publish.py](../../../src/auto_publish.py) — untouched (per-repo wingpack publishing)
- [src/wing_user_snapshot.py](../../../src/wing_user_snapshot.py) — untouched
- All `mempalace_user_*` MCP tools in [src/mcp_http_server.py](../../../src/mcp_http_server.py) — untouched
- [config/mempalace.yaml](../../../config/mempalace.yaml) multi-wing structure — untouched

---

## Final TL;DR

- **27 task units**, ~30 commits when complete.
- **Phase 0** = critical fixes (~1 hour). Do first, sequentially.
- **Phase 1** = audits (~30 min). Likely zero changes.
- **Phase 2** = Claude Code hooks (URGENT). Do as soon as possible to prevent more data loss.
- **Phase 3** = subtraction. Largest phase. Three independent streams parallelizable.
- **Phase 4** = config knobs (15 minutes). All `Dockerfile` additions.
- **Phase 5** = verification + docs (~1 hour). Sequential.

If executed sequentially: ~6–8 hours. With parallel subagents: ~3–4 hours.

After completion: wrapper repo loses ~400 lines, imports drop from ~20 to ~8 upstream symbols, and the codebase becomes recognizably "thin orchestrator over `mempalace` + 4 wrapper-unique modules" instead of a parallel implementation.
