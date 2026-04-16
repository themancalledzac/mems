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
