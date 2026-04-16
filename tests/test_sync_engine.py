import json
from pathlib import Path

import pytest

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
