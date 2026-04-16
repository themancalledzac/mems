# Memory Palace — Full Buildout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dockerized MCP server that indexes local code repos into a searchable knowledge store using mempalace, adds multi-repo sync orchestration, a User Wing for persistent user context, and serves everything over StreamableHTTP.

**Architecture:** Three layers on top of `mempalace` (v3.3.0): (1) SyncEngine orchestrates git-diff-based incremental indexing across 8 repos, (2) UserWing provides 6 MCP tools for capturing/recalling user thoughts organized by hall, (3) an MCP HTTP server (FastMCP + StreamableHTTP) exposes mempalace's 27 tools + our 8 custom tools on port 8787 inside Docker.

**Tech Stack:** Python 3.12, mempalace 3.3.0, mcp SDK (FastMCP + StreamableHTTP), ChromaDB (via mempalace), Docker, PyYAML, uvicorn

**Spec:** `docs/superpowers/specs/2026-04-15-memory-palace-design.md`

---

## File Structure

```
Memory/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── pyproject.toml
│
├── config/
│   ├── mempalace.yaml          # Wing/room taxonomy with file patterns
│   └── repos.json              # Repo registry: paths, wing name mappings
│
├── src/
│   ├── __init__.py
│   ├── sync_engine.py          # SyncLedger + SyncEngine classes
│   ├── user_wing.py            # UserWing class with 6 tool handlers
│   ├── mcp_http_server.py      # FastMCP server composing all tools
│   └── tools.py                # memory_sync + memory_sync_status handlers
│
├── integration/
│   ├── user-wing.mdc           # Cursor rule: capture user thoughts
│   ├── mempalace-discovery.mdc # Cursor rule: search palace at start
│   └── stop-hook.sh            # Claude Code stop hook backstop
│
├── tests/
│   ├── conftest.py             # Shared fixtures (tmp palace, mock repos)
│   ├── test_sync_engine.py
│   ├── test_user_wing.py
│   ├── test_mcp_server.py
│   └── test_tools.py
│
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-04-15-memory-palace-design.md
        └── plans/
            └── 2026-04-15-memory-palace-buildout.md  (this file)
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/themancalledzac/Code/Memory
git init
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
.env
*.db
*.sqlite3
chroma/
sync_ledger.json
.pytest_cache/
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "memory-palace"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mempalace>=3.3.0",
    "mcp>=1.0.0",
    "uvicorn>=0.30.0",
    "pyyaml>=6.0,<7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["src*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 4: Create `src/__init__.py`**

```python
"""Memory Palace — multi-repo MCP knowledge store."""
```

- [ ] **Step 5: Create `tests/conftest.py` with shared fixtures**

```python
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_palace(tmp_path):
    """Temporary palace data directory."""
    palace = tmp_path / "palace"
    palace.mkdir()
    return palace


@pytest.fixture
def tmp_config(tmp_path):
    """Temporary config directory with minimal config files."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    repos = {
        "test-wing": {
            "path": str(tmp_path / "repos" / "test-repo"),
            "wing": "test-wing",
        }
    }
    (config_dir / "repos.json").write_text(json.dumps(repos, indent=2))

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
    (config_dir / "mempalace.yaml").write_text(yaml.dump(taxonomy))

    return config_dir


@pytest.fixture
def mock_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    repo_dir = tmp_path / "repos" / "test-repo"
    repo_dir.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_dir,
        capture_output=True,
    )

    (repo_dir / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir,
        capture_output=True,
    )

    return repo_dir
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/__init__.py tests/conftest.py .gitignore
git commit -m "feat: project scaffolding with pyproject.toml and test fixtures"
```

---

## Task 2: Config Files

**Files:**
- Create: `config/mempalace.yaml`
- Create: `config/repos.json`

- [ ] **Step 1: Create `config/repos.json`**

This maps wing names to repo paths (as they'll appear inside Docker at `/repos/`).

```json
{
  "edens-zac": {
    "path": "/repos/edens.zac",
    "wing": "edens-zac"
  },
  "edens-zac-backend": {
    "path": "/repos/edens.zac.backend",
    "wing": "edens-zac-backend"
  },
  "edens-zac-backend-go": {
    "path": "/repos/edens.zac.backend.go",
    "wing": "edens-zac-backend-go"
  },
  "edens-zac-ml": {
    "path": "/repos/edens.zac.ml",
    "wing": "edens-zac-ml"
  },
  "lightroom-export": {
    "path": "/repos/lightroom-portfolio-export",
    "wing": "lightroom-export"
  },
  "job-search": {
    "path": "/repos/job-search",
    "wing": "job-search"
  },
  "running": {
    "path": "/repos/running",
    "wing": "running"
  },
  "memory": {
    "path": "/repos/Memory",
    "wing": "memory"
  }
}
```

- [ ] **Step 2: Create `config/mempalace.yaml`**

Full wing/room taxonomy with file-matching patterns (from the spec).

```yaml
wings:
  edens-zac:
    rooms:
      landing:
        patterns:
          - "**/page.tsx"
          - "**/Hero*"
          - "**/Nav*"
          - "**/Header*"
          - "**/Footer*"
          - "**/layout.tsx"
      collections:
        patterns:
          - "**/Collection*"
          - "**/collection*"
          - "**/Parallax*"
          - "**/ImageGrid*"
      admin:
        patterns:
          - "**/admin/**"
          - "**/CollectionManager*"
          - "**/ImageBrowser*"
          - "**/DragDrop*"
          - "**/MetadataEdit*"
      layout-engine:
        patterns:
          - "**/BoxTree*"
          - "**/boxtree*"
          - "**/layout*"
          - "**/breakpoint*"
      media:
        patterns:
          - "**/Image*"
          - "**/image*"
          - "**/cdn*"
          - "**/WebP*"
          - "**/responsive*"
      api-client:
        patterns:
          - "**/api/**"
          - "**/proxy*"
          - "**/client*"
          - "**/fetch*"
      styling:
        patterns:
          - "**/*.scss"
          - "**/*.css"
          - "**/theme*"
          - "**/style*"
      types:
        patterns:
          - "**/types/**"
          - "**/types.ts"
          - "**/interfaces*"
          - "**/enums*"

  edens-zac-backend:
    rooms:
      image-processing:
        patterns:
          - "**/ImageService*"
          - "**/Thumbnail*"
          - "**/WebP*"
          - "**/Exif*"
          - "**/GifService*"
          - "**/upload*"
      collections:
        patterns:
          - "**/Collection*"
          - "**/collection*"
      search:
        patterns:
          - "**/Search*"
          - "**/search*"
          - "**/filter*"
      client-galleries:
        patterns:
          - "**/ClientGallery*"
          - "**/clientgallery*"
          - "**/password*"
          - "**/access*"
      storage:
        patterns:
          - "**/S3*"
          - "**/s3*"
          - "**/CloudFront*"
          - "**/storage*"
      database:
        patterns:
          - "**/migration*"
          - "**/flyway*"
          - "**/V[0-9]*"
          - "**/Jdbc*"
          - "**/Repository*"
      config:
        patterns:
          - "**/config/**"
          - "**/application*.yml"
          - "**/application*.yaml"
          - "**/exception*"
          - "**/WebConfig*"

  edens-zac-backend-go:
    rooms:
      collections:
        patterns:
          - "**/collection*"
          - "**/Collection*"
      database:
        patterns:
          - "**/repository*"
          - "**/migration*"
          - "**/sql*"
      server:
        patterns:
          - "**/router*"
          - "**/middleware*"
          - "**/server*"
          - "**/config*"
          - "**/main.go"

  edens-zac-ml:
    rooms:
      classification:
        patterns:
          - "**/clip*"
          - "**/CLIP*"
          - "**/tag*"
          - "**/taxonomy*"
          - "**/zero_shot*"
      face-recognition:
        patterns:
          - "**/face*"
          - "**/insightface*"
          - "**/recognition*"
      pipeline:
        patterns:
          - "**/pipeline*"
          - "**/orchestrat*"
          - "**/analyze*"
      lightroom-plugin:
        patterns:
          - "**/*.lua"
          - "**/lightroom*"
          - "**/keyword*"
      api:
        patterns:
          - "**/routes*"
          - "**/schemas*"
          - "**/main.py"
          - "**/app.py"

  lightroom-export:
    rooms:
      export:
        patterns:
          - "**/*.lua"
          - "*"

  job-search:
    rooms:
      evaluation:
        patterns:
          - "**/eval*"
          - "**/score*"
          - "**/grade*"
      resume:
        patterns:
          - "**/resume*"
          - "**/cv*"
          - "**/template*"
          - "**/pdf*"
      scanning:
        patterns:
          - "**/scan*"
          - "**/greenhouse*"
          - "**/ashby*"
          - "**/lever*"
          - "**/portal*"
      tracking:
        patterns:
          - "**/track*"
          - "**/pipeline*"
          - "**/status*"
          - "**/merge*"
      interview-prep:
        patterns:
          - "**/interview*"
          - "**/story*"
          - "**/star*"
          - "**/negotiat*"
      dashboard:
        patterns:
          - "**/tui*"
          - "**/dashboard*"
          - "**/bubble*"
          - "**/view*"

  running:
    rooms:
      sync:
        patterns:
          - "**/strava*"
          - "**/fetch*"
          - "**/sync*"
          - "**/api*"
      visualization:
        patterns:
          - "**/heatmap*"
          - "**/dashboard*"
          - "**/plot*"
          - "**/github_actions*"

  memory:
    rooms:
      sync-engine:
        patterns:
          - "**/sync_engine*"
      mcp-server:
        patterns:
          - "**/mcp_http_server*"
          - "**/tools.py"
      user-wing:
        patterns:
          - "**/user_wing*"
      integration:
        patterns:
          - "**/integration/**"
          - "**/*.mdc"
          - "**/stop-hook*"
```

- [ ] **Step 3: Commit**

```bash
git add config/repos.json config/mempalace.yaml
git commit -m "feat: add wing taxonomy and repo registry config files"
```

---

## Task 3: Sync Engine — Ledger Management

**Files:**
- Create: `src/sync_engine.py`
- Create: `tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests for SyncLedger**

```python
# tests/test_sync_engine.py
import json
from pathlib import Path

from src.sync_engine import SyncLedger


class TestSyncLedger:
    def test_load_empty_ledger(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.entries == {}

    def test_load_existing_ledger(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger_path.write_text(json.dumps({
            "test-wing": {
                "repo_path": "/repos/test",
                "last_commit_sha": "abc123",
                "last_sync_ts": "2026-04-15T10:00:00Z",
                "files_indexed": 10,
                "status": "synced",
            }
        }))
        ledger = SyncLedger(ledger_path)
        assert ledger.entries["test-wing"]["status"] == "synced"

    def test_update_and_save(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger = SyncLedger(ledger_path)
        ledger.update("my-wing", {
            "repo_path": "/repos/mine",
            "last_commit_sha": "def456",
            "last_sync_ts": "2026-04-15T11:00:00Z",
            "files_indexed": 5,
            "status": "synced",
        })
        ledger.save()

        reloaded = SyncLedger(ledger_path)
        assert reloaded.entries["my-wing"]["last_commit_sha"] == "def456"

    def test_get_entry_missing(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.get("nonexistent") is None

    def test_mark_error(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        ledger.mark_error("bad-wing", "/repos/bad", "repo not found")
        assert ledger.entries["bad-wing"]["status"] == "error"
        assert ledger.entries["bad-wing"]["error"] == "repo not found"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/themancalledzac/Code/Memory
python -m pytest tests/test_sync_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.sync_engine'`

- [ ] **Step 3: Implement SyncLedger**

```python
# src/sync_engine.py
"""Multi-repo git-diff sync orchestrator."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml


class SyncLedger:
    """Manages sync_ledger.json — tracks per-repo sync state."""

    def __init__(self, ledger_path: str | Path):
        self.ledger_path = Path(ledger_path)
        self.entries: dict = {}
        if self.ledger_path.exists():
            self.entries = json.loads(self.ledger_path.read_text())

    def get(self, wing_name: str) -> dict | None:
        return self.entries.get(wing_name)

    def update(self, wing_name: str, entry: dict):
        self.entries[wing_name] = entry

    def mark_error(self, wing_name: str, repo_path: str, error_msg: str):
        self.entries[wing_name] = {
            "repo_path": repo_path,
            "last_commit_sha": None,
            "last_sync_ts": datetime.now(timezone.utc).isoformat(),
            "files_indexed": 0,
            "status": "error",
            "error": error_msg,
        }

    def save(self):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(self.entries, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sync_engine.py::TestSyncLedger -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: SyncLedger for tracking per-repo sync state"
```

---

## Task 4: Sync Engine — Git Operations

**Files:**
- Modify: `src/sync_engine.py`
- Modify: `tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests for git helpers**

Append to `tests/test_sync_engine.py`:

```python
import subprocess

from src.sync_engine import get_head_sha, get_changed_files


class TestGitOps:
    def test_get_head_sha(self, mock_repo):
        sha = get_head_sha(str(mock_repo))
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_get_head_sha_bad_path(self):
        sha = get_head_sha("/nonexistent/repo")
        assert sha is None

    def test_get_changed_files(self, mock_repo):
        # Make a second commit with changes
        (mock_repo / "new_file.py").write_text("x = 1\n")
        (mock_repo / "hello.py").write_text("print('updated')\n")
        subprocess.run(["git", "add", "."], cwd=mock_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "second"],
            cwd=mock_repo,
            capture_output=True,
        )

        # Get the first commit SHA
        result = subprocess.run(
            ["git", "log", "--reverse", "--format=%H"],
            cwd=mock_repo,
            capture_output=True,
            text=True,
        )
        first_sha = result.stdout.strip().split("\n")[0]

        changes = get_changed_files(str(mock_repo), first_sha)
        assert "new_file.py" in changes["added"]
        assert "hello.py" in changes["modified"]

    def test_get_changed_files_no_changes(self, mock_repo):
        sha = get_head_sha(str(mock_repo))
        changes = get_changed_files(str(mock_repo), sha)
        assert changes["added"] == []
        assert changes["modified"] == []
        assert changes["deleted"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_sync_engine.py::TestGitOps -v
```

Expected: `ImportError: cannot import name 'get_head_sha' from 'src.sync_engine'`

- [ ] **Step 3: Implement git helpers**

Append to `src/sync_engine.py`:

```python
def get_head_sha(repo_path: str) -> str | None:
    """Get HEAD commit SHA for a repo. Returns None if repo is invalid."""
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_changed_files(repo_path: str, since_sha: str) -> dict:
    """Get files changed since a commit SHA. Returns {added, modified, deleted} lists."""
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-status", since_sha, "HEAD"],
        capture_output=True,
        text=True,
    )
    changes = {"added": [], "modified": [], "deleted": []}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, filepath = parts[0], parts[1]
        if status.startswith("A"):
            changes["added"].append(filepath)
        elif status.startswith("M"):
            changes["modified"].append(filepath)
        elif status.startswith("D"):
            changes["deleted"].append(filepath)
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sync_engine.py::TestGitOps -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: git helper functions for sync engine"
```

---

## Task 5: Sync Engine — Full & Incremental Sync

**Files:**
- Modify: `src/sync_engine.py`
- Modify: `tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests for SyncEngine**

Append to `tests/test_sync_engine.py`:

```python
import os
from unittest.mock import patch, MagicMock

from src.sync_engine import SyncEngine


class TestSyncEngine:
    def test_init_loads_config(self, tmp_config, tmp_palace):
        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )
        assert "test-wing" in engine.repos

    def test_full_sync_indexes_repo(self, tmp_config, tmp_palace, mock_repo):
        # Point config at the mock repo
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with patch("src.sync_engine.mine") as mock_mine:
            engine.full_sync()

        mock_mine.assert_called_once()
        entry = engine.ledger.get("test-wing")
        assert entry is not None
        assert entry["status"] == "synced"
        assert entry["last_commit_sha"] is not None

    def test_full_sync_handles_bad_repo(self, tmp_config, tmp_palace):
        repos = {"bad-wing": {"path": "/nonexistent/repo", "wing": "bad-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with patch("src.sync_engine.mine", side_effect=Exception("repo not found")):
            engine.full_sync()

        entry = engine.ledger.get("bad-wing")
        assert entry["status"] == "error"
        assert "repo not found" in entry["error"]

    def test_incremental_sync_no_changes(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        # Simulate a previous full sync
        sha = get_head_sha(str(mock_repo))
        engine.ledger.update("test-wing", {
            "repo_path": str(mock_repo),
            "last_commit_sha": sha,
            "last_sync_ts": "2026-04-15T10:00:00Z",
            "files_indexed": 1,
            "status": "synced",
        })

        with patch("src.sync_engine.process_file") as mock_process:
            engine.incremental_sync()

        mock_process.assert_not_called()

    def test_incremental_sync_with_changes(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        old_sha = get_head_sha(str(mock_repo))
        engine.ledger.update("test-wing", {
            "repo_path": str(mock_repo),
            "last_commit_sha": old_sha,
            "last_sync_ts": "2026-04-15T10:00:00Z",
            "files_indexed": 1,
            "status": "synced",
        })

        # Add a new file and commit
        (mock_repo / "added.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=mock_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            cwd=mock_repo,
            capture_output=True,
        )

        with patch("src.sync_engine.process_file") as mock_process:
            engine.incremental_sync()

        assert mock_process.call_count >= 1
        entry = engine.ledger.get("test-wing")
        assert entry["status"] == "synced"
        assert entry["last_commit_sha"] != old_sha

    def test_full_sync_specific_wing(self, tmp_config, tmp_palace, mock_repo):
        repos = {
            "test-wing": {"path": str(mock_repo), "wing": "test-wing"},
            "other-wing": {"path": "/other/repo", "wing": "other-wing"},
        }
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with patch("src.sync_engine.mine") as mock_mine:
            engine.full_sync(wing_name="test-wing")

        # Only test-wing should be synced
        mock_mine.assert_called_once()
        assert engine.ledger.get("test-wing") is not None
        assert engine.ledger.get("other-wing") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_sync_engine.py::TestSyncEngine -v
```

Expected: `ImportError: cannot import name 'SyncEngine' from 'src.sync_engine'`

- [ ] **Step 3: Implement SyncEngine**

Add to `src/sync_engine.py` (after the existing code):

```python
from mempalace.miner import mine, process_file
from mempalace.palace import get_collection


class SyncEngine:
    """Orchestrates multi-repo sync using mempalace mining."""

    def __init__(self, config_path: str, data_path: str):
        self.config_path = Path(config_path)
        self.data_path = Path(data_path)
        self.ledger = SyncLedger(self.data_path / "sync_ledger.json")

        with open(self.config_path / "repos.json") as f:
            self.repos: dict = json.load(f)

        with open(self.config_path / "mempalace.yaml") as f:
            self.taxonomy: dict = yaml.safe_load(f)

    def full_sync(self, wing_name: str | None = None):
        """Run full mine on all repos (or a specific wing)."""
        targets = (
            {wing_name: self.repos[wing_name]}
            if wing_name
            else self.repos
        )

        for name, repo_config in targets.items():
            repo_path = repo_config["path"]
            try:
                mine(
                    project_dir=repo_path,
                    palace_path=str(self.data_path),
                    wing_override=name,
                )
                head_sha = get_head_sha(repo_path)
                self.ledger.update(name, {
                    "repo_path": repo_path,
                    "last_commit_sha": head_sha,
                    "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                    "files_indexed": self._count_files(repo_path),
                    "status": "synced",
                })
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self.ledger.save()

    def incremental_sync(self, wing_name: str | None = None):
        """Sync only files changed since last sync."""
        targets = (
            {wing_name: self.repos[wing_name]}
            if wing_name
            else self.repos
        )

        for name, repo_config in targets.items():
            entry = self.ledger.get(name)
            if not entry or entry.get("status") == "error" or not entry.get("last_commit_sha"):
                self.full_sync(wing_name=name)
                continue

            repo_path = repo_config["path"]
            try:
                head_sha = get_head_sha(repo_path)
                if head_sha == entry["last_commit_sha"]:
                    continue

                changes = get_changed_files(repo_path, entry["last_commit_sha"])
                collection = get_collection(str(self.data_path))
                wing_rooms = self.taxonomy.get("wings", {}).get(name, {}).get("rooms", {})

                for filepath in changes["deleted"]:
                    full_path = str(Path(repo_path) / filepath)
                    self._delete_drawers_for_file(collection, full_path)

                for filepath in changes["added"] + changes["modified"]:
                    full_path = str(Path(repo_path) / filepath)
                    if Path(full_path).exists():
                        process_file(
                            filepath=full_path,
                            project_path=repo_path,
                            collection=collection,
                            wing=name,
                            rooms=wing_rooms,
                            agent="memory-sync",
                        )

                self.ledger.update(name, {
                    "repo_path": repo_path,
                    "last_commit_sha": head_sha,
                    "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                    "files_indexed": self._count_files(repo_path),
                    "status": "synced",
                })
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self.ledger.save()

    def _count_files(self, repo_path: str) -> int:
        """Count indexable files in a repo."""
        try:
            from mempalace.miner import scan_project
            return len(scan_project(repo_path))
        except Exception:
            return 0

    def _delete_drawers_for_file(self, collection, source_file: str):
        """Remove all drawers originating from a deleted file."""
        try:
            results = collection.get(where={"source_file": source_file})
            if results and results.get("ids"):
                collection.delete(ids=results["ids"])
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sync_engine.py::TestSyncEngine -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: SyncEngine with full and incremental sync"
```

---

## Task 6: Sync Engine — MCP Tool Handlers

**Files:**
- Create: `src/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests for sync tool handlers**

```python
# tests/test_tools.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tools import handle_sync, handle_sync_status


class TestHandleSync:
    def test_sync_all(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with patch("src.sync_engine.mine"):
            result = handle_sync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
            )

        assert result["status"] == "ok"
        assert "test-wing" in result["synced"]

    def test_sync_specific_wing(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with patch("src.sync_engine.mine"):
            result = handle_sync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
                wing="test-wing",
            )

        assert result["status"] == "ok"

    def test_sync_unknown_wing(self, tmp_config, tmp_palace):
        result = handle_sync(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
            wing="nonexistent",
        )
        assert result["status"] == "error"


class TestHandleSyncStatus:
    def test_status_empty_ledger(self, tmp_config, tmp_palace):
        result = handle_sync_status(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )
        assert result["wings"] == {}

    def test_status_after_sync(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with patch("src.sync_engine.mine"):
            handle_sync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
            )

        result = handle_sync_status(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )
        assert "test-wing" in result["wings"]
        assert result["wings"]["test-wing"]["status"] == "synced"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.tools'`

- [ ] **Step 3: Implement sync tool handlers**

```python
# src/tools.py
"""MCP tool handlers for sync operations."""

from src.sync_engine import SyncEngine, SyncLedger


def handle_sync(
    config_path: str,
    data_path: str,
    wing: str | None = None,
    full: bool = False,
) -> dict:
    """Handle memory_sync tool call."""
    engine = SyncEngine(config_path=config_path, data_path=data_path)

    if wing and wing not in engine.repos:
        return {"status": "error", "message": f"Unknown wing: {wing}"}

    if full or not SyncLedger(f"{data_path}/sync_ledger.json").entries:
        engine.full_sync(wing_name=wing)
    else:
        engine.incremental_sync(wing_name=wing)

    synced = []
    errors = []
    for name, entry in engine.ledger.entries.items():
        if entry["status"] == "synced":
            synced.append(name)
        elif entry["status"] == "error":
            errors.append({"wing": name, "error": entry.get("error", "unknown")})

    return {"status": "ok", "synced": synced, "errors": errors}


def handle_sync_status(config_path: str, data_path: str) -> dict:
    """Handle memory_sync_status tool call."""
    ledger = SyncLedger(f"{data_path}/sync_ledger.json")
    return {"wings": ledger.entries}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_tools.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/tools.py tests/test_tools.py
git commit -m "feat: memory_sync and memory_sync_status tool handlers"
```

---

## Task 7: User Wing — Write & Search

**Files:**
- Create: `src/user_wing.py`
- Create: `tests/test_user_wing.py`

- [ ] **Step 1: Write failing tests for UserWing write and search**

```python
# tests/test_user_wing.py
import pytest
from unittest.mock import patch, MagicMock

from src.user_wing import UserWing, VALID_HALLS


class TestUserWingWrite:
    def test_valid_halls(self):
        assert "questions" in VALID_HALLS
        assert "discoveries" in VALID_HALLS
        assert "frustrations" in VALID_HALLS
        assert "goals" in VALID_HALLS
        assert "decisions" in VALID_HALLS
        assert "observations" in VALID_HALLS

    def test_write_thought(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="discoveries",
            content="CLIP ViT-L/14 works better than B/32 for photography tags",
            topic="ml-tagging",
        )
        assert result["status"] == "created"
        assert result["hall"] == "discoveries"
        assert result["id"].startswith("user-")

    def test_write_invalid_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="invalid-hall",
            content="test",
            topic="test",
        )
        assert result["status"] == "error"
        assert "invalid-hall" in result["message"].lower() or "Invalid hall" in result["message"]

    def test_write_with_source_wing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="observations",
            content="BoxTree algorithm gets slow above 200 images",
            topic="performance",
            source_wing="edens-zac",
        )
        assert result["status"] == "created"

    def test_write_dedup_updates_existing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r1 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by Q2",
            topic="portfolio",
        )
        r2 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by end of Q2",
            topic="portfolio",
        )
        assert r2["status"] == "updated"


class TestUserWingSearch:
    def test_search_returns_results(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(
            hall="discoveries",
            content="CLIP ViT-L/14 outperforms B/32 for photography classification",
            topic="ml",
        )
        results = wing.search(query="CLIP model performance")
        assert len(results["results"]) >= 1
        assert results["results"][0]["hall"] == "discoveries"

    def test_search_filter_by_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio by Q2", topic="portfolio")
        wing.write(hall="frustrations", content="JDBC errors are useless", topic="backend")

        results = wing.search(query="portfolio", hall="goals")
        for r in results["results"]:
            assert r["hall"] == "goals"

    def test_search_filter_by_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast", topic="go-backend")
        wing.write(hall="discoveries", content="React is flexible", topic="frontend")

        results = wing.search(query="programming", topic="go-backend")
        for r in results["results"]:
            assert r["topic"] == "go-backend"

    def test_search_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        results = wing.search(query="nonexistent query xyz123")
        assert results["results"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_user_wing.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.user_wing'`

- [ ] **Step 3: Implement UserWing with write and search**

```python
# src/user_wing.py
"""User Wing — persistent user context organized by thought type."""

import hashlib
import uuid
from datetime import datetime, timezone

from mempalace.palace import get_collection


VALID_HALLS = frozenset({
    "questions",
    "discoveries",
    "frustrations",
    "goals",
    "decisions",
    "observations",
})

DEDUP_THRESHOLD = 0.15


class UserWing:
    """Manages the User Wing — thoughts organized by hall, not by code area."""

    def __init__(self, palace_path: str):
        self.palace_path = palace_path
        self.collection = get_collection(palace_path, collection_name="mempalace_drawers", create=True)

    def write(
        self,
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
        session_id: str | None = None,
        confidence: float = 0.9,
    ) -> dict:
        """File a thought into a hall. Deduplicates against recent entries."""
        if hall not in VALID_HALLS:
            return {
                "status": "error",
                "message": f"Invalid hall: {hall}. Must be one of: {', '.join(sorted(VALID_HALLS))}",
            }

        # Check for near-duplicate in same hall
        existing = self._find_duplicate(hall, content)
        if existing:
            self.collection.upsert(
                ids=[existing["id"]],
                documents=[content],
                metadatas=[{
                    **existing["metadata"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }],
            )
            return {"status": "updated", "id": existing["id"], "hall": hall}

        drawer_id = f"user-{uuid.uuid4().hex[:24]}"
        metadata = {
            "wing": "user",
            "hall": hall,
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
            "added_by": "user-wing",
        }
        if source_wing:
            metadata["source_wing"] = source_wing
        if session_id:
            metadata["session_id"] = session_id

        self.collection.upsert(
            ids=[drawer_id],
            documents=[content],
            metadatas=[metadata],
        )
        return {"status": "created", "id": drawer_id, "hall": hall}

    def search(
        self,
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
    ) -> dict:
        """Semantic search across user wing."""
        where = {"wing": "user"}
        where_conditions = [{"wing": "user"}]
        if hall:
            where_conditions.append({"hall": hall})
        if topic:
            where_conditions.append({"topic": topic})

        if len(where_conditions) > 1:
            where = {"$and": where_conditions}
        else:
            where = where_conditions[0]

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception:
            return {"query": query, "results": []}

        if not results or not results.get("ids") or not results["ids"][0]:
            return {"query": query, "results": []}

        formatted = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            dist = results["distances"][0][i] if results.get("distances") else None
            formatted.append({
                "id": doc_id,
                "content": results["documents"][0][i],
                "hall": meta.get("hall", ""),
                "topic": meta.get("topic", ""),
                "source_wing": meta.get("source_wing"),
                "timestamp": meta.get("timestamp", ""),
                "distance": dist,
            })

        return {"query": query, "results": formatted}

    def _find_duplicate(self, hall: str, content: str) -> dict | None:
        """Find a near-duplicate in the same hall. Returns {id, metadata} or None."""
        try:
            results = self.collection.query(
                query_texts=[content],
                n_results=1,
                where={"$and": [{"wing": "user"}, {"hall": hall}]},
            )
        except Exception:
            return None

        if (
            not results
            or not results.get("ids")
            or not results["ids"][0]
            or not results.get("distances")
            or not results["distances"][0]
        ):
            return None

        distance = results["distances"][0][0]
        if distance < DEDUP_THRESHOLD:
            return {
                "id": results["ids"][0][0],
                "metadata": results["metadatas"][0][0] if results.get("metadatas") else {},
            }
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_user_wing.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/user_wing.py tests/test_user_wing.py
git commit -m "feat: UserWing with write (dedup) and semantic search"
```

---

## Task 8: User Wing — Summary & Status

**Files:**
- Modify: `src/user_wing.py`
- Modify: `tests/test_user_wing.py`

- [ ] **Step 1: Write failing tests for summary and status**

Append to `tests/test_user_wing.py`:

```python
class TestUserWingSummary:
    def test_summary_with_data(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio by Q2", topic="portfolio")
        wing.write(hall="decisions", content="Chose Go over Rust for backend", topic="backend")
        wing.write(hall="frustrations", content="JDBC errors are useless", topic="backend")
        wing.write(hall="discoveries", content="CLIP ViT-L/14 is better", topic="ml")
        wing.write(hall="questions", content="How does CloudFront invalidation work?", topic="infra")
        wing.write(hall="observations", content="BoxTree slows above 200 images", topic="perf")

        summary = wing.summary()
        assert "## User Context" in summary["text"]
        assert "portfolio" in summary["text"].lower() or "Q2" in summary["text"]

    def test_summary_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        summary = wing.summary()
        assert summary["text"] == ""
        assert summary["token_estimate"] == 0


class TestUserWingStatus:
    def test_status_with_data(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio", topic="portfolio")
        wing.write(hall="goals", content="Learn Go", topic="learning")
        wing.write(hall="frustrations", content="JDBC is bad", topic="backend")

        status = wing.status()
        assert status["total_thoughts"] == 3
        assert status["halls"]["goals"] == 2
        assert status["halls"]["frustrations"] == 1
        assert "portfolio" in status["recent_topics"] or "learning" in status["recent_topics"]

    def test_status_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        status = wing.status()
        assert status["total_thoughts"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_user_wing.py::TestUserWingSummary -v
python -m pytest tests/test_user_wing.py::TestUserWingStatus -v
```

Expected: `AttributeError: 'UserWing' object has no attribute 'summary'`

- [ ] **Step 3: Implement summary and status**

Add to the `UserWing` class in `src/user_wing.py`:

```python
    def summary(self) -> dict:
        """Synthesize a compact user context summary (~300-500 tokens)."""
        sections = {}
        hall_labels = {
            "goals": "Goals",
            "decisions": "Recent decisions",
            "frustrations": "Active frustrations",
            "discoveries": "Recent discoveries",
            "questions": "Open questions",
            "observations": "Observations",
        }

        has_content = False
        for hall, label in hall_labels.items():
            try:
                results = self.collection.get(
                    where={"$and": [{"wing": "user"}, {"hall": hall}]},
                    limit=5,
                )
            except Exception:
                continue

            if results and results.get("documents"):
                items = results["documents"][:3]
                sections[label] = "; ".join(items)
                has_content = True

        if not has_content:
            return {"text": "", "token_estimate": 0}

        lines = ["## User Context"]
        for label, content in sections.items():
            lines.append(f"**{label}:** {content}")

        text = "\n".join(lines)
        token_estimate = len(text) // 4
        return {"text": text, "token_estimate": token_estimate}

    def status(self) -> dict:
        """Hall counts, recent topics, protocol guidance."""
        halls = {}
        topics = set()
        total = 0

        for hall in VALID_HALLS:
            try:
                results = self.collection.get(
                    where={"$and": [{"wing": "user"}, {"hall": hall}]},
                )
            except Exception:
                continue

            count = len(results["ids"]) if results and results.get("ids") else 0
            if count > 0:
                halls[hall] = count
                total += count
                if results.get("metadatas"):
                    for meta in results["metadatas"][:10]:
                        if meta.get("topic"):
                            topics.add(meta["topic"])

        return {
            "total_thoughts": total,
            "halls": halls,
            "recent_topics": sorted(topics),
            "guidance": (
                "Capture user context at session end via mempalace_user_write. "
                "Call mempalace_user_summary at session start for context."
            ),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_user_wing.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/user_wing.py tests/test_user_wing.py
git commit -m "feat: UserWing summary synthesizer and status reporting"
```

---

## Task 9: User Wing — Merge Topics & Prune

**Files:**
- Modify: `src/user_wing.py`
- Modify: `tests/test_user_wing.py`

- [ ] **Step 1: Write failing tests for merge and prune**

Append to `tests/test_user_wing.py`:

```python
from datetime import datetime, timezone, timedelta


class TestUserWingMergeTopic:
    def test_merge_topics(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast for APIs", topic="golang")
        wing.write(hall="discoveries", content="Go concurrency is great", topic="go-lang")

        result = wing.merge_topics(source_topic="go-lang", target_topic="golang")
        assert result["merged"] >= 1
        assert result["remaining"] >= 1

    def test_merge_topics_scoped_to_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast", topic="golang")
        wing.write(hall="goals", content="Learn Go", topic="golang")
        wing.write(hall="discoveries", content="Go has goroutines", topic="go-lang")

        result = wing.merge_topics(
            source_topic="go-lang",
            target_topic="golang",
            hall="discoveries",
        )
        assert result["merged"] >= 1

    def test_merge_nonexistent_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.merge_topics(source_topic="nope", target_topic="also-nope")
        assert result["merged"] == 0


class TestUserWingPrune:
    def test_prune_dry_run(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="observations", content="Test observation", topic="test")

        result = wing.prune(hall="observations", dry_run=True)
        assert "candidates" in result
        assert result["pruned"] == 0

    def test_prune_old_entries(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        # Write a thought with an old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        drawer_id = f"user-{uuid.uuid4().hex[:24]}"
        wing.collection.upsert(
            ids=[drawer_id],
            documents=["very old thought"],
            metadatas=[{
                "wing": "user",
                "hall": "observations",
                "topic": "old-stuff",
                "timestamp": old_time,
                "confidence": 0.5,
                "added_by": "user-wing",
            }],
        )

        result = wing.prune(hall="observations", older_than_days=90, dry_run=False)
        assert result["pruned"] >= 1

    def test_prune_by_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="frustrations", content="X is annoying", topic="temp-issue")
        wing.write(hall="frustrations", content="Y is important", topic="real-issue")

        result = wing.prune(hall="frustrations", topic="temp-issue", older_than_days=0, dry_run=False)
        assert result["pruned"] >= 1
```

Add at top of test file if not present:

```python
import uuid
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_user_wing.py::TestUserWingMergeTopic -v
python -m pytest tests/test_user_wing.py::TestUserWingPrune -v
```

Expected: `AttributeError: 'UserWing' object has no attribute 'merge_topics'`

- [ ] **Step 3: Implement merge_topics and prune**

Add to the `UserWing` class in `src/user_wing.py`:

```python
    def merge_topics(
        self,
        source_topic: str,
        target_topic: str,
        hall: str | None = None,
    ) -> dict:
        """Merge drifted topics — rewrite metadata, deduplicate."""
        where_conditions = [{"wing": "user"}, {"topic": source_topic}]
        if hall:
            where_conditions.append({"hall": hall})
        where = {"$and": where_conditions} if len(where_conditions) > 1 else where_conditions[0]

        try:
            results = self.collection.get(where=where)
        except Exception:
            return {"merged": 0, "deduped": 0, "remaining": 0}

        if not results or not results.get("ids"):
            return {"merged": 0, "deduped": 0, "remaining": 0}

        merged = 0
        deduped = 0
        for i, drawer_id in enumerate(results["ids"]):
            meta = results["metadatas"][i].copy()
            content = results["documents"][i]

            # Check if a near-duplicate exists in the target topic
            dup = self._find_duplicate_in_topic(target_topic, content, meta.get("hall"))
            if dup:
                self.collection.delete(ids=[drawer_id])
                deduped += 1
            else:
                meta["topic"] = target_topic
                self.collection.upsert(
                    ids=[drawer_id],
                    documents=[content],
                    metadatas=[meta],
                )
                merged += 1

        remaining = merged
        return {"merged": merged, "deduped": deduped, "remaining": remaining}

    def prune(
        self,
        hall: str | None = None,
        topic: str | None = None,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> dict:
        """Remove stale/low-value thoughts by age, similarity, or cluster."""
        where_conditions = [{"wing": "user"}]
        if hall:
            where_conditions.append({"hall": hall})
        if topic:
            where_conditions.append({"topic": topic})
        where = {"$and": where_conditions} if len(where_conditions) > 1 else where_conditions[0]

        try:
            results = self.collection.get(where=where)
        except Exception:
            return {"candidates": 0, "pruned": 0}

        if not results or not results.get("ids"):
            return {"candidates": 0, "pruned": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        candidates = []
        for i, drawer_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            ts_str = meta.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                candidates.append(drawer_id)

        if dry_run:
            return {"candidates": len(candidates), "pruned": 0}

        if candidates:
            self.collection.delete(ids=candidates)

        return {"candidates": len(candidates), "pruned": len(candidates)}

    def _find_duplicate_in_topic(self, topic: str, content: str, hall: str | None = None) -> dict | None:
        """Check if near-duplicate exists in the target topic."""
        where_conditions = [{"wing": "user"}, {"topic": topic}]
        if hall:
            where_conditions.append({"hall": hall})

        try:
            results = self.collection.query(
                query_texts=[content],
                n_results=1,
                where={"$and": where_conditions},
            )
        except Exception:
            return None

        if (
            not results
            or not results.get("ids")
            or not results["ids"][0]
            or not results.get("distances")
            or not results["distances"][0]
        ):
            return None

        if results["distances"][0][0] < DEDUP_THRESHOLD:
            return {"id": results["ids"][0][0]}
        return None
```

Also add import at top of `src/user_wing.py`:

```python
from datetime import datetime, timezone, timedelta
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_user_wing.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/user_wing.py tests/test_user_wing.py
git commit -m "feat: UserWing merge_topics and prune operations"
```

---

## Task 10: MCP HTTP Server

**Files:**
- Create: `src/mcp_http_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for the MCP server**

```python
# tests/test_mcp_server.py
import os
from unittest.mock import patch

from src.mcp_http_server import create_server


class TestCreateServer:
    def test_server_has_tools(self):
        """The server should register mempalace tools + our custom tools."""
        with patch.dict(os.environ, {
            "PALACE_PATH": "/tmp/test-palace",
            "CONFIG_PATH": "/tmp/test-config",
        }):
            server = create_server(
                palace_path="/tmp/test-palace",
                config_path="/tmp/test-config",
            )
        # FastMCP stores tools internally
        # Our 8 custom tools should be registered
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        assert "memory_sync" in tool_names
        assert "memory_sync_status" in tool_names
        assert "mempalace_user_write" in tool_names
        assert "mempalace_user_search" in tool_names
        assert "mempalace_user_summary" in tool_names
        assert "mempalace_user_status" in tool_names
        assert "mempalace_user_merge_topics" in tool_names
        assert "mempalace_user_prune" in tool_names


class TestToolSchemas:
    def test_user_write_params(self):
        """mempalace_user_write should require hall and content."""
        with patch.dict(os.environ, {
            "PALACE_PATH": "/tmp/test-palace",
            "CONFIG_PATH": "/tmp/test-config",
        }):
            server = create_server(
                palace_path="/tmp/test-palace",
                config_path="/tmp/test-config",
            )
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        write_tool = tools["mempalace_user_write"]
        schema = write_tool.parameters
        assert "hall" in schema.get("properties", schema.get("required", {}))
        assert "content" in schema.get("properties", schema.get("required", {}))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mcp_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.mcp_http_server'`

- [ ] **Step 3: Implement the MCP HTTP server**

```python
# src/mcp_http_server.py
"""StreamableHTTP MCP server composing mempalace + custom tools."""

import os

from mcp.server.fastmcp import FastMCP

from src.user_wing import UserWing
from src.tools import handle_sync, handle_sync_status


def create_server(
    palace_path: str | None = None,
    config_path: str | None = None,
) -> FastMCP:
    """Create and configure the FastMCP server with all tools."""
    palace_path = palace_path or os.environ.get("PALACE_PATH", "/data")
    config_path = config_path or os.environ.get("CONFIG_PATH", "/config")

    mcp = FastMCP(
        "Memory Palace",
        host="0.0.0.0",
        port=int(os.environ.get("MEMORY_PORT", "8787")),
    )

    user_wing = UserWing(palace_path=palace_path)

    # --- User Wing tools (6) ---

    @mcp.tool()
    def mempalace_user_write(
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
    ) -> dict:
        """File a user thought into a hall. Deduplicates near-identical entries.

        Halls: questions, discoveries, frustrations, goals, decisions, observations.
        """
        return user_wing.write(
            hall=hall,
            content=content,
            topic=topic,
            source_wing=source_wing,
        )

    @mcp.tool()
    def mempalace_user_search(
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
    ) -> dict:
        """Semantic search across the User Wing."""
        return user_wing.search(
            query=query,
            hall=hall,
            topic=topic,
            n_results=n_results,
        )

    @mcp.tool()
    def mempalace_user_summary() -> dict:
        """Synthesize compact user context for agent wake-up (~300-500 tokens)."""
        return user_wing.summary()

    @mcp.tool()
    def mempalace_user_status() -> dict:
        """Hall counts, recent topics, and protocol guidance for agents."""
        return user_wing.status()

    @mcp.tool()
    def mempalace_user_merge_topics(
        source_topic: str,
        target_topic: str,
        hall: str | None = None,
    ) -> dict:
        """Merge drifted topics — rewrite metadata, deduplicate."""
        return user_wing.merge_topics(
            source_topic=source_topic,
            target_topic=target_topic,
            hall=hall,
        )

    @mcp.tool()
    def mempalace_user_prune(
        hall: str | None = None,
        topic: str | None = None,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> dict:
        """Remove stale/low-value thoughts by age, similarity, or cluster."""
        return user_wing.prune(
            hall=hall,
            topic=topic,
            older_than_days=older_than_days,
            dry_run=dry_run,
        )

    # --- Sync tools (2) ---

    @mcp.tool()
    def memory_sync(
        wing: str | None = None,
        full: bool = False,
    ) -> dict:
        """Sync repos into the palace. Incremental by default, full if requested."""
        return handle_sync(
            config_path=config_path,
            data_path=palace_path,
            wing=wing,
            full=full,
        )

    @mcp.tool()
    def memory_sync_status() -> dict:
        """Show sync status for all registered repos."""
        return handle_sync_status(
            config_path=config_path,
            data_path=palace_path,
        )

    # --- Health resource ---

    @mcp.resource("health://status")
    def health() -> dict:
        """Health check with tool count and last sync timestamp."""
        from src.sync_engine import SyncLedger
        ledger = SyncLedger(f"{palace_path}/sync_ledger.json")
        last_sync = None
        for entry in ledger.entries.values():
            ts = entry.get("last_sync_ts")
            if ts and (last_sync is None or ts > last_sync):
                last_sync = ts

        tool_count = len(mcp._tool_manager.list_tools())
        return {
            "status": "ok",
            "tools": tool_count,
            "last_sync": last_sync,
        }

    return mcp


def main():
    """Entry point: create server and run with StreamableHTTP transport."""
    server = create_server()
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_mcp_server.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mcp_http_server.py tests/test_mcp_server.py
git commit -m "feat: FastMCP HTTP server with 8 custom tools"
```

---

## Task 11: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `entrypoint.sh`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY config/ config/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8787

ENTRYPOINT ["./entrypoint.sh"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

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

- [ ] **Step 3: Create `entrypoint.sh`**

```bash
#!/bin/bash
set -e

echo "Memory Palace starting..."

if [ ! -f /data/sync_ledger.json ]; then
    echo "First boot — running full sync across all repos..."
    python -c "
from src.tools import handle_sync
import os
result = handle_sync(
    config_path=os.environ.get('CONFIG_PATH', '/config'),
    data_path=os.environ.get('PALACE_PATH', '/data'),
    full=True,
)
print(f'Sync complete: {result}')
"
else
    echo "Existing ledger found — validating..."
    python -c "
from src.sync_engine import SyncLedger
import os
ledger = SyncLedger(os.path.join(os.environ.get('PALACE_PATH', '/data'), 'sync_ledger.json'))
wings = list(ledger.entries.keys())
print(f'Ledger OK — {len(wings)} wings: {wings}')
"
fi

echo "Starting MCP server on port ${MEMORY_PORT:-8787}..."
exec python -m src.mcp_http_server
```

- [ ] **Step 4: Verify Docker build works**

```bash
cd /Users/themancalledzac/Code/Memory
docker compose build
```

Expected: Builds successfully

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml entrypoint.sh
git commit -m "feat: Docker setup with compose, entrypoint, and volume mounts"
```

---

## Task 12: IDE Integration Files

**Files:**
- Create: `integration/user-wing.mdc`
- Create: `integration/mempalace-discovery.mdc`
- Create: `integration/stop-hook.sh`

- [ ] **Step 1: Create `integration/user-wing.mdc`**

```markdown
---
description: Capture user thoughts into Memory Palace at session end
globs:
alwaysApply: true
---

# User Wing — Memory Palace

At the end of every session, capture any distinct user thoughts using the `mempalace_user_write` tool.

## Halls

| Hall | When to use |
|------|------------|
| `questions` | User is wondering about something |
| `discoveries` | User learned something new |
| `frustrations` | User hit a blocker or pain point |
| `goals` | User stated a short or long-term objective |
| `decisions` | User made a choice and explained reasoning |
| `observations` | User noted a pattern, insight, or factoid |

## Protocol

1. Before ending the session, review the conversation for user thoughts
2. For each distinct thought, call `mempalace_user_write` with the appropriate `hall`, a descriptive `content`, and a short `topic` slug
3. If the thought relates to a specific codebase, set `source_wing` (e.g., `edens-zac`, `edens-zac-backend`)
4. Deduplication is automatic — don't worry about repeats
```

- [ ] **Step 2: Create `integration/mempalace-discovery.mdc`**

```markdown
---
description: Search Memory Palace for context at session start
globs:
alwaysApply: true
---

# Memory Palace Discovery

At the start of every session:

1. Call `mempalace_user_summary` to get user context (goals, frustrations, recent decisions)
2. When investigating code, use `mempalace_search` to find relevant indexed knowledge across repos
3. Use `mempalace_user_search` to find prior user thoughts on the current topic

## Cross-repo connections

Use `mempalace_find_tunnels` to discover connections between wings when working across repos.
```

- [ ] **Step 3: Create `integration/stop-hook.sh`**

```bash
#!/bin/bash
# Claude Code stop hook — nudge user context capture
# Install: add to ~/.claude/settings.json hooks.Stop

echo "💭 Memory Palace: Did you capture any user thoughts this session?"
echo "   Use mempalace_user_write to file thoughts into halls:"
echo "   questions | discoveries | frustrations | goals | decisions | observations"
```

- [ ] **Step 4: Commit**

```bash
git add integration/
git commit -m "feat: IDE integration rules and stop hook for Memory Palace"
```

---

## Task 13: Wire Up __main__ Entry Point & Final Integration Test

**Files:**
- Create: `src/__main__.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Create `src/__main__.py`**

```python
"""Allow running the server via `python -m src`."""

from src.mcp_http_server import main

main()
```

- [ ] **Step 2: Write an integration smoke test**

Append to `tests/test_mcp_server.py`:

```python
class TestHealthResource:
    def test_health_returns_status(self):
        with patch.dict(os.environ, {
            "PALACE_PATH": "/tmp/test-palace",
            "CONFIG_PATH": "/tmp/test-config",
        }):
            server = create_server(
                palace_path="/tmp/test-palace",
                config_path="/tmp/test-config",
            )
        # Verify the health resource is registered
        resources = server._resource_manager.list_resources()
        resource_uris = [str(r.uri) for r in resources]
        assert any("health" in uri for uri in resource_uris)
```

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/themancalledzac/Code/Memory
python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/__main__.py tests/test_mcp_server.py
git commit -m "feat: __main__ entry point and integration smoke test"
```

---

## Task 14: Docker Smoke Test & MCP Client Config

- [ ] **Step 1: Build and start the container**

```bash
cd /Users/themancalledzac/Code/Memory
docker compose up -d
```

- [ ] **Step 2: Verify health endpoint**

```bash
curl -s http://localhost:8787/health 2>/dev/null || echo "Health endpoint may not be exposed as HTTP GET — check MCP protocol"
```

If health is only via MCP resource, verify the container is running:

```bash
docker compose logs memory | tail -20
```

Expected: "Starting MCP server on port 8787..."

- [ ] **Step 3: Verify MCP server responds to tool list**

```bash
curl -s -X POST http://localhost:8787/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 -m json.tool | head -30
```

Expected: JSON response listing all tools (mempalace's 27 + our 8 = ~35 tools)

- [ ] **Step 4: Add MCP client config for Claude Code**

Print the config the user needs to add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "mempalace": {
      "url": "http://localhost:8787/mcp"
    }
  }
}
```

- [ ] **Step 5: Stop the container**

```bash
docker compose down
```

- [ ] **Step 6: Commit any final tweaks**

```bash
git add -A
git commit -m "chore: finalize docker integration and MCP client config"
```

---

## Spec Coverage Checklist

| Spec Section | Plan Task |
|---|---|
| Repository Structure | Task 1, 2 |
| Wing Taxonomy | Task 2 (mempalace.yaml) |
| Sync Engine — State Tracking | Task 3 (SyncLedger) |
| Sync Engine — Initial Sync | Task 5 (full_sync) |
| Sync Engine — Incremental Sync | Task 5 (incremental_sync) |
| Sync Engine — Room Assignment | Task 2 (patterns in mempalace.yaml) |
| Sync Engine — Error Handling | Task 5 (mark_error) |
| User Wing — Data Model | Task 7 (UserWing.write) |
| User Wing — 6 MCP Tools | Tasks 7, 8, 9 |
| User Wing — Summary Synthesizer | Task 8 |
| User Wing — Deduplication | Task 7 (_find_duplicate) |
| User Wing — Topic Merging | Task 9 |
| User Wing — Pruning | Task 9 |
| MCP HTTP Server — Transport | Task 10 (FastMCP + StreamableHTTP) |
| MCP HTTP Server — Tool Registry | Task 10 (create_server) |
| MCP HTTP Server — Endpoints | Task 10 |
| Docker Container | Task 11 |
| IDE Integration — Claude Code | Task 14 (MCP config) |
| IDE Integration — Cursor | Task 12 (.mdc rules) |
| IDE Integration — Stop Hook | Task 12 |
| Testing | Tasks 3-10, 13 |
| Dependencies | Task 1 (pyproject.toml) |
| Excluded Repos | Task 2 (repos.json only lists included repos) |

**Note on spec deviations:**
- Spec says `mcp[server]` extra — the `[server]` extra does not exist. Using `mcp>=1.0.0` directly.
- Spec says "29 MCP tools" from mempalace — actual count is 27. Total tool count will be ~35 instead of ~37.
- Spec shows a dict-based `TOOLS` registry — mempalace uses that internally, but we wrap everything in FastMCP decorator pattern for our HTTP server.
- `entities.json` from the spec is omitted — mempalace's `KnowledgeGraph` handles entity storage natively via `seed_from_entity_facts()`. Can be added later if needed.
