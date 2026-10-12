"""Tests for the Claude Code Agent-orientation PreToolUse hook.

Each case feeds a JSON payload to the hook script via stdin and asserts
either a block decision (with reason) or a clean approve (empty stdout).
The 9-case matrix is the same one in the plan file at
~/.claude/plans/share-this-password-with-memoized-mitten.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "integration"
    / "claude_code"
    / "pretooluse_agent_orientation.py"
)


def _run_hook(payload: dict) -> tuple[str, int]:
    """Invoke the hook with a JSON payload on stdin. Returns (stdout, exit_code)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout, result.returncode


def _agent_payload(prompt: str, subagent_type: str | None = "Explore") -> dict:
    tool_input: dict = {"prompt": prompt}
    if subagent_type is not None:
        tool_input["subagent_type"] = subagent_type
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
    }


def _is_blocked(stdout: str) -> bool:
    if not stdout.strip():
        return False
    decision = json.loads(stdout)
    return decision.get("decision") == "block"


def test_case_1_explore_code_task_no_orientation_blocks():
    """Code keywords + path-like file + Explore + no orientation → block."""
    out, _ = _run_hook(_agent_payload("find ContactForm.tsx and trace its callers"))
    assert _is_blocked(out)
    assert "Memory Palace" in out


def test_case_2_explore_with_orientation_passes():
    """Marker present → pass even with code keywords."""
    prompt = (
        "Memory Palace orientation. Wing: edens-zac (2270 drawers). Use mempalace_search "
        "before any batch.\n\nfind ContactForm.tsx and trace its callers."
    )
    out, _ = _run_hook(_agent_payload(prompt))
    assert not _is_blocked(out)


def test_case_3_explore_non_code_task_passes():
    """No code keywords → pass."""
    out, _ = _run_hook(_agent_payload("summarize this poem for me"))
    assert not _is_blocked(out)


def test_case_4_general_purpose_code_task_blocks():
    """general-purpose is in scope, code keywords trigger block."""
    out, _ = _run_hook(
        _agent_payload(
            "investigate why the saveGalleryAccess endpoint propagation skips children",
            subagent_type="general-purpose",
        )
    )
    assert _is_blocked(out)


def test_case_5_feature_dev_code_explorer_passes():
    """feature-dev:* lacks mempalace MCP — blocking is pointless friction, so pass."""
    out, _ = _run_hook(
        _agent_payload("find ContactForm.tsx", subagent_type="feature-dev:code-explorer")
    )
    assert not _is_blocked(out)


def test_case_6_explicit_opt_out_passes():
    """The escape-hatch token short-circuits the block."""
    out, _ = _run_hook(_agent_payload("find ContactForm.tsx\n# skip-mempalace-orientation"))
    assert not _is_blocked(out)


def test_case_7_unset_subagent_type_with_path_blocks():
    """Unset subagent_type + path-like token → still gate (default-explore semantics)."""
    out, _ = _run_hook(_agent_payload("trace src/services/foo.py", subagent_type=None))
    assert _is_blocked(out)


def test_case_8_keyword_only_no_path_blocks():
    """Code keyword without path token still trips the gate."""
    out, _ = _run_hook(_agent_payload("fix the bug in CollectionService.java"))
    assert _is_blocked(out)


def test_case_9_bare_mempalace_token_mention_blocks():
    """Bare mention of a mempalace_* token is NOT evidence of orientation — block.

    The orientation block conveys the per-batch rule, the editing-read
    exemption, and the feature-dev tool-allowlist gotcha. A prompt that
    merely says "use mempalace_search" conveys none of those, so the hook
    must still block. Accepting bare token mentions was a false-negative
    surface fixed in Phase 1.4 of the 2026-05-06 plan. The escape hatch
    `# skip-mempalace-orientation` remains available for legitimate
    "just one quick search" cases (test_case_6).
    """
    out, _ = _run_hook(
        _agent_payload("use mempalace_search to map the repo and find the entrypoint")
    )
    assert _is_blocked(out)


def test_paraphrased_orientation_label_blocks():
    """The hook checks the literal marker, not paraphrases.

    A prompt that says "Memory Palace guidance" or "orientation to the
    palace" without the literal phrase 'Memory Palace orientation' must
    still block. This documents the intentional strictness — paraphrases
    fail open elsewhere; here they fail closed.
    """
    prompt = (
        "Here's some Memory Palace guidance for you: be sure to call "
        "mempalace_search and check the wing taxonomy.\n\n"
        "fix the bug in src/foo.py"
    )
    out, _ = _run_hook(_agent_payload(prompt))
    assert _is_blocked(out)


def test_non_agent_tool_passes_through():
    """Hook only gates Agent. A Bash event must pass untouched."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "find . -name '*.py'"},
    }
    out, code = _run_hook(payload)
    assert code == 0
    assert not _is_blocked(out)


def test_empty_stdin_is_no_op():
    """If stdin is empty, exit clean — never block on a parse failure."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_malformed_json_fails_open():
    """Garbage stdin → exit 0 with no decision (fail open, never brick the harness)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_block_reason_mentions_snippet_path():
    """The block message must point the operator at the snippet they need to paste."""
    out, _ = _run_hook(_agent_payload("fix the auth bug in src/auth.py"))
    assert _is_blocked(out)
    decision = json.loads(out)
    assert "mempalace-orientation.md" in decision["reason"]
    assert "skip-mempalace-orientation" in decision["reason"]


@pytest.mark.parametrize(
    "subagent_type",
    ["code-simplifier", "pr-review-toolkit:code-reviewer", "Plan", "statusline-setup"],
)
def test_other_subagent_types_pass(subagent_type: str):
    """Any subagent type outside the gated set passes regardless of prompt."""
    out, _ = _run_hook(_agent_payload("fix the bug in src/foo.py", subagent_type=subagent_type))
    assert not _is_blocked(out)


def test_claude_subagent_type_is_gated():
    out, _ = _run_hook(_agent_payload("fix the bug in src/foo.py", subagent_type="claude"))
    assert _is_blocked(out)
