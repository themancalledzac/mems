import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.user_wing import VALID_HALLS, UserWing


class TestUserWingWrite:
    def test_valid_halls(self):
        assert "questions" in VALID_HALLS
        assert "discoveries" in VALID_HALLS
        assert "frustrations" in VALID_HALLS
        assert "goals" in VALID_HALLS
        assert "decisions" in VALID_HALLS
        assert "observations" in VALID_HALLS

    def test_write_thought(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="discoveries",
            content="CLIP ViT-L/14 works better than B/32 for photography tags",
            topic="ml-tagging",
        )
        assert result["status"] == "created"
        assert result["hall"] == "discoveries"
        assert result["id"].startswith("user-")

    def test_write_invalid_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="invalid-hall",
            content="test",
            topic="test",
        )
        assert result["status"] == "error"
        assert result["code"] == "invalid_hall"

    def test_write_with_source_wing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.write(
            hall="observations",
            content="BoxTree algorithm gets slow above 200 images",
            topic="performance",
            source_wing="edens-zac",
        )
        assert result["status"] == "created"

    def test_write_dedup_updates_existing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r1 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by Q2",
            topic="portfolio",
        )
        r2 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by end of Q2",
            topic="portfolio",
        )
        assert r2["status"] == "updated"
        assert r2["id"] == r1["id"]


class TestUserWingSearch:
    def test_search_returns_results(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(
            hall="discoveries",
            content="CLIP ViT-L/14 outperforms B/32 for photography classification",
            topic="ml",
        )
        results = wing.search(query="CLIP model performance")
        assert len(results["results"]) >= 1
        assert results["results"][0]["hall"] == "discoveries"

    def test_search_filter_by_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio by Q2", topic="portfolio")
        wing.write(hall="frustrations", content="JDBC errors are useless", topic="backend")

        results = wing.search(query="portfolio", hall="goals")
        for r in results["results"]:
            assert r["hall"] == "goals"

    def test_search_filter_by_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast for APIs", topic="go-backend")
        wing.write(hall="discoveries", content="React is flexible", topic="frontend")

        results = wing.search(query="programming", topic="go-backend")
        for r in results["results"]:
            assert r["topic"] == "go-backend"

    def test_search_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        results = wing.search(query="nonexistent query xyz123")
        assert results["results"] == []


class TestUserWingSummary:
    def test_summary_with_data(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio by Q2", topic="portfolio")
        wing.write(hall="decisions", content="Chose Go over Rust for backend", topic="backend")
        wing.write(hall="frustrations", content="JDBC errors are useless", topic="backend")
        wing.write(hall="discoveries", content="CLIP ViT-L/14 is better", topic="ml")
        wing.write(
            hall="questions", content="How does CloudFront invalidation work?", topic="infra"
        )
        wing.write(hall="observations", content="BoxTree slows above 200 images", topic="perf")

        summary = wing.summary()
        assert "## User Context" in summary["text"]
        assert summary["token_estimate"] > 0

    def test_summary_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        summary = wing.summary()
        assert summary["text"] == ""
        assert summary["token_estimate"] == 0


class TestUserWingStatus:
    def test_status_with_data(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="goals", content="Ship portfolio", topic="portfolio")
        wing.write(hall="goals", content="Learn Go", topic="learning")
        wing.write(hall="frustrations", content="JDBC is bad", topic="backend")

        status = wing.status()
        assert status["total_thoughts"] == 3
        assert status["halls"]["goals"] == 2
        assert status["halls"]["frustrations"] == 1
        assert "portfolio" in status["recent_topics"] or "learning" in status["recent_topics"]

    def test_status_empty(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        status = wing.status()
        assert status["total_thoughts"] == 0


class TestUserWingMergeTopic:
    def test_merge_topics(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast for APIs", topic="golang")
        wing.write(hall="discoveries", content="Go concurrency is great", topic="go-lang")

        result = wing.merge_topics(source_topic="go-lang", target_topic="golang")
        assert result["merged"] >= 1
        assert result["remaining"] >= 1

    def test_merge_topics_scoped_to_hall(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="discoveries", content="Go is fast", topic="golang")
        wing.write(hall="goals", content="Learn Go", topic="golang")
        wing.write(hall="discoveries", content="Go has goroutines", topic="go-lang")

        result = wing.merge_topics(
            source_topic="go-lang",
            target_topic="golang",
            hall="discoveries",
        )
        assert result["merged"] >= 1

    def test_merge_nonexistent_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.merge_topics(source_topic="nope", target_topic="also-nope")
        assert result["merged"] == 0


class TestUserWingPrune:
    def test_prune_dry_run(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="observations", content="Test observation", topic="test")

        result = wing.prune(hall="observations", dry_run=True)
        assert "candidates" in result
        assert result["pruned"] == 0

    def test_prune_old_entries(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        old_time = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        drawer_id = f"user-{uuid.uuid4().hex[:24]}"
        wing.collection.upsert(
            ids=[drawer_id],
            documents=["very old thought"],
            metadatas=[
                {
                    "wing": "user",
                    "hall": "observations",
                    "topic": "old-stuff",
                    "timestamp": old_time,
                    "confidence": 0.5,
                    "added_by": "user-wing",
                }
            ],
        )

        result = wing.prune(hall="observations", older_than_days=90, dry_run=False)
        assert result["pruned"] >= 1

    def test_prune_by_topic(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.write(hall="frustrations", content="X is annoying", topic="temp-issue")
        wing.write(hall="frustrations", content="Y is important", topic="real-issue")

        result = wing.prune(
            hall="frustrations", topic="temp-issue", older_than_days=0, dry_run=False
        )
        assert result["pruned"] >= 1


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _put(wing, doc, hall="observations", topic="t", days_ago=0.0, drawer_id=None, **extra):
    """Insert a raw user entry. Without `last_seen` in extra it mimics a pre-recency entry."""
    drawer_id = drawer_id or f"user-{uuid.uuid4().hex[:24]}"
    meta = {
        "wing": "user",
        "hall": hall,
        "topic": topic,
        "timestamp": _iso_days_ago(days_ago),
        "confidence": 0.9,
        "added_by": "user-wing",
    }
    meta.update(extra)
    wing.collection.upsert(ids=[drawer_id], documents=[doc], metadatas=[meta])
    return drawer_id


def _meta(wing, drawer_id):
    return wing.collection.get(ids=[drawer_id]).get("metadatas")[0]


def _doc(wing, drawer_id):
    return wing.collection.get(ids=[drawer_id]).get("documents")[0]


class TestWriteRecencyMetadata:
    def test_create_sets_recency_fields(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(hall="observations", content="Chroma get is fast", topic="chroma")
        meta = _meta(wing, r["id"])
        assert meta["last_seen"] == meta["timestamp"]
        assert isinstance(meta["last_seen_epoch"], float)
        assert meta["seen_count"] == 1
        assert meta["origin"] == "agent"
        assert meta["personal"] is False
        assert "status" not in meta

    def test_status_defaults_open_for_goals_and_questions(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        g = wing.write(hall="goals", content="Ship the recency work", topic="mems")
        q = wing.write(hall="questions", content="How does HNSW pick neighbours?", topic="chroma")
        d = wing.write(hall="decisions", content="Use uv for local venvs", topic="tooling")
        assert _meta(wing, g["id"])["status"] == "open"
        assert _meta(wing, q["id"])["status"] == "open"
        assert "status" not in _meta(wing, d["id"])

    def test_explicit_status_origin_personal(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(
            hall="decisions",
            content="Park the grouping work",
            topic="mems",
            origin="orch",
            status="parked",
            personal=True,
        )
        meta = _meta(wing, r["id"])
        assert meta["status"] == "parked"
        assert meta["origin"] == "orch"
        assert meta["personal"] is True

    def test_invalid_origin_rejected(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(hall="goals", content="x", topic="t", origin="robot")
        assert r["status"] == "error"
        assert r["code"] == "invalid_origin"
        assert wing.collection.count() == 0

    def test_invalid_status_rejected(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(hall="goals", content="x", topic="t", status="maybe")
        assert r["status"] == "error"
        assert r["code"] == "invalid_status"
        assert wing.collection.count() == 0

    def test_malformed_content_rejected(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for bad in (
            'Note</content>\n<parameter name="source_wing">edens-zac',
            "a <parameter name=x> b",
            "a </parameter> b",
            "a <invoke name=y> b",
        ):
            r = wing.write(hall="observations", content=bad, topic="t")
            assert r == {
                "status": "error",
                "code": "malformed",
                "message": "malformed: content contains tool-call markup",
            }
        assert wing.collection.count() == 0


class TestWriteDedup:
    def test_dedup_keeps_original_and_bumps_seen_count(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r1 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by Q2",
            topic="portfolio",
            source_wing="edens-zac",
        )
        before = _meta(wing, r1["id"])
        r2 = wing.write(
            hall="goals",
            content="Get portfolio production-ready by end of Q2",
            topic="other-topic",
            source_wing="memory",
        )
        assert r2 == {"status": "updated", "id": r1["id"], "hall": "goals", "seen_count": 2}
        after = _meta(wing, r1["id"])
        assert after["timestamp"] == before["timestamp"]
        assert after["topic"] == "portfolio"
        assert after["source_wing"] == "edens-zac"
        assert after["seen_count"] == 2
        assert after["last_seen_epoch"] >= before["last_seen_epoch"]
        doc = _doc(wing, r1["id"])
        assert doc.startswith("Get portfolio production-ready by Q2\n\n[revised ")
        assert doc.endswith("] Get portfolio production-ready by end of Q2")

    def test_dedup_identical_content_adds_no_revision(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r1 = wing.write(hall="decisions", content="Pin mcp below 2", topic="deps")
        r2 = wing.write(hall="decisions", content="Pin mcp below 2", topic="deps")
        assert r2["status"] == "updated"
        assert r2["seen_count"] == 2
        assert _doc(wing, r1["id"]) == "Pin mcp below 2"

    def test_dedup_fills_missing_source_wing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r1 = wing.write(hall="decisions", content="Pin mcp below 2", topic="deps")
        wing.write(hall="decisions", content="Pin mcp below 2", topic="deps", source_wing="memory")
        assert _meta(wing, r1["id"])["source_wing"] == "memory"

    def test_dedup_on_legacy_entry_starts_from_one(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        legacy = _put(wing, "Pin mcp below 2", hall="decisions", days_ago=30)
        r = wing.write(hall="decisions", content="Pin mcp below 2", topic="deps")
        assert r["id"] == legacy
        assert r["seen_count"] == 2

    def test_revisions_capped_at_three(self, tmp_palace, monkeypatch):
        wing = UserWing(palace_path=str(tmp_palace))
        first = wing.write(hall="observations", content="base text", topic="t")
        monkeypatch.setattr(
            wing,
            "_find_duplicate",
            lambda hall, content: {
                "id": first["id"],
                "metadata": _meta(wing, first["id"]),
                "document": _doc(wing, first["id"]),
            },
        )
        for i in range(5):
            wing.write(hall="observations", content=f"variant {i}", topic="t")
        doc = _doc(wing, first["id"])
        assert doc.startswith("base text\n\n[revised ")
        assert doc.count("[revised ") == 3
        assert "variant 0" not in doc
        assert "variant 1" not in doc
        assert doc.endswith("] variant 4")
        assert _meta(wing, first["id"])["seen_count"] == 6


class TestSearchRecency:
    def test_recent_entry_ranks_above_older_at_equal_distance(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        old = _put(wing, "same words exactly", days_ago=60, drawer_id="user-a-old")
        new = _put(wing, "same words exactly", days_ago=0, drawer_id="user-z-new")
        results = wing.search(query="same words exactly")["results"]
        assert [r["id"] for r in results] == [new, old]
        assert results[0]["effective_distance"] < results[1]["effective_distance"]

    def test_recency_weight_zero_falls_back_to_id_order(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "same words exactly", days_ago=60, drawer_id="user-a-old")
        _put(wing, "same words exactly", days_ago=0, drawer_id="user-z-new")
        results = wing.search(query="same words exactly", recency_weight=0.0)["results"]
        assert [r["id"] for r in results] == ["user-a-old", "user-z-new"]

    def test_legacy_entry_reads_with_defaults(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        drawer_id = _put(wing, "a legacy observation", days_ago=3)
        r = wing.search(query="a legacy observation")["results"][0]
        assert r["id"] == drawer_id
        assert r["last_seen"] == r["timestamp"]
        assert r["seen_count"] == 1
        assert r["origin"] == "agent"
        assert r["personal"] is False
        assert r["status"] is None
        assert r["distance"] is not None

    def test_since_days_uses_last_seen(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "release notes", days_ago=30, drawer_id="user-old")
        _put(
            wing,
            "release notes",
            days_ago=30,
            drawer_id="user-touched",
            last_seen=_iso_days_ago(1),
        )
        ids = [r["id"] for r in wing.search(query="release notes", since_days=7)["results"]]
        assert ids == ["user-touched"]

    def test_source_wing_filter_with_unscoped(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "deploy notes", drawer_id="user-a", source_wing="alpha")
        _put(wing, "deploy notes", drawer_id="user-b", source_wing="beta")
        _put(wing, "deploy notes", drawer_id="user-none")
        with_unscoped = wing.search(query="deploy notes", source_wing="alpha")["results"]
        assert {r["id"] for r in with_unscoped} == {"user-a", "user-none"}
        scoped_only = wing.search(
            query="deploy notes", source_wing="alpha", include_unscoped=False
        )["results"]
        assert [r["id"] for r in scoped_only] == ["user-a"]

    def test_status_filter_and_personal(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "plan item", hall="goals", drawer_id="user-legacy-goal")
        _put(wing, "plan item", hall="goals", drawer_id="user-done", status="done")
        _put(wing, "plan item", hall="goals", drawer_id="user-private", personal=True)
        open_ids = {r["id"] for r in wing.search(query="plan item", status="open")["results"]}
        assert open_ids == {"user-legacy-goal", "user-private"}
        public = wing.search(query="plan item", include_personal=False)["results"]
        public = {r["id"] for r in public}
        assert public == {"user-legacy-goal", "user-done"}

    def test_open_filter_matches_legacy_goals_and_questions_only(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "pending item", hall="goals", drawer_id="user-goal")
        _put(wing, "pending item", hall="questions", drawer_id="user-question")
        _put(wing, "pending item", hall="decisions", drawer_id="user-decision")
        _put(wing, "pending item", hall="observations", drawer_id="user-observation")
        hits = wing.search(query="pending item", status="open")["results"]
        assert {r["id"] for r in hits} == {"user-goal", "user-question"}
        assert all(r["status"] is None for r in hits)

    def test_n_results_caps_output(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for i in range(5):
            _put(wing, f"note number {i}")
        assert len(wing.search(query="note", n_results=2)["results"]) == 2


class TestRecent:
    def test_recent_orders_newest_first_and_respects_days(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "three days", days_ago=3, drawer_id="user-3")
        _put(wing, "one day", days_ago=1, drawer_id="user-1")
        _put(wing, "old but touched", days_ago=90, drawer_id="user-t", last_seen=_iso_days_ago(2))
        _put(wing, "ten days", days_ago=10, drawer_id="user-10")
        result = wing.recent(days=7)
        assert [r["id"] for r in result["results"]] == ["user-1", "user-t", "user-3"]
        first = result["results"][0]
        assert first["content"] == "one day"
        assert "distance" not in first
        assert "effective_distance" not in first

    def test_recent_filters_and_limit(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "a", hall="goals", days_ago=1, drawer_id="user-g1", source_wing="alpha")
        _put(wing, "b", hall="goals", days_ago=2, drawer_id="user-g2", status="done")
        _put(wing, "c", hall="decisions", days_ago=1.5, drawer_id="user-d1", source_wing="beta")
        _put(wing, "d", hall="goals", days_ago=3, drawer_id="user-g3", personal=True)
        assert [r["id"] for r in wing.recent(hall="goals", status="open")["results"]] == [
            "user-g1",
            "user-g3",
        ]
        assert [r["id"] for r in wing.recent(source_wing="beta")["results"]] == [
            "user-d1",
            "user-g2",
            "user-g3",
        ]
        assert [r["id"] for r in wing.recent(include_personal=False, n=2)["results"]] == [
            "user-g1",
            "user-d1",
        ]

    def test_recent_open_filter_matches_legacy_goals_and_questions_only(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "g", hall="goals", days_ago=1, drawer_id="user-goal")
        _put(wing, "q", hall="questions", days_ago=2, drawer_id="user-question")
        _put(wing, "d", hall="decisions", days_ago=1, drawer_id="user-decision")
        _put(wing, "o", hall="observations", days_ago=1, drawer_id="user-observation")
        _put(wing, "a", hall="decisions", days_ago=1, drawer_id="user-active", status="active")
        assert [r["id"] for r in wing.recent(status="open")["results"]] == [
            "user-goal",
            "user-question",
        ]
        assert [r["id"] for r in wing.recent(status="active")["results"]] == ["user-active"]

    def test_recent_ignores_other_wings(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.collection.upsert(
            ids=["repo-1"],
            documents=["code"],
            metadatas=[{"wing": "memory", "room": "src", "timestamp": _iso_days_ago(0)}],
        )
        assert wing.recent()["results"] == []


class TestSetStatus:
    def test_set_status_updates_metadata_only(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(hall="goals", content="Ship it", topic="mems")
        result = wing.set_status(r["id"], "done")
        assert result == {"status": "updated", "id": r["id"], "entry_status": "done"}
        meta = _meta(wing, r["id"])
        assert meta["status"] == "done"
        assert meta["topic"] == "mems"
        assert _doc(wing, r["id"]) == "Ship it"

    def test_set_status_rejects_invalid_status(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        r = wing.write(hall="goals", content="Ship it", topic="mems")
        result = wing.set_status(r["id"], "finished")
        assert result["status"] == "error"
        assert result["code"] == "invalid_status"
        assert _meta(wing, r["id"])["status"] == "open"

    def test_set_status_unknown_id(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        result = wing.set_status("user-missing", "done")
        assert result["status"] == "error"
        assert result["code"] == "not_found"

    def test_set_status_rejects_non_user_entry(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        wing.collection.upsert(
            ids=["repo-1"], documents=["code"], metadatas=[{"wing": "memory", "room": "src"}]
        )
        result = wing.set_status("repo-1", "done")
        assert result["status"] == "error"
        assert result["code"] == "not_found"
        assert "status" not in _meta(wing, "repo-1")


class TestSummaryRecency:
    def test_summary_shows_two_newest_decisions(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "decision oldest", hall="decisions", days_ago=40)
        _put(wing, "decision newer", hall="decisions", days_ago=3)
        _put(wing, "decision newest", hall="decisions", days_ago=1)
        _put(wing, "decision touched", hall="decisions", days_ago=50, last_seen=_iso_days_ago(2))
        text = wing.summary()["text"]
        assert "decision oldest" not in text
        assert "decision newer" not in text
        assert text.index("decision newest") < text.index("decision touched")

    def test_summary_items_per_section(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for hall in sorted(VALID_HALLS):
            for i in range(6):
                _put(wing, f"{hall} {i}", hall=hall, days_ago=i)
        lines = wing.summary()["text"].splitlines()[1:]
        counts = {line.split(":**")[0].strip("*"): line.count(";") + 1 for line in lines}
        assert counts == {
            "Open ideas": 4,
            "Goals": 2,
            "Recent decisions": 2,
            "Active frustrations": 2,
            "Recent discoveries": 2,
            "Recent questions": 1,
            "Observations": 1,
        }

    def test_summary_excludes_personal(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "public decision", hall="decisions")
        _put(wing, "private decision", hall="decisions", personal=True)
        text = wing.summary()["text"]
        assert "public decision" in text
        assert "private decision" not in text

    def test_summary_open_ideas_first(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "legacy goal", hall="goals", days_ago=2)
        _put(wing, "finished goal", hall="goals", days_ago=1, status="done")
        _put(wing, "open question", hall="questions", days_ago=1, status="open")
        _put(wing, "a decision", hall="decisions")
        text = wing.summary()["text"]
        lines = text.splitlines()
        assert lines[0] == "## User Context"
        assert lines[1].startswith("**Open ideas:**")
        assert "open question" in lines[1]
        assert "legacy goal" in lines[1]
        assert "finished goal" not in lines[1]

    def test_summary_skips_entries_already_in_open_ideas(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for i in range(3):
            _put(wing, f"open goal {i}", hall="goals", days_ago=i)
        _put(wing, "open question", hall="questions", days_ago=3)
        _put(wing, "older goal", hall="goals", days_ago=10)
        _put(wing, "oldest goal", hall="goals", days_ago=11)
        _put(wing, "old question", hall="questions", days_ago=12)
        text = wing.summary()["text"]
        lines = {
            line.split(":** ")[0].strip("*"): line.split(":** ")[1].split("; ")
            for line in text.splitlines()[1:]
        }
        assert lines["Open ideas"] == ["open goal 0", "open goal 1", "open goal 2", "open question"]
        assert lines["Goals"] == ["older goal", "oldest goal"]
        assert lines["Recent questions"] == ["old question"]

    def test_summary_scoped_to_source_wing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "alpha decision", hall="decisions", source_wing="alpha")
        _put(wing, "beta decision", hall="decisions", source_wing="beta")
        _put(wing, "unscoped decision", hall="decisions")
        text = wing.summary(source_wing="alpha")["text"]
        assert "alpha decision" in text
        assert "unscoped decision" in text
        assert "beta decision" not in text

    def test_summary_drops_whole_items_from_the_end(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for hall in sorted(VALID_HALLS):
            for i in range(4):
                _put(wing, f"{hall} {i} " + "x" * 900, hall=hall, days_ago=i)
        result = wing.summary()
        text = result["text"]
        assert len(text) <= 2400
        assert "**Observations:**" not in text
        assert "**Recent questions:**" not in text
        assert "**Open ideas:**" in text
        assert "**Goals:**" in text
        for line in text.splitlines()[1:]:
            for item in line.split(":** ", 1)[1].split("; "):
                assert len(item) == 223
        assert result["token_estimate"] == len(text) // 4

    def test_summary_item_truncation_defaults_to_220(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "y" * 500, hall="decisions")
        text = wing.summary()["text"]
        assert ("y" * 220 + "...") in text
        assert ("y" * 221) not in text

    def test_summary_item_truncation_uses_max_item_chars(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "y" * 500, hall="decisions")
        text = wing.summary(max_item_chars=50)["text"]
        assert ("y" * 50 + "...") in text
        assert ("y" * 51) not in text


class TestStatusRecentTopics:
    def test_recent_topics_newest_first(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        _put(wing, "a", topic="zeta", days_ago=1)
        _put(wing, "b", topic="alpha", days_ago=5)
        _put(wing, "c", topic="zeta", days_ago=6)
        _put(wing, "d", topic="mid", hall="goals", days_ago=90, last_seen=_iso_days_ago(3))
        status = wing.status()
        assert status["recent_topics"] == ["zeta", "mid", "alpha"]
        assert status["total_thoughts"] == 4
        assert status["halls"] == {"observations": 3, "goals": 1}
        assert "guidance" in status


class TestSearchScoping:
    def test_search_scoped_finds_minority_wing_entries(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for i in range(40):
            _put(wing, f"release checklist item {i}", source_wing="wing-a")
        small = {
            _put(wing, "release checklist for the small repo", source_wing="wing-b"),
            _put(wing, "release checklist small repo notes", source_wing="wing-b"),
        }
        hits = wing.search(query="release checklist", source_wing="wing-b", include_unscoped=False)[
            "results"
        ]
        assert {r["id"] for r in hits} == small

    def test_search_scoped_with_unscoped_returns_both(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for i in range(40):
            _put(wing, f"release checklist item {i}", source_wing="wing-a")
        scoped = _put(wing, "release checklist for the small repo", source_wing="wing-b")
        free = _put(wing, "release checklist with no wing")
        hits = wing.search(query="release checklist", source_wing="wing-b")["results"]
        assert {r["id"] for r in hits} == {scoped, free}
        assert [r["effective_distance"] for r in hits] == sorted(
            r["effective_distance"] for r in hits
        )

    def test_search_unscoped_covers_empty_string_wing(self, tmp_palace):
        wing = UserWing(palace_path=str(tmp_palace))
        for i in range(40):
            _put(wing, f"release checklist item {i}", source_wing="wing-a")
        empty = _put(wing, "release checklist blank wing", source_wing="")
        hits = wing.search(query="release checklist", source_wing="wing-b")["results"]
        assert {r["id"] for r in hits} == {empty}


class TestOrchCallsSkipPersonal:
    """orch scopes every read to its repo wing with include_personal=False."""

    def _seed(self, wing):
        _put(wing, "release plan", days_ago=1, drawer_id="user-repo", source_wing="orch")
        _put(wing, "release plan", days_ago=1, drawer_id="user-free")
        _put(wing, "release plan", days_ago=1, drawer_id="user-other", source_wing="edens")
        for drawer_id, scope in (
            ("user-p-repo", {"source_wing": "orch"}),
            ("user-p-free", {}),
            ("user-p-other", {"source_wing": "job-search"}),
        ):
            _put(wing, "release plan", days_ago=1, drawer_id=drawer_id, personal=True, **scope)

    @pytest.mark.parametrize(
        "include_unscoped, expected",
        [(True, {"user-repo", "user-free"}), (False, {"user-repo"})],
    )
    def test_search(self, tmp_palace, include_unscoped, expected):
        wing = UserWing(palace_path=str(tmp_palace))
        self._seed(wing)
        hits = wing.search(
            query="release plan",
            source_wing="orch",
            include_unscoped=include_unscoped,
            include_personal=False,
        )["results"]
        assert {r["id"] for r in hits} == expected
        assert all(r["personal"] is False for r in hits)

    @pytest.mark.parametrize(
        "include_unscoped, expected",
        [(True, {"user-repo", "user-free"}), (False, {"user-repo"})],
    )
    def test_recent(self, tmp_palace, include_unscoped, expected):
        wing = UserWing(palace_path=str(tmp_palace))
        self._seed(wing)
        hits = wing.recent(
            days=7,
            source_wing="orch",
            include_unscoped=include_unscoped,
            include_personal=False,
        )["results"]
        assert {r["id"] for r in hits} == expected
        assert all(r["personal"] is False for r in hits)
