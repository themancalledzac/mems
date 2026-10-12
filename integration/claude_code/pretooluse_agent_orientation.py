#!/usr/bin/env python3
"""Claude Code PreToolUse hook: block subagent dispatches that look like code work but omit the Memory Palace orientation block.

Only Agent calls whose `subagent_type` is unset or in `GATED_SUBAGENT_TYPES` are checked, and the
literal `# skip-mempalace-orientation` opts out. Install with `bash scripts/install_claude_code.sh`;
any parse error passes the call through.
"""

from __future__ import annotations

import json
import re
import sys

GATED_SUBAGENT_TYPES = {"Explore", "general-purpose", "claude"}

CODE_TASK_KEYWORDS = {
    "code",
    "file",
    "function",
    "class",
    "endpoint",
    "component",
    "repo",
    "repository",
    "bug",
    "fix",
    "refactor",
    "test",
    "debug",
    "implement",
    "investigate",
    "trace",
}

PATH_LIKE_RE = re.compile(r"\b(?:\w+/)+\w+\.(?:ts|tsx|js|jsx|py|java|go|rs|md|yaml|yml|json|sh)\b")

ORIENTATION_MARKER = "Memory Palace orientation"

OPT_OUT_TOKEN = "# skip-mempalace-orientation"

BLOCK_REASON = (
    "Subagent prompt is missing the Memory Palace orientation block. "
    "Prepend the contents of ~/.claude/snippets/mempalace-orientation.md "
    "(with {{wing}} and {{drawer_count}} filled in) before dispatching. "
    "If this subagent intentionally does not need mempalace, add the literal "
    "token '# skip-mempalace-orientation' anywhere in the prompt to override."
)


def looks_like_code_task(prompt: str) -> bool:
    """Heuristic: does this prompt mention code work?

    Uses word-boundary keyword matching (case-insensitive) plus a path-like
    token check. False positives are tolerable — the cost of a false-positive
    block is one annotation; the cost of a false negative is a 3rd recurrence.
    """
    if PATH_LIKE_RE.search(prompt):
        return True
    lowered = prompt.lower()
    for kw in CODE_TASK_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            return True
    return False


def has_orientation(prompt: str) -> bool:
    """True if the prompt contains the literal orientation marker."""
    return ORIENTATION_MARKER in prompt


def should_block(payload: dict) -> bool:
    """Top-level decision — see module docstring for the rules."""
    if payload.get("hook_event_name") != "PreToolUse":
        return False
    if payload.get("tool_name") != "Agent":
        return False

    tool_input = payload.get("tool_input") or {}
    subagent_type = tool_input.get("subagent_type")
    if subagent_type is not None and subagent_type not in GATED_SUBAGENT_TYPES:
        return False

    prompt = tool_input.get("prompt") or ""
    if OPT_OUT_TOKEN in prompt:
        return False
    if not looks_like_code_task(prompt):
        return False
    if has_orientation(prompt):
        return False

    return True


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if should_block(payload):
        print(json.dumps({"decision": "block", "reason": BLOCK_REASON}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
