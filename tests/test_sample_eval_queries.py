"""Tests for scripts/sample_eval_queries.py against fixture transcripts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sample_eval_queries.py"
spec = importlib.util.spec_from_file_location("sample_eval_queries", SCRIPT)
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)


def _line(name: str, tool_input: dict) -> str:
    block = {"type": "tool_use", "id": "t", "name": name, "input": tool_input}
    return json.dumps({"message": {"role": "assistant", "content": [block]}, "cwd": "/secret"})


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _search(query: str, wing: str | None, name: str = "mcp__mempalace__mempalace_search") -> str:
    args = {"query": query}
    if wing:
        args["wing"] = wing
    return _line(name, args)


def test_samples_counted_deduped_and_sorted_by_frequency(tmp_path):
    _write(
        tmp_path / "proj" / "s1.jsonl",
        [_search("rare", "memory"), _search("common", "memory"), _search("common", "memory")],
    )
    result = sampler.sample(tmp_path, per_wing=30)
    assert result == {"memory": [{"query": "common", "count": 2}, {"query": "rare", "count": 1}]}


def test_subagent_transcripts_are_included(tmp_path):
    _write(tmp_path / "proj" / "s1.jsonl", [_search("a", "memory")])
    _write(tmp_path / "proj" / "sess" / "subagents" / "agent-1.jsonl", [_search("a", "memory")])
    assert sampler.sample(tmp_path, per_wing=30)["memory"] == [{"query": "a", "count": 2}]


def test_per_wing_cap_applies(tmp_path):
    _write(tmp_path / "proj" / "s1.jsonl", [_search(f"q{i}", "memory") for i in range(5)])
    assert len(sampler.sample(tmp_path, per_wing=3)["memory"]) == 3


def test_only_search_calls_with_a_wing_and_query_are_kept(tmp_path):
    _write(
        tmp_path / "proj" / "s1.jsonl",
        [
            _search("no wing", None),
            _search("all wings", "memory", name="mcp__mempalace__mempalace_search_all"),
            _line("Read", {"query": "x", "wing": "memory"}),
            _line("mempalace_search", {"wing": "memory"}),
            _search("kept", "memory", name="mempalace_search"),
        ],
    )
    assert sampler.sample(tmp_path, per_wing=30) == {"memory": [{"query": "kept", "count": 1}]}


def test_output_holds_only_queries_and_wings(tmp_path):
    _write(tmp_path / "proj" / "s1.jsonl", [_search("q", "memory")])
    text = json.dumps(sampler.sample(tmp_path, per_wing=30))
    assert "/secret" not in text
    assert "proj" not in text


def test_main_writes_output_file(tmp_path):
    _write(tmp_path / "proj" / "s1.jsonl", [_search("q", "memory")])
    out = tmp_path / "out.json"
    code = sampler.main(["--projects-dir", str(tmp_path), "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text()) == {"memory": [{"query": "q", "count": 1}]}
