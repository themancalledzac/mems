"""Tests for `mems standup` — exercises the handler directly (no main.py).

Each of the three sections (Jira / palace / git) is monkeypatched at the
standup-module boundary so we can drive both the happy path and the
graceful-degradation path without a live server, Jira, or git history.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from unittest.mock import MagicMock

from mems_cli.commands import standup as standup_module
from mems_cli.commands.standup import JiraClientError, cmd_standup
from mems_cli.palace_client import PalaceClientError
from tests.conftest import argparse_namespace_for

# --- fakes --------------------------------------------------------------------


class _FakePalaceClient:
    """Drop-in for PalaceClient. Records calls; returns a canned value."""

    last_instance: "_FakePalaceClient | None" = None
    return_value: dict = {"content": [{"type": "text", "text": "{}"}]}

    def __init__(self, *a, **k):
        self.calls: list[tuple[str, dict]] = []
        _FakePalaceClient.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def call(self, name: str, arguments: dict | None = None) -> dict:
        self.calls.append((name, arguments or {}))
        return self.return_value


def _install_palace(monkeypatch, return_value):
    class _Factory(_FakePalaceClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.return_value = return_value

    monkeypatch.setattr(standup_module, "PalaceClient", _Factory)
    return _Factory


def _install_palace_raises(monkeypatch, exc):
    class _Boom:
        def __init__(self, *a, **k):
            raise exc

    monkeypatch.setattr(standup_module, "PalaceClient", _Boom)


def _ok_subprocess(stdout):
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = stdout
    completed.stderr = ""
    return MagicMock(return_value=completed)


def _ns(**over):
    base = {"days": 1, "json": False}
    base.update(over)
    return argparse_namespace_for(**base)


# --- happy path: all three sections populate ---------------------------------


def test_standup_full_report(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(
        return_value={
            "issues": [
                {
                    "key": "ABC-9",
                    "fields": {"summary": "Ship the thing", "status": {"name": "Done"}},
                }
            ]
        }
    )
    monkeypatch.setattr(standup_module, "load_client", lambda: client)
    _install_palace(
        monkeypatch,
        return_value={"structuredContent": {"text": "Recent: chose Go over Rust."}},
    )
    monkeypatch.setattr(
        subprocess, "run", _ok_subprocess("abc1234 fix: a thing\ndef5678 feat: another\n")
    )

    rc = cmd_standup(_ns(days=3))
    assert rc == 0

    # Jira JQL uses the day window and currentUser().
    jql = client.search.call_args.args[0]
    assert "updated >= -3d" in jql
    assert "assignee = currentUser()" in jql

    # Palace summary tool was called.
    assert _FakePalaceClient.last_instance.calls[0][0] == "mempalace_user_summary"

    # git log invoked with the right window.
    git_cmd = subprocess.run.call_args.args[0]
    assert git_cmd[:2] == ["git", "log"]
    assert "--since=3 days ago" in git_cmd
    assert "--oneline" in git_cmd

    out = capsys.readouterr().out
    assert "## Jira updates" in out
    assert "ABC-9" in out
    assert "Ship the thing" in out
    assert "## Palace (recent)" in out
    assert "chose Go over Rust" in out
    assert "## Commits" in out
    assert "fix: a thing" in out


# --- graceful degradation: each section can fail independently ---------------


def test_standup_no_jira_creds_skips_section(monkeypatch, capsys):
    monkeypatch.setattr(standup_module, "load_client", lambda: None)
    _install_palace(monkeypatch, return_value={"structuredContent": {"text": "ctx"}})
    monkeypatch.setattr(subprocess, "run", _ok_subprocess(""))

    rc = cmd_standup(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Jira updates" in out
    assert "no Jira creds" in out
    # Still renders the other sections.
    assert "## Palace (recent)" in out
    assert "## Commits" in out


def test_standup_jira_error_does_not_crash(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(side_effect=JiraClientError("HTTP 500"))
    monkeypatch.setattr(standup_module, "load_client", lambda: client)
    _install_palace(monkeypatch, return_value={"structuredContent": {"text": "ctx"}})
    monkeypatch.setattr(subprocess, "run", _ok_subprocess(""))

    rc = cmd_standup(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "jira error" in out
    assert "## Palace (recent)" in out


def test_standup_palace_unavailable_continues(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(return_value={"issues": []})
    monkeypatch.setattr(standup_module, "load_client", lambda: client)
    _install_palace_raises(monkeypatch, PalaceClientError("connection refused"))
    monkeypatch.setattr(subprocess, "run", _ok_subprocess("abc1234 a commit\n"))

    rc = cmd_standup(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Palace (recent)" in out
    assert "palace unavailable" in out
    # Commits still render after the palace failure.
    assert "a commit" in out


def test_standup_git_failure_continues(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(return_value={"issues": []})
    monkeypatch.setattr(standup_module, "load_client", lambda: client)
    _install_palace(monkeypatch, return_value={"structuredContent": {"text": "ctx"}})

    failed = MagicMock(spec=subprocess.CompletedProcess)
    failed.returncode = 128
    failed.stdout = ""
    failed.stderr = "fatal: not a git repository"
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=failed))

    rc = cmd_standup(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Commits" in out
    assert "git error" in out
    assert "not a git repository" in out


# --- JSON mode ---------------------------------------------------------------


def test_standup_json_output(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(
        return_value={
            "issues": [
                {"key": "ABC-1", "fields": {"summary": "S", "status": {"name": "To Do"}}}
            ]
        }
    )
    monkeypatch.setattr(standup_module, "load_client", lambda: client)
    _install_palace(monkeypatch, return_value={"structuredContent": {"text": "ctx"}})
    monkeypatch.setattr(subprocess, "run", _ok_subprocess("abc1234 a commit\n"))

    rc = cmd_standup(_ns(json=True))
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["days"] == 1
    assert payload["jira"]["issues"][0]["key"] == "ABC-1"
    assert payload["palace"]["summary"]["text"] == "ctx"
    assert payload["commits"]["entries"] == ["abc1234 a commit"]


# --- registration ------------------------------------------------------------


def test_register_attaches_standup_subparser():
    parser = argparse.ArgumentParser(prog="mems")
    subparsers = parser.add_subparsers(dest="cmd")
    standup_module.register(subparsers)

    args = parser.parse_args(["standup", "--days", "5", "--json"])
    assert args.func is cmd_standup
    assert args.days == 5
    assert args.json is True

    defaults = parser.parse_args(["standup"])
    assert defaults.days == 1
    assert defaults.json is False
