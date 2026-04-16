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
