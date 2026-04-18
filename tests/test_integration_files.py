"""Structural tests for Phase 8 install artifacts.

These tests verify the shape of config snippets and installer scripts — NOT
their runtime behaviour (that would require Docker + a real IDE).
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = REPO_ROOT / "integration"
SCRIPTS = REPO_ROOT / "scripts"


# --- JSON snippet (Cursor) ---


def test_cursor_mcp_json_is_valid_json():
    path = INTEGRATION / "mempalace_mcp_cursor.json"
    assert path.exists(), f"missing {path}"
    data = json.loads(path.read_text())
    assert "mcpServers" in data, "top-level key 'mcpServers' missing"
    mempalace = data["mcpServers"].get("mempalace")
    assert mempalace is not None, "mcpServers.mempalace entry missing"
    assert "url" in mempalace, "mcpServers.mempalace.url missing"
    assert mempalace["url"].startswith("http"), "url should be an http(s) URL"


# --- TOML snippet (Codex) ---


def test_codex_append_toml_is_valid_toml():
    path = INTEGRATION / "mempalace_codex_append.toml"
    assert path.exists(), f"missing {path}"
    data = tomllib.loads(path.read_text())
    assert "mcp_servers" in data, "top-level [mcp_servers] table missing"
    assert "mempalace" in data["mcp_servers"], "[mcp_servers.mempalace] missing"
    entry = data["mcp_servers"]["mempalace"]
    assert "url" in entry, "mcp_servers.mempalace.url missing"
    assert entry["url"].startswith("http"), "url should be an http(s) URL"


# --- shell scripts: exist, executable, syntactically valid ---


@pytest.mark.parametrize(
    "relpath",
    [
        "scripts/setup.sh",
        "scripts/install_cursor.sh",
        "scripts/install_codex.sh",
    ],
)
def test_shell_script_exists_executable_and_valid(relpath: str):
    path = REPO_ROOT / relpath
    assert path.exists(), f"missing {path}"

    mode = path.stat().st_mode
    is_exec = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    assert is_exec, f"{path} is not marked executable"

    # bash -n: parse without executing. Non-zero exit means syntax error.
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n failed for {path}:\n{result.stderr}"


# --- Cursor .mdc rule ---


def test_cursor_mdc_rule_has_expected_frontmatter():
    path = SCRIPTS / "cursor_rules" / "mempalace.mdc"
    assert path.exists(), f"missing {path}"

    text = path.read_text()
    assert text.startswith("---"), ".mdc must start with YAML frontmatter"

    # pull out the frontmatter block
    parts = text.split("---", 2)
    assert len(parts) >= 3, "frontmatter delimiter pair not found"
    frontmatter = parts[1]
    assert "alwaysApply: true" in frontmatter, "alwaysApply: true missing from frontmatter"
