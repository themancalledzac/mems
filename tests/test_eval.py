"""Tests for the retrieval eval harness: scoring, `mems eval`, the corpus file."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from mems_cli.eval_scoring import (
    aggregate,
    compare,
    normalize_hit,
    score_question,
    served_files,
)
from mems_cli.main import main

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval_corpus.json"


def test_normalize_hit_strips_container_prefix():
    hit = {"source_path": "/repos/Memory/src/sync_engine.py", "text": "body"}
    assert normalize_hit(hit) == ("src/sync_engine.py", "body")


def test_normalize_hit_falls_back_to_metadata_and_document():
    hit = {"metadata": {"source_path": "/repos/edens.zac/a/b.ts"}, "document": "doc"}
    assert normalize_hit(hit) == ("a/b.ts", "doc")


def test_served_files_dedupes_in_first_seen_order():
    hits = [
        {"source_path": "/repos/R/a.py"},
        {"source_path": "/repos/R/b.py"},
        {"source_path": "/repos/R/a.py"},
        {"source_path": "/repos/R/c.py"},
    ]
    assert served_files(hits) == ["a.py", "b.py", "c.py"]


def test_worktree_copy_does_not_match_gold():
    served = ["x/y.py", ".claude/worktrees/w/x/y.py"]
    row = score_question(served, [["x/y.py"]], served)
    assert row["ranks"] == [1]
    row = score_question([".claude/worktrees/w/x/y.py"], [["x/y.py"]], [])
    assert row["ranks"] == [None]
    assert row["hit1"] is False


def test_hit1_true_only_when_top_file_is_gold():
    assert score_question(["g.py", "o.py"], [["g.py"]], [])["hit1"] is True
    assert score_question(["o.py", "g.py"], [["g.py"]], [])["hit1"] is False


def test_recall_at_k_divides_by_min_k_and_groups():
    served = ["a", "b", "c", "d", "e"]
    row = score_question(served, [["a"], ["d"], ["e"], ["zzz"]], [])
    assert row["recall3"] == pytest.approx(1 / 3)
    assert row["recall5"] == pytest.approx(3 / 4)
    row = score_question(["a", "b"], [["a"], ["b"]], [])
    assert row["recall3"] == 1.0


def test_any_of_group_counts_once():
    row = score_question(["copy1", "copy2"], [["copy1", "copy2"]], [])
    assert row["recall3"] == 1.0
    assert row["ranks"] == [1]


def test_reciprocal_rank_zero_when_gold_absent():
    assert score_question(["a"], [["g"]], [])["rr"] == 0.0
    assert score_question(["a", "g"], [["g"]], [])["rr"] == 0.5


def test_chunk_precision_counts_chunks_not_files():
    row = score_question(["g", "o"], [["g"]], ["g", "g", "o", "o"])
    assert row["chunk_precision"] == 0.5
    assert row["file_precision"] == 0.5
    row = score_question(["g", "o"], [["g"]], ["g", "g", "g", "o"])
    assert row["chunk_precision"] == 0.75


def _agg(hit1_flips: int, n: int = 50) -> dict:
    rows = [
        {
            "hit1": i >= hit1_flips,
            "recall3": 1.0,
            "recall5": 1.0,
            "rr": 1.0,
            "file_precision": 1.0,
            "chunk_precision": 1.0,
            "latency_ms": 10.0,
        }
        for i in range(n)
    ]
    return aggregate(rows)


def test_compare_one_flip_passes_two_flips_fail():
    base = _agg(0)
    assert compare(_agg(1), base)["ok"] is True
    result = compare(_agg(2), base)
    assert result["ok"] is False
    assert "hit1" in result["regressions"]


def test_compare_warns_when_p95_doubles():
    base = _agg(0)
    slow = dict(base, p95_ms=base["p95_ms"] * 2.5)
    result = compare(slow, base)
    assert result["ok"] is True
    assert result["warnings"]


def _fake_client_class(responses: dict, calls: list):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def call(self, name, arguments=None):
            calls.append((name, arguments or {}))
            value = responses[name]
            if callable(value):
                value = value(arguments or {})
            return {"structuredContent": value}

    return _Client


def _corpus(tmp_path, questions, wings=None) -> Path:
    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "wings": wings or {"memory": {"repo_dir": "Memory"}},
                "questions": questions,
            }
        )
    )
    return path


def _q(qid, gold, wing="memory", split="dev"):
    return {
        "id": qid,
        "wing": wing,
        "split": split,
        "style": "prose",
        "query": f"query {qid}",
        "gold": gold,
        "basis": "test",
    }


def _hit(path):
    return {"source_path": f"/repos/Memory/{path}", "text": "chunk"}


def _install(monkeypatch, responses, calls, present=lambda *a: True):
    from mems_cli.commands import eval as eval_cmd

    monkeypatch.setattr(eval_cmd, "PalaceClient", _fake_client_class(responses, calls))
    monkeypatch.setattr(eval_cmd, "gold_present", present)
    return eval_cmd


def test_stale_question_excluded_from_means_and_counted(tmp_path, monkeypatch, capsys):
    corpus = _corpus(tmp_path, [_q("m1", ["a.py"]), _q("m2", ["gone.py"])])
    responses = {
        "memory_sync_status": {"wings": {"memory": {"last_commit_sha": "abc"}}},
        "mempalace_search": {"results": [_hit("a.py")]},
    }
    _install(monkeypatch, responses, [], present=lambda repo, sha, path: path != "gone.py")
    out = tmp_path / "run.json"
    code = main(["eval", "--corpus", str(corpus), "--out", str(out), "--json"])
    assert code == 0
    run = json.loads(out.read_text())
    assert run["stale"] == 1
    assert run["n_scored"] == 1
    assert run["hit1"] == 1.0


def test_compare_refuses_on_sha_drift_exit_3(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path, [_q("m1", ["a.py"])])
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(_agg(0), shas={"memory": "old"})))
    responses = {
        "memory_sync_status": {"wings": {"memory": {"last_commit_sha": "new"}}},
        "mempalace_search": {"results": [_hit("a.py")]},
    }
    _install(monkeypatch, responses, [])
    argv = ["eval", "--corpus", str(corpus), "--compare", str(base)]
    assert main(argv) == 3
    assert main(argv + ["--allow-drift"]) in (0, 1)


def test_server_error_exits_2(tmp_path, monkeypatch):
    from mems_cli.palace_client import PalaceClientError

    corpus = _corpus(tmp_path, [_q("m1", ["a.py"])])

    def boom(_args):
        raise PalaceClientError("down")

    _install(monkeypatch, {"memory_sync_status": boom}, [])
    assert main(["eval", "--corpus", str(corpus)]) == 2


def test_user_wing_questions_reported_not_gated(tmp_path, monkeypatch):
    questions = [_q("m1", ["a.py"]), _q("u1", ["user-abc"], wing="user")]
    corpus = _corpus(tmp_path, questions)
    base = tmp_path / "base.json"
    base.write_text(json.dumps(dict(_agg(0), n_scored=1, shas={"memory": "abc"})))
    responses = {
        "memory_sync_status": {"wings": {"memory": {"last_commit_sha": "abc"}}},
        "mempalace_search": {"results": [_hit("a.py")]},
        "mempalace_user_search": {"results": [{"id": "user-zzz", "content": "x"}]},
    }
    calls: list = []
    _install(monkeypatch, responses, calls)
    out = tmp_path / "run.json"
    code = main(["eval", "--corpus", str(corpus), "--compare", str(base), "--out", str(out)])
    assert code == 0
    run = json.loads(out.read_text())
    assert run["n_scored"] == 1
    assert run["user"]["n"] == 1
    assert run["user"]["hit1"] == 0.0
    assert any(name == "mempalace_user_search" for name, _ in calls)


def test_cmd_eval_calls_search_with_extra_args(tmp_path, monkeypatch):
    corpus = _corpus(tmp_path, [_q("m1", ["a.py"])])
    responses = {
        "memory_sync_status": {"wings": {"memory": {"last_commit_sha": "abc"}}},
        "mempalace_search": {"results": [_hit("a.py")]},
    }
    calls: list = []
    _install(monkeypatch, responses, calls)
    code = main(["eval", "--corpus", str(corpus), "--n", "7", "--arg", "candidate_strategy=union"])
    assert code == 0
    search = [c for c in calls if c[0] == "mempalace_search"][0][1]
    assert search["query"] == "query m1"
    assert search["wing"] == "memory"
    assert search["n"] == 7
    assert search["candidate_strategy"] == "union"


def test_holdout_flag_selects_holdout_split(tmp_path, monkeypatch):
    questions = [_q("m1", ["a.py"]), _q("m2", ["a.py"], split="holdout")]
    corpus = _corpus(tmp_path, questions)
    responses = {
        "memory_sync_status": {"wings": {"memory": {"last_commit_sha": "abc"}}},
        "mempalace_search": {"results": [_hit("a.py")]},
    }
    calls: list = []
    _install(monkeypatch, responses, calls)
    main(["eval", "--corpus", str(corpus), "--holdout"])
    queries = [c[1]["query"] for c in calls if c[0] == "mempalace_search"]
    assert queries == ["query m2"]


def test_corpus_schema_valid():
    data = json.loads(CORPUS_PATH.read_text())
    assert data["version"] == 1
    assert data["wings"]
    ids = set()
    for q in data["questions"]:
        assert {"id", "wing", "split", "style", "query", "gold", "basis"} <= set(q)
        assert q["id"] not in ids
        ids.add(q["id"])
        assert q["split"] in {"dev", "holdout"}
        assert q["style"] in {"prose", "identifiers"}
        assert q["wing"] == "user" or q["wing"] in data["wings"]
        assert q["gold"]
        for item in q["gold"]:
            assert isinstance(item, (str, list))


def test_corpus_gold_paths_exist_at_head():
    data = json.loads(CORPUS_PATH.read_text())
    root = Path(os.environ.get("MEMS_CODE_ROOT", "~/Code")).expanduser()
    checked = 0
    for q in data["questions"]:
        if q["wing"] == "user":
            continue
        repo = root / data["wings"][q["wing"]]["repo_dir"]
        if not (repo / ".git").exists():
            pytest.skip(f"{repo} not present")
        for item in q["gold"]:
            for path in [item] if isinstance(item, str) else item:
                proc = subprocess.run(
                    ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{path}"],
                    capture_output=True,
                )
                assert proc.returncode == 0, f"{q['id']}: {path} missing at HEAD"
                checked += 1
    if not checked:
        pytest.skip("no repo-backed questions")
