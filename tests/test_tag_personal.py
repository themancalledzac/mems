"""Tests for scripts/tag_personal.py against an in-memory fake collection."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tag_personal.py"


@pytest.fixture(scope="module")
def tagger():
    spec = importlib.util.spec_from_file_location("tag_personal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCollection:
    """Holds ids, documents and metadatas in dicts and mimics the get/update calls used."""

    def __init__(self, rows):
        self.docs = {r[0]: r[1] for r in rows}
        self.metas = {r[0]: dict(r[2]) for r in rows}
        self.updates = []

    def get(self, where=None, include=None):
        ids = [i for i, m in self.metas.items() if m.get("wing") == where["wing"]]
        return {
            "ids": ids,
            "documents": [self.docs[i] for i in ids],
            "metadatas": [self.metas[i] for i in ids],
        }

    def update(self, ids, documents=None, metadatas=None):
        self.updates.append((ids, documents, metadatas))
        for n, drawer_id in enumerate(ids):
            if metadatas is not None:
                self.metas[drawer_id].update(metadatas[n])


def _user(hall="decisions", topic="t", **extra):
    return {"wing": "user", "hall": hall, "topic": topic, **extra}


def _rows():
    return [
        ("user-job", "Applied to two roles", _user(source_wing="job-search")),
        ("user-run", "Long run felt easy", _user(source_wing="running")),
        ("user-code", "Chose Go for the API", _user(source_wing="edens-zac")),
        (
            "user-tagged",
            "Already handled",
            _user(source_wing="job-search", personal=True),
        ),
        (
            "user-cheat",
            "Rewrite the Integrate interview cheat sheet",
            _user(topic="interview-prep"),
        ),
        ("user-plain", "Prefer small commits", _user(topic="git")),
        ("repo-1", "interview notes in code", {"wing": "job-search", "room": "src"}),
    ]


def test_plan_tags_by_wing(tagger):
    plan = tagger.plan_tags(FakeCollection(_rows()), {"job-search", "running"})
    assert [e["id"] for e in plan["by_wing"]] == ["user-job", "user-run"]
    assert plan["already_personal"] == 1
    assert plan["scanned"] == 6


def test_plan_matches_unscoped_keywords(tagger):
    plan = tagger.plan_tags(FakeCollection(_rows()), {"job-search", "running"})
    assert [e["id"] for e in plan["by_keyword"]] == ["user-cheat"]
    assert "cheat sheet" in plan["by_keyword"][0]["keywords"]
    assert [e["id"] for e in plan["unmatched"]] == ["user-plain"]


def test_keywords_match_case_insensitively_in_topic(tagger):
    rows = [("user-x", "Practice answers", _user(topic="RECRUITER call"))]
    plan = tagger.plan_tags(FakeCollection(rows), set())
    assert [e["id"] for e in plan["by_keyword"]] == ["user-x"]


def test_keywords_match_inside_hyphenated_topic(tagger):
    rows = [("user-y", "Questions for Andrew", _user(topic="interview-prep-accuracy"))]
    plan = tagger.plan_tags(FakeCollection(rows), set())
    assert [e["id"] for e in plan["by_keyword"]] == ["user-y"]


def test_keywords_ignore_partial_words(tagger):
    rows = [("user-z", "The integrated runner shipped", _user(topic="orch"))]
    plan = tagger.plan_tags(FakeCollection(rows), set())
    assert plan["by_keyword"] == []


def test_dry_run_writes_nothing(tagger, capsys):
    collection = FakeCollection(_rows())
    result = tagger.run(collection, {"job-search", "running"}, apply=False, apply_unscoped=False)
    assert collection.updates == []
    assert result["by_wing"] == 2
    assert result["by_keyword"] == 1
    assert result["unmatched"] == 1
    assert result["applied"] == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "user-cheat interview-prep Rewrite the Integrate" in out


def test_apply_tags_wing_entries_only(tagger):
    collection = FakeCollection(_rows())
    result = tagger.run(collection, {"job-search", "running"}, apply=True, apply_unscoped=False)
    assert result["applied"] == 2
    assert collection.metas["user-job"]["personal"] is True
    assert collection.metas["user-run"]["personal"] is True
    assert "personal" not in collection.metas["user-cheat"]
    assert "personal" not in collection.metas["user-code"]
    assert "personal" not in collection.metas["repo-1"]


def test_apply_unscoped_tags_keyword_matches(tagger):
    collection = FakeCollection(_rows())
    result = tagger.run(collection, {"job-search", "running"}, apply=False, apply_unscoped=True)
    assert result["applied"] == 1
    assert collection.metas["user-cheat"]["personal"] is True
    assert "personal" not in collection.metas["user-job"]
    assert "personal" not in collection.metas["user-plain"]


def test_already_tagged_left_alone(tagger):
    collection = FakeCollection(_rows())
    tagger.run(collection, {"job-search", "running"}, apply=True, apply_unscoped=True)
    touched = {drawer_id for ids, _, _ in collection.updates for drawer_id in ids}
    assert "user-tagged" not in touched


def test_wing_samples_capped_at_ten(tagger, capsys):
    rows = [(f"user-{i}", f"note {i}", _user(source_wing="running")) for i in range(12)]
    tagger.run(FakeCollection(rows), {"running"}, apply=False, apply_unscoped=False)
    out = capsys.readouterr().out
    assert "user-9 " in out
    assert "user-10 " not in out
    assert "12" in out


def test_preview_cut_to_one_hundred_chars(tagger, capsys):
    rows = [("user-long", "salary " + "z" * 300, _user(topic="cv"))]
    tagger.run(FakeCollection(rows), set(), apply=False, apply_unscoped=False)
    out = capsys.readouterr().out
    assert ("z" * 93) in out
    assert ("z" * 94) not in out


def test_main_defaults_to_dry_run_and_parses_wings(tagger, monkeypatch):
    collection = FakeCollection(_rows())
    seen = {}

    def fake_open(path):
        seen["path"] = path
        return collection

    monkeypatch.setattr(tagger, "open_collection", fake_open)
    monkeypatch.setenv("PALACE_PATH", "/tmp/somewhere")
    assert tagger.main([]) == 0
    assert seen["path"] == "/tmp/somewhere"
    assert collection.updates == []
    assert tagger.main(["--wings", "running", "--apply"]) == 0
    assert collection.metas["user-run"]["personal"] is True
    assert "personal" not in collection.metas["user-job"]


def test_main_rejects_dry_run_with_apply(tagger, monkeypatch):
    monkeypatch.setattr(tagger, "open_collection", lambda path: FakeCollection([]))
    with pytest.raises(SystemExit):
        tagger.main(["--dry-run", "--apply-unscoped"])


def test_ids_dry_run_lists_named_entries_and_writes_nothing(tagger, capsys):
    collection = FakeCollection(_rows())
    result = tagger.run_ids(collection, ["user-code", "user-tagged", "repo-1", "nope"], apply=False)
    assert collection.updates == []
    assert result == {"to_tag": 1, "already_personal": 1, "missing": 2, "applied": 0}
    out = capsys.readouterr().out
    assert "user-code t Chose Go for the API" in out
    assert "user-tagged already personal" in out
    assert "repo-1 not found in the user wing" in out


def test_main_ids_apply_tags_only_named_entries(tagger, monkeypatch):
    collection = FakeCollection(_rows())
    monkeypatch.setattr(tagger, "open_collection", lambda path: collection)
    assert tagger.main(["--ids", "user-code, user-plain,repo-1", "--apply"]) == 0
    assert collection.metas["user-code"]["personal"] is True
    assert collection.metas["user-plain"]["personal"] is True
    for untouched in ("user-job", "user-run", "user-cheat", "repo-1"):
        assert "personal" not in collection.metas[untouched]


def test_main_ids_rejects_apply_unscoped_and_empty_list(tagger, monkeypatch):
    monkeypatch.setattr(tagger, "open_collection", lambda path: FakeCollection([]))
    with pytest.raises(SystemExit):
        tagger.main(["--ids", "user-code", "--apply-unscoped"])
    with pytest.raises(SystemExit):
        tagger.main(["--ids", " , "])
