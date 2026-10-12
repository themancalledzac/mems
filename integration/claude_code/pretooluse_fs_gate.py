#!/usr/bin/env python3
"""Claude Code PreToolUse hook: remind the model to search the palace before more filesystem discovery.

It reads the session transcript (or the subagent's own transcript), counts discovery calls since the
last palace search, and warns at every multiple of the threshold when a target path belongs to a wing.
Settings: `MEMPALACE_FS_GATE_MODE` (warn|block|off), `_THRESHOLD`, `_TAIL_BYTES` and `_HOLDOUT`
(fraction of sessions left silent); a non-empty `MEMS_DIGEST` silences it, and every error fails open.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

FS_TOOLS = {"Grep", "Glob", "Read"}
BASH_TOOL = "Bash"
SEARCH_TOOLS = {"mempalace_search", "mempalace_search_all", "mempalace_user_search"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

DISCOVERY_COMMANDS = {
    "grep",
    "rg",
    "ripgrep",
    "find",
    "fd",
    "ls",
    "tree",
    "cat",
    "sed",
    "awk",
    "wc",
    "bat",
}

_SEGMENT_SPLIT_RE = re.compile(r"[\n;|]|&&|\|\|")
_WRAPPER_TOKENS = {"sudo", "command", "time", "nice", "xargs", "env"}

DEFAULT_THRESHOLD = 3
DEFAULT_TAIL_BYTES = 512 * 1024


def _load_repo_scope():
    path = Path(__file__).resolve().parent / "repo_scope.py"
    try:
        spec = importlib.util.spec_from_file_location("repo_scope", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


repo_scope = _load_repo_scope()


def is_discovery_command(command: str) -> bool:
    """True if any segment of a shell command leads with a discovery verb.

    Splits on newlines, `;`, `|`, `&&`, `||` and inspects the first real token of
    each segment. This catches the common multi-line probe:

        cd /repo
        echo "=== types ==="; sed -n '1,30p' app/types/GalleryFilter.ts
        grep -rn "Content" tests

    while leaving `git log --oneline | head` alone (no segment leads with a
    discovery verb — `head` is not in the set).
    """
    if not command:
        return False
    for segment in _SEGMENT_SPLIT_RE.split(command):
        tokens = segment.strip().split()
        idx = 0
        while idx < len(tokens) and ("=" in tokens[idx] or tokens[idx] in _WRAPPER_TOKENS):
            idx += 1
        if idx >= len(tokens):
            continue
        head = os.path.basename(tokens[idx])
        if head in DISCOVERY_COMMANDS:
            return True
    return False


def classify_tool(tool_name: str, tool_input: dict | None) -> str:
    """Classify one tool call as 'MEM', 'FS', or 'OTHER'.

    Only the three palace search tools count as 'MEM'; other mempalace tools are 'OTHER'.
    Shared with `mems_cli.protocol_audit` so the gate and the audit agree.
    """
    if not tool_name:
        return "OTHER"
    if tool_name.rsplit("__", 1)[-1] in SEARCH_TOOLS:
        return "MEM"
    if tool_name in FS_TOOLS:
        return "FS"
    if tool_name == BASH_TOOL:
        command = (tool_input or {}).get("command", "") or ""
        return "FS" if is_discovery_command(command) else "OTHER"
    return "OTHER"


def _edited_path(tool_name: str, tool_input: dict) -> str | None:
    if tool_name not in EDIT_TOOLS:
        return None
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return os.path.normpath(path) if isinstance(path, str) and path else None


def _read_path(tool_name: str, tool_input: dict) -> str | None:
    if tool_name != "Read":
        return None
    path = tool_input.get("file_path")
    return os.path.normpath(path) if isinstance(path, str) and path else None


def classify_calls(calls, edited: set[str] | None = None):
    """Yield the kind of each (tool_name, tool_input) call in order.

    A Read of a file already edited or written earlier counts as 'OTHER'. Pass `edited` to
    collect the edited paths.
    """
    edited = set() if edited is None else edited
    for tool_name, tool_input in calls:
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        path = _edited_path(tool_name, tool_input)
        if path:
            edited.add(path)
            yield "OTHER"
            continue
        if _read_path(tool_name, tool_input) in edited:
            yield "OTHER"
            continue
        yield classify_tool(tool_name, tool_input)


def iter_tool_calls(lines):
    """Yield (tool_name, tool_input) for each tool_use block in transcript lines."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        message = record.get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block.get("name") or "", block.get("input") or {}


def read_transcript_tail(path: Path, tail_bytes: int = DEFAULT_TAIL_BYTES) -> list[str]:
    """Read the last `tail_bytes` of a JSONL transcript as whole lines.

    Truncation can only shorten the observed run, which errs toward not warning.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        chunk = handle.read()
    lines = chunk.decode("utf-8", errors="replace").split("\n")
    if size > tail_bytes and lines:
        lines = lines[1:]
    return lines


def uncovered_run_length(lines, edited: set[str] | None = None) -> int:
    """Count filesystem calls since the last palace search in the transcript."""
    run = 0
    for kind in classify_calls(iter_tool_calls(lines), edited):
        if kind == "MEM":
            run = 0
        elif kind == "FS":
            run += 1
    return run


def _session_transcript(payload: dict) -> Path | None:
    explicit = payload.get("transcript_path")
    if explicit:
        return Path(explicit).expanduser()
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not session_id or not cwd:
        return None
    mangled = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    return Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"


def derive_transcript_path(payload: dict) -> Path | None:
    """Locate the transcript of the agent making this call.

    A payload with `agent_id` comes from a subagent, whose transcript is
    `<session transcript without .jsonl>/subagents/agent-<agent_id>.jsonl`.
    """
    session = _session_transcript(payload)
    if session is None:
        return None
    agent_id = payload.get("agent_id")
    if agent_id:
        candidate = session.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
    else:
        candidate = session
    return candidate if candidate.is_file() else None


def is_held_out(session_id: str | None) -> bool:
    """True when `MEMPALACE_FS_GATE_HOLDOUT` places this session in the silent group."""
    raw = os.environ.get("MEMPALACE_FS_GATE_HOLDOUT")
    if not raw or not session_id:
        return False
    try:
        fraction = float(raw)
    except ValueError:
        return False
    bucket = int(hashlib.sha1(str(session_id).encode()).hexdigest()[:8], 16) % 100
    return bucket < fraction * 100


def build_reminder(run: int, wing: str) -> str:
    """The message injected back into the model's context."""
    return (
        f"MEMORY PALACE GATE: {run} filesystem discovery calls in a row with no palace search.\n\n"
        f"Search before the next batch:\n"
        f'    mempalace_search(query="<what you are looking for>", wing="{wing}")\n\n'
        f"Exempt: reads-for-editing (a file you are about to change)."
    )


def _mode() -> str:
    return (os.environ.get("MEMPALACE_FS_GATE_MODE") or "warn").strip().lower()


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def evaluate(payload: dict) -> dict | None:
    """Decide what to emit for one hook payload. None means 'stay silent'."""
    if os.environ.get("MEMS_DIGEST"):
        return None
    if payload.get("hook_event_name") != "PreToolUse":
        return None
    mode = _mode()
    if mode == "off" or repo_scope is None:
        return None

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if classify_tool(tool_name, tool_input) != "FS":
        return None

    targets = repo_scope.target_paths(tool_name, tool_input, payload.get("cwd") or "")
    wing = repo_scope.first_wing(targets)
    if not wing:
        return None

    transcript = derive_transcript_path(payload)
    if transcript is None:
        return None
    try:
        lines = read_transcript_tail(
            transcript, _positive_int_env("MEMPALACE_FS_GATE_TAIL_BYTES", DEFAULT_TAIL_BYTES)
        )
    except OSError:
        return None

    edited: set[str] = set()
    run = uncovered_run_length(lines, edited)
    if _read_path(tool_name, tool_input) in edited:
        return None
    run += 1
    threshold = _positive_int_env("MEMPALACE_FS_GATE_THRESHOLD", DEFAULT_THRESHOLD)
    if run < threshold or run % threshold != 0:
        return None
    if is_held_out(payload.get("session_id")):
        return None

    reminder = build_reminder(run, wing)
    if mode == "block":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reminder,
            }
        }
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reminder,
        }
    }


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        decision = evaluate(payload)
    except Exception:
        return 0
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
