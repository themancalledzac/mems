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


import uuid
from datetime import datetime, timedelta, timezone


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
        # Write a thought with an old timestamp
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
