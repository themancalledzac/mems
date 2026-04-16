import json
import subprocess
from pathlib import Path

import pytest

from src.sync_engine import SyncLedger, get_head_sha, get_changed_files


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
