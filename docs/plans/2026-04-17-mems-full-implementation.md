# `mems` Full Implementation Plan — Master Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan phase-by-phase. Each phase below is a standalone sub-plan that produces working, testable software on its own. Phases are ordered by dependency — do NOT run them out of order unless the dependency graph allows it.

**Goal:** Bring `/Users/themancalledzac/Code/Memory/` (the `mems` repo) to the target state described in `CONTEXT.md` — a multi-repo orchestrator wrapping the `mempalace` PyPI package with wingpacks, disaster recovery, unified `mems` CLI, and IDE integrations.

**Architecture:** Thin wrapper over `mempalace`. `src/` hosts the HTTP MCP server, sync orchestrator, wingpack author/publisher, and disaster-recovery scripts. `mems_cli/` hosts the user-facing `mems` command. `scripts/setup.sh` installs everything. Docker runs the MCP server with persistent volume and bind-mounted repos.

**Tech Stack:** Python 3.12, `mempalace>=3.3.0`, FastMCP (via `mcp[cli]`), uvicorn+starlette, chromadb, sentence-transformers, hatchling (build), ruff (lint/format), pytest (tests). Docker Compose for runtime.

**Current state (audit 2026-04-17):**
- ✅ `src/mcp_http_server.py` exists with 8 tools (22 more missing)
- ✅ `src/sync_engine.py` has git-diff + full sync (no hash-scan tier)
- ✅ `src/user_wing.py` complete (6 wing_user tools)
- ❌ Missing: `filters.py`, `wing_pack.py`, `wing_publish.py`, `wing_user_snapshot.py`, `restore_wing_user.py`, `auto_publish.py`
- ❌ Missing: entire `mems_cli/` package
- ❌ Missing: `scripts/setup.sh`, IDE config snippets
- ⚠️ `pyproject.toml` uses setuptools (target: hatchling), missing `ruff`, missing console script
- ⚠️ `entrypoint.sh` skips snapshot→restore; `Dockerfile` missing env vars + healthcheck; `docker-compose.yml` port mapping wrong

---

## Phase Dependency Graph

```
Phase 0 (pyproject baseline) ──┬─→ Phase 1 (filters.py)
                               ├─→ Phase 2 (wingpacks)
                               ├─→ Phase 3 (snapshot/restore)
                               ├─→ Phase 4 (MCP tools)
                               └─→ Phase 6 (mems_cli foundation)
                                       │
Phase 3 ──────────────────────────────┐│
Phase 4 ──────────────────────────────┼┼─→ Phase 5 (Docker runtime)
Phase 2 ──────────────────────────────┘│
                                       │
Phase 6 ──→ Phase 7 (mems_cli commands)┘
                                       │
Phases 5 + 7 ──→ Phase 8 (setup.sh installer)
                                       │
Phase 8 ──→ Phase 9 (docs + README)
```

**Parallelization note:** Phases 1, 2, 3, and 4 can all run in parallel (all depend only on Phase 0). Phase 6 can also run in parallel with 1–4. Phase 7 depends on 6. Phase 5 depends on 2+3+4. Phase 8 depends on 5+7. Phase 9 is last.

---

## Phase Index

- [Phase 0: Package Baseline & pyproject Hygiene](#phase-0-package-baseline)
- [Phase 1: Room Detection (`filters.py`)](#phase-1-room-detection)
- [Phase 2: Wingpack Author + Publisher](#phase-2-wingpacks)
- [Phase 3: `wing_user` Snapshot + Restore](#phase-3-snapshot-restore)
- [Phase 4: MCP Tools Completion](#phase-4-mcp-tools)
- [Phase 5: Docker Runtime Hardening](#phase-5-docker)
- [Phase 6: `mems` CLI Foundation + `PalaceClient`](#phase-6-cli-foundation)
- [Phase 7: `mems` CLI Command Surface](#phase-7-cli-commands)
- [Phase 8: `scripts/setup.sh` + IDE Integration](#phase-8-installer)
- [Phase 9: README + Troubleshooting + Final Verification](#phase-9-docs)

---

## Conventions Every Phase Must Follow

- **TDD:** For each new module, write the failing test first, confirm it fails, implement minimum code, confirm pass, commit.
- **Commits:** Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `cli:`). One logical change per commit.
- **Lint/format:** Run `ruff check --fix src/ mems_cli/ tests/` and `ruff format src/ mems_cli/ tests/` before each commit.
- **Verification:** Before marking a phase complete, run `pytest -q` + `ruff check`. Plus any phase-specific smoke tests listed under "Phase Exit Criteria."
- **No placeholders:** If a piece of functionality isn't in this plan, don't invent it. Ask.

---

<a id="phase-0-package-baseline"></a>
## Phase 0: Package Baseline & pyproject Hygiene

**Goal:** Fix `pyproject.toml`, add `requirements.txt` for Docker, update `.gitignore`, add ruff config. All downstream phases depend on this.

**Files:**
- Modify: `pyproject.toml`
- Create: `requirements.txt`
- Modify: `.gitignore`
- Create: `exports/.gitkeep`

### Task 0.1: Rewrite `pyproject.toml`

- [ ] **Step 1: Write failing test for console script resolution**

Create `tests/test_packaging.py`:

```python
"""Sanity checks for package configuration."""

import importlib.metadata
import subprocess
import sys


def test_console_script_installed():
    """`mems` console script resolves to mems_cli.main:main."""
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    mems_ep = next((ep for ep in entry_points if ep.name == "mems"), None)
    assert mems_ep is not None, "mems console script not registered"
    assert mems_ep.value == "mems_cli.main:main"


def test_package_imports():
    """Both src and mems_cli are importable."""
    subprocess.check_call([sys.executable, "-c", "import src; import mems_cli"])
```

- [ ] **Step 2: Run test, confirm FAIL**

Run: `pytest tests/test_packaging.py -v`
Expected: both tests FAIL (no `mems` entry point, no `mems_cli` package).

- [ ] **Step 3: Rewrite `pyproject.toml`**

Replace the entire file with:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mems"
version = "0.1.0"
description = "Memory Palace multi-repo orchestrator — wraps mempalace with wingpacks, disaster recovery, and a unified CLI."
requires-python = ">=3.12,<3.15"
readme = "README.md"
dependencies = [
    "mempalace>=3.3.0",
    "mcp[cli]>=1.0.0",
    "uvicorn>=0.30.0",
    "starlette>=0.38.0",
    "sentence-transformers>=2.7.0",
    "pyyaml>=6.0,<7",
    "h2>=4.1.0",
    "chromadb>=0.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.4.0",
]

[project.scripts]
mems = "mems_cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src", "mems_cli"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py39"

[tool.ruff.lint]
select = ["B", "E", "F", "W", "I"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

Note on ruff target-version: CONTEXT.md §2 says `target py39` even though runtime is 3.12; this keeps syntax portable for anyone pip-installing on older interpreters.

- [ ] **Step 4: Install editable + run tests**

```bash
pip install -e ".[dev]"
pytest tests/test_packaging.py -v
```

Expected: `test_console_script_installed` still FAILS (no `mems_cli` package yet — deferred to Phase 6). `test_package_imports` also FAILS for same reason.

Mark these two tests `@pytest.mark.xfail(reason="mems_cli not yet implemented — see Phase 6")` for now. Remove xfail markers in Phase 6 Task 6.1.

- [ ] **Step 5: Run existing suite to confirm no regressions**

```bash
pytest -q
ruff check src/ tests/
```

Expected: existing tests pass; ruff clean (may report import-order nits — run `ruff check --fix` to resolve).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "feat(packaging): migrate to hatchling, add mems console script, ruff config"
```

### Task 0.2: Create `requirements.txt` for Docker

Rationale: Dockerfile currently does `pip install .` which pulls from `pyproject.toml` — fine, but CONTEXT.md §2 lists a slightly different Docker-only dep set. Keep them aligned via a file that the Dockerfile can `pip install -r`.

- [ ] **Step 1: Create `requirements.txt`**

```text
mempalace>=3.3.0
mcp[cli]>=1.0.0
uvicorn>=0.30.0
starlette>=0.38.0
pyyaml>=6.0,<7
h2>=4.1.0
# chromadb + sentence-transformers arrive transitively via mempalace;
# listed explicitly here so Docker builds fail loudly if upstream drops them
chromadb>=0.5.0
sentence-transformers>=2.7.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "feat(packaging): add requirements.txt aligned with Dockerfile"
```

### Task 0.3: Update `.gitignore`

- [ ] **Step 1: Append missing entries**

Read the current `.gitignore`, then append these (check each is not already present):

```
# mems per-user state
config/repos.json
docker-compose.override.yml
.env
exports/*
!exports/.gitkeep
palace/
.todo/
```

- [ ] **Step 2: Create `exports/.gitkeep`**

```bash
mkdir -p exports
touch exports/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore exports/.gitkeep
git commit -m "chore(gitignore): ignore per-user state (repos.json, exports, palace, .todo)"
```

### Phase 0 Exit Criteria

- `pip install -e ".[dev]"` succeeds.
- `ruff check src/ tests/` is clean.
- `pytest -q` passes (the two xfail tests are expected).
- `.gitignore` covers all CONTEXT.md §10 paths.

---

<a id="phase-1-room-detection"></a>
## Phase 1: Room Detection (`filters.py`)

**Goal:** Extract priority-ordered room detection into `src/filters.py` per CONTEXT.md §6. This is a thin layer over `mempalace.miner.detect_room` with our wing-level overrides.

**Files:**
- Create: `src/filters.py`
- Create: `tests/test_filters.py`

### Task 1.1: Implement `detect_room_for_wing`

- [ ] **Step 1: Write failing test**

Create `tests/test_filters.py`:

```python
"""Priority-ordered room detection (CONTEXT.md §6)."""

from pathlib import Path

import pytest

from src.filters import detect_room_for_wing


@pytest.fixture
def rooms():
    return [
        {"name": "auth", "keywords": ["login", "password", "jwt"]},
        {"name": "billing", "keywords": ["stripe", "invoice"]},
        {"name": "general", "keywords": []},
    ]


def test_explicit_rooms_json_blocks_override(tmp_path, rooms):
    (tmp_path / "rooms.json").write_text('{"blocks": {"src/payments/": "billing"}}')
    room = detect_room_for_wing(
        filepath=tmp_path / "src" / "payments" / "stripe.py",
        content="# handle login jwt",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "billing", "explicit block should override keyword score"


def test_path_prefix_wins_over_content(tmp_path, rooms):
    (tmp_path / "src" / "auth").mkdir(parents=True)
    room = detect_room_for_wing(
        filepath=tmp_path / "src" / "auth" / "session.py",
        content="# stripe invoice processing",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "auth", "path-prefix 'auth' should beat keyword 'stripe'"


def test_keyword_scoring_fallback(tmp_path, rooms):
    room = detect_room_for_wing(
        filepath=tmp_path / "lib" / "util.py",
        content="def handle_login(password, jwt): ...",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "auth"


def test_unrouted_falls_through_to_general(tmp_path, rooms):
    room = detect_room_for_wing(
        filepath=tmp_path / "lib" / "util.py",
        content="def hello(): pass",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "general"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/test_filters.py -v`
Expected: all four FAIL (`ModuleNotFoundError: src.filters`).

- [ ] **Step 3: Implement `src/filters.py`**

```python
"""Priority-ordered room detection layered over mempalace.

Priority (per CONTEXT.md §6):
  1. rooms.json explicit blocks override
  2. Path prefix — wing path segment substring-matches a room name or keyword
  3. Keyword match — bag-of-words against room keywords, highest score wins
  4. Fallback — 'general'
"""

import json
from pathlib import Path


def _load_rooms_json(wing_root: Path) -> dict:
    path = wing_root / "rooms.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _explicit_block(rel_path: str, rooms_json: dict) -> str | None:
    blocks = rooms_json.get("blocks", {})
    for prefix, room_name in blocks.items():
        if rel_path.startswith(prefix):
            return room_name
    return None


def _path_prefix_match(rel_path: str, rooms: list[dict]) -> str | None:
    segments = {s.lower() for s in Path(rel_path).parts}
    for room in rooms:
        if room["name"].lower() in segments:
            return room["name"]
        for kw in room.get("keywords", []):
            if kw.lower() in segments:
                return room["name"]
    return None


def _keyword_score(content: str, rooms: list[dict]) -> str | None:
    lowered = (content or "")[:2000].lower()
    best_name, best_score = None, 0
    for room in rooms:
        score = sum(lowered.count(kw.lower()) for kw in room.get("keywords", []))
        if score > best_score:
            best_name, best_score = room["name"], score
    return best_name


def detect_room_for_wing(
    filepath: Path,
    content: str,
    wing_root: Path,
    rooms: list[dict],
) -> str:
    """Return the room name for a file within a wing. Falls through to 'general'."""
    rel_path = str(Path(filepath).resolve().relative_to(Path(wing_root).resolve()))
    rooms_json = _load_rooms_json(Path(wing_root))

    explicit = _explicit_block(rel_path, rooms_json)
    if explicit:
        return explicit

    prefixed = _path_prefix_match(rel_path, rooms)
    if prefixed:
        return prefixed

    scored = _keyword_score(content, rooms)
    if scored:
        return scored

    return "general"
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/test_filters.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/filters.py tests/test_filters.py
git commit -m "feat(filters): priority-ordered room detection with rooms.json overrides"
```

### Task 1.2: Wire `filters.py` into `sync_engine.py`

- [ ] **Step 1: Identify call site**

Open `src/sync_engine.py` and find where `process_file` is called (`grep -n "process_file" src/sync_engine.py`). The existing call passes `rooms` from `mempalace.yaml`. We now want to call `detect_room_for_wing` explicitly and pass the resolved room to whatever mempalace API accepts a pre-resolved room (check `mempalace.miner` — `process_file` may accept `room=` override; if not, this becomes a post-insert metadata patch via `update_drawer`).

- [ ] **Step 2: Write failing integration test**

Add to `tests/test_sync_engine.py` (or create `tests/test_sync_integration.py`):

```python
def test_sync_respects_explicit_rooms_json(tmp_path, mock_repo, tmp_palace, tmp_config):
    """A rooms.json block routes files even when content keywords disagree."""
    # ... fixture sets up a repo with src/payments/stripe.py containing "login jwt"
    # ... and rooms.json with {"blocks": {"src/payments/": "billing"}}
    # Assert the drawer lands in 'billing' after sync.
    pytest.skip("TODO: fixtures need work — see Phase 1.2")
```

For now this is a TODO stub — honest about the gap. The unit tests in Task 1.1 are the real coverage; the integration test lands once Phase 2 (wingpacks) establishes the fixture patterns.

- [ ] **Step 3: Integrate**

In `src/sync_engine.py`, import `detect_room_for_wing` and call it before each `process_file`. If mempalace's `process_file` doesn't accept a pre-resolved room, wrap the call: detect → process → if room differs from detected, emit a warning (don't patch — upstream is authoritative, this just logs drift).

Exact edit (approximate — adjust to real call site):

```python
from src.filters import detect_room_for_wing

# inside sync loop, before process_file:
detected = detect_room_for_wing(
    filepath=filepath,
    content=filepath.read_text(errors="ignore")[:2000],
    wing_root=Path(repo_path),
    rooms=rooms_list,
)
# Pass through — mempalace uses the same rooms list, our detection is a sanity check
process_file(filepath=filepath, project_path=Path(repo_path), ..., rooms=rooms_list)
```

- [ ] **Step 4: Run full suite**

```bash
pytest -q
ruff check src/ tests/
```

Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/sync_engine.py tests/
git commit -m "feat(sync): use filters.detect_room_for_wing for drift-detection logging"
```

### Phase 1 Exit Criteria

- `tests/test_filters.py` 4/4 passing.
- `src/sync_engine.py` imports `detect_room_for_wing` and at minimum logs drift.
- Full `pytest -q` green.

---

<a id="phase-2-wingpacks"></a>
## Phase 2: Wingpack Author + Publisher

**Goal:** Implement the `.wingpack` bundle system per CONTEXT.md §6. Three files: author (`wing_pack.py`), publisher (`wing_publish.py`), post-sync hook (`auto_publish.py`).

**Files:**
- Create: `src/wing_pack.py`
- Create: `src/wing_publish.py`
- Create: `src/auto_publish.py`
- Create: `tests/test_wing_pack.py`
- Create: `tests/test_wing_publish.py`

### Task 2.1: `wing_pack.py` — bundle author

A `.wingpack` is a zip containing `manifest.json`, `wingpack.yaml`, `keywords.json`, `rooms.json`, `prompts.json`, and optionally `sync_manifest.json`.

- [ ] **Step 1: Write failing test**

Create `tests/test_wing_pack.py`:

```python
"""Wingpack bundle author tests."""

import json
import zipfile
from pathlib import Path

import pytest

from src.wing_pack import WingpackBuilder, write_wingpack


@pytest.fixture
def sample_wing_meta():
    return {
        "name": "my-wing",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "drawer_count": 42,
        "rooms": [
            {"name": "auth", "keywords": ["jwt", "login"], "tags": ["security"]},
            {"name": "general", "keywords": [], "tags": []},
        ],
        "prompts": {"tunnels": []},
    }


def test_write_wingpack_emits_six_members(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert {"manifest.json", "wingpack.yaml", "keywords.json", "rooms.json", "prompts.json"} <= names


def test_manifest_records_embedding_metadata(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["embedding_model"] == "all-MiniLM-L6-v2"
    assert manifest["embedding_dim"] == 384
    assert manifest["wing"] == "my-wing"
    assert manifest["drawer_count"] == 42
    assert "source_digest" in manifest


def test_default_filename_is_timestamped(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    assert out.name.endswith(".wingpack")
    # YYYYMMDD-HHMMSS.wingpack
    assert len(out.stem) == 15 and out.stem[8] == "-"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/test_wing_pack.py -v`
Expected: `ModuleNotFoundError: src.wing_pack`.

- [ ] **Step 3: Implement `src/wing_pack.py`**

```python
"""Wingpack bundle author — produces portable .wingpack zips."""

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


WINGPACK_SCHEMA_VERSION = "1.0"


class WingpackBuilder:
    """Builds a .wingpack zip in memory then writes to disk."""

    def __init__(self, wing_meta: dict[str, Any]):
        self.meta = wing_meta
        self._members: dict[str, bytes] = {}

    def add_manifest(self) -> None:
        manifest = {
            "schema_version": WINGPACK_SCHEMA_VERSION,
            "wing": self.meta["name"],
            "drawer_count": self.meta.get("drawer_count", 0),
            "embedding_model": self.meta["embedding_model"],
            "embedding_dim": self.meta["embedding_dim"],
            "source_digest": self._digest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._members["manifest.json"] = json.dumps(manifest, indent=2).encode()

    def add_wingpack_yaml(self) -> None:
        body = {
            "wing": self.meta["name"],
            "rooms": self.meta.get("rooms", []),
        }
        self._members["wingpack.yaml"] = yaml.safe_dump(body).encode()

    def add_keywords(self) -> None:
        kw = {r["name"]: r.get("keywords", []) for r in self.meta.get("rooms", [])}
        self._members["keywords.json"] = json.dumps(kw, indent=2).encode()

    def add_rooms(self) -> None:
        body = [
            {"name": r["name"], "tags": r.get("tags", []), "keywords": r.get("keywords", [])}
            for r in self.meta.get("rooms", [])
        ]
        self._members["rooms.json"] = json.dumps(body, indent=2).encode()

    def add_prompts(self) -> None:
        self._members["prompts.json"] = json.dumps(
            self.meta.get("prompts", {"tunnels": []}), indent=2
        ).encode()

    def add_sync_manifest(self, sync_manifest: dict) -> None:
        self._members["sync_manifest.json"] = json.dumps(sync_manifest, indent=2).encode()

    def write(self, output_path: Path) -> Path:
        self.add_manifest()
        self.add_wingpack_yaml()
        self.add_keywords()
        self.add_rooms()
        self.add_prompts()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in self._members.items():
                zf.writestr(name, data)
        return output_path

    def _digest(self) -> str:
        blob = json.dumps(self.meta.get("rooms", []), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def write_wingpack(wing_meta: dict[str, Any], output_dir: Path) -> Path:
    """Convenience: timestamped filename, default location."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = Path(output_dir) / f"{ts}.wingpack"
    return WingpackBuilder(wing_meta).write(output_path)
```

- [ ] **Step 4: Run, confirm PASS**

`pytest tests/test_wing_pack.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wing_pack.py tests/test_wing_pack.py
git commit -m "feat(wing_pack): author .wingpack bundles with manifest + embedding metadata"
```

### Task 2.2: `wing_publish.py` — stage bundle into source repo

- [ ] **Step 1: Write failing test**

Create `tests/test_wing_publish.py`:

```python
"""Wingpack publish tests."""

import json
import zipfile
from pathlib import Path

import pytest

from src.wing_pack import write_wingpack
from src.wing_publish import PublishRefused, publish_to_repo


def _bundle(tmp_path: Path, wing="my-wing", dim=384) -> Path:
    meta = {
        "name": wing,
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": dim,
        "drawer_count": 1,
        "rooms": [{"name": "general", "keywords": []}],
        "prompts": {"tunnels": []},
    }
    return write_wingpack(meta, tmp_path)


def test_publish_writes_wingpack_into_repo(tmp_path):
    bundle = _bundle(tmp_path / "src")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = publish_to_repo(bundle, repo_root=repo, mode="default")
    assert result.path.exists()
    assert result.path.parent == repo / ".mempalace" / "wings"


def test_publish_refuses_embedding_dim_mismatch(tmp_path):
    bundle = _bundle(tmp_path / "src", dim=512)
    repo = tmp_path / "repo"
    repo.mkdir()
    # Seed repo with a stale wingpack at 384
    stale_meta = {
        "name": "my-wing",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "drawer_count": 0,
        "rooms": [],
    }
    stale = write_wingpack(stale_meta, repo / ".mempalace" / "wings")
    with pytest.raises(PublishRefused, match="embedding"):
        publish_to_repo(bundle, repo_root=repo, mode="default")


def test_publish_dry_run_does_not_write(tmp_path):
    bundle = _bundle(tmp_path / "src")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = publish_to_repo(bundle, repo_root=repo, mode="default", dry_run=True)
    assert not (repo / ".mempalace").exists()
    assert result.dry_run is True
```

- [ ] **Step 2: Confirm FAIL** — `pytest tests/test_wing_publish.py -v`.

- [ ] **Step 3: Implement `src/wing_publish.py`**

```python
"""Publish .wingpack bundles into source repos."""

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


class PublishRefused(RuntimeError):
    """Raised when a compatibility gate blocks a publish."""


@dataclass
class PublishResult:
    path: Path
    mode: str
    dry_run: bool


PUBLISH_MODES = {"default", "force", "keep"}
BLOCKED_WING_NAMES = {"wing_user"}  # never re-publish user-private data


def _read_manifest(bundle: Path) -> dict:
    with zipfile.ZipFile(bundle) as zf:
        return json.loads(zf.read("manifest.json"))


def _existing_manifest(dest_dir: Path) -> dict | None:
    if not dest_dir.exists():
        return None
    candidates = sorted(dest_dir.glob("*.wingpack"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return _read_manifest(candidates[0])


def _check_compat(new_m: dict, old_m: dict | None) -> None:
    if new_m["wing"] in BLOCKED_WING_NAMES:
        raise PublishRefused(f"wing {new_m['wing']!r} is blocked from publish")
    if old_m is None:
        return
    if new_m["embedding_dim"] != old_m["embedding_dim"]:
        raise PublishRefused(
            f"embedding dim mismatch: new={new_m['embedding_dim']} vs existing={old_m['embedding_dim']}"
        )
    if new_m["embedding_model"] != old_m["embedding_model"]:
        raise PublishRefused(
            f"embedding model mismatch: new={new_m['embedding_model']!r} vs {old_m['embedding_model']!r}"
        )


def publish_to_repo(
    bundle: Path,
    repo_root: Path,
    mode: str = "default",
    dry_run: bool = False,
) -> PublishResult:
    """Stage a .wingpack at <repo>/.mempalace/wings/<bundle>.

    Raises PublishRefused on compatibility gate failure.
    """
    if mode not in PUBLISH_MODES:
        raise ValueError(f"mode must be one of {PUBLISH_MODES}, got {mode!r}")

    bundle = Path(bundle)
    repo_root = Path(repo_root)
    dest_dir = repo_root / ".mempalace" / "wings"

    new_m = _read_manifest(bundle)
    old_m = _existing_manifest(dest_dir)
    _check_compat(new_m, old_m)

    if mode == "keep" and old_m is not None:
        return PublishResult(path=dest_dir / bundle.name, mode=mode, dry_run=False)

    dest = dest_dir / bundle.name
    if dry_run:
        return PublishResult(path=dest, mode=mode, dry_run=True)

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, dest)
    return PublishResult(path=dest, mode=mode, dry_run=False)
```

- [ ] **Step 4: Confirm PASS** — `pytest tests/test_wing_publish.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/wing_publish.py tests/test_wing_publish.py
git commit -m "feat(wing_publish): stage wingpacks into source repos with compat gates"
```

### Task 2.3: `auto_publish.py` — post-sync hook

- [ ] **Step 1: Implement**

Create `src/auto_publish.py`:

```python
"""Post-sync hook: re-export wings as .wingpack and publish back into source repos."""

import json
from pathlib import Path

from src.wing_pack import write_wingpack
from src.wing_publish import PublishRefused, publish_to_repo


def publish_all_wings(
    repos_json_path: Path,
    exports_dir: Path,
    wing_metas: dict[str, dict],
    mode: str = "default",
) -> list[dict]:
    """For each registered repo, author a fresh wingpack and publish into its repo root."""
    repos = json.loads(Path(repos_json_path).read_text())
    results = []
    for slug, entry in repos.items():
        wing_name = entry.get("wing", slug)
        meta = wing_metas.get(wing_name)
        if meta is None:
            results.append({"slug": slug, "status": "skipped", "reason": "no wing meta"})
            continue
        bundle = write_wingpack(meta, exports_dir)
        try:
            pr = publish_to_repo(bundle, repo_root=Path(entry["path"]), mode=mode)
            results.append({"slug": slug, "status": "published", "path": str(pr.path)})
        except PublishRefused as exc:
            results.append({"slug": slug, "status": "refused", "reason": str(exc)})
    return results
```

- [ ] **Step 2: Smoke test manually**

```bash
python -c "from src.auto_publish import publish_all_wings; print('import ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/auto_publish.py
git commit -m "feat(auto_publish): post-sync hook to re-export + publish wingpacks"
```

### Phase 2 Exit Criteria

- `pytest tests/test_wing_pack.py tests/test_wing_publish.py -v` green.
- `src/auto_publish.py` imports cleanly.
- Manual: author a wingpack from a test wing and inspect its zip members.

---

<a id="phase-3-snapshot-restore"></a>
## Phase 3: `wing_user` Snapshot + Restore

**Goal:** Daily sqlite snapshot of `wing_user` + boot-time auto-restore when the palace volume is wiped. Two scripts wired into `entrypoint.sh` per CONTEXT.md §5 + §7.

**Files:**
- Create: `src/wing_user_snapshot.py`
- Create: `src/restore_wing_user.py`
- Create: `tests/test_wing_user_snapshot.py`
- Create: `tests/test_restore_wing_user.py`

### Task 3.1: `wing_user_snapshot.py`

A snapshot = JSON dump of all drawers in `wing_user`, written to `exports/wing_user_backup_YYYYMMDD.json`. Pruning keeps N most recent.

- [ ] **Step 1: Write failing test**

Create `tests/test_wing_user_snapshot.py`:

```python
"""wing_user snapshot tests."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.wing_user_snapshot import snapshot_wing_user, prune_snapshots


def test_snapshot_writes_dated_json(tmp_palace, tmp_path):
    # tmp_palace fixture yields a data dir w/ wing_user seeded
    export_dir = tmp_path / "exports"
    out = snapshot_wing_user(palace_path=tmp_palace, exports_dir=export_dir)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "drawers" in data
    assert "captured_at" in data


def test_prune_keeps_recent(tmp_path):
    exp = tmp_path / "exports"
    exp.mkdir()
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = (now - timedelta(days=i)).strftime("%Y%m%d")
        p = exp / f"wing_user_backup_{ts}.json"
        p.write_text("{}")
    pruned = prune_snapshots(exp, retention_days=3)
    remaining = sorted(exp.glob("wing_user_backup_*.json"))
    assert len(remaining) == 3
    assert len(pruned) == 7
```

- [ ] **Step 2: Confirm FAIL**

- [ ] **Step 3: Implement `src/wing_user_snapshot.py`**

```python
"""Daily sqlite snapshot of wing_user — writes exports/wing_user_backup_YYYYMMDD.json."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mempalace.palace import get_collection


BACKUP_RE = re.compile(r"wing_user_backup_(\d{8})\.json$")


def snapshot_wing_user(palace_path: Path, exports_dir: Path) -> Path:
    """Dump all wing_user drawers to a dated JSON file. Idempotent per day."""
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = exports_dir / f"wing_user_backup_{ts}.json"

    col = get_collection(palace_path=palace_path, wing_name="wing_user")
    # mempalace collection API — list all drawers (ids, documents, metadatas)
    raw = col.get()  # returns {ids, documents, metadatas, embeddings?}
    drawers = [
        {"id": rid, "content": doc, "metadata": meta}
        for rid, doc, meta in zip(raw["ids"], raw["documents"], raw["metadatas"])
    ]

    payload = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "drawer_count": len(drawers),
        "drawers": drawers,
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def prune_snapshots(exports_dir: Path, retention_days: int) -> list[Path]:
    """Delete wing_user_backup_*.json files older than retention_days. Returns pruned paths."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = []
    for p in Path(exports_dir).glob("wing_user_backup_*.json"):
        m = BACKUP_RE.search(p.name)
        if not m:
            continue
        dt = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
        if dt < cutoff:
            p.unlink()
            pruned.append(p)
    return pruned


def main():
    import os
    palace = Path(os.environ.get("PALACE_PATH", "/data"))
    exports = Path(os.environ.get("MEMPALACE_EXPORTS_DIR", "/exports"))
    retention = int(os.environ.get("MEMPALACE_EXPORTS_RETENTION", "7"))
    out = snapshot_wing_user(palace, exports)
    pruned = prune_snapshots(exports, retention)
    print(f"snapshot: {out} (pruned {len(pruned)} old backups)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Extend `tests/conftest.py`** to provide a `tmp_palace` with `wing_user` seeded.

Add a fixture:

```python
@pytest.fixture
def tmp_palace_with_wing_user(tmp_path):
    """A palace with a seeded wing_user collection containing 2 drawers."""
    from mempalace.palace import get_collection
    palace = tmp_path / "palace"
    palace.mkdir()
    col = get_collection(palace_path=palace, wing_name="wing_user")
    col.add(
        ids=["d1", "d2"],
        documents=["I'm frustrated about X", "Decision: use Y"],
        metadatas=[{"hall": "frustrations", "topic": "debugging"},
                   {"hall": "decisions", "topic": "architecture"}],
    )
    return palace
```

Update the test to use `tmp_palace_with_wing_user`.

- [ ] **Step 5: Confirm PASS** — `pytest tests/test_wing_user_snapshot.py -v`.

- [ ] **Step 6: Commit**

```bash
git add src/wing_user_snapshot.py tests/test_wing_user_snapshot.py tests/conftest.py
git commit -m "feat(snapshot): daily wing_user sqlite snapshot with retention pruning"
```

### Task 3.2: `restore_wing_user.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_restore_wing_user.py`:

```python
"""wing_user restore tests."""

import json
from pathlib import Path

import pytest

from src.restore_wing_user import restore_if_empty
from src.wing_user_snapshot import snapshot_wing_user


def test_restore_noops_when_non_empty(tmp_palace_with_wing_user, tmp_path):
    exp = tmp_path / "exports"
    snapshot_wing_user(tmp_palace_with_wing_user, exp)
    result = restore_if_empty(tmp_palace_with_wing_user, exp)
    assert result["action"] == "skipped"
    assert result["reason"] == "wing_user not empty"


def test_restore_reinserts_when_empty(tmp_palace_with_wing_user, tmp_path):
    from mempalace.palace import get_collection
    exp = tmp_path / "exports"
    snapshot_wing_user(tmp_palace_with_wing_user, exp)
    # Wipe wing_user
    col = get_collection(palace_path=tmp_palace_with_wing_user, wing_name="wing_user")
    col.delete(ids=["d1", "d2"])
    assert len(col.get()["ids"]) == 0
    # Restore
    result = restore_if_empty(tmp_palace_with_wing_user, exp)
    assert result["action"] == "restored"
    assert result["drawers_restored"] == 2


def test_restore_noops_when_no_backup(tmp_palace_with_wing_user, tmp_path):
    from mempalace.palace import get_collection
    col = get_collection(palace_path=tmp_palace_with_wing_user, wing_name="wing_user")
    col.delete(ids=["d1", "d2"])
    result = restore_if_empty(tmp_palace_with_wing_user, tmp_path / "empty_exports")
    assert result["action"] == "skipped"
    assert "no backup" in result["reason"].lower()
```

- [ ] **Step 2: Confirm FAIL**

- [ ] **Step 3: Implement `src/restore_wing_user.py`**

```python
"""Auto-restore wing_user from newest backup if the collection is empty."""

import json
from pathlib import Path

from mempalace.palace import get_collection


def _newest_backup(exports_dir: Path) -> Path | None:
    exports_dir = Path(exports_dir)
    if not exports_dir.exists():
        return None
    backups = sorted(
        exports_dir.glob("wing_user_backup_*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    return backups[0] if backups else None


def restore_if_empty(palace_path: Path, exports_dir: Path) -> dict:
    """Re-insert wing_user drawers from newest backup if wing_user is empty.

    Returns {action: 'restored'|'skipped', ...}.
    """
    col = get_collection(palace_path=palace_path, wing_name="wing_user")
    current = col.get()
    if len(current["ids"]) > 0:
        return {"action": "skipped", "reason": "wing_user not empty"}

    backup = _newest_backup(exports_dir)
    if backup is None:
        return {"action": "skipped", "reason": "no backup available"}

    data = json.loads(backup.read_text())
    drawers = data["drawers"]
    if not drawers:
        return {"action": "skipped", "reason": "backup empty"}

    col.add(
        ids=[d["id"] for d in drawers],
        documents=[d["content"] for d in drawers],
        metadatas=[d["metadata"] for d in drawers],
    )
    return {
        "action": "restored",
        "drawers_restored": len(drawers),
        "source": str(backup),
    }


def main():
    import os
    palace = Path(os.environ.get("PALACE_PATH", "/data"))
    exports = Path(os.environ.get("MEMPALACE_EXPORTS_DIR", "/exports"))
    print(restore_if_empty(palace, exports))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Confirm PASS** — `pytest tests/test_restore_wing_user.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/restore_wing_user.py tests/test_restore_wing_user.py
git commit -m "feat(restore): auto-restore wing_user from newest backup on empty collection"
```

### Phase 3 Exit Criteria

- `pytest tests/test_wing_user_snapshot.py tests/test_restore_wing_user.py -v` green.
- Manual: run `python -m src.wing_user_snapshot` then wipe wing_user, then `python -m src.restore_wing_user` — verify restore succeeds.

---

<a id="phase-4-mcp-tools"></a>
## Phase 4: MCP Tools Completion

**Goal:** Register the 22 tool handlers missing from `src/mcp_http_server.py` per CONTEXT.md §9. Plus a `/health` HTTP endpoint. Most tools are thin wrappers over `mempalace` top-level functions — verify API shapes in `.venv/lib/python3.12/site-packages/mempalace/` before writing.

**Strategy:** Implement in tool-group batches, with one test per tool verifying registration + schema. Execute behavior tests only for tools with non-trivial wiring (search, kg_query, resync).

**Files:**
- Modify: `src/mcp_http_server.py`
- Modify: `src/tools.py` (or split into `src/tools/navigation.py`, `src/tools/kg.py`, etc. if file gets >500 lines)
- Create: `tests/test_mcp_tools_extended.py`

### Task 4.1: Audit mempalace API surface

- [ ] **Step 1:** Read `.venv/lib/python3.12/site-packages/mempalace/palace.py`, `knowledge_graph.py`, and top-level `__init__.py`. Document which public functions exist for: `list_wings`, `list_rooms`, `search`, `kg_query`, `kg_add`, `traverse`, `find_tunnels`, `create_tunnel`, `list_tunnels`, `diary_write`, `diary_read`, `export_wing`.

- [ ] **Step 2:** Record findings as a comment block at the top of `src/tools.py`:

```python
# mempalace public API map (verified 2026-04-17 against mempalace 3.3.0):
# - palace.list_wings() -> list[str]
# - palace.list_rooms(wing) -> list[dict]
# - palace.search(query, wing=None, room=None, n=10) -> list[dict]
# - knowledge_graph.kg_query(entity, as_of=None, direction=None) -> ...
# - ... etc
# If an upstream API differs, update this map and the wrapper accordingly.
```

If a function doesn't exist upstream, note it: we'll need to implement it here, or skip and document in CONTEXT.md §9 as "not yet available."

### Task 4.2: Navigation tools

Batch: `status`, `list_wings`, `list_rooms`, `check_logs`, `get_logs_recent`.

- [ ] **Step 1:** Write registration tests (extend `tests/test_mcp_server.py`):

```python
def test_navigation_tools_registered(server):
    tool_names = {t.name for t in server.list_tools()}
    expected = {
        "mempalace_status",
        "mempalace_list_wings",
        "mempalace_list_rooms",
        "mempalace_check_logs",
        "mempalace_get_logs_recent",
    }
    assert expected <= tool_names
```

Note: the `server` fixture should call `create_server()` from `src.mcp_http_server`.

- [ ] **Step 2:** Confirm FAIL.

- [ ] **Step 3:** Add handlers to `src/tools.py`:

```python
def handle_status(palace_path: str, config_path: str) -> dict:
    from mempalace.palace import list_wings
    return {"ok": True, "wings": list_wings(palace_path=palace_path)}


def handle_list_wings(palace_path: str) -> list[str]:
    from mempalace.palace import list_wings
    return list_wings(palace_path=palace_path)


def handle_list_rooms(palace_path: str, wing: str | None = None) -> list[dict]:
    from mempalace.palace import list_rooms
    return list_rooms(palace_path=palace_path, wing=wing)


def handle_check_logs(palace_path: str, content: str, threshold: float = 0.65) -> dict:
    """Semantic dedup check — does a similar drawer already exist?"""
    from mempalace.palace import search
    hits = search(query=content, palace_path=palace_path, n=3)
    top = hits[0] if hits else None
    return {"duplicate": bool(top and top.get("score", 0) >= threshold), "top": top}


def handle_get_logs_recent(palace_path: str, n: int = 20) -> list[dict]:
    from mempalace.palace import list_drawers
    return list_drawers(palace_path=palace_path, n=n, order="recent")
```

(If `mempalace.palace.list_drawers` lacks `order="recent"`, sort client-side by metadata timestamp.)

- [ ] **Step 4:** Register in `mcp_http_server.py`:

```python
# --- Navigation tools (5) ---

@mcp.tool()
def mempalace_status() -> dict:
    """Palace health + wing count."""
    return handle_status(palace_path, config_path)

@mcp.tool()
def mempalace_list_wings() -> list[str]:
    """List all wing names."""
    return handle_list_wings(palace_path)

@mcp.tool()
def mempalace_list_rooms(wing: str | None = None) -> list[dict]:
    """List rooms (optionally filtered by wing)."""
    return handle_list_rooms(palace_path, wing=wing)

@mcp.tool()
def mempalace_check_logs(content: str, threshold: float = 0.65) -> dict:
    """Check if content semantically duplicates an existing drawer."""
    return handle_check_logs(palace_path, content=content, threshold=threshold)

@mcp.tool()
def mempalace_get_logs_recent(n: int = 20) -> list[dict]:
    """Most recent drawers across the palace."""
    return handle_get_logs_recent(palace_path, n=n)
```

- [ ] **Step 5:** Confirm PASS. Commit: `feat(mcp): add navigation tools (status, list_wings, list_rooms, check_logs, get_logs_recent)`.

### Task 4.3: Search tools

Batch: `search`, `search_all`.

- [ ] **Step 1:** Handler:

```python
def handle_search(
    palace_path: str,
    query: str,
    wing: str | None = None,
    room: str | None = None,
    slug: str | None = None,
    n: int = 10,
) -> list[dict]:
    from mempalace.palace import search
    return search(query=query, palace_path=palace_path, wing=wing, room=room, n=n)


def handle_search_all(palace_path: str, query: str, n: int = 10) -> list[dict]:
    from mempalace.palace import search
    return search(query=query, palace_path=palace_path, n=n)
```

- [ ] **Step 2:** Register:

```python
@mcp.tool()
def mempalace_search(
    query: str,
    slug: str | None = None,
    wing: str | None = None,
    room: str | None = None,
    n: int = 10,
) -> list[dict]:
    """Semantic search within the palace."""
    return handle_search(palace_path, query=query, wing=wing, room=room, slug=slug, n=n)

@mcp.tool()
def mempalace_search_all(query: str, n: int = 10) -> list[dict]:
    """Cross-wing semantic search."""
    return handle_search_all(palace_path, query=query, n=n)
```

- [ ] **Step 3:** Add smoke test in `tests/test_mcp_tools_extended.py` that calls `handle_search` against a fixture palace with a known drawer, verifies a hit. Commit: `feat(mcp): add search + search_all`.

### Task 4.4: KG tools

Batch: `kg_query`, `kg_add`, `kg_time`, `kg_time_kv`, `kg_stats`.

- [ ] **Step 1:** Handlers wrap `mempalace.knowledge_graph`:

```python
def handle_kg_query(palace_path, entity, as_of=None, direction=None):
    from mempalace.knowledge_graph import kg_query
    return kg_query(palace_path=palace_path, entity=entity, as_of=as_of, direction=direction)

def handle_kg_add(palace_path, subject, predicate, object_, valid_from=None, source_time=None):
    from mempalace.knowledge_graph import kg_add
    return kg_add(palace_path=palace_path, subject=subject, predicate=predicate,
                  object=object_, valid_from=valid_from, source_time=source_time)

def handle_kg_time(palace_path, entity=None):
    from mempalace.knowledge_graph import kg_time
    return kg_time(palace_path=palace_path, entity=entity)

def handle_kg_time_kv(palace_path, entry=None, **kwargs):
    from mempalace.knowledge_graph import kg_time_kv
    return kg_time_kv(palace_path=palace_path, entry=entry, **kwargs)

def handle_kg_stats(palace_path):
    from mempalace.knowledge_graph import kg_stats
    return kg_stats(palace_path=palace_path)
```

- [ ] **Step 2:** Register five `@mcp.tool()` decorators with matching signatures in `mcp_http_server.py`. Use `object_` → `object` rename in tool signature (Python keyword collision is fine as a function argument if quoted: `object: str`). Commit: `feat(mcp): add KG tools (kg_query, kg_add, kg_time, kg_time_kv, kg_stats)`.

### Task 4.5: Graph traversal tools

Batch: `traverse`, `find_tunnels`.

- [ ] Same pattern: `mempalace.knowledge_graph.traverse(start_room, max_hops=N)` and `find_tunnels(root, max_hops=N)`. Wire + commit.

### Task 4.6: Drawers tools

Batch: `kg_drawer`, `delete_drawer`, `list_drawers`, `update_drawer`.

- [ ] Wire to `mempalace.palace.*`. Commit.

### Task 4.7: Tunnels tools

Batch: `create_tunnel`, `delete_tunnel`, `list_tunnels`, `tunnel_read`.

- [ ] Wire to `mempalace.knowledge_graph.*`. Commit.

### Task 4.8: Diary tools

Batch: `diary_write`, `diary_read`, `diary_read_time`.

- [ ] Wire to `mempalace.diary` (or equivalent upstream module). If not available upstream, skip and document in CONTEXT.md §9.

### Task 4.9: Ops tools

Batch: add `mempalace_resync`.

```python
@mcp.tool()
def mempalace_resync(fix_blob_ids: bool = True, full_refresh: bool = False, output_dir: str | None = None) -> dict:
    """Trigger a resync with optional blob-id repair and full refresh."""
    return handle_sync(config_path=config_path, data_path=palace_path, full=full_refresh)
```

### Task 4.10: Wing sharing

```python
@mcp.tool()
def mempalace_export_wing(slug: str, output_dir: str | None = None) -> dict:
    """Export a wing as a .wingpack bundle."""
    from src.wing_pack import write_wingpack
    from mempalace.palace import list_rooms, list_wings
    # Assemble wing_meta from live state, then author a bundle
    # (implementation depends on mempalace API for embedding metadata)
    ...
```

### Task 4.11: `/health` HTTP endpoint

- [ ] **Step 1:** FastMCP exposes a Starlette app via `mcp.streamable_http_app()`. Mount a `/health` route on it:

```python
def _build_health_route():
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from datetime import datetime, timezone

    async def health(request):
        from mempalace.palace import list_wings
        try:
            wings = list_wings(palace_path=palace_path)
            return JSONResponse({"ok": True, "wings": wings, "ts": datetime.now(timezone.utc).isoformat()})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    return Route("/health", health)


# In main(): build the streamable-http app and insert the route
def main():
    server = create_server()
    app = server.streamable_http_app()  # Starlette app
    app.routes.append(_build_health_route())
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MEMPALACE_PORT", "8080")))
```

- [ ] **Step 2:** Integration test: `curl -sf http://localhost:8080/health` after `docker compose up -d` returns 200 JSON. Capture this as a test in `tests/test_health.py` using `httpx.AsyncClient(app=app)`.

- [ ] **Step 3:** Commit: `feat(mcp): add /health HTTP endpoint for Docker healthcheck + diagnostics`.

### Phase 4 Exit Criteria

- All 22+ new tools registered (verify via `test_mcp_server.py` counting tools).
- `/health` returns 200 when palace is reachable.
- `pytest -q` green.

---

<a id="phase-5-docker"></a>
## Phase 5: Docker Runtime Hardening

**Goal:** Align `Dockerfile`, `docker-compose.yml`, `entrypoint.sh` with CONTEXT.md §5.

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `entrypoint.sh`

### Task 5.1: Rewrite `Dockerfile`

- [ ] **Step 1:** Replace content:

```dockerfile
FROM --platform=linux/arm64 python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl \
    && rm -rf /var/lib/apt/lists/*

ENV MEMPALACE_REPOS_ROOT=/repos \
    MEMPALACE_STATIC_DIRS=/config \
    MEMPALACE_PORT=8080 \
    MEMPALACE_EXPORTS_RETENTION=7 \
    MEMPALACE_EXPORTS_DIR=/exports \
    PALACE_PATH=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download embedding model so cold start waits ~80s once, not every boot.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY src/ src/
COPY mems_cli/ mems_cli/
COPY config/ /config/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
```

- [ ] **Step 2:** Build: `docker compose build`. Expect success (cold first build ~5min for embedding download).

- [ ] **Step 3:** Commit: `feat(docker): add healthcheck, env vars, embedding warmup, port 8080`.

### Task 5.2: Rewrite `docker-compose.yml`

- [ ] **Step 1:** Replace content:

```yaml
services:
  memory:
    build: .
    ports:
      - "8787:8080"   # host:container — CONTEXT.md §5
    volumes:
      - palace_data:/data
      - exports_data:/exports
      - ~/Code/edens.zac:/repos/edens.zac:ro
      - ~/Code/edens.zac.backend:/repos/edens.zac.backend:ro
      - ~/Code/edens.zac.backend.go:/repos/edens.zac.backend.go:ro
      - ~/Code/edens.zac.ml:/repos/edens.zac.ml:ro
      - ~/Code/lightroom-portfolio-export:/repos/lightroom-portfolio-export:ro
      - ~/Code/job-search:/repos/job-search:ro
      - ~/Code/running:/repos/running:ro
      - ~/Code/Memory:/repos/Memory:ro
    environment:
      - MEMPALACE_PORT=8080
      - MEMPALACE_REPOS_ROOT=/repos
      - MEMPALACE_STATIC_DIRS=/config
      - MEMPALACE_EXPORTS_DIR=/exports
      - MEMPALACE_EXPORTS_RETENTION=7
      - PALACE_PATH=/data
      - CONFIG_PATH=/config

volumes:
  palace_data:
  exports_data:
```

- [ ] **Step 2:** Smoke test: `docker compose up -d --wait`. Then `curl -sf http://localhost:8787/health` → 200.

- [ ] **Step 3:** Commit: `feat(compose): port 8787→8080, exports volume, canonical env vars`.

### Task 5.3: Rewrite `entrypoint.sh`

- [ ] **Step 1:** Replace with the full snapshot→restore→sync→serve flow:

```bash
#!/bin/bash
set -e

echo "Memory Palace starting..."

# 1. Snapshot wing_user (always)
echo "  → snapshot wing_user"
python -m src.wing_user_snapshot || echo "  (snapshot skipped — wing_user not yet initialized)"

# 2. Restore wing_user if empty
echo "  → restore wing_user if empty"
python -m src.restore_wing_user || true

# 3. Sync — incremental by default, full if MEMPALACE_FULL_REFRESH=true
echo "  → sync"
if [ "${MEMPALACE_FULL_REFRESH:-false}" = "true" ]; then
    python -c "
from src.sync_engine import SyncEngine
import os
engine = SyncEngine(config_path=os.environ['CONFIG_PATH'], data_path=os.environ['PALACE_PATH'])
for name in engine.repos:
    print(f'  full-sync: {name}', flush=True)
    engine.full_sync(wing_name=name)
"
elif [ ! -f /data/sync_ledger.json ]; then
    python -c "
from src.sync_engine import SyncEngine
import os
engine = SyncEngine(config_path=os.environ['CONFIG_PATH'], data_path=os.environ['PALACE_PATH'])
for name in engine.repos:
    print(f'  first-boot sync: {name}', flush=True)
    engine.full_sync(wing_name=name)
"
else
    python -c "
from src.sync_engine import SyncEngine
import os
engine = SyncEngine(config_path=os.environ['CONFIG_PATH'], data_path=os.environ['PALACE_PATH'])
for name in engine.repos:
    print(f'  incremental: {name}', flush=True)
    engine.incremental_sync(wing_name=name)
"
fi

# 4. Serve
echo "Starting MCP server on port ${MEMPALACE_PORT:-8080}..."
exec python -m src.mcp_http_server
```

- [ ] **Step 2:** Boot + verify logs show snapshot→restore→sync→serve in order: `docker compose up && docker compose logs memory | head -40`.

- [ ] **Step 3:** Commit: `feat(entrypoint): snapshot→restore→sync→serve flow with full-refresh gate`.

### Phase 5 Exit Criteria

- `docker compose up -d --wait` succeeds.
- `curl -sf http://localhost:8787/health` returns 200.
- `docker compose logs memory` shows the four-phase boot.

---

<a id="phase-6-cli-foundation"></a>
## Phase 6: `mems` CLI Foundation + `PalaceClient`

**Goal:** Create the `mems_cli/` package skeleton, console entry point, and `PalaceClient` that performs JSON-RPC against the MCP HTTP server.

**Files:**
- Create: `mems_cli/__init__.py`
- Create: `mems_cli/__main__.py`
- Create: `mems_cli/main.py`
- Create: `mems_cli/common.py`
- Create: `tests/test_cli_main.py`
- Create: `tests/test_palace_client.py`

### Task 6.1: Package skeleton + console script

- [ ] **Step 1:** Create `mems_cli/__init__.py`:

```python
"""mems — Memory Palace CLI wrapper around the MCP HTTP server."""

__version__ = "0.1.0"
```

- [ ] **Step 2:** Create `mems_cli/main.py`:

```python
"""Console script entry point for `mems`."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mems", description="Memory Palace CLI")
    subs = parser.add_subparsers(dest="command", required=True)

    # Placeholders — wired in Phase 7.
    subs.add_parser("list", help="List registered repos")
    subs.add_parser("doctor", help="Verify palace health")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        from mems_cli.repo_registry import cmd_list
        return cmd_list(args)
    if args.command == "doctor":
        from mems_cli.palace_ops import cmd_doctor
        return cmd_doctor(args)
    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3:** Create `mems_cli/__main__.py`:

```python
from mems_cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4:** Remove the `xfail` markers from `tests/test_packaging.py` added in Phase 0.

- [ ] **Step 5:** Reinstall + run tests:

```bash
pip install -e ".[dev]"
pytest tests/test_packaging.py -v
```

Expected: both tests pass. Commit: `feat(cli): package skeleton, console entry point, argparse scaffold`.

### Task 6.2: `PalaceClient` — JSON-RPC to MCP server

- [ ] **Step 1:** Write failing test `tests/test_palace_client.py`:

```python
"""PalaceClient JSON-RPC tests."""

import json
from unittest.mock import patch, MagicMock

import pytest

from mems_cli.common import PalaceClient, PalaceError


def test_call_posts_jsonrpc_tool_call():
    with patch("mems_cli.common.urllib.request.urlopen") as uo:
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": '{"ok": true}'}]},
        }).encode()
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda *a: None
        uo.return_value = resp

        client = PalaceClient(url="http://localhost:8787")
        out = client.call("mempalace_status", {})
        assert out == {"ok": True}


def test_call_raises_on_rpc_error():
    with patch("mems_cli.common.urllib.request.urlopen") as uo:
        resp = MagicMock()
        resp.read.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }).encode()
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda *a: None
        uo.return_value = resp

        client = PalaceClient(url="http://localhost:8787")
        with pytest.raises(PalaceError, match="Method not found"):
            client.call("bad_tool", {})
```

- [ ] **Step 2:** Confirm FAIL.

- [ ] **Step 3:** Implement `mems_cli/common.py`:

```python
"""Shared utilities — PalaceClient for MCP JSON-RPC."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class PalaceError(RuntimeError):
    """An MCP RPC call failed."""


def default_url() -> str:
    return os.environ.get("MEMPALACE_URL", "http://localhost:8787")


def mems_root() -> Path:
    """Resolve the mems repo root — walks up from this file."""
    env = os.environ.get("MEMS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


class PalaceClient:
    """Minimal JSON-RPC client for FastMCP's streamable-http endpoint."""

    def __init__(self, url: str | None = None, timeout: float = 30.0):
        self.url = (url or default_url()).rstrip("/")
        self.timeout = timeout
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def call(self, tool: str, arguments: dict) -> dict | list | str:
        """Invoke an MCP tool via JSON-RPC 2.0 tools/call."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        req = urllib.request.Request(
            f"{self.url}/mcp",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode()
        except urllib.error.URLError as exc:
            raise PalaceError(f"connection error: {exc}") from exc

        msg = json.loads(body)
        if "error" in msg:
            raise PalaceError(msg["error"].get("message", "unknown MCP error"))

        # FastMCP returns result.content = [{"type":"text","text":"<json>"}]
        content = msg.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0]["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return msg.get("result")

    def health(self) -> dict:
        req = urllib.request.Request(f"{self.url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())
```

- [ ] **Step 4:** Confirm PASS. Commit: `feat(cli): PalaceClient — stdlib-only JSON-RPC to MCP server`.

### Phase 6 Exit Criteria

- `mems --help` prints a usage banner with at least `list`, `doctor`.
- `mems_cli.common.PalaceClient` can call a live server (manual smoke test after Phase 5).
- `pytest tests/test_palace_client.py tests/test_packaging.py -v` green.

---

<a id="phase-7-cli-commands"></a>
## Phase 7: `mems` CLI Command Surface

**Goal:** Implement the full command surface from CONTEXT.md §8: repo registry, publishing, palace ops, search, tickets, hybrid. Each module is one file in `mems_cli/` and registers sub-commands via `main.py`.

**Files:**
- Create: `mems_cli/repo_registry.py`
- Create: `mems_cli/publishing.py`
- Create: `mems_cli/palace_ops.py`
- Create: `mems_cli/search.py`
- Create: `mems_cli/tickets.py`
- Create: `mems_cli/hybrid.py`
- Create: `tests/test_repo_registry.py` (and one per module)
- Modify: `mems_cli/main.py`

**Shared pattern:** Each module exports:
- `def register(subs: argparse._SubParsersAction) -> None` — wires its parsers
- `def cmd_<name>(args) -> int` — one handler per subcommand

Then `main.py` imports each module's `register()`.

### Task 7.1: `repo_registry.py`

Commands: `list`, `add`, `scaffold`, `unlist`, `remove`.

- [ ] **Step 1:** Write failing tests (cover `cmd_list` reading `config/repos.json`, `cmd_add` writing an entry, `cmd_unlist` removing one).

- [ ] **Step 2:** Implement:

```python
"""mems repo registry — manage config/repos.json."""

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from mems_cli.common import PalaceClient, mems_root


def _repos_json_path() -> Path:
    return mems_root() / "config" / "repos.json"


def _load_repos() -> dict:
    p = _repos_json_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _save_repos(data: dict) -> None:
    p = _repos_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def cmd_list(args) -> int:
    repos = _load_repos()
    if not repos:
        print("(no repos registered)")
        return 0
    for slug, entry in repos.items():
        print(f"  {slug:30s}  {entry['wing']:20s}  {entry['path']}")
    return 0


def cmd_add(args) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 1
    slug = path.name
    wing = slug.replace(".", "-").replace("_", "-")
    repos = _load_repos()
    repos[slug] = {"path": str(path), "wing": wing}
    _save_repos(repos)
    print(f"registered {slug} → wing {wing}")

    # Force-install wingpack YAML if present
    wingpacks = sorted((path / ".mempalace" / "wings").glob("*.wingpack"))
    if wingpacks:
        print(f"  found wingpack: {wingpacks[-1].name} — install via `mems publish`")
    if args.goto:
        subprocess.run(["open", str(path)], check=False)
    return 0


def cmd_scaffold(args) -> int:
    path = Path(args.repo).expanduser().resolve()
    wing_name = path.name.replace(".", "-")
    rooms = []
    for child in sorted(path.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            rooms.append({"name": child.name.lower(), "keywords": [child.name.lower()]})
    doc = {"wings": {wing_name: {"path": str(path), "rooms": rooms}}}
    out = path / ".mempalace" / "wingpack.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    out.write_text(yaml.safe_dump(doc))
    print(f"scaffolded {out}")
    if args.setup:
        cmd_add(argparse.Namespace(path=str(path), goto=False))
    return 0


def cmd_unlist(args) -> int:
    repos = _load_repos()
    if args.slug not in repos:
        print(f"error: {args.slug} not registered", file=sys.stderr)
        return 1
    del repos[args.slug]
    _save_repos(repos)
    print(f"unlisted {args.slug}")
    # Prompt to remove wing
    if sys.stdin.isatty():
        ans = input("also remove wing from palace? [y/N] ").strip().lower()
        if ans == "y":
            client = PalaceClient()
            try:
                client.call("mempalace_remove_wing", {"wing": args.slug})
            except Exception as exc:
                print(f"  wing removal failed: {exc}", file=sys.stderr)
    return 0


def cmd_remove(args) -> int:
    client = PalaceClient()
    try:
        result = client.call("mempalace_remove_wing", {"wing": args.name})
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def register(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser("list", help="Show registered repos")
    p.set_defaults(func=cmd_list)

    p = subs.add_parser("add", help="Register a repo")
    p.add_argument("path")
    p.add_argument("--goto", action="store_true")
    p.set_defaults(func=cmd_add)

    p = subs.add_parser("scaffold", help="Generate starter wing YAML")
    p.add_argument("repo")
    p.add_argument("--setup", action="store_true")
    p.set_defaults(func=cmd_scaffold)

    p = subs.add_parser("unlist", help="Unregister a slug")
    p.add_argument("slug")
    p.set_defaults(func=cmd_unlist)

    p = subs.add_parser("remove", help="Delete wing entirely")
    p.add_argument("name")
    p.set_defaults(func=cmd_remove)
```

- [ ] **Step 3:** Refactor `mems_cli/main.py` to dispatch via `args.func`:

```python
def build_parser():
    parser = argparse.ArgumentParser(prog="mems")
    subs = parser.add_subparsers(dest="command", required=True)

    from mems_cli import repo_registry, publishing, palace_ops, search, tickets, hybrid
    repo_registry.register(subs)
    publishing.register(subs)
    palace_ops.register(subs)
    search.register(subs)
    tickets.register(subs)
    hybrid.register(subs)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4:** Run tests + commit: `cli(repo): list/add/scaffold/unlist/remove`.

### Task 7.2: `publishing.py`

Commands: `publish <repo> [--dry-run]`, `tags`.

- [ ] Implement using `src.wing_pack.write_wingpack` + `src.wing_publish.publish_to_repo`. Call `PalaceClient.call("mempalace_export_wing", ...)` to get fresh wing metadata. Commit: `cli(publish): wingpack staging + tag listing`.

### Task 7.3: `palace_ops.py`

Commands: `sync [--full]`, `restart`, `make [--full]`, `doctor`.

Behaviors:
- `sync`: `client.call("memory_sync", {"full": args.full})`; exits nonzero if status != ok.
- `restart`: `subprocess.run(["docker", "compose", "restart", "memory"])`.
- `make`: snapshot wing_user (invoke `python -m src.wing_user_snapshot` on host — or via `docker exec`), `docker compose down -v`, `docker compose up --build --wait`, poll `/health`.
- `doctor`: check newest backup age (refuse if >6h unless `--force`), then run `make`.

- [ ] Implement + test (use mocks for subprocess). Commit: `cli(ops): sync/restart/make/doctor`.

### Task 7.4: `search.py`

Commands:
- `search <query> [--wing W] [--room R] [--list N] [--json]`
- `my frustrations | my questions | my goals | my todo | my tools | my recent | my <hall> --type T | my note "..."`

Each delegates to `PalaceClient.call("mempalace_search", {...})` or `mempalace_user_search`, `mempalace_user_summary`, `mempalace_user_write`.

- [ ] Implement. Commit: `cli(search): search + my-* subcommands`.

### Task 7.5: `tickets.py`

Commands: `tickets`, `todo`, `backlog`, `ticket <key>` + sub-actions.

- [ ] Implement Jira client in stdlib only — `urllib` + basic auth. Env vars from `~/.config/atlassian.env`. ADF flattener for comments. Commit: `cli(tickets): Jira integration, stdlib only`.

### Task 7.6: `hybrid.py`

Commands: `standup [--days N]`, `context <title>`.

- [ ] Implement. `standup` composes Jira + palace + git log for repos in `repos.json`. `context` runs palace search on ticket summary. Commit: `cli(hybrid): standup + context composers`.

### Phase 7 Exit Criteria

- `mems --help` lists all commands from CONTEXT.md §8.
- `mems list` prints registered repos.
- `mems doctor` verifies palace health end-to-end.
- `pytest tests/test_cli_*.py -v` green.

---

<a id="phase-8-installer"></a>
## Phase 8: `scripts/setup.sh` + IDE Integration

**Goal:** One-shot installer per CONTEXT.md §3. Populate `integration/` and `scripts/` with IDE configs and installer.

**Files:**
- Create: `scripts/setup.sh`
- Create: `integration/mempalace_mcp_cursor.json`
- Create: `integration/mempalace_codex_append.toml`
- Rename: `integration/stop-hook.sh` → `integration/mempalace-stop-hook.sh`
- Create: `scripts/mempalace-discovery.md`
- Create: `scripts/operations.md`
- Move: `integration/user-wing.mdc` → `scripts/user-wing.mdc`

### Task 8.1: IDE config snippets

- [ ] **Step 1:** Create `integration/mempalace_mcp_cursor.json`:

```json
{
  "mempalace": {
    "url": "http://localhost:8787/mcp",
    "transport": "http"
  }
}
```

- [ ] **Step 2:** Create `integration/mempalace_codex_append.toml`:

```toml
[[mcp_servers]]
name = "mempalace"
url = "http://localhost:8787/mcp"
transport = "http"
```

- [ ] **Step 3:** Rename stop hook:

```bash
git mv integration/stop-hook.sh integration/mempalace-stop-hook.sh
```

- [ ] **Step 4:** Commit: `feat(integration): Cursor + Codex MCP configs, renamed stop hook`.

### Task 8.2: Cursor rules

- [ ] **Step 1:** Move `integration/user-wing.mdc` → `scripts/user-wing.mdc` (keep as-is).

- [ ] **Step 2:** Create `scripts/mempalace-discovery.md` (search-first rule):

```markdown
---
alwaysApply: true
---
# Mempalace Discovery Rule

Before Grep/Glob/Read for exploring code, call `mempalace_search` first.
Use `mempalace_find_tunnels` for cross-wing connections.
```

- [ ] **Step 3:** Create `scripts/operations.md`:

```markdown
---
alwaysApply: false
---
# Mempalace Operations Rule

Diagnose palace issues with `mems doctor`. Rebuild with `mems make`.
Check `/health` at http://localhost:8787/health.
```

- [ ] **Step 4:** Commit: `feat(scripts): Cursor rules for discovery + operations + user-wing`.

### Task 8.3: `scripts/setup.sh`

- [ ] **Step 1:** Create `scripts/setup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IDE=""
SKIP_DISCOVERY=false
SETUP_HOOK=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ide) IDE="$2"; shift 2 ;;
        --skip-discovery) SKIP_DISCOVERY=true; shift ;;
        --setup-hook) SETUP_HOOK=true; shift ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
done

# 1. Pre-flight
command -v docker >/dev/null || { echo "docker not found"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

# 2. Editable install
pip install --user -e .

# Ensure user-site bin is on PATH
USER_BIN="$(python3 -m site --user-base)/bin"
if ! echo "$PATH" | grep -q "$USER_BIN"; then
    echo "appending $USER_BIN to shell rc"
    {
        echo ""
        echo "# mems"
        echo "export PATH=\"\$PATH:$USER_BIN\""
    } >> "$HOME/.zshrc"
fi

# 3. IDE selection
if [[ -z "$IDE" ]]; then
    read -rp "Install IDE integration? (cursor/codex/both/none): " IDE
fi

install_cursor() {
    local target="$HOME/.cursor/mcp.json"
    mkdir -p "$(dirname "$target")"
    if [[ ! -f "$target" ]]; then echo "{}" > "$target"; fi
    if grep -q "# mempalace" "$target"; then
        echo "cursor: mempalace already installed"
        return
    fi
    python3 - "$target" <<'PY'
import json, sys
from pathlib import Path
target = Path(sys.argv[1])
current = json.loads(target.read_text())
snippet = json.loads(Path(__file__).parent.joinpath("../integration/mempalace_mcp_cursor.json").resolve().read_text()) if False else None
from pathlib import Path as P
snip_path = P("integration/mempalace_mcp_cursor.json")
snippet = json.loads(snip_path.read_text())
current.setdefault("mcpServers", {})
current["mcpServers"].update(snippet)
target.write_text(json.dumps(current, indent=2) + "\n# mempalace\n")
PY
    echo "cursor: installed"
}

install_codex() {
    local target="$HOME/.codex/config.toml"
    mkdir -p "$(dirname "$target")"
    if grep -q "# mempalace" "$target" 2>/dev/null; then
        echo "codex: mempalace already installed"
        return
    fi
    {
        echo ""
        echo "# mempalace"
        cat integration/mempalace_codex_append.toml
    } >> "$target"
    echo "codex: installed"
}

case "$IDE" in
    cursor) install_cursor ;;
    codex) install_codex ;;
    both) install_cursor; install_codex ;;
    none|"") echo "skipping IDE install" ;;
    *) echo "unknown IDE: $IDE" >&2; exit 1 ;;
esac

# 4. Stop hook
if [[ "$SETUP_HOOK" == true ]] || [[ -z "${SETUP_HOOK_ANSWERED:-}" && "$IDE" != "none" ]]; then
    HOOK_DIR="$HOME/.config/claude/stop-hooks"
    mkdir -p "$HOOK_DIR"
    if ! grep -q "# mempalace" "$HOOK_DIR/mempalace-stop-hook.sh" 2>/dev/null; then
        cp integration/mempalace-stop-hook.sh "$HOOK_DIR/mempalace-stop-hook.sh"
        echo "# mempalace" >> "$HOOK_DIR/mempalace-stop-hook.sh"
        chmod +x "$HOOK_DIR/mempalace-stop-hook.sh"
        echo "stop hook: installed"
    fi
fi

# 5. Repo discovery
if [[ "$SKIP_DISCOVERY" != true ]]; then
    echo "scanning ~/Code for sibling repos..."
    python3 - <<'PY'
import json, os
from pathlib import Path
code = Path.home() / "Code"
out = {}
for child in code.iterdir():
    if (child / ".git").exists():
        slug = child.name
        out[slug] = {"path": str(child), "wing": slug.replace(".", "-")}
target = Path("config/repos.json")
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    current = json.loads(target.read_text())
    current.update(out)
    out = current
target.write_text(json.dumps(out, indent=2))
print(f"discovered {len(out)} repos")
PY
fi

# 6. Build + run
docker compose up --build -d --wait

# 7. Final check
mems doctor || echo "warning: mems doctor reported issues — see logs"

echo ""
echo "✓ mems installed. Try: mems list | mems search '<query>' | mems doctor"
```

- [ ] **Step 2:** Make executable: `chmod +x scripts/setup.sh`.

- [ ] **Step 3:** Smoke test: `python3 scripts/setup.sh --ide none --skip-discovery`. Should idempotently install + build + start + run doctor.

- [ ] **Step 4:** Commit: `feat(setup): one-shot installer with IDE selection + repo discovery`.

### Phase 8 Exit Criteria

- `python3 scripts/setup.sh --ide cursor` installs from a cold machine.
- Re-running is idempotent (marker-comment guards).
- Cursor sees `mempalace` MCP server after restart.

---

<a id="phase-9-docs"></a>
## Phase 9: README + Troubleshooting + Final Verification

**Goal:** User-facing README + troubleshooting runbook + final end-to-end verification.

**Files:**
- Modify: `README.md` (currently a stub)
- Create: `docs/TROUBLESHOOTING.md`

### Task 9.1: README.md

- [ ] **Step 1:** Write a README with these sections (kept short — point to CONTEXT.md for deep details):

1. One-paragraph pitch
2. Quickstart (`python3 scripts/setup.sh --ide cursor`)
3. Common commands (5–6 from CONTEXT.md §13)
4. Link to `CONTEXT.md` for architecture
5. Link to `docs/TROUBLESHOOTING.md`

- [ ] **Step 2:** Commit: `docs(readme): quickstart + common commands`.

### Task 9.2: TROUBLESHOOTING.md

- [ ] **Step 1:** Copy CONTEXT.md §12 table verbatim into `docs/TROUBLESHOOTING.md` with an added "Diagnostics first" section at the top:

```markdown
# mems Troubleshooting

## Diagnostics first

Run these before doing anything destructive:

1. `curl -sf http://localhost:8787/health` — is the server up?
2. `docker compose ps` — is the container running?
3. `docker compose logs memory --tail 50` — what's failing?
4. `mems doctor` — automated end-to-end check.

## Symptom → First action

[copy CONTEXT.md §12 table here]
```

- [ ] **Step 2:** Commit: `docs: troubleshooting runbook`.

### Task 9.3: End-to-end verification

- [ ] **Step 1:** Fresh-clone smoke test:

```bash
cd /tmp
git clone <mems origin> mems-smoke
cd mems-smoke
python3 scripts/setup.sh --ide none --skip-discovery
curl -sf http://localhost:8787/health | python -m json.tool
mems list
mems my note "smoke test from fresh clone" --type observation --topic tooling
mems my recent --days 1
docker compose logs memory --tail 20
```

- [ ] **Step 2:** Full test suite + lint:

```bash
pytest -q
ruff check src/ mems_cli/ tests/
ruff format --check src/ mems_cli/ tests/
```

- [ ] **Step 3:** Wing-user disaster recovery drill:

```bash
mems my note "DR test — before rebuild" --type discovery --topic tooling
docker compose down -v
docker compose up -d --wait
mems search "DR test"    # should still find it
```

Expected: note survives volume wipe via snapshot/restore.

- [ ] **Step 4:** Commit final state: `chore: full implementation complete — all phases verified`.

### Phase 9 Exit Criteria

- README + troubleshooting published.
- Full pytest + ruff green.
- DR drill passes.
- Fresh-clone `setup.sh` finishes without manual intervention.

---

## Execution Guidance

**Recommended approach:** Subagent-driven. Dispatch one subagent per **task** (not per phase — tasks are bite-sized per the writing-plans skill; phases are larger units). Between tasks, review diffs and run the test suite.

**Parallelization windows:**
- After Phase 0 ships: run Phases 1, 2, 3, 4, 6 in parallel (they share no files).
- After Phase 6 ships: Phase 7 sub-tasks (7.1–7.6) are mostly independent — parallelize by CLI module.
- Phases 5, 8, 9 are sequential and must be single-threaded.

**Checkpoints (user review gates):** After Phase 0, after Phase 4, after Phase 7, after Phase 9. At each checkpoint, the user should:
1. Review git log since last checkpoint.
2. Run `pytest -q && ruff check`.
3. Boot the container if Phase ≥5: `docker compose up -d --wait && curl -sf localhost:8787/health`.

**If a phase blocks:** STOP, re-plan in a follow-up doc (e.g. `docs/plans/2026-04-17-mems-phase-N-rework.md`), then resume.

---

## Self-Review (per writing-plans skill)

**Spec coverage check:** Every CONTEXT.md section §1–§13 is addressed —
- §1 (what this repo is) → addressed implicitly across all phases
- §2 (deps) → Phase 0
- §3 (install) → Phase 8
- §4 (file layout) → Phases 1–8 create every file listed
- §5 (Docker runtime) → Phase 5 (+ Phase 3 snapshot/restore integration)
- §6 (sync + rooms + wingpacks) → Phases 1 + 2
- §7 (wing_user + DR) → Phase 3
- §8 (mems CLI reference) → Phases 6 + 7
- §9 (MCP tools) → Phase 4
- §10 (conventions) → enforced via ruff config in Phase 0
- §11 (current wings) → data-only, covered by `config/repos.json` seed
- §12 (troubleshooting) → Phase 9
- §13 (quick reference) → README in Phase 9

**Placeholder scan:** One placeholder remains — Phase 1 Task 1.2 has an integration-test stub marked `pytest.skip("TODO")`. This is intentional and explicitly called out; it lands in Phase 2 once wingpack fixtures exist. Flagged, not hidden.

**Type consistency:** `PalaceClient.call()` signature is consistent across `common.py` and all CLI modules. `wing_meta` dict shape is consistent between `write_wingpack` author (Phase 2) and `auto_publish.publish_all_wings` consumer. `PublishResult` dataclass used consistently. `restore_if_empty` return dict has stable keys (`action`, `reason`, `drawers_restored`).

**Known approximations (call these out for executors):**
- Phase 4 tool wiring assumes specific `mempalace` public API shapes. Task 4.1 is the API audit — if upstream differs, the wrappers need light rework. Not a blocker; failure mode is obvious (import error or signature mismatch).
- Phase 7 Task 7.1 references `mempalace_remove_wing` tool — this does not exist in the current tool list. Either add to Phase 4 or replace with a direct sqlite/chroma deletion call in `repo_registry.py`. Flagged for the Phase 4 executor.
- Phase 5 healthcheck assumes `/health` endpoint exists → built in Phase 4 Task 4.11. If Phase 5 runs before Phase 4 completes, the healthcheck will report unhealthy — acceptable as long as Phase 4 is done before Phase 9 verification.
