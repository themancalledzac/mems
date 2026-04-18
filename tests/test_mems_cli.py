"""mems CLI dispatcher tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mems_cli import __version__
from mems_cli import main as main_module
from mems_cli.main import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_help_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "mems" in captured.out
    assert "health" in captured.out
    assert "tools" in captured.out


def test_no_args_prints_help_and_errors(capsys):
    code = main([])
    assert code == 1
    captured = capsys.readouterr()
    assert "mems" in captured.out


def test_bogus_command_exits_nonzero(capsys):
    # argparse prints its own error and exits with 2.
    with pytest.raises(SystemExit) as exc:
        main(["bogus"])
    assert exc.value.code in (1, 2)


def test_health_command_calls_palace_client(capsys):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def health(self):
            return {"ok": True, "wings": [{"slug": "test"}]}

    with patch.object(main_module, "PalaceClient", FakeClient):
        code = main(["health"])
    assert code == 0
    captured = capsys.readouterr()
    assert "status" in captured.out
    assert "wings" in captured.out


def test_health_server_error_returns_exit_2(capsys):
    from mems_cli.palace_client import PalaceClientError

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def health(self):
            raise PalaceClientError("connection refused")

    with patch.object(main_module, "PalaceClient", FakeClient):
        code = main(["health"])
    assert code == 2
    captured = capsys.readouterr()
    assert "server error" in captured.err
    assert "connection refused" in captured.err


def test_tools_command_prints_names(capsys):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def list_tools(self):
            return [
                {"name": "mempalace_status", "description": "Overview."},
                {"name": "mempalace_search", "description": "Search the palace."},
            ]

    with patch.object(main_module, "PalaceClient", FakeClient):
        code = main(["tools"])
    assert code == 0
    captured = capsys.readouterr()
    assert "mempalace_status" in captured.out
    assert "mempalace_search" in captured.out
    assert "2 tool(s)" in captured.out


def test_tools_server_error_returns_exit_2(capsys):
    from mems_cli.palace_client import PalaceClientError

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def list_tools(self):
            raise PalaceClientError("boom")

    with patch.object(main_module, "PalaceClient", FakeClient):
        code = main(["tools"])
    assert code == 2
