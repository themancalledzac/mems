import argparse
import json
import subprocess

import pytest
import yaml


def argparse_namespace_for(**kwargs):
    """Build an argparse.Namespace from kwargs — handy for shell-out CLI tests."""
    return argparse.Namespace(**kwargs)


@pytest.fixture
def tmp_palace(tmp_path):
    """Temporary palace data directory."""
    palace = tmp_path / "palace"
    palace.mkdir()
    return palace


@pytest.fixture
def tmp_config(tmp_path):
    """Temporary config directory with minimal config files."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    repos = {
        "test-wing": {
            "path": str(tmp_path / "repos" / "test-repo"),
            "wing": "test-wing",
        }
    }
    (config_dir / "repos.json").write_text(json.dumps(repos, indent=2))

    taxonomy = {
        "wings": {
            "test-wing": {
                "rooms": {
                    "general": {
                        "patterns": ["*"],
                    }
                }
            }
        }
    }
    (config_dir / "mempalace.yaml").write_text(yaml.dump(taxonomy))

    return config_dir


@pytest.fixture
def mock_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    repo_dir = tmp_path / "repos" / "test-repo"
    repo_dir.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_dir,
        capture_output=True,
    )

    (repo_dir / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir,
        capture_output=True,
    )

    return repo_dir
