"""Tests for scripts/repair_user_wing.py against an in-memory fake collection."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "repair_user_wing.py"


@pytest.fixture(scope="module")
def repair():
    spec = importlib.util.spec_from_file_location("repair_user_wing", SCRIPT)
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
            if documents is not None:
                self.docs[drawer_id] = documents[n]
            if metadatas is not None:
                self.metas[drawer_id].update(metadatas[n])


LEAK = 'Real thought.\n</content>\n<parameter name="source_wing">edens-zac'


def _rows():
    return [
        ("user-leak", LEAK, {"wing": "user", "hall": "decisions"}),
        (
            "user-leak-scoped",
            'Other thought <parameter name="source_wing">memory</parameter>',
            {"wing": "user", "hall": "goals", "source_wing": "kept"},
        ),
        ("user-clean", "Nothing wrong here", {"wing": "user", "hall": "goals"}),
        ("user-empty", "</content><parameter name=x>", {"wing": "user", "hall": "goals"}),
        ("repo-1", LEAK, {"wing": "memory", "room": "src"}),
    ]


def test_plan_finds_and_strips_leaks(repair):
    plan = repair.plan_repairs(FakeCollection(_rows()))
    by_id = {r["id"]: r for r in plan["repairs"]}
    assert set(by_id) == {"user-leak", "user-leak-scoped"}
    assert by_id["user-leak"]["after"] == "Real thought."
    assert by_id["user-leak"]["metadata_updates"] == {"source_wing": "edens-zac"}
    assert by_id["user-leak-scoped"]["after"] == "Other thought"
    assert by_id["user-leak-scoped"]["metadata_updates"] == {}
    assert plan["skipped_empty"] == ["user-empty"]
    assert plan["scanned"] == 4


def test_plan_reads_bare_source_wing_tag(repair):
    rows = [
        (
            "user-bare",
            "Thought.</content>\n<source_wing>edens-zac-backend</source_wing>\n</invoke>",
            {"wing": "user"},
        )
    ]
    plan = repair.plan_repairs(FakeCollection(rows))
    assert plan["repairs"][0]["after"] == "Thought."
    assert plan["repairs"][0]["metadata_updates"] == {"source_wing": "edens-zac-backend"}


def test_dry_run_writes_nothing(repair, capsys):
    collection = FakeCollection(_rows())
    summary = repair.run(collection, apply=False)
    assert collection.updates == []
    assert summary["would_repair"] == 2
    assert summary["applied"] == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "user-leak" in out
    assert "Real thought." in out


def test_apply_updates_documents_and_source_wing(repair):
    collection = FakeCollection(_rows())
    summary = repair.run(collection, apply=True)
    assert summary["applied"] == 2
    assert collection.docs["user-leak"] == "Real thought."
    assert collection.metas["user-leak"]["source_wing"] == "edens-zac"
    assert collection.docs["user-leak-scoped"] == "Other thought"
    assert collection.metas["user-leak-scoped"]["source_wing"] == "kept"
    assert collection.docs["user-empty"] == "</content><parameter name=x>"
    assert collection.docs["repo-1"] == LEAK


def test_samples_capped_at_five(repair, capsys):
    rows = [(f"user-{i}", f"thought {i}{LEAK}", {"wing": "user"}) for i in range(8)]
    repair.run(FakeCollection(rows), apply=False)
    out = capsys.readouterr().out
    assert out.count("before:") == 5
    assert "8" in out


def test_main_defaults_to_dry_run(repair, monkeypatch):
    collection = FakeCollection(_rows())
    seen = {}

    def fake_open(path):
        seen["path"] = path
        return collection

    monkeypatch.setattr(repair, "open_collection", fake_open)
    monkeypatch.setenv("PALACE_PATH", "/tmp/somewhere")
    assert repair.main([]) == 0
    assert seen["path"] == "/tmp/somewhere"
    assert collection.updates == []
    assert repair.main(["--apply"]) == 0
    assert len(collection.updates) == 2
