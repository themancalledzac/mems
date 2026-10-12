"""Tests for the host-side path-to-wing resolver used by the Claude Code hooks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "integration" / "claude_code" / "repo_scope.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_scope", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repo_scope = _load()


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git("init", "-q", cwd=path)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=path)
    return path


@pytest.fixture
def config(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(config_dir))

    def write(entries: dict) -> None:
        (config_dir / "repos.json").write_text(json.dumps(entries))

    return write


def test_path_under_registered_root_maps_to_wing(tmp_path, config):
    config(
        {
            "outer": {"path": str(tmp_path / "Code"), "wing": "outer"},
            "inner": {"path": str(tmp_path / "Code" / "inner"), "wing": "inner-wing"},
        }
    )
    assert repo_scope.wing_for_path(str(tmp_path / "Code" / "inner" / "src" / "a.py")) == "inner-wing"
    assert repo_scope.wing_for_path(str(tmp_path / "Code" / "other.py")) == "outer"
    roots = repo_scope.load_repo_roots()
    assert [wing for _, wing in roots] == ["inner-wing", "outer"]


def test_path_outside_all_roots_is_none(tmp_path, config):
    config({"memory": {"path": str(tmp_path / "Code" / "Memory"), "wing": "memory"}})
    assert repo_scope.wing_for_path(str(tmp_path / "Code" / "MemoryOther" / "a.py")) is None
    assert repo_scope.wing_for_path(str(tmp_path / "elsewhere")) is None


def test_worktree_resolves_via_git_common_dir(tmp_path, config):
    main = _init_repo(tmp_path / "Code" / "proj")
    config({"proj": {"path": str(main), "wing": "proj-wing"}})
    worktree = tmp_path / "wt" / "feature-x"
    _git("worktree", "add", "-q", "-b", "feature-x", str(worktree), cwd=main)
    (worktree / "src").mkdir()
    assert repo_scope.wing_for_path(str(worktree / "src" / "a.py")) == "proj-wing"


def test_orch_style_clone_resolves_via_origin(tmp_path, config):
    source = _init_repo(tmp_path / "Code" / "proj")
    config({"proj": {"path": str(source), "wing": "proj-wing"}})
    clone = tmp_path / "cache" / "orch" / "runner"
    _git("clone", "-q", str(source), str(clone), cwd=tmp_path)
    assert repo_scope.wing_for_path(str(clone / "a.py")) == "proj-wing"

    remote_clone = tmp_path / "cache" / "orch" / "clone"
    _git("clone", "-q", str(source), str(remote_clone), cwd=tmp_path)
    _git("remote", "set-url", "origin", "git@github.com:someone/proj.git", cwd=remote_clone)
    assert repo_scope.wing_for_path(str(remote_clone / "a.py")) == "proj-wing"


def test_missing_repos_json_returns_no_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_CONFIG_DIR", str(tmp_path / "absent"))
    assert repo_scope.load_repo_roots() == []
    assert repo_scope.wing_for_path(str(tmp_path / "a.py")) is None


def test_bash_target_paths_ignore_dev_null_and_use_cwd_for_relative():
    command = "grep -rn foo src/a.py 2>/dev/null; cat /etc/hosts > /dev/null"
    assert repo_scope.target_paths("Bash", {"command": command}, "/repo") == [
        "/repo/src/a.py",
        "/etc/hosts",
    ]
    assert repo_scope.target_paths("Bash", {"command": "ls -la"}, "/repo") == ["/repo"]
    assert repo_scope.target_paths(
        "Bash", {"command": "cd /other && sed -n 1,5p lib/b.py"}, "/repo"
    ) == ["/other", "/other/lib/b.py"]
    assert repo_scope.target_paths("Read", {"file_path": "/x/y.py"}, "/repo") == ["/x/y.py"]
    assert repo_scope.target_paths("Grep", {"pattern": "foo"}, "/repo") == ["/repo"]
    assert repo_scope.target_paths("Glob", {"pattern": "*.py", "path": "sub"}, "/repo") == [
        "/repo/sub"
    ]
