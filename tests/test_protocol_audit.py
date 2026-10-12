"""Tests for `mems doctor --protocol` — the Hard Rule #1 compliance measurement.

The audit and the live gate must never disagree about what counts as a
violation, so `protocol_audit` imports its classifier from the hook module.
`test_audit_shares_classifier_with_gate` is the guard on that.
"""

from __future__ import annotations

import argparse
import json

import pytest

from mems_cli import protocol_audit
from mems_cli.commands import palace_ops


def _tool_use(name: str, tool_input: dict | None = None) -> str:
    return json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t", "name": name, "input": tool_input or {}}
                ],
            }
        }
    )


def _session(projects_dir, project: str, calls: list[tuple[str, dict]]):
    directory = projects_dir / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"session-{len(list(directory.iterdir()))}.jsonl"
    path.write_text("\n".join(_tool_use(n, i) for n, i in calls) + "\n")
    return path


def test_run_of_three_is_a_violation(tmp_path):
    """Hard Rule #1's own bright line: 3+ calls with no mempalace between them."""
    _session(tmp_path, "repo-a", [("Grep", {}), ("Read", {}), ("Grep", {})])
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["sessions"] == 1
    assert data["batches"] == 1
    assert data["violations"] == 1
    assert data["violation_rate"] == 1.0


def test_run_of_two_is_a_batch_but_not_a_violation(tmp_path):
    """A pair is judgeable but under the line — it counts in the denominator only."""
    _session(tmp_path, "repo-a", [("Grep", {}), ("Read", {})])
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["batches"] == 1
    assert data["violations"] == 0
    assert data["violation_rate"] == 0.0


def test_search_does_not_license_an_unbounded_run(tmp_path):
    """One search must NOT excuse the 60 greps that follow it.

    Runs are delimited by mempalace calls, so "preceded by a search" is true for
    almost every run and cannot be the test. Length is.
    """
    calls = [("mcp__mempalace__mempalace_search", {})] + [("Grep", {})] * 30
    _session(tmp_path, "repo-a", calls)
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["violations"] == 1
    assert data["longest_run"] == 30


def test_single_call_is_not_a_batch(tmp_path):
    """Hard Rule #1 applies to batches of 2+; a lone call is not judgeable.

    It must not appear in the denominator either — counting compliant-by-default
    single calls would dilute the violation rate toward zero.
    """
    _session(tmp_path, "repo-a", [("Grep", {})])
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["batches"] == 0
    assert data["violations"] == 0
    assert data["fs_calls"] == 1


def test_mempalace_call_splits_runs(tmp_path):
    """Only a palace search ends a run. Other mempalace tools do not."""
    _session(
        tmp_path,
        "repo-a",
        [
            ("Grep", {}),
            ("mcp__mempalace__mempalace_list_rooms", {}),
            ("Read", {}),
            ("Grep", {}),
            ("mcp__mempalace__mempalace_search", {}),
            ("Grep", {}),
            ("Read", {}),
        ],
    )
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["batches"] == 2
    assert data["violations"] == 1
    assert data["longest_run"] == 3
    assert data["mem_calls"] == 1


def test_non_discovery_bash_excluded(tmp_path):
    """`git commit` and `pytest` are not discovery and must not inflate the count."""
    _session(
        tmp_path,
        "repo-a",
        [
            ("Bash", {"command": "git commit -m x"}),
            ("Bash", {"command": "pytest tests/"}),
            ("Bash", {"command": "git log --oneline | head"}),
        ],
    )
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["fs_calls"] == 0
    assert data["batches"] == 0


def test_discovery_bash_counted(tmp_path):
    _session(
        tmp_path,
        "repo-a",
        [
            ("Bash", {"command": "grep -rn foo src"}),
            ("Bash", {"command": "sed -n '1,30p' a.ts"}),
        ],
    )
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["fs_calls"] == 2
    assert data["batches"] == 1


def test_longest_run_reported(tmp_path):
    _session(tmp_path, "repo-a", [("Grep", {})] * 7)
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["longest_run"] == 7


def test_multiple_sessions_aggregate(tmp_path):
    _session(tmp_path, "repo-a", [("Grep", {}), ("Read", {}), ("Grep", {})])
    _session(tmp_path, "repo-b", [("Grep", {}), ("Read", {})])
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["sessions"] == 2
    assert data["batches"] == 2
    assert data["violations"] == 1
    assert data["violation_rate"] == pytest.approx(0.5)


def test_gate_triggers_match_gate_cadence(tmp_path):
    """A run of 10 fires the gate at 3, 6, 9 — three reminders."""
    _session(tmp_path, "repo-a", [("Grep", {})] * 10)
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["gate_triggers"] == 3


def test_empty_projects_dir(tmp_path):
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["sessions"] == 0
    assert data["violation_rate"] == 0.0
    assert "no filesystem batches" in protocol_audit.format_report(data)


def test_missing_projects_dir_does_not_raise(tmp_path):
    data = protocol_audit.audit(projects_dir=tmp_path / "nope")
    assert data["sessions"] == 0


def test_malformed_transcript_is_skipped(tmp_path):
    directory = tmp_path / "repo-a"
    directory.mkdir()
    (directory / "bad.jsonl").write_text("not json\n{also not\n")
    data = protocol_audit.audit(projects_dir=tmp_path)
    assert data["sessions"] == 0


def test_audit_shares_classifier_with_gate():
    """The audit must classify exactly as the live hook does.

    If these ever diverge, `mems doctor --protocol` would report a compliance
    number for rules the gate isn't actually enforcing.
    """
    gate = protocol_audit._load_gate()
    cases = [
        ("mcp__mempalace__mempalace_search", {}, "MEM"),
        ("Grep", {}, "FS"),
        ("Bash", {"command": "grep -rn x ."}, "FS"),
        ("Bash", {"command": "git push"}, "OTHER"),
        ("Edit", {}, "OTHER"),
    ]
    for name, tool_input, expected in cases:
        assert gate.classify_tool(name, tool_input) == expected


def test_format_report_leads_with_the_rate(tmp_path):
    _session(tmp_path, "repo-a", [("Grep", {}), ("Read", {}), ("Grep", {})])
    report = protocol_audit.format_report(protocol_audit.audit(projects_dir=tmp_path))
    assert "violations" in report
    assert "100%" in report
    assert "compliance: 0%" in report


def test_gate_installed_detects_hook(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash|Grep|Glob|Read",
                            "hooks": [{"command": "/x/pretooluse_fs_gate.py"}],
                        }
                    ]
                }
            }
        )
    )
    assert protocol_audit.gate_installed(settings)


def test_gate_installed_false_when_absent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": []}}))
    assert not protocol_audit.gate_installed(settings)


def test_gate_installed_false_on_missing_file(tmp_path):
    assert not protocol_audit.gate_installed(tmp_path / "nope.json")


def test_doctor_protocol_returns_ok_exit_code(tmp_path, monkeypatch, capsys):
    """`mems doctor --protocol` must exit 0 and not require --palace-path."""
    monkeypatch.setattr(protocol_audit, "DEFAULT_PROJECTS_DIR", tmp_path)
    args = argparse.Namespace(
        protocol=True, days=30, as_json=False, palace_path=None
    )
    assert palace_ops.cmd_doctor(args) == palace_ops.EXIT_OK
    assert "Protocol audit" in capsys.readouterr().out


def test_doctor_without_palace_path_errors(capsys):
    args = argparse.Namespace(protocol=False, palace_path=None)
    assert palace_ops.cmd_doctor(args) == palace_ops.EXIT_USER_ERROR
    assert "--palace-path is required" in capsys.readouterr().err
