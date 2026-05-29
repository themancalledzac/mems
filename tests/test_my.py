"""Tests for the `mems my <action>` User Wing shortcut module.

These exercise the handlers DIRECTLY (no `mems_cli.main` registration), so
they stay green even while a sibling agent is wiring `register()` into
`main.py`. We monkeypatch `PalaceClient` inside `mems_cli.commands.my` with a
fake that records `(tool_name, arguments)` and returns a canned MCP response.
"""

from __future__ import annotations

import argparse
import json

import pytest

from mems_cli.commands import my as my_module
from mems_cli.commands.my import (
    EXIT_OK,
    EXIT_SERVER_ERROR,
    EXIT_USER_ERROR,
    VALID_HALLS,
    cmd_my_decisions,
    cmd_my_discoveries,
    cmd_my_frustrations,
    cmd_my_goals,
    cmd_my_note,
    cmd_my_observations,
    cmd_my_questions,
    cmd_my_recent,
    register,
)
from tests.conftest import argparse_namespace_for

# --- fake palace client -------------------------------------------------------


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


def _install_fake(monkeypatch, return_value=None):
    """Patch `my.PalaceClient` with a fake. Returns the factory."""
    # `last_instance` is class-level and leaks across tests; reset it so each
    # test observes only its own client instantiations.
    _FakePalaceClient.last_instance = None

    class _Factory(_FakePalaceClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            if return_value is not None:
                self.return_value = return_value

    monkeypatch.setattr(my_module, "PalaceClient", _Factory)
    return _Factory


# --- hall search subcommands --------------------------------------------------

# Map each importable handler to the hall name it should query.
_HALL_HANDLERS = {
    "questions": cmd_my_questions,
    "discoveries": cmd_my_discoveries,
    "frustrations": cmd_my_frustrations,
    "goals": cmd_my_goals,
    "decisions": cmd_my_decisions,
    "observations": cmd_my_observations,
}


def test_all_six_halls_have_a_handler():
    assert set(_HALL_HANDLERS) == set(VALID_HALLS)


@pytest.mark.parametrize("hall,handler", list(_HALL_HANDLERS.items()))
def test_my_hall_calls_user_search_with_correct_args(hall, handler, monkeypatch, capsys):
    return_value = {
        "structuredContent": {
            "results": [
                {
                    "document": f"a {hall} thought about widgets",
                    "topic": "widgets",
                    "timestamp": "2026-05-29T00:00:00Z",
                }
            ]
        }
    }
    _install_fake(monkeypatch, return_value=return_value)

    ns = argparse_namespace_for(query="widgets", limit=7, as_json=False, hall=hall)
    assert handler(ns) == EXIT_OK

    calls = _FakePalaceClient.last_instance.calls
    assert len(calls) == 1
    tool, payload = calls[0]
    assert tool == "mempalace_user_search"
    assert payload["hall"] == hall
    assert payload["query"] == "widgets"
    assert payload["n_results"] == 7

    out = capsys.readouterr().out
    assert "widgets" in out
    assert f"a {hall} thought about widgets" in out


def test_my_hall_empty_query_defaults_to_blank(monkeypatch, capsys):
    _install_fake(monkeypatch, return_value={"structuredContent": {"results": []}})

    # `query` absent entirely -> handler should fall back to "".
    ns = argparse_namespace_for(as_json=False)
    assert cmd_my_questions(ns) == EXIT_OK

    tool, payload = _FakePalaceClient.last_instance.calls[0]
    assert tool == "mempalace_user_search"
    assert payload["query"] == ""
    assert payload["hall"] == "questions"
    assert payload["n_results"] == 10  # default limit

    out = capsys.readouterr().out
    assert "no matching thoughts" in out


def test_my_hall_json_flag_dumps_raw_payload(monkeypatch, capsys):
    payload = {"results": [{"document": "raw", "topic": "t", "timestamp": "ts"}]}
    _install_fake(monkeypatch, return_value={"structuredContent": payload})

    ns = argparse_namespace_for(query="", limit=10, as_json=True)
    assert cmd_my_goals(ns) == EXIT_OK

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == payload


def test_my_hall_accepts_bare_list_payload(monkeypatch, capsys):
    """user-search may return a bare list rather than a dict."""
    bare = [{"document": "listy", "topic": "lt", "timestamp": "lts"}]
    _install_fake(monkeypatch, return_value={"structuredContent": {"result": bare}})

    ns = argparse_namespace_for(query="", limit=10, as_json=False)
    assert cmd_my_discoveries(ns) == EXIT_OK
    out = capsys.readouterr().out
    assert "listy" in out
    assert "lt" in out


# --- recent (user summary) ----------------------------------------------------


def test_my_recent_calls_user_summary_and_prints_text(monkeypatch, capsys):
    _install_fake(
        monkeypatch,
        return_value={"structuredContent": {"text": "## User Context\nGoals: ship mems"}},
    )

    ns = argparse_namespace_for(as_json=False)
    assert cmd_my_recent(ns) == EXIT_OK

    calls = _FakePalaceClient.last_instance.calls
    assert calls[0][0] == "mempalace_user_summary"
    assert calls[0][1] == {}

    out = capsys.readouterr().out
    assert "User Context" in out
    assert "ship mems" in out


def test_my_recent_json_flag(monkeypatch, capsys):
    _install_fake(monkeypatch, return_value={"structuredContent": {"text": "hello"}})
    ns = argparse_namespace_for(as_json=True)
    assert cmd_my_recent(ns) == EXIT_OK
    out = capsys.readouterr().out
    assert json.loads(out) == {"text": "hello"}


# --- note (user write) --------------------------------------------------------


def test_my_note_writes_to_user_wing(monkeypatch, capsys):
    _install_fake(
        monkeypatch,
        return_value={"structuredContent": {"status": "created", "id": "user-abc123"}},
    )

    ns = argparse_namespace_for(
        text="CLIP ViT-L/14 beats B/32 for photo tags",
        hall="discoveries",
        topic="clip-models",
        source_wing="edens-zac",
    )
    assert cmd_my_note(ns) == EXIT_OK

    tool, payload = _FakePalaceClient.last_instance.calls[0]
    assert tool == "mempalace_user_write"
    assert payload["hall"] == "discoveries"
    assert payload["content"] == "CLIP ViT-L/14 beats B/32 for photo tags"
    assert payload["topic"] == "clip-models"
    assert payload["source_wing"] == "edens-zac"

    out = capsys.readouterr().out
    assert "created" in out
    assert "user-abc123" in out


def test_my_note_omits_source_wing_when_absent(monkeypatch):
    _install_fake(monkeypatch, return_value={"structuredContent": {"status": "created"}})
    ns = argparse_namespace_for(text="t", hall="goals", topic="general", source_wing=None)
    assert cmd_my_note(ns) == EXIT_OK
    _, payload = _FakePalaceClient.last_instance.calls[0]
    assert "source_wing" not in payload


def test_my_note_rejects_bad_hall(monkeypatch, capsys):
    factory = _install_fake(monkeypatch)
    ns = argparse_namespace_for(text="t", hall="bogus", topic="general", source_wing=None)
    assert cmd_my_note(ns) == EXIT_USER_ERROR

    err = capsys.readouterr().err
    assert "hall must be one of" in err
    assert "bogus" in err
    # Must NOT have hit the server with an invalid hall.
    assert factory.last_instance is None or factory.last_instance.calls == []


# --- server-error path --------------------------------------------------------


def test_server_error_returns_exit_server_error(monkeypatch, capsys):
    from mems_cli.palace_client import PalaceClientError

    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def call(self, *a, **k):
            raise PalaceClientError("connection refused")

    monkeypatch.setattr(my_module, "PalaceClient", lambda *a, **k: _Boom())

    ns = argparse_namespace_for(query="", limit=10, as_json=False)
    assert cmd_my_questions(ns) == EXIT_SERVER_ERROR
    err = capsys.readouterr().err
    assert "server error" in err
    assert "connection refused" in err


# --- register() wiring --------------------------------------------------------


def test_register_wires_my_subparser_and_actions():
    parser = argparse.ArgumentParser(prog="mems")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)

    # Every hall + recent + note must parse and bind a callable `func`.
    for hall in VALID_HALLS:
        ns = parser.parse_args(["my", hall, "some query"])
        assert callable(ns.func)
        assert ns.hall == hall
        assert ns.query == "some query"

    ns = parser.parse_args(["my", "recent"])
    assert callable(ns.func)

    ns = parser.parse_args(["my", "note", "a thought", "--hall", "goals", "--topic", "x"])
    assert callable(ns.func)
    assert ns.text == "a thought"
    assert ns.hall == "goals"
    assert ns.topic == "x"


def test_register_my_with_no_action_returns_user_error(capsys):
    parser = argparse.ArgumentParser(prog="mems")
    subparsers = parser.add_subparsers(dest="command")
    register(subparsers)

    ns = parser.parse_args(["my"])
    assert callable(ns.func)
    assert ns.func(ns) == EXIT_USER_ERROR
    out = capsys.readouterr().out
    assert "usage: mems my" in out
