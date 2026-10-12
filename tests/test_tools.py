import json
from pathlib import Path
from unittest.mock import patch

from src.tools import handle_sync, handle_sync_status


class TestHandleSync:
    def test_sync_all(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
            result = handle_sync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
            )

        assert result["status"] == "ok"
        assert "test-wing" in result["synced"]

    def test_sync_specific_wing(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
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
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
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
