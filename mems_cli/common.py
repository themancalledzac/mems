"""Shared utilities for the mems CLI.

Small, stdlib-only helpers for config, env resolution, and human-friendly
output. Kept dependency-free so `mems` can ship without pulling in anything
beyond what the base package already requires.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence

DEFAULT_SERVER_URL = "http://localhost:8787"
DEFAULT_CONFIG_DIR = "~/.config/mems"


def get_server_url() -> str:
    """Return the Memory Palace server URL.

    Reads `MEMORY_SERVER_URL` env var, falling back to the default.
    """
    return os.environ.get("MEMORY_SERVER_URL", DEFAULT_SERVER_URL)


def get_config_dir() -> Path:
    """Return the mems config directory, creating it if missing.

    Reads `MEMORY_CONFIG_DIR` env var, falling back to `~/.config/mems`.
    """
    raw = os.environ.get("MEMORY_CONFIG_DIR", DEFAULT_CONFIG_DIR)
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Output helpers ----------------------------------------------------------


def print_json(data: Any) -> None:
    """Print `data` as pretty JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def print_table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> None:
    """Print a simple padded text table.

    Empty `rows` prints only the header line. No external deps.
    """
    columns = [str(h) for h in headers]
    string_rows = [[str(cell) for cell in row] for row in rows]

    widths = [len(c) for c in columns]
    for row in string_rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def _fmt(row: Iterable[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    print(_fmt(columns))
    print(_fmt("-" * w for w in widths))
    for row in string_rows:
        print(_fmt(row))


# --- repos.json helpers ------------------------------------------------------


def load_repos_json(config_dir: Path) -> dict:
    """Load `repos.json` from `config_dir`. Returns `{}` if absent."""
    path = Path(config_dir) / "repos.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_repos_json(config_dir: Path, data: Mapping[str, Any]) -> None:
    """Write `repos.json` into `config_dir` (pretty-printed)."""
    path = Path(config_dir) / "repos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(dict(data), fh, indent=2, sort_keys=True)
        fh.write("\n")


# --- Error helper ------------------------------------------------------------


def err(msg: str, code: int = 1) -> NoReturn:
    """Print `msg` to stderr and exit with `code`."""
    print(msg, file=sys.stderr)
    sys.exit(code)


# --- MCP tool-call result helpers --------------------------------------------


def extract_tool_result(result: Mapping[str, Any]) -> Any:
    """Pull a useful payload out of an MCP `tools/call` response.

    FastMCP returns `{content: [{type, text}, ...], isError: bool,
    structuredContent: {...}}`. Prefer `structuredContent` when present
    (that's the real dict the tool returned). Fall back to decoding the
    first text block as JSON, then to the raw text.
    """
    if not isinstance(result, Mapping):
        return result

    structured = result.get("structuredContent")
    if structured is not None:
        # FastMCP wraps list returns as {"result": [...]} inside structuredContent.
        if isinstance(structured, Mapping) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, Mapping):
            text = first.get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
    return result
