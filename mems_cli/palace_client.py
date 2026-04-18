"""JSON-RPC 2.0 client for the Memory Palace MCP HTTP server.

FastMCP's streamable-http transport exposes the MCP protocol at `/mcp/`.
A `/health` route is mounted alongside it by `src.mcp_http_server`. This
client speaks the minimum JSON-RPC needed to initialize a session, list
tools, and call tools — using stdlib only so the `mems` CLI has no extra
runtime deps beyond what `pyproject.toml` already declares.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from mems_cli.common import get_server_url

# Endpoint for FastMCP streamable-http. Trailing slash matters: FastMCP
# mounts its handler at "/mcp" and redirects "/mcp" → "/mcp/".
MCP_PATH = "/mcp/"
HEALTH_PATH = "/health"

# MCP protocol version this client speaks. Matches current mcp-python.
MCP_PROTOCOL_VERSION = "2025-06-18"


class PalaceClientError(RuntimeError):
    """An HTTP, JSON-RPC, or parsing error talking to the palace server."""


class PalaceClient:
    """Minimal JSON-RPC 2.0 client over FastMCP's streamable HTTP transport.

    Usage:
        with PalaceClient() as client:
            client.initialize()
            tools = client.list_tools()
            result = client.call("mempalace_status", {})
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or get_server_url()).rstrip("/")
        self.timeout = timeout
        self._session_id: str | None = None
        self._initialized = False

    # --- Context-manager hooks -------------------------------------------

    def __enter__(self) -> "PalaceClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """No-op for stdlib urllib; present for parity with context usage."""
        return None

    # --- Public API ------------------------------------------------------

    def health(self) -> dict:
        """GET /health. Returns parsed JSON body, raises on non-2xx."""
        url = f"{self.base_url}{HEALTH_PATH}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise PalaceClientError(f"health check failed: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise PalaceClientError(f"health check failed: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001 — surface any transport error
            raise PalaceClientError(f"health check failed: {exc}") from exc

        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PalaceClientError(f"health returned non-JSON body: {exc}") from exc

    def initialize(self) -> dict:
        """Perform MCP `initialize` handshake; capture session id header."""
        params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mems-cli", "version": "0.1.0"},
        }
        result = self._rpc("initialize", params)
        # After initialize, FastMCP expects a `notifications/initialized`.
        self._notify("notifications/initialized", {})
        self._initialized = True
        return result

    def list_tools(self) -> list[dict]:
        """Return the server's registered MCP tools."""
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        return list(result.get("tools", []))

    def call(self, tool_name: str, arguments: dict | None = None) -> dict:
        """Invoke `tool_name` via MCP `tools/call`.

        Returns the server's `result` dict (typically `{content, isError}`).
        Raises `PalaceClientError` on JSON-RPC errors.
        """
        self._ensure_initialized()
        params = {"name": tool_name, "arguments": arguments or {}}
        return self._rpc("tools/call", params)

    # --- Internals -------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _rpc(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the `result` payload."""
        request_id = str(uuid.uuid4())
        envelope = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        msg = self._send(envelope, expect_response=True, match_id=request_id)
        if msg is None:
            raise PalaceClientError(f"no response for {method}")
        if "error" in msg and msg["error"] is not None:
            err = msg["error"]
            code = err.get("code", "?")
            message = err.get("message", "unknown error")
            raise PalaceClientError(f"JSON-RPC error {code}: {message}")
        return msg.get("result", {})

    def _notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no `id`, no response expected)."""
        envelope = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send(envelope, expect_response=False, match_id=None)

    def _send(
        self,
        envelope: dict,
        expect_response: bool,
        match_id: str | None,
    ) -> dict | None:
        """POST a JSON-RPC envelope to `/mcp/` and decode the reply."""
        url = f"{self.base_url}{MCP_PATH}"
        data = json.dumps(envelope).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raise PalaceClientError(f"HTTP {exc.code} {exc.reason} from {url}") from exc
        except urllib.error.URLError as exc:
            raise PalaceClientError(f"connection failed to {url}: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise PalaceClientError(f"connection failed to {url}: {exc}") from exc

        try:
            # Capture session id from the first response (initialize).
            session_header = None
            try:
                session_header = resp.headers.get("mcp-session-id")
            except Exception:  # noqa: BLE001
                session_header = None
            if session_header and not self._session_id:
                self._session_id = session_header

            content_type = ""
            try:
                content_type = (resp.headers.get("content-type") or "").lower()
            except Exception:  # noqa: BLE001
                content_type = ""

            if not expect_response:
                # Drain but don't parse.
                try:
                    resp.read()
                except Exception:  # noqa: BLE001
                    pass
                return None

            body = resp.read()
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

        if "text/event-stream" in content_type:
            return _parse_sse_for_id(body, match_id)

        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PalaceClientError(f"invalid JSON from server: {exc}") from exc


def _parse_sse_for_id(body: bytes | str, match_id: str | None) -> dict | None:
    """Scan an SSE payload for a JSON-RPC frame whose `id` matches.

    If `match_id` is None, returns the first parseable JSON-RPC frame.
    Returns None if no matching frame is present.
    """
    text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    fallback: dict | None = None
    for raw_event in text.split("\n\n"):
        data_lines = [
            line[5:].lstrip() for line in raw_event.splitlines() if line.startswith("data:")
        ]
        if not data_lines:
            continue
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        if match_id is None:
            return msg
        if str(msg.get("id")) == str(match_id):
            return msg
        if fallback is None and ("result" in msg or "error" in msg):
            fallback = msg
    return fallback
