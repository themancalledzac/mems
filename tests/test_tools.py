import json
from pathlib import Path
from unittest.mock import patch

from src.sync_engine import SyncLedger
from src.tools import handle_resync, handle_sync, handle_sync_status


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

    def test_sync_status_partial_on_prune_error(self, tmp_config, tmp_palace, mock_repo):
        error_report = {
            "status": "error",
            "removed": 0,
            "would_remove": 0,
            "reason": "RuntimeError: boom",
        }
        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.prune_wing", return_value=error_report),
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
            result = handle_sync(config_path=str(tmp_config), data_path=str(tmp_palace))

        assert result["status"] == "partial"
        assert result["synced"] == ["test-wing"]
        assert result["errors"] == []
        assert result["prune"]["test-wing"]["status"] == "error"

    def test_sync_status_partial_on_blocked_prune(self, tmp_config, tmp_palace, mock_repo):
        blocked = {"status": "blocked", "removed": 0, "would_remove": 300, "reason": "large"}
        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.prune_wing", return_value=blocked) as prune,
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
            result = handle_resync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
                full_refresh=True,
                allow_large_prune=True,
            )

        assert result["status"] == "partial"
        assert result["prune"]["test-wing"]["status"] == "blocked"
        assert prune.call_args.kwargs["allow_large"] is True

    def test_sync_reports_only_touched_wings(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}, "other-wing": {"path": "/nowhere"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))
        ledger = SyncLedger(Path(tmp_palace) / "sync_ledger.json")
        ledger.mark_error("other-wing", "/nowhere", "old failure")
        ledger.save()

        with (
            patch("src.sync_engine.list_indexable_files", return_value=[]),
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
            result = handle_sync(
                config_path=str(tmp_config),
                data_path=str(tmp_palace),
                wing="test-wing",
                full=True,
            )

        assert result["status"] == "ok"
        assert result["synced"] == ["test-wing"]
        assert result["errors"] == []
        assert list(result["prune"]) == ["test-wing"]

    def test_sync_reports_errored_wing(self, tmp_config, tmp_palace):
        repos = {"bad-wing": {"path": "/nonexistent/repo"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        result = handle_sync(config_path=str(tmp_config), data_path=str(tmp_palace))

        assert result["status"] == "partial"
        assert result["synced"] == []
        assert [e["wing"] for e in result["errors"]] == ["bad-wing"]


def test_second_sync_waits_for_first(tmp_config, tmp_palace, monkeypatch):
    import threading

    from src import tools

    first_entered = threading.Event()
    release_first = threading.Event()
    order = []

    class FakeEngine:
        def __init__(self, config_path, data_path):
            self.repos = {"first": {}, "second": {}}
            self.ledger = SyncLedger(Path(data_path) / "sync_ledger.json")

        def full_sync(self, wing_name=None, allow_large_prune=False):
            order.append(f"start-{wing_name}")
            if wing_name == "first":
                first_entered.set()
                release_first.wait(5)
            order.append(f"end-{wing_name}")
            return []

    monkeypatch.setattr(tools, "SyncEngine", FakeEngine)

    def sync(wing):
        tools.handle_sync(str(tmp_config), str(tmp_palace), wing=wing, full=True)

    first = threading.Thread(target=sync, args=("first",))
    second = threading.Thread(target=sync, args=("second",))
    first.start()
    assert first_entered.wait(5)
    second.start()
    second.join(0.3)
    assert order == ["start-first"]
    release_first.set()
    first.join(5)
    second.join(5)
    assert order == ["start-first", "end-first", "start-second", "end-second"]


class TestSyncToolsRunInWorkerThread:
    async def test_memory_sync_runs_in_worker_thread(self, tmp_palace, tmp_config, monkeypatch):
        import anyio

        from src import mcp_http_server

        threaded = []

        async def fake_run_sync(func, *args, **kwargs):
            threaded.append(func)
            return func(*args)

        def fake_handle_sync(**kwargs):
            return {"status": "ok", "synced": [], "errors": [], "prune": {}, "kwargs": kwargs}

        monkeypatch.setattr(anyio.to_thread, "run_sync", fake_run_sync)
        monkeypatch.setattr(mcp_http_server, "handle_sync", fake_handle_sync)
        server = mcp_http_server.create_server(
            palace_path=str(tmp_palace), config_path=str(tmp_config)
        )

        result = await server._tool_manager.call_tool(
            "memory_sync", {"wing": "test-wing", "allow_large_prune": True}
        )

        assert len(threaded) == 1
        assert result["kwargs"]["allow_large_prune"] is True
        assert result["kwargs"]["wing"] == "test-wing"

    async def test_resync_runs_in_worker_thread(self, tmp_palace, tmp_config, monkeypatch):
        import anyio

        from src import mcp_http_server

        threaded = []

        async def fake_run_sync(func, *args, **kwargs):
            threaded.append(func)
            return func(*args)

        def fake_handle_resync(**kwargs):
            return {"status": "ok", "kwargs": kwargs}

        monkeypatch.setattr(anyio.to_thread, "run_sync", fake_run_sync)
        monkeypatch.setattr(mcp_http_server, "handle_resync", fake_handle_resync)
        server = mcp_http_server.create_server(
            palace_path=str(tmp_palace), config_path=str(tmp_config)
        )

        result = await server._tool_manager.call_tool(
            "mempalace_resync", {"full_refresh": True, "allow_large_prune": True}
        )

        assert len(threaded) == 1
        assert result["kwargs"] == {
            "config_path": str(tmp_config),
            "data_path": str(tmp_palace),
            "full_refresh": True,
            "allow_large_prune": True,
        }


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
