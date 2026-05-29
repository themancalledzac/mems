"""Tests for `mems todo` — exercises the handler directly (no main.py).

The command is registered separately by the parent, so these tests call
`cmd_todo` with a hand-built argparse.Namespace and monkeypatch the Jira
`load_client` inside the todo module.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

from mems_cli.commands import todo as todo_module
from mems_cli.commands.todo import JiraClientError, cmd_todo
from tests.conftest import argparse_namespace_for


def _fake_search_client(issues):
    client = MagicMock()
    client.search = MagicMock(return_value={"issues": issues})
    return client


_ISSUES = [
    {
        "key": "ABC-1",
        "fields": {"summary": "Wire up the widget", "status": {"name": "In Progress"}},
    },
    {
        "key": "ABC-2",
        "fields": {"summary": "Fix the flaky test", "status": {"name": "To Do"}},
    },
]


def test_todo_lists_open_tickets(monkeypatch, capsys):
    client = _fake_search_client(_ISSUES)
    monkeypatch.setattr(todo_module, "load_client", lambda: client)

    rc = cmd_todo(argparse_namespace_for(limit=20, project=None, json=False))
    assert rc == 0

    # Correct JQL: assigned to me, not Done, newest first.
    client.search.assert_called_once()
    jql = client.search.call_args.args[0]
    assert "assignee = currentUser()" in jql
    assert "statusCategory != Done" in jql
    assert "ORDER BY updated DESC" in jql
    assert client.search.call_args.kwargs["limit"] == 20

    out = capsys.readouterr().out
    assert "ABC-1" in out
    assert "In Progress" in out
    assert "Wire up the widget" in out


def test_todo_project_scopes_jql(monkeypatch, capsys):
    client = _fake_search_client([])
    monkeypatch.setattr(todo_module, "load_client", lambda: client)

    rc = cmd_todo(argparse_namespace_for(limit=5, project="ABC", json=False))
    assert rc == 0

    jql = client.search.call_args.args[0]
    assert 'project = "ABC"' in jql
    assert client.search.call_args.kwargs["limit"] == 5


def test_todo_json_output(monkeypatch, capsys):
    client = _fake_search_client(_ISSUES)
    monkeypatch.setattr(todo_module, "load_client", lambda: client)

    rc = cmd_todo(argparse_namespace_for(limit=20, project=None, json=True))
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["key"] == "ABC-1"


def test_todo_no_creds_returns_user_error(monkeypatch):
    # load_client returns None (and prints its own error) when creds are missing.
    monkeypatch.setattr(todo_module, "load_client", lambda: None)
    rc = cmd_todo(argparse_namespace_for(limit=20, project=None, json=False))
    assert rc == 1


def test_todo_jira_error_returns_server_error(monkeypatch, capsys):
    client = MagicMock()
    client.search = MagicMock(side_effect=JiraClientError("HTTP 500 boom"))
    monkeypatch.setattr(todo_module, "load_client", lambda: client)

    rc = cmd_todo(argparse_namespace_for(limit=20, project=None, json=False))
    assert rc == 2
    err = capsys.readouterr().err
    assert "jira error" in err
    assert "boom" in err


def test_register_attaches_todo_subparser():
    parser = argparse.ArgumentParser(prog="mems")
    subparsers = parser.add_subparsers(dest="cmd")
    todo_module.register(subparsers)

    args = parser.parse_args(["todo", "--limit", "7", "--project", "ABC", "--json"])
    assert args.func is cmd_todo
    assert args.limit == 7
    assert args.project == "ABC"
    assert args.json is True

    # Defaults.
    defaults = parser.parse_args(["todo"])
    assert defaults.limit == 20
    assert defaults.project is None
    assert defaults.json is False
