"""Wingpack bundle author tests."""

import json
import zipfile

import pytest

from src.wing_pack import write_wingpack


@pytest.fixture
def sample_wing_meta():
    return {
        "name": "my-wing",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "drawer_count": 42,
        "rooms": [
            {"name": "auth", "keywords": ["jwt", "login"], "tags": ["security"]},
            {"name": "general", "keywords": [], "tags": []},
        ],
    }


def test_write_wingpack_emits_four_members(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    expected = {"manifest.json", "wingpack.yaml", "keywords.json", "rooms.json"}
    assert expected <= names
    assert "prompts.json" not in names


def test_manifest_records_embedding_metadata(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["embedding_model"] == "all-MiniLM-L6-v2"
    assert manifest["embedding_dim"] == 384
    assert manifest["wing"] == "my-wing"
    assert manifest["drawer_count"] == 42
    assert "source_digest" in manifest


def test_default_filename_is_timestamped(tmp_path, sample_wing_meta):
    out = write_wingpack(sample_wing_meta, output_dir=tmp_path)
    assert out.name.endswith(".wingpack")
    # YYYYMMDD-HHMMSS.wingpack
    assert len(out.stem) == 15 and out.stem[8] == "-"
