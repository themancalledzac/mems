"""Multi-repo git-diff sync orchestrator."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mempalace.miner import process_file, scan_project
from mempalace.palace import get_collection


def _flatten_rooms(wing_def: dict) -> list:
    """Flatten halls.<hall>.rooms into a single list for process_file."""
    halls = wing_def.get("halls", {}) or {}
    flat = []
    for hall_def in halls.values():
        for room in hall_def.get("rooms", []) or []:
            flat.append(room)
    return flat


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
        """Run full mine on all repos (or a specific wing).

        Uses scan_project + process_file instead of mine() because repos
        are mounted read-only and mine() expects a mempalace.yaml in each repo.
        """
        targets = (
            {wing_name: self.repos[wing_name]}
            if wing_name
            else self.repos
        )

        for name, repo_config in targets.items():
            repo_path = repo_config["path"]
            try:
                files = scan_project(repo_path)
                collection = get_collection(str(self.data_path))
                wing_def = self.taxonomy.get("wings", {}).get(name, {})
                wing_rooms = _flatten_rooms(wing_def)

                for filepath in files:
                    process_file(
                        filepath=Path(filepath),
                        project_path=Path(repo_path),
                        collection=collection,
                        wing=name,
                        rooms=wing_rooms,
                        agent="memory-sync",
                        dry_run=False,
                    )

                head_sha = get_head_sha(repo_path)
                self.ledger.update(name, {
                    "repo_path": repo_path,
                    "last_commit_sha": head_sha,
                    "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                    "files_indexed": len(files),
                    "status": "synced",
                })
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self._post_ingest_prune()
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
                wing_def = self.taxonomy.get("wings", {}).get(name, {})
                wing_rooms = _flatten_rooms(wing_def)

                for filepath in changes["deleted"]:
                    full_path = str(Path(repo_path) / filepath)
                    self._delete_drawers_for_file(collection, full_path)

                for filepath in changes["added"] + changes["modified"]:
                    full_path = Path(repo_path) / filepath
                    if full_path.exists():
                        process_file(
                            filepath=full_path,
                            project_path=Path(repo_path),
                            collection=collection,
                            wing=name,
                            rooms=wing_rooms,
                            agent="memory-sync",
                            dry_run=False,
                        )

                file_count = len(changes["added"]) + len(changes["modified"])
                prev_count = entry.get("files_indexed", 0)
                self.ledger.update(name, {
                    "repo_path": repo_path,
                    "last_commit_sha": head_sha,
                    "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                    "files_indexed": prev_count + len(changes["added"]) - len(changes["deleted"]),
                    "status": "synced",
                })
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self._post_ingest_prune()
        self.ledger.save()

    def _post_ingest_prune(self) -> None:
        """Prune drawers whose source files were gitignored/deleted/moved.

        Upstream cmd_sync handles this — runs against the same palace_path the
        wrapper just wrote to (MEMPALACE_PALACE_PATH already set via _bind_palace).
        Non-fatal: ingest already succeeded. Log + continue on failure.
        """
        try:
            subprocess.run(
                ["mempalace", "sync", "--apply"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            print(f"warning: post-ingest mempalace sync skipped: {exc}", flush=True)

    def _delete_drawers_for_file(self, collection, source_file: str):
        """Remove all drawers originating from a deleted file."""
        try:
            results = collection.get(where={"source_file": source_file})
            if results and results.get("ids"):
                collection.delete(ids=results["ids"])
        except Exception:
            pass
