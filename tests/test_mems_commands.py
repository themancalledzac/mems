"""Tests for Phase 7 `mems` command modules.

One representative test per module, using monkeypatch for env + tmp_path
for config, and `unittest.mock.patch` for PalaceClient / Jira.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mems_cli.main import main


class _FakePalaceClient:
    """Drop-in for PalaceClient. Records calls; returns a canned value."""

    last_instance: "_FakePalaceClient | None" = None

    def __init__(self, *a, **k):
        self.calls: list[tuple[str, dict]] = []
        self.return_value: dict = {"content": [{"type": "text", "text": "{}"}]}
        _FakePalaceClient.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def call(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        return self.return_value


def _install_fake_palace(monkeypatch, return_value=None):
    """Patch PalaceClient in every module that imports it."""
    from mems_cli import main as main_module
    from mems_cli.commands import hybrid as hybrid_module
    from mems_cli.commands import palace_ops, publishing, search

    if return_value is not None:
        _FakePalaceClient.return_value_override = return_value

    class _Factory(_FakePalaceClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            if return_value is not None:
                self.return_value = return_value

    monkeypatch.setattr(main_module, "PalaceClient", _Factory)
    monkeypatch.setattr(palace_ops, "PalaceClient", _Factory)
    monkeypatch.setattr(search, "PalaceClient", _Factory)
    monkeypatch.setattr(publishing, "PalaceClient", _Factory)
    monkeypatch.setattr(hybrid_module, "PalaceClient", _Factory)
    return _Factory


def test_repo_add_and_list_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(tmp_path / "cfg"))

    # A git repo-ish path (just the .git marker is enough for the validator).
    repo = tmp_path / "myrepo"
    (repo / ".git").mkdir(parents=True)

    assert main(["repo", "add", "my-wing", str(repo)]) == 0
    captured = capsys.readouterr()
    assert "added my-wing" in captured.out

    # Verify the repos.json on disk matches the expected shape.
    repos = json.loads((tmp_path / "cfg" / "repos.json").read_text())
    assert "my-wing" in repos
    assert repos["my-wing"]["path"] == str(repo.resolve())
    assert repos["my-wing"]["wing"] == "my-wing"

    # List should include the wing we just added.
    capsys.readouterr()  # drain
    assert main(["repo", "list"]) == 0
    out = capsys.readouterr().out
    assert "my-wing" in out
    assert str(repo.resolve()) in out


def test_repo_add_rejects_non_git_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(tmp_path / "cfg"))
    plain = tmp_path / "plain"
    plain.mkdir()

    assert main(["repo", "add", "plain", str(plain)]) == 1
    err = capsys.readouterr().err
    assert "not a git repo" in err


def test_publish_dry_run_invokes_publish_to_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(tmp_path / "cfg"))

    # Seed repos.json with a wing.
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (cfg / "repos.json").write_text(json.dumps({"my-wing": {"path": str(repo), "wing": "my-wing"}}))

    # Fake bundle file the fake palace "wrote".
    bundle = tmp_path / "my-wing.wingpack"
    bundle.write_bytes(b"fake-zip")

    fake_palace_return = {"structuredContent": {"path": str(bundle), "slug": "my-wing"}}
    _install_fake_palace(monkeypatch, return_value=fake_palace_return)

    from mems_cli.commands import publishing
    from src.wing_publish import PublishResult

    spy = MagicMock(return_value=PublishResult(path=bundle, mode="default", dry_run=True))
    monkeypatch.setattr(publishing, "publish_to_repo", spy)

    assert main(["publish", "my-wing", "--dry-run"]) == 0
    spy.assert_called_once()
    kwargs = spy.call_args.kwargs
    assert kwargs["dry_run"] is True
    assert kwargs["bundle"] == bundle
    assert kwargs["repo_root"] == type(kwargs["repo_root"])(repo)


def test_status_calls_memory_sync_status(monkeypatch, capsys):
    return_value = {
        "structuredContent": {
            "wings": {
                "wing-a": {
                    "last_sync_ts": "2026-04-18T00:00:00Z",
                    "files_indexed": 42,
                    "status": "synced",
                }
            }
        }
    }
    _install_fake_palace(monkeypatch, return_value=return_value)

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "wing-a" in out
    assert "synced" in out

    assert _FakePalaceClient.last_instance is not None
    calls = _FakePalaceClient.last_instance.calls
    assert calls[0][0] == "memory_sync_status"


def test_search_wing_calls_mempalace_search(monkeypatch):
    _install_fake_palace(monkeypatch, return_value={"structuredContent": {"results": []}})

    assert main(["search", "my query", "--wing", "foo"]) == 0

    calls = _FakePalaceClient.last_instance.calls
    assert calls[0][0] == "mempalace_search"
    assert calls[0][1]["query"] == "my query"
    assert calls[0][1]["wing"] == "foo"


def test_search_human_output_shows_path_and_snippet(monkeypatch, capsys):
    hit = {
        "text": "the matching content",
        "source_path": "/repos/Memory/src/x.py",
        "distance": 0.1,
        "wing": "memory",
    }
    _install_fake_palace(monkeypatch, return_value={"structuredContent": {"results": [hit]}})

    assert main(["search", "my query", "--wing", "memory"]) == 0

    out = capsys.readouterr().out
    assert "src/x.py" in out
    assert "the matching content" in out
    first = out.splitlines()[0]
    assert first.endswith("src/x.py")
    assert "?" not in first


def test_search_without_wing_calls_search_all(monkeypatch):
    _install_fake_palace(monkeypatch, return_value={"structuredContent": {"results": []}})
    assert main(["search", "something"]) == 0
    calls = _FakePalaceClient.last_instance.calls
    assert calls[0][0] == "mempalace_search_all"


def test_ticket_list_missing_env_errors_clearly(monkeypatch, capsys):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    assert main(["ticket", "list"]) == 1
    err = capsys.readouterr().err
    assert "JIRA_URL" in err
    assert "JIRA_EMAIL" in err
    assert "JIRA_API_TOKEN" in err


def test_hybrid_joins_jira_and_palace(monkeypatch, capsys):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")

    # Mock the Jira client's issue() method.
    fake_issue = {
        "key": "FOO-123",
        "fields": {
            "summary": "Fix the bug",
            "status": {"name": "In Progress"},
            "description": "Some context text",
        },
    }
    from mems_cli.commands import hybrid as hybrid_module
    from mems_cli.commands import tickets as tickets_module

    issue_mock = MagicMock(return_value=fake_issue)
    fake_client = MagicMock()
    fake_client.issue = issue_mock
    monkeypatch.setattr(tickets_module, "load_client", lambda: fake_client)
    monkeypatch.setattr(hybrid_module, "load_client", lambda: fake_client)

    _install_fake_palace(
        monkeypatch,
        return_value={
            "structuredContent": {
                "drawers": [
                    {
                        "document": "matching palace drawer",
                        "distance": 0.2,
                        "metadata": {"source_path": "src/thing.py"},
                    }
                ]
            }
        },
    )

    assert main(["hybrid", "FOO-123"]) == 0
    issue_mock.assert_called_once_with("FOO-123")

    palace_calls = _FakePalaceClient.last_instance.calls
    assert palace_calls[0][0] == "mempalace_search_all"
    assert "Fix the bug" in palace_calls[0][1]["query"]

    out = capsys.readouterr().out
    assert "FOO-123" in out
    assert "Fix the bug" in out
    assert "src/thing.py" in out
    assert "matching palace drawer" in out


def test_mems_make_shells_out_to_mempalace_init(monkeypatch, tmp_path):
    """`mems make <dir>` should invoke `mempalace init --auto-mine <dir>` via subprocess."""
    from tests.conftest import argparse_namespace_for

    captured = []

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        captured.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr("subprocess.run", fake_run)

    from mems_cli.commands import palace_ops

    palace_ops.cmd_make(argparse_namespace_for(dir=str(tmp_path), yes=True))

    assert captured, "subprocess.run was not called"
    cmd = captured[0]
    assert "mempalace" in cmd[0] or cmd[0].endswith("mempalace")
    assert "init" in cmd
    assert "--auto-mine" in cmd
    assert str(tmp_path) in cmd
