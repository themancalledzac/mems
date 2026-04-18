"""Auto-publish post-sync hook tests."""


def test_auto_publish_imports():
    """Smoke test — module loads cleanly."""
    from src.auto_publish import publish_all_wings
    assert callable(publish_all_wings)


def test_auto_publish_skips_wings_with_no_meta(tmp_path):
    from src.auto_publish import publish_all_wings
    repos_json = tmp_path / "repos.json"
    repos_json.write_text('{"foo": {"path": "/nonexistent", "wing": "foo-wing"}}')
    exports = tmp_path / "exports"
    results = publish_all_wings(repos_json, exports, wing_metas={})
    assert results == [{"slug": "foo", "status": "skipped", "reason": "no wing meta"}]
