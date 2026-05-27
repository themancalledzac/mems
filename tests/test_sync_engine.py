import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from src.sync_engine import SyncEngine, SyncLedger, get_changed_files, get_head_sha


class TestSyncLedger:
    def test_load_empty_ledger(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.entries == {}

    def test_load_existing_ledger(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger_path.write_text(
            json.dumps(
                {
                    "test-wing": {
                        "repo_path": "/repos/test",
                        "last_commit_sha": "abc123",
                        "last_sync_ts": "2026-04-15T10:00:00Z",
                        "files_indexed": 10,
                        "status": "synced",
                    }
                }
            )
        )
        ledger = SyncLedger(ledger_path)
        assert ledger.entries["test-wing"]["status"] == "synced"

    def test_update_and_save(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger = SyncLedger(ledger_path)
        ledger.update(
            "my-wing",
            {
                "repo_path": "/repos/mine",
                "last_commit_sha": "def456",
                "last_sync_ts": "2026-04-15T11:00:00Z",
                "files_indexed": 5,
                "status": "synced",
            },
        )
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

        with (
            patch(
                "src.sync_engine.scan_project", return_value=[mock_repo / "hello.py"]
            ) as mock_scan,
            patch("src.sync_engine.process_file") as mock_process,
        ):
            engine.full_sync()

        mock_scan.assert_called_once()
        mock_process.assert_called_once()
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

        with patch("src.sync_engine.scan_project", side_effect=Exception("repo not found")):
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
        engine.ledger.update(
            "test-wing",
            {
                "repo_path": str(mock_repo),
                "last_commit_sha": sha,
                "last_sync_ts": "2026-04-15T10:00:00Z",
                "files_indexed": 1,
                "status": "synced",
            },
        )

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
        engine.ledger.update(
            "test-wing",
            {
                "repo_path": str(mock_repo),
                "last_commit_sha": old_sha,
                "last_sync_ts": "2026-04-15T10:00:00Z",
                "files_indexed": 1,
                "status": "synced",
            },
        )

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

        with (
            patch(
                "src.sync_engine.scan_project", return_value=[mock_repo / "hello.py"]
            ) as mock_scan,
            patch("src.sync_engine.process_file") as mock_process,
        ):
            engine.full_sync(wing_name="test-wing")

        # Only test-wing should be synced
        mock_scan.assert_called_once()
        assert engine.ledger.get("test-wing") is not None
        assert engine.ledger.get("other-wing") is None


def test_full_sync_calls_mempalace_sync_after_ingest(monkeypatch, tmp_config, tmp_palace, mock_repo):
    """SyncEngine.full_sync should invoke upstream `mempalace sync` after ingest to prune stale drawers."""
    calls = []
    real_run = subprocess.run

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_subprocess_run(cmd, *args, **kwargs):
        calls.append(cmd)
        # Let git-related commands run for real (used by sync_engine for HEAD sha + diff).
        if cmd and isinstance(cmd, list) and cmd[0] == "git":
            return real_run(cmd, *args, **kwargs)
        return R()

    monkeypatch.setattr("src.sync_engine.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("src.sync_engine.scan_project", lambda *a, **k: [])
    monkeypatch.setattr("src.sync_engine.process_file", lambda *a, **k: None)

    repos = {"test-wing": {"path": str(mock_repo), "wing": "test-wing"}}
    (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

    engine = SyncEngine(
        config_path=str(tmp_config),
        data_path=str(tmp_palace),
    )

    engine.full_sync()

    # Look for `mempalace sync` in subprocess calls. Match the literal argv
    # (cmd[0] == "mempalace" and "sync" appears as a separate argv token) so
    # tmp_path strings that contain "mempalace"/"sync" don't false-positive.
    sync_calls = [
        c for c in calls
        if isinstance(c, list) and len(c) >= 2 and c[0] == "mempalace" and "sync" in c
    ]
    assert sync_calls, f"expected `mempalace sync` post-ingest call; got {calls}"
