"""Wingpack publish tests."""

from pathlib import Path

import pytest

from src.wing_pack import write_wingpack
from src.wing_publish import PublishRefused, publish_to_repo


def _bundle(tmp_path: Path, wing="my-wing", dim=384) -> Path:
    meta = {
        "name": wing,
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": dim,
        "drawer_count": 1,
        "rooms": [{"name": "general", "keywords": []}],
        "prompts": {"tunnels": []},
    }
    return write_wingpack(meta, tmp_path)


def test_publish_writes_wingpack_into_repo(tmp_path):
    (tmp_path / "src").mkdir()
    bundle = _bundle(tmp_path / "src")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = publish_to_repo(bundle, repo_root=repo, mode="default")
    assert result.path.exists()
    assert result.path.parent == repo / ".mempalace" / "wings"


def test_publish_refuses_embedding_dim_mismatch(tmp_path):
    (tmp_path / "src").mkdir()
    bundle = _bundle(tmp_path / "src", dim=512)
    repo = tmp_path / "repo"
    repo.mkdir()
    # Seed repo with stale wingpack at 384
    stale_meta = {
        "name": "my-wing",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "drawer_count": 0,
        "rooms": [],
    }
    (repo / ".mempalace" / "wings").mkdir(parents=True)
    write_wingpack(stale_meta, repo / ".mempalace" / "wings")
    with pytest.raises(PublishRefused, match="embedding"):
        publish_to_repo(bundle, repo_root=repo, mode="default")


def test_publish_dry_run_does_not_write(tmp_path):
    (tmp_path / "src").mkdir()
    bundle = _bundle(tmp_path / "src")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = publish_to_repo(bundle, repo_root=repo, mode="default", dry_run=True)
    assert not (repo / ".mempalace").exists()
    assert result.dry_run is True
