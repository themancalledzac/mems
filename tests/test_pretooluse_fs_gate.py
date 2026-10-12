"""Tests for the filesystem-discovery PreToolUse gate.

The gate reads the session transcript, counts filesystem calls since the last
palace search, and reminds the model once the run hits a multiple of the
threshold. Most tests drive it end-to-end through stdin and stdout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / "integration" / "claude_code" / "pretooluse_fs_gate.py"

EDENS_ROOT = "/work/edens.zac"
MEMORY_ROOT = "/work/Memory"
OUTSIDE = "/nonexistent-fs-gate-root/scratch"


def _load_hook():
    spec = importlib.util.spec_from_file_location("pretooluse_fs_gate", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_hook()


def _tool_use(name: str, tool_input: dict | None = None) -> str:
    """One transcript line containing a single tool_use block."""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_test",
                        "name": name,
                        "input": tool_input or {},
                    }
                ],
            },
        }
    )


def _write_transcript(tmp_path: Path, calls: list[tuple[str, dict]], name: str = "transcript.jsonl") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_tool_use(n, i) for n, i in calls) + "\n")
    return path


def _payload(
    transcript: Path,
    tool_name: str = "Grep",
    tool_input: dict | None = None,
    cwd: str = EDENS_ROOT,
    **extra,
) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "test-session",
        "transcript_path": str(transcript),
        "cwd": cwd,
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"pattern": "foo"},
        **extra,
    }


@pytest.fixture(scope="module")
def config_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("cfg")
    (directory / "repos.json").write_text(
        json.dumps(
            {
                "edens-zac": {"path": EDENS_ROOT, "wing": "edens-zac"},
                "memory": {"path": MEMORY_ROOT, "wing": "memory"},
            }
        )
    )
    return directory


@pytest.fixture(autouse=True)
def _hook_env(config_dir, monkeypatch):
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(config_dir))
    for name in (
        "MEMPALACE_FS_GATE_MODE",
        "MEMPALACE_FS_GATE_THRESHOLD",
        "MEMPALACE_FS_GATE_HOLDOUT",
        "MEMS_DIGEST",
    ):
        monkeypatch.delenv(name, raising=False)


def _run_hook(payload: dict, env_overrides: dict | None = None) -> tuple[str, int]:
    env = dict(os.environ)
    env.update(env_overrides or {})
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result.stdout, result.returncode


def _reminder_of(stdout: str) -> str | None:
    if not stdout.strip():
        return None
    payload = json.loads(stdout)
    hso = payload.get("hookSpecificOutput") or {}
    return hso.get("additionalContext") or hso.get("permissionDecisionReason")


def test_screenshot_command_is_discovery():
    """Regression: the exact compound command that slipped through on 2026-08-22.

    Leading `cd` and `echo` segments must not mask the `sed`/`grep` that follow.
    """
    command = (
        'cd /Users/themancalledzac/Code/edens.zac\n'
        'echo "=== GalleryFilter.ts:1-30 ==="; sed -n \'1,30p\' app/types/GalleryFilter.ts\n'
        'echo "=== any barrel-index test? ==="; grep -rn "components/Content" tests | head\n'
    )
    assert gate.is_discovery_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "grep -rn 'foo' src",
        "rg --files-with-matches TODO",
        "find . -name '*.py'",
        "ls -la app/components",
        "cat app/types/GalleryFilter.ts",
        "sed -n '1,30p' file.ts",
        "tree -L 2",
        "wc -l src/*.py",
        "cd /repo && grep -rn needle .",
        "FOO=bar grep needle file",
        "sudo find / -name conf",
    ],
)
def test_discovery_commands_detected(command: str):
    assert gate.is_discovery_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'fix'",
        "git log --oneline | head -20",
        "pytest tests/ -v",
        "npm run build",
        "docker compose up -d",
        "echo hello",
        "mkdir -p foo/bar",
        "python3 -c 'import sys'",
        "",
    ],
)
def test_non_discovery_commands_ignored(command: str):
    """`head` as a pager must not make `git log` look like discovery."""
    assert not gate.is_discovery_command(command)


def test_classify_tool_matrix():
    assert gate.classify_tool("mcp__mempalace__mempalace_search", {}) == "MEM"
    assert gate.classify_tool("mcp__mempalace__mempalace_search_all", {}) == "MEM"
    assert gate.classify_tool("mcp__mempalace__mempalace_user_search", {}) == "MEM"
    assert gate.classify_tool("mcp__mempalace__mempalace_list_rooms", {}) == "OTHER"
    assert gate.classify_tool("Grep", {}) == "FS"
    assert gate.classify_tool("Read", {}) == "FS"
    assert gate.classify_tool("Bash", {"command": "grep -rn foo ."}) == "FS"
    assert gate.classify_tool("Bash", {"command": "git push"}) == "OTHER"
    assert gate.classify_tool("Edit", {}) == "OTHER"
    assert gate.classify_tool("", {}) == "OTHER"


def test_run_counter_resets_on_mempalace(tmp_path: Path):
    transcript = _write_transcript(
        tmp_path,
        [
            ("Grep", {}),
            ("Read", {}),
            ("mcp__mempalace__mempalace_search", {}),
            ("Grep", {}),
        ],
    )
    lines = gate.read_transcript_tail(transcript)
    assert gate.uncovered_run_length(lines) == 1


def test_run_counter_ignores_non_fs_tools(tmp_path: Path):
    transcript = _write_transcript(
        tmp_path,
        [("Grep", {}), ("Edit", {}), ("Bash", {"command": "git status"}), ("Read", {})],
    )
    lines = gate.read_transcript_tail(transcript)
    assert gate.uncovered_run_length(lines) == 2


def test_run_counter_survives_malformed_lines(tmp_path: Path):
    path = tmp_path / "transcript.jsonl"
    path.write_text(_tool_use("Grep") + "\nnot json at all\n" + _tool_use("Read") + "\n")
    lines = gate.read_transcript_tail(path)
    assert gate.uncovered_run_length(lines) == 2


def test_warns_at_threshold(tmp_path: Path):
    """Two prior FS calls + the one being gated = 3 = threshold → remind."""
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, code = _run_hook(_payload(transcript))
    assert code == 0
    reminder = _reminder_of(out)
    assert reminder is not None
    assert "MEMORY PALACE GATE" in reminder
    assert "mempalace_search" in reminder


def test_silent_below_threshold(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {})])
    out, _ = _run_hook(_payload(transcript))
    assert _reminder_of(out) is None


def test_warn_cadence_is_every_multiple(tmp_path: Path):
    """Stateless cadence: fire at 3, 6, 9 — stay quiet at 4, 5, 7, 8."""
    fired = []
    for prior in range(0, 9):
        transcript = _write_transcript(tmp_path, [("Grep", {})] * prior)
        out, _ = _run_hook(_payload(transcript))
        if _reminder_of(out) is not None:
            fired.append(prior + 1)
    assert fired == [3, 6, 9]


def test_mempalace_call_silences_the_gate(tmp_path: Path):
    """A search resets the run, so the next call is quiet even after a long batch."""
    calls = [("Grep", {})] * 10 + [("mcp__mempalace__mempalace_search", {})]
    transcript = _write_transcript(tmp_path, calls)
    out, _ = _run_hook(_payload(transcript))
    assert _reminder_of(out) is None




def test_reminder_mentions_editing_read_exemption(tmp_path: Path):
    """False positives are tolerable only if the model is told how to judge them."""
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(_payload(transcript))
    assert "reads-for-editing" in _reminder_of(out)


def test_block_mode_denies(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, code = _run_hook(_payload(transcript), {"MEMPALACE_FS_GATE_MODE": "block"})
    assert code == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "MEMORY PALACE GATE" in decision["permissionDecisionReason"]


def test_off_mode_is_silent(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(_payload(transcript), {"MEMPALACE_FS_GATE_MODE": "off"})
    assert _reminder_of(out) is None


def test_custom_threshold(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {})])
    out, _ = _run_hook(_payload(transcript), {"MEMPALACE_FS_GATE_THRESHOLD": "2"})
    assert _reminder_of(out) is not None


def test_warn_mode_emits_only_additional_context(tmp_path: Path):
    """Warn mode must not deny, and must not emit unconfirmed top-level keys."""
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(_payload(transcript))
    payload = json.loads(out)
    assert set(payload.keys()) == {"hookSpecificOutput"}
    assert "permissionDecision" not in payload["hookSpecificOutput"]


def test_non_pretooluse_event_is_silent(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    payload = _payload(transcript)
    payload["hook_event_name"] = "PostToolUse"
    out, code = _run_hook(payload)
    assert code == 0
    assert not out.strip()


def test_non_fs_tool_is_silent(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(_payload(transcript, tool_name="Edit", tool_input={"file_path": "a.py"}))
    assert not out.strip()


def test_non_discovery_bash_is_silent(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(
        _payload(transcript, tool_name="Bash", tool_input={"command": "git commit -m x"})
    )
    assert not out.strip()


def test_missing_transcript_fails_open(tmp_path: Path):
    payload = _payload(tmp_path / "does-not-exist.jsonl")
    out, code = _run_hook(payload)
    assert code == 0
    assert not out.strip()


def test_empty_stdin_is_no_op():
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)], input="", capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_malformed_json_fails_open():
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert not result.stdout.strip()


def test_tail_window_truncates_safely(tmp_path: Path):
    """A tiny tail window must still produce a valid (if shorter) count, never crash."""
    transcript = _write_transcript(tmp_path, [("Grep", {})] * 200)
    lines = gate.read_transcript_tail(transcript, tail_bytes=2048)
    run = gate.uncovered_run_length(lines)
    assert 0 < run < 200


def test_silent_when_target_outside_any_wing(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, code = _run_hook(_payload(transcript, cwd=OUTSIDE))
    assert code == 0
    assert _reminder_of(out) is None


def test_fires_when_one_of_several_targets_is_in_wing(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    command = f"grep -n foo {OUTSIDE}/a.txt {MEMORY_ROOT}/src/b.py"
    out, _ = _run_hook(
        _payload(transcript, tool_name="Bash", tool_input={"command": command}, cwd=OUTSIDE)
    )
    assert 'wing="memory"' in _reminder_of(out)


def test_subagent_payload_uses_subagent_transcript(tmp_path: Path):
    parent = _write_transcript(tmp_path, [("Grep", {})] * 5)
    _write_transcript(
        tmp_path,
        [("Grep", {}), ("Read", {})],
        name="transcript/subagents/agent-abc123.jsonl",
    )
    out, _ = _run_hook(_payload(parent, agent_id="abc123", agent_type="general-purpose"))
    assert _reminder_of(out) is not None

    _write_transcript(
        tmp_path, [("Grep", {})], name="transcript/subagents/agent-quiet.jsonl"
    )
    out, _ = _run_hook(_payload(parent, agent_id="quiet", agent_type="general-purpose"))
    assert _reminder_of(out) is None


def test_subagent_payload_without_transcript_is_silent(tmp_path: Path):
    parent = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, code = _run_hook(_payload(parent, agent_id="missing", agent_type="Explore"))
    assert code == 0
    assert _reminder_of(out) is None


def test_only_search_tools_reset_run(tmp_path: Path):
    not_reset = _write_transcript(
        tmp_path,
        [("Grep", {}), ("mcp__mempalace__mempalace_list_rooms", {}), ("Read", {})],
        name="a.jsonl",
    )
    out, _ = _run_hook(_payload(not_reset))
    assert _reminder_of(out) is not None

    for search in (
        "mcp__mempalace__mempalace_search",
        "mcp__mempalace__mempalace_search_all",
        "mcp__mempalace__mempalace_user_search",
    ):
        reset = _write_transcript(
            tmp_path, [("Grep", {}), ("Grep", {}), (search, {}), ("Read", {})], name="b.jsonl"
        )
        out, _ = _run_hook(_payload(reset))
        assert _reminder_of(out) is None, search


def test_read_of_already_edited_file_not_counted(tmp_path: Path):
    edited = f"{EDENS_ROOT}/src/a.py"
    transcript = _write_transcript(
        tmp_path,
        [("Edit", {"file_path": edited}), ("Grep", {}), ("Read", {"file_path": edited})],
        name="a.jsonl",
    )
    out, _ = _run_hook(_payload(transcript))
    assert _reminder_of(out) is None

    transcript = _write_transcript(
        tmp_path,
        [("Write", {"file_path": edited}), ("Grep", {}), ("Grep", {})],
        name="b.jsonl",
    )
    out, _ = _run_hook(_payload(transcript, tool_name="Read", tool_input={"file_path": edited}))
    assert _reminder_of(out) is None


def _held_out(session_id: str, fraction: float) -> bool:
    return int(hashlib.sha1(session_id.encode()).hexdigest()[:8], 16) % 100 < fraction * 100


def test_holdout_session_is_silent_and_deterministic(tmp_path: Path):
    ids = [f"session-{n}" for n in range(50)]
    held = next(i for i in ids if _held_out(i, 0.5))
    kept = next(i for i in ids if not _held_out(i, 0.5))
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    env = {"MEMPALACE_FS_GATE_HOLDOUT": "0.5"}
    for _ in range(2):
        out, _ = _run_hook({**_payload(transcript), "session_id": held}, env)
        assert _reminder_of(out) is None
        out, _ = _run_hook({**_payload(transcript), "session_id": kept}, env)
        assert _reminder_of(out) is not None


def test_reminder_names_wing_from_target_not_cwd(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(
        _payload(
            transcript,
            tool_name="Read",
            tool_input={"file_path": f"{MEMORY_ROOT}/README.md"},
            cwd=EDENS_ROOT,
        )
    )
    reminder = _reminder_of(out)
    assert 'wing="memory"' in reminder
    assert "edens-zac" not in reminder


def test_reminder_does_not_claim_indexed(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, _ = _run_hook(_payload(transcript))
    reminder = _reminder_of(out)
    assert "indexed" not in reminder
    assert len(reminder) <= 320


def test_digest_env_silences_gate(tmp_path: Path):
    transcript = _write_transcript(tmp_path, [("Grep", {}), ("Read", {})])
    out, code = _run_hook(_payload(transcript), {"MEMS_DIGEST": "1"})
    assert code == 0
    assert _reminder_of(out) is None
