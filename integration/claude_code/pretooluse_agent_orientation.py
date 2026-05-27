#!/usr/bin/env python3
"""Claude Code PreToolUse hook: enforce Memory Palace orientation in subagent prompts.

Reads a hook payload from stdin (per the Claude Code hook contract), inspects
Agent tool calls, and blocks dispatches whose prompt looks like a code task but
omits the Memory Palace orientation block.

Install via `mems setup install-hooks`. Tested by tests/test_pretooluse_agent_orientation.py.

Hook contract (Claude Code):
    Input (stdin, JSON):
      {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": {
          "prompt": "...",
          "subagent_type": "Explore" | "general-purpose" | ...
        }
      }
    Output (stdout, JSON or empty):
      block:    {"decision": "block", "reason": "..."}
      approve:  no body, exit 0

A non-Agent event always passes (we only gate Agent dispatches).
"""

from __future__ import annotations

import json
import re
import sys

# Subagent types that have mempalace MCP access. Only these benefit from being
# blocked — feature-dev:* etc. cannot call mempalace anyway, so blocking them
# would be pointless friction.
GATED_SUBAGENT_TYPES = {"Explore", "general-purpose"}

# Keywords that signal a code-investigation or implementation task.
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

# Path-like token: at least one slash-separated segment, ending with a known
# code/config extension. Matches "src/foo.py", "app/components/Bar.tsx", etc.
PATH_LIKE_RE = re.compile(r"\b(?:\w+/)+\w+\.(?:ts|tsx|js|jsx|py|java|go|rs|md|yaml|yml|json|sh)\b")

# Marker string that indicates the orientation block IS present.
#
# We deliberately do NOT accept bare mentions of `mempalace_*` tool names as
# evidence of orientation. The orientation block conveys the per-batch rule,
# the editing-read exemption, and the feature-dev tool-allowlist gotcha; a
# bare token mention conveys none of those. Accepting tokens was a
# false-negative surface (prompt hints like "use mempalace_search if you
# want" passed the gate). Strict marker check + the explicit opt-out below
# is more honest. (See plan 2026-05-06, Phase 1.4.)
ORIENTATION_MARKER = "Memory Palace orientation"

# Explicit opt-out — caller deliberately marks this subagent as non-code work.
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
        # If we can't parse the payload, don't block — fail open so the hook
        # never bricks the harness when Claude Code changes the schema.
        return 0

    if should_block(payload):
        print(json.dumps({"decision": "block", "reason": BLOCK_REASON}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
