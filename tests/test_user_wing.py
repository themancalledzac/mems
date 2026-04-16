import pytest

from src.user_wing import UserWing, VALID_HALLS


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
