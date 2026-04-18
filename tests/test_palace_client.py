"""PalaceClient JSON-RPC + SSE tests.

Mocks `urllib.request.urlopen` so tests can run offline and assert on the
exact request envelope the client constructs.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mems_cli.palace_client import PalaceClient, PalaceClientError


def _mock_response(body: bytes, content_type: str = "application/json", headers=None):
    """Build a MagicMock that mimics urlopen's context-manager response."""
    resp = MagicMock()
    resp.read.return_value = body
    hdrs = {"content-type": content_type}
    if headers:
        hdrs.update({k.lower(): v for k, v in headers.items()})
    resp.headers.get.side_effect = lambda key, default=None: hdrs.get(key.lower(), default)
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    resp.close = MagicMock()
    return resp


# --- health ------------------------------------------------------------------


def test_health_returns_parsed_json():
    body = json.dumps({"ok": True, "wings": []}).encode()
    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.return_value = _mock_response(body)
        client = PalaceClient(base_url="http://localhost:8787")
        out = client.health()
    assert out == {"ok": True, "wings": []}
    args, _ = uo.call_args
    req = args[0]
    assert req.full_url == "http://localhost:8787/health"
    assert req.get_method() == "GET"


def test_health_raises_on_http_error():
    import urllib.error

    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = urllib.error.HTTPError(
            url="http://localhost:8787/health",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )
        client = PalaceClient(base_url="http://localhost:8787")
        with pytest.raises(PalaceClientError, match="500"):
            client.health()


def test_health_raises_on_connection_error():
    import urllib.error

    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = urllib.error.URLError("connection refused")
        client = PalaceClient(base_url="http://localhost:8787")
        with pytest.raises(PalaceClientError, match="connection refused"):
            client.health()


# --- call / JSON-RPC ---------------------------------------------------------


def _init_response(body_dict: dict) -> MagicMock:
    return _mock_response(
        json.dumps(body_dict).encode(),
        headers={"mcp-session-id": "sess-abc"},
    )


def test_call_builds_correct_jsonrpc_envelope_and_headers():
    init_body = {"jsonrpc": "2.0", "id": "x", "result": {"protocolVersion": "1"}}
    call_body = {"jsonrpc": "2.0", "id": "y", "result": {"content": [], "isError": False}}

    responses = [
        _init_response(init_body),
        _mock_response(b""),  # initialized notification
        _mock_response(json.dumps(call_body).encode()),
    ]
    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = responses
        client = PalaceClient(base_url="http://localhost:8787")
        result = client.call("mempalace_status", {"foo": "bar"})

    assert result == {"content": [], "isError": False}

    # Three calls: initialize, notifications/initialized, tools/call.
    assert uo.call_count == 3

    # Inspect the tools/call request (the third one).
    req = uo.call_args_list[2].args[0]
    assert req.full_url == "http://localhost:8787/mcp/"
    assert req.get_method() == "POST"
    # Headers are lowercased by urllib.
    hdrs = {k.lower(): v for k, v in req.headers.items()}
    assert hdrs["content-type"] == "application/json"
    assert "application/json" in hdrs["accept"]
    assert "text/event-stream" in hdrs["accept"]
    # Session id propagated from initialize response.
    assert hdrs["mcp-session-id"] == "sess-abc"

    payload = json.loads(req.data.decode())
    assert payload["jsonrpc"] == "2.0"
    assert payload["method"] == "tools/call"
    assert payload["params"] == {"name": "mempalace_status", "arguments": {"foo": "bar"}}
    assert "id" in payload


def test_call_handles_sse_response():
    init_body = {"jsonrpc": "2.0", "id": "x", "result": {}}
    # Two SSE frames — the second matches the call's id. We don't know the
    # id in advance, so emit a payload without id-match and rely on the
    # fallback (first frame that has result/error) to be returned.
    sse_payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "unknown",
            "result": {"content": [{"type": "text", "text": "hi"}]},
        }
    )
    sse_body = b"event: message\n" + f"data: {sse_payload}\n".encode() + b"\n"

    responses = [
        _init_response(init_body),
        _mock_response(b""),
        _mock_response(sse_body, content_type="text/event-stream; charset=utf-8"),
    ]
    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = responses
        client = PalaceClient(base_url="http://localhost:8787")
        result = client.call("some_tool", {})

    assert result == {"content": [{"type": "text", "text": "hi"}]}


def test_call_raises_on_jsonrpc_error():
    init_body = {"jsonrpc": "2.0", "id": "x", "result": {}}
    err_body = {
        "jsonrpc": "2.0",
        "id": "y",
        "error": {"code": -32601, "message": "Method not found"},
    }
    responses = [
        _init_response(init_body),
        _mock_response(b""),
        _mock_response(json.dumps(err_body).encode()),
    ]
    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = responses
        client = PalaceClient(base_url="http://localhost:8787")
        with pytest.raises(PalaceClientError, match="Method not found"):
            client.call("bogus_tool", {})


def test_list_tools_returns_tool_array():
    init_body = {"jsonrpc": "2.0", "id": "x", "result": {}}
    tools_body = {
        "jsonrpc": "2.0",
        "id": "y",
        "result": {"tools": [{"name": "a"}, {"name": "b"}]},
    }
    responses = [
        _init_response(init_body),
        _mock_response(b""),
        _mock_response(json.dumps(tools_body).encode()),
    ]
    with patch("mems_cli.palace_client.urllib.request.urlopen") as uo:
        uo.side_effect = responses
        client = PalaceClient(base_url="http://localhost:8787")
        tools = client.list_tools()
    assert [t["name"] for t in tools] == ["a", "b"]


def test_context_manager_calls_close():
    client = PalaceClient(base_url="http://localhost:8787")
    with client as c:
        assert c is client
    # Close is a no-op but must not raise.
