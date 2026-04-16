import json
from pathlib import Path
from unittest.mock import patch

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
