#!/usr/bin/env python3
"""Claude Code PreToolUse hook: gate naked filesystem discovery on mempalace usage.

This is the structural counterpart to `pretooluse_agent_orientation.py`. That hook
gates *subagent dispatch*; this one gates the *parent loop* — the case CLAUDE.md
Hard Rule #1 covers and which procedural enforcement measurably fails to catch
(83% of filesystem batches ran with no preceding mempalace call, measured across
83 sessions on 2026-08-22; see `mems doctor --protocol`).

Why this is not the "doom loop" the audit tracker ruled out
-----------------------------------------------------------
`docs/protocol-audit-tracker.md` previously marked this OPEN-U on the reasoning
that such a hook "either calls mempalace or reads a ledger that gets stale."
Both horns are avoidable. This hook reads the **session transcript** that Claude
Code hands it on stdin, counts consecutive filesystem tool calls since the last
`mempalace_*` call, and decides from that. It calls no MCP tool (no recursion)
and keeps no state file (nothing to go stale) — the transcript is the ground
truth and reading it is plain local file I/O.

The warn cadence is likewise stateless: it fires when the run length is an exact
multiple of the threshold (3, 6, 9, ...), so there is no "have I already warned?"
bookkeeping to drift out of sync.

Behavior
--------
- Only `Bash`/`Grep`/`Glob`/`Read`/`LS`/`NotebookRead` events are considered.
- `Bash` is further filtered to *discovery* commands (see `is_discovery_command`),
  so `git commit`, `pytest`, and `npm run build` never trip the gate.
- Default mode is `warn`: it injects a reminder the model sees, and the tool call
  proceeds. Set `MEMPALACE_FS_GATE_MODE=block` to deny instead.
- Fails open on every error path. A hook that bricks the harness is worse than a
  hook that misses a violation.

Environment
-----------
    MEMPALACE_FS_GATE_THRESHOLD   int, default 3   consecutive FS calls before warning
    MEMPALACE_FS_GATE_MODE        warn|block|off,  default warn
    MEMPALACE_FS_GATE_TAIL_BYTES  int, default 524288  transcript tail window

Install via `bash scripts/install_claude_code.sh`.
Tested by tests/test_pretooluse_fs_gate.py.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Tools that count as filesystem discovery on their own.
FS_TOOLS = {"Grep", "Glob", "Read", "LS", "NotebookRead"}

# Bash is conditional — only discovery-shaped commands count.
BASH_TOOL = "Bash"

# Commands that mean "I am looking for something in the tree".
#
# `head`/`tail` are deliberately EXCLUDED: they appear overwhelmingly as pagers
# on non-discovery pipelines (`git log | head`) and including them produced
# false positives in the 2026-08-22 measurement.
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

# Segment separators inside a compound shell command.
_SEGMENT_SPLIT_RE = re.compile(r"[\n;|]|&&|\|\|")

# Leading tokens that wrap a real command without being one themselves.
_WRAPPER_TOKENS = {"sudo", "command", "time", "nice", "xargs", "env"}

MEMPALACE_MARKER = "mempalace"

DEFAULT_THRESHOLD = 3
DEFAULT_TAIL_BYTES = 512 * 1024


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
        # Skip env-var assignments (FOO=bar cmd) and wrapper tokens.
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

    Shared with `mems_cli.protocol_audit` so the gate and the measurement always
    agree on what counts as a violation.
    """
    if not tool_name:
        return "OTHER"
    if MEMPALACE_MARKER in tool_name:
        return "MEM"
    if tool_name in FS_TOOLS:
        return "FS"
    if tool_name == BASH_TOOL:
        command = (tool_input or {}).get("command", "") or ""
        return "FS" if is_discovery_command(command) else "OTHER"
    return "OTHER"


def _iter_tool_calls(lines):
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

    Transcripts reach many megabytes; this hook runs before every filesystem call,
    so we only look at the recent window. Truncating can only *shorten* the run we
    observe, and a short run errs toward not warning — the safe direction.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        chunk = handle.read()
    text = chunk.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if size > tail_bytes and lines:
        # First line is probably a partial record from mid-file.
        lines = lines[1:]
    return lines


def uncovered_run_length(lines) -> int:
    """Count filesystem calls since the last mempalace call in the transcript.

    Walks forward and resets on every mempalace call, so the returned value is the
    length of the trailing uncovered run.
    """
    run = 0
    for tool_name, tool_input in _iter_tool_calls(lines):
        kind = classify_tool(tool_name, tool_input)
        if kind == "MEM":
            run = 0
        elif kind == "FS":
            run += 1
    return run


def derive_transcript_path(payload: dict) -> Path | None:
    """Locate the session transcript.

    Prefers the `transcript_path` the hook contract supplies. Falls back to
    reconstructing `~/.claude/projects/<mangled-cwd>/<session_id>.jsonl` so the
    gate keeps working if that field is ever absent.
    """
    explicit = payload.get("transcript_path")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate

    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not session_id or not cwd:
        return None
    mangled = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    candidate = Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"
    return candidate if candidate.is_file() else None


def guess_wing(cwd: str | None) -> str | None:
    """Best-effort repo-dir -> wing-slug guess for the reminder text."""
    if not cwd:
        return None
    name = Path(str(cwd)).name
    if not name:
        return None
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or None


def build_reminder(run: int, wing: str | None) -> str:
    """The message injected back into the model's context."""
    if wing:
        target = f'mempalace_search(query="<what you are looking for>", wing="{wing}")'
    else:
        target = "mempalace_search"
    return (
        f"MEMORY PALACE GATE: {run} consecutive filesystem discovery calls with no "
        f"mempalace search in between.\n\n"
        f"CLAUDE.md Hard Rule #1 requires a mempalace search before each batch of 2+ "
        f"Grep/Glob/Read/Bash discovery calls. The palace has already indexed this repo — "
        f"searching it is faster than grepping and returns the surrounding context.\n\n"
        f"Run this before continuing:\n    {target}\n\n"
        f"If these are reads-for-editing (loading a file you are about to modify), the "
        f"per-batch rule does not apply and you may proceed — that exemption is real, "
        f"but it does not cover discovery reads."
    )


def _mode() -> str:
    return (os.environ.get("MEMPALACE_FS_GATE_MODE") or "warn").strip().lower()


def _threshold() -> int:
    raw = os.environ.get("MEMPALACE_FS_GATE_THRESHOLD")
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return value if value > 0 else DEFAULT_THRESHOLD


def _tail_bytes() -> int:
    raw = os.environ.get("MEMPALACE_FS_GATE_TAIL_BYTES")
    if not raw:
        return DEFAULT_TAIL_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TAIL_BYTES
    return value if value > 0 else DEFAULT_TAIL_BYTES


def evaluate(payload: dict) -> dict | None:
    """Decide what to emit for one hook payload. None means 'stay silent'."""
    if payload.get("hook_event_name") != "PreToolUse":
        return None

    mode = _mode()
    if mode == "off":
        return None

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if classify_tool(tool_name, tool_input) != "FS":
        return None

    transcript = derive_transcript_path(payload)
    if transcript is None:
        return None

    try:
        lines = read_transcript_tail(transcript, _tail_bytes())
    except OSError:
        return None

    # +1 for the call currently being gated, which is not in the transcript yet.
    run = uncovered_run_length(lines) + 1
    threshold = _threshold()
    if run < threshold or run % threshold != 0:
        return None

    reminder = build_reminder(run, guess_wing(payload.get("cwd")))

    if mode == "block":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reminder,
            }
        }
    # `additionalContext` is non-blocking: the model sees the reminder, the tool
    # call still runs. Deliberately the only key emitted — `systemMessage` is not
    # in the current hook reference, and an unrecognized key risks the whole
    # payload being discarded, which would silently disable the gate.
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
        # Never block on a parse failure — mirrors pretooluse_agent_orientation.py.
        return 0
    if not isinstance(payload, dict):
        return 0

    try:
        decision = evaluate(payload)
    except Exception:
        # Fail open on any unexpected error. A broken gate must not stop work.
        return 0

    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
