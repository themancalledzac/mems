"""Measure how often filesystem discovery ran without a palace search (`mems doctor --protocol`).

Classification is imported from `integration/claude_code/pretooluse_fs_gate.py`, so the audit
counts what the gate enforces. A run is the discovery calls between two palace searches
(`mempalace_search`, `mempalace_search_all`, `mempalace_user_search`); other mempalace tools
and Reads of files already edited do not count either way.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

_GATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "integration"
    / "claude_code"
    / "pretooluse_fs_gate.py"
)

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"

BATCH_SIZE = 2
VIOLATION_RUN_LENGTH = 3


def _load_gate():
    """Import the hook module by path — one source of truth for classification."""
    spec = importlib.util.spec_from_file_location("pretooluse_fs_gate", _GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load gate module at {_GATE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class SessionStat:
    """Filesystem runs in one session, each ended by a palace search.

    What matters is how long a run got before the next search, since one search
    does not license 60 greps.
    """

    project: str
    path: Path
    fs_calls: int = 0
    mem_calls: int = 0
    runs: list[int] = field(default_factory=list)

    @property
    def batches(self) -> int:
        """Runs big enough for Hard Rule #1 to have an opinion about."""
        return sum(1 for size in self.runs if size >= BATCH_SIZE)

    @property
    def violations(self) -> int:
        return sum(1 for size in self.runs if size >= VIOLATION_RUN_LENGTH)

    @property
    def gate_triggers(self) -> int:
        """How many reminders the live gate would have emitted."""
        return sum(size // VIOLATION_RUN_LENGTH for size in self.runs)

    @property
    def longest_run(self) -> int:
        return max(self.runs, default=0)


def _iter_tool_calls(path: Path):
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
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


def analyze_session(path: Path, gate) -> SessionStat | None:
    """Walk one transcript and record its filesystem runs.

    Only a palace search ends a run, matching the gate's `uncovered_run_length`.
    """
    stat = SessionStat(project=path.parent.name, path=path)
    run = 0
    try:
        for kind in gate.classify_calls(_iter_tool_calls(path)):
            if kind == "MEM":
                stat.mem_calls += 1
                if run:
                    stat.runs.append(run)
                run = 0
            elif kind == "FS":
                stat.fs_calls += 1
                run += 1
    except OSError:
        return None
    if run:
        stat.runs.append(run)
    return stat if (stat.fs_calls or stat.mem_calls) else None


def audit(projects_dir: Path | None = None, days: int = 30) -> dict:
    """Aggregate protocol compliance across recent sessions."""
    gate = _load_gate()
    root = Path(projects_dir) if projects_dir else DEFAULT_PROJECTS_DIR
    cutoff = time.time() - days * 86400

    sessions: list[SessionStat] = []
    if root.is_dir():
        for path in root.glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            stat = analyze_session(path, gate)
            if stat is not None:
                sessions.append(stat)

    total_batches = sum(s.batches for s in sessions)
    violations = sum(s.violations for s in sessions)
    fs_calls = sum(s.fs_calls for s in sessions)
    mem_calls = sum(s.mem_calls for s in sessions)

    sessions.sort(key=lambda s: -s.fs_calls)
    return {
        "days": days,
        "projects_dir": str(root),
        "sessions": len(sessions),
        "fs_calls": fs_calls,
        "mem_calls": mem_calls,
        "batches": total_batches,
        "violations": violations,
        "gate_triggers": sum(s.gate_triggers for s in sessions),
        "violation_rate": (violations / total_batches) if total_batches else 0.0,
        "longest_run": max((s.longest_run for s in sessions), default=0),
        "worst": [
            {
                "project": s.project,
                "fs_calls": s.fs_calls,
                "mem_calls": s.mem_calls,
                "batches": s.batches,
                "uncovered": s.violations,
                "longest_run": s.longest_run,
            }
            for s in sessions[:10]
        ],
    }


def format_report(data: dict) -> str:
    """Human-readable summary. Leads with the number that matters."""
    rate = data["violation_rate"] * 100
    lines = [
        f"Protocol audit — last {data['days']} days ({data['sessions']} sessions)",
        "",
        f"  discovery filesystem calls : {data['fs_calls']}",
        f"  mempalace calls            : {data['mem_calls']}",
        f"  filesystem batches (2+)    : {data['batches']}",
        f"  violations (runs of 3+)    : {data['violations']}  ({rate:.0f}%)",
        f"  gate reminders it'd emit   : {data['gate_triggers']}",
        f"  longest run, no mempalace  : {data['longest_run']}",
    ]
    if data["worst"]:
        lines += ["", "  worst sessions:", ""]
        lines.append(f"    {'project':<44}{'FS':>6}{'MEM':>6}{'uncov':>7}{'max':>6}")
        for row in data["worst"]:
            lines.append(
                f"    {row['project'][:43]:<44}{row['fs_calls']:>6}"
                f"{row['mem_calls']:>6}{row['uncovered']:>7}{row['longest_run']:>6}"
            )
    if data["batches"] == 0:
        lines += ["", "  no filesystem batches recorded — nothing to judge yet."]
    else:
        lines += ["", f"  compliance: {100 - rate:.0f}% of batches stayed under 3 calls."]
    return "\n".join(lines)


def gate_installed(settings_path: Path | None = None) -> bool:
    """True if the fs-gate hook is registered in Claude Code settings."""
    path = settings_path or (Path.home() / ".claude" / "settings.json")
    try:
        settings = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    for entry in (settings.get("hooks") or {}).get("PreToolUse") or []:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks") or []:
            if "pretooluse_fs_gate" in str(hook.get("command", "")):
                return True
    return False


def gate_mode() -> str:
    return (os.environ.get("MEMPALACE_FS_GATE_MODE") or "warn").strip().lower()
