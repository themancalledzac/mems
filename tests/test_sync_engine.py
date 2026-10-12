import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from mempalace.miner import process_file as real_process_file
from mempalace.palace import get_closets_collection, get_collection

from src.sync_engine import (
    SyncEngine,
    SyncLedger,
    SyncSourceError,
    _flatten_rooms,
    get_head_sha,
    list_indexable_files,
    main,
    prune_wing,
)


class TestSyncLedger:
    def test_load_empty_ledger(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.entries == {}

    def test_load_existing_ledger(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger_path.write_text(
            json.dumps(
                {
                    "test-wing": {
                        "repo_path": "/repos/test",
                        "last_commit_sha": "abc123",
                        "last_sync_ts": "2026-04-15T10:00:00Z",
                        "files_indexed": 10,
                        "status": "synced",
                    }
                }
            )
        )
        ledger = SyncLedger(ledger_path)
        assert ledger.entries["test-wing"]["status"] == "synced"

    def test_update_and_save(self, tmp_palace):
        ledger_path = tmp_palace / "sync_ledger.json"
        ledger = SyncLedger(ledger_path)
        ledger.update(
            "my-wing",
            {
                "repo_path": "/repos/mine",
                "last_commit_sha": "def456",
                "last_sync_ts": "2026-04-15T11:00:00Z",
                "files_indexed": 5,
                "status": "synced",
            },
        )
        ledger.save()

        reloaded = SyncLedger(ledger_path)
        assert reloaded.entries["my-wing"]["last_commit_sha"] == "def456"

    def test_get_entry_missing(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.get("nonexistent") is None

    def test_mark_error(self, tmp_palace):
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        ledger.mark_error("bad-wing", "/repos/bad", "repo not found")
        assert ledger.entries["bad-wing"]["status"] == "error"
        assert ledger.entries["bad-wing"]["error"] == "repo not found"


class TestGitOps:
    def test_get_head_sha(self, mock_repo):
        sha = get_head_sha(str(mock_repo))
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_get_head_sha_bad_path(self):
        sha = get_head_sha("/nonexistent/repo")
        assert sha is None


class TestSyncEngine:
    def test_init_loads_config(self, tmp_config, tmp_palace):
        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )
        assert "test-wing" in engine.repos
        assert _flatten_rooms(engine.taxonomy["wings"]["test-wing"]) == [
            {"name": "general", "keywords": ["hello"]}
        ]

    def test_full_sync_indexes_repo(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with (
            patch(
                "src.sync_engine.list_indexable_files", return_value=[mock_repo / "hello.py"]
            ) as mock_scan,
            patch(
                "src.sync_engine.process_file", return_value=(1, "general", None)
            ) as mock_process,
        ):
            engine.full_sync()

        mock_scan.assert_called_once()
        mock_process.assert_called_once()
        entry = engine.ledger.get("test-wing")
        assert entry is not None
        assert entry["status"] == "synced"
        assert entry["last_commit_sha"] is not None

    def test_full_sync_handles_bad_repo(self, tmp_config, tmp_palace):
        repos = {"bad-wing": {"path": "/nonexistent/repo"}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with patch(
            "src.sync_engine.list_indexable_files", side_effect=SyncSourceError("repo not found")
        ):
            engine.full_sync()

        entry = engine.ledger.get("bad-wing")
        assert entry["status"] == "error"
        assert "repo not found" in entry["error"]

    def test_incremental_sync_no_changes(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        sha = get_head_sha(str(mock_repo))
        engine.ledger.update(
            "test-wing",
            {
                "repo_path": str(mock_repo),
                "last_commit_sha": sha,
                "last_sync_ts": "2026-04-15T10:00:00Z",
                "files_indexed": 1,
                "status": "synced",
                "prune": {"status": "ok"},
            },
        )

        with patch("src.sync_engine.process_file") as mock_process:
            engine.incremental_sync()

        mock_process.assert_not_called()

    def test_incremental_sync_with_changes(self, tmp_config, tmp_palace, mock_repo):
        repos = {"test-wing": {"path": str(mock_repo)}}
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        old_sha = get_head_sha(str(mock_repo))
        engine.ledger.update(
            "test-wing",
            {
                "repo_path": str(mock_repo),
                "last_commit_sha": old_sha,
                "last_sync_ts": "2026-04-15T10:00:00Z",
                "files_indexed": 1,
                "status": "synced",
            },
        )

        (mock_repo / "added.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=mock_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            cwd=mock_repo,
            capture_output=True,
        )

        with patch(
            "src.sync_engine.process_file", return_value=(1, "general", None)
        ) as mock_process:
            engine.incremental_sync()

        assert mock_process.call_count >= 1
        entry = engine.ledger.get("test-wing")
        assert entry["status"] == "synced"
        assert entry["last_commit_sha"] != old_sha

    def test_full_sync_specific_wing(self, tmp_config, tmp_palace, mock_repo):
        repos = {
            "test-wing": {"path": str(mock_repo)},
            "other-wing": {"path": "/other/repo"},
        }
        (Path(tmp_config) / "repos.json").write_text(json.dumps(repos))

        engine = SyncEngine(
            config_path=str(tmp_config),
            data_path=str(tmp_palace),
        )

        with (
            patch(
                "src.sync_engine.list_indexable_files", return_value=[mock_repo / "hello.py"]
            ) as mock_scan,
            patch("src.sync_engine.process_file", return_value=(1, "general", None)),
        ):
            engine.full_sync(wing_name="test-wing")

        mock_scan.assert_called_once()
        assert engine.ledger.get("test-wing") is not None
        assert engine.ledger.get("other-wing") is None


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    return path


def _commit_all(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")


def _rel(repo, files):
    return sorted(p.relative_to(repo).as_posix() for p in files)


class TestListIndexableFiles:
    def test_indexable_excludes_gitignored_dir(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / ".gitignore").write_text("output/\n")
        (repo / "output").mkdir()
        (repo / "output" / "dump.md").write_text("x")
        (repo / "keep.md").write_text("x")
        _commit_all(repo)
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["keep.md"]

    def test_indexable_includes_untracked_not_ignored(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "a.md").write_text("x")
        _commit_all(repo)
        (repo / "new.py").write_text("x")
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["a.md", "new.py"]

    def test_indexable_honors_git_info_exclude(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "exclude").write_text("secret.md\n")
        (repo / "secret.md").write_text("x")
        (repo / "open.md").write_text("x")
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["open.md"]

    def test_indexable_skips_nested_repo_dir(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "top.md").write_text("x")
        nested = _init_repo(repo / "wt")
        (nested / "inner.md").write_text("x")
        _commit_all(nested)
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["top.md"]

    def test_indexable_applies_upstream_filters(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "package-lock.json").write_text("{}")
        (repo / "logo.png").write_bytes(b"\x89PNG")
        (repo / "real.md").write_text("x")
        (repo / "link.md").symlink_to(repo / "real.md")
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "dep.js").write_text("x")
        (repo / "UPPER.MD").write_text("x")
        _commit_all(repo)
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["UPPER.MD", "real.md"]

    def test_indexable_unborn_head_lists_files(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "main.go").write_text("package main")
        (repo / "staged.md").write_text("x")
        _git(repo, "add", "staged.md")
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["main.go", "staged.md"]

    def test_indexable_drops_tracked_file_deleted_from_disk(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "gone.md").write_text("x")
        (repo / "here.md").write_text("x")
        _commit_all(repo)
        (repo / "gone.md").unlink()
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["here.md"]

    def test_indexable_unquoted_paths(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "café.md").write_text("x")
        (repo / "sp ace.md").write_text("x")
        _commit_all(repo)
        files = list_indexable_files(str(repo), {})
        assert sorted(f.name for f in files) == ["café.md", "sp ace.md"]
        assert all(f.is_file() for f in files)
        assert all(str(f).startswith(str(repo) + "/") for f in files)

    def test_indexable_config_exclude_patterns(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / ".claude" / ".cc-writes").mkdir(parents=True)
        (repo / ".claude" / ".cc-writes" / "w.json").write_text("{}")
        (repo / ".claude" / "settings.local.json").write_text("{}")
        (repo / ".claude" / "settings.json").write_text("{}")
        (repo / "sub" / ".claude").mkdir(parents=True)
        (repo / "sub" / ".claude" / "settings.local.json").write_text("{}")
        cfg = {"exclude": ["**/.claude/settings.local.json", "**/.claude/.cc-writes/**"]}
        assert _rel(repo, list_indexable_files(str(repo), cfg)) == [".claude/settings.json"]

    def test_indexable_data_size_cap_only_hits_data_extensions(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "big.json").write_text("x" * 200)
        (repo / "big.md").write_text("x" * 200)
        (repo / "small.csv").write_text("x" * 10)
        cfg = {"max_data_file_bytes": 100, "data_extensions": [".json", ".jsonl", ".csv"]}
        assert _rel(repo, list_indexable_files(str(repo), cfg)) == ["big.md", "small.csv"]
        assert _rel(repo, list_indexable_files(str(repo), {"max_data_file_bytes": None})) == [
            "big.json",
            "big.md",
            "small.csv",
        ]

    def test_indexable_raises_on_non_git_dir(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.md").write_text("x")
        with pytest.raises(SyncSourceError, match="(?i)not a git repository"):
            list_indexable_files(str(plain), {})

    def test_indexable_wraps_git_launch_failure(self, tmp_path):
        with patch("src.sync_engine.subprocess.run", side_effect=FileNotFoundError("git")):
            with pytest.raises(SyncSourceError, match="git"):
                list_indexable_files(str(tmp_path), {})

    def test_indexable_wraps_git_timeout(self, tmp_path):
        timeout = subprocess.TimeoutExpired(cmd="git", timeout=30)
        with patch("src.sync_engine.subprocess.run", side_effect=timeout) as run:
            with pytest.raises(SyncSourceError):
                list_indexable_files(str(tmp_path), {})
        assert run.call_args.kwargs["timeout"] == 30

    def test_indexable_accepts_missing_sync_block(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "a.md").write_text("x")
        assert _rel(repo, list_indexable_files(str(repo), None)) == ["a.md"]

    def test_indexable_extra_extensions(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "main.tf").write_text("x")
        (repo / "VARS.TF").write_text("x")
        (repo / "notes.hcl").write_text("x")
        (repo / "a.md").write_text("x")
        assert _rel(repo, list_indexable_files(str(repo), {})) == ["a.md"]
        cfg = {"extra_extensions": [".tf"]}
        assert _rel(repo, list_indexable_files(str(repo), cfg)) == ["VARS.TF", "a.md", "main.tf"]

    def test_indexable_extra_filenames(self, tmp_path):
        repo = _init_repo(tmp_path / "r")
        (repo / "Dockerfile").write_text("FROM python")
        (repo / "svc").mkdir()
        (repo / "svc" / "pom.xml").write_text("<project/>")
        (repo / "other.xml").write_text("<x/>")
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "Dockerfile").write_text("FROM node")
        assert _rel(repo, list_indexable_files(str(repo), {})) == []
        cfg = {"extra_filenames": ["Dockerfile", "pom.xml"]}
        assert _rel(repo, list_indexable_files(str(repo), cfg)) == ["Dockerfile", "svc/pom.xml"]


def _drawers(collection, rows):
    """Add (id, metadata) rows to a real Chroma collection with fixed embeddings."""
    for start in range(0, len(rows), 500):
        chunk = rows[start : start + 500]
        collection.add(
            ids=[r[0] for r in chunk],
            documents=["doc"] * len(chunk),
            metadatas=[r[1] for r in chunk],
            embeddings=[[0.1, 0.2, 0.3]] * len(chunk),
        )


def _ids(collection):
    return sorted(collection.get(include=[])["ids"])


@pytest.fixture
def prune_env(tmp_path, tmp_palace):
    repo = tmp_path / "repo"
    repo.mkdir()
    collection = get_collection(str(tmp_palace))
    return repo, collection


def _meta(wing, source=None, room="general"):
    meta = {"wing": wing, "room": room}
    if source is not None:
        meta["source_file"] = str(source)
    return meta


class TestPruneWing:
    def test_prune_removes_untracked_source(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("a", _meta("w", repo / "a.md")), ("b", _meta("w", repo / "build/out.md"))])
        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert report["status"] == "ok"
        assert report["removed"] == 1
        assert _ids(col) == ["a"]

    def test_prune_removes_drawers_for_deleted_files(self, prune_env):
        repo, col = prune_env
        _drawers(
            col,
            [
                ("gone1", _meta("w", repo / "gone.md")),
                ("gone2", _meta("w", repo / "gone.md")),
                ("here", _meta("w", repo / "here.md")),
            ],
        )
        report = prune_wing(col, "w", str(repo), {str(repo / "here.md")})
        assert report["removed"] == 2
        assert report["top_sources"][0] == {"source_file": str(repo / "gone.md"), "drawers": 2}
        assert _ids(col) == ["here"]

    def test_prune_keeps_drawers_without_source_file(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("nosrc", _meta("w")), ("a", _meta("w", repo / "a.md"))])
        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert report["no_source"] == 1
        assert report["removed"] == 0
        assert _ids(col) == ["a", "nosrc"]

    def test_prune_never_touches_other_wings(self, prune_env):
        repo, col = prune_env
        _drawers(
            col,
            [
                ("u", _meta("user", repo / "old.md")),
                ("ci", _meta("claude_imports", repo / "old.md")),
                ("w", _meta("w", repo / "old.md")),
                ("keep", _meta("w", repo / "a.md")),
            ],
        )
        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert report["scanned"] == 2
        assert _ids(col) == ["ci", "keep", "u"]

    def test_prune_keeps_source_outside_repo_path(self, prune_env, tmp_path):
        repo, col = prune_env
        sibling = tmp_path / "repo-other" / "x.md"
        _drawers(
            col,
            [
                ("out", _meta("w", sibling)),
                ("abs", _meta("w", "/elsewhere/y.md")),
                ("a", _meta("w", repo / "a.md")),
            ],
        )
        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert report["out_of_scope"] == 2
        assert _ids(col) == ["a", "abs", "out"]

    def test_prune_skips_registry_rows(self, prune_env):
        repo, col = prune_env
        _drawers(
            col,
            [
                ("_reg_w", _meta("w", repo / "gone.md")),
                ("r1", _meta("w", repo / "gone.md", room="_registry")),
                ("a", _meta("w", repo / "a.md")),
            ],
        )
        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert report["removed"] == 0
        assert _ids(col) == ["_reg_w", "a", "r1"]

    def test_prune_dry_run_deletes_nothing(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("a", _meta("w", repo / "a.md")), ("b", _meta("w", repo / "b.md"))])
        live = prune_wing(col, "w", str(repo), {str(repo / "a.md")}, dry_run=True)
        assert live["status"] == "ok"
        assert live["removed"] == 0
        assert live["would_remove"] == 1
        assert _ids(col) == ["a", "b"]

    def test_prune_pages_past_1000(self, prune_env):
        repo, col = prune_env
        rows = [(f"k{i}", _meta("w", repo / f"k{i}.md")) for i in range(1300)]
        rows += [(f"g{i}", _meta("w", repo / f"g{i}.md")) for i in range(200)]
        _drawers(col, rows)
        keep = {str(repo / f"k{i}.md") for i in range(1300)}
        report = prune_wing(col, "w", str(repo), keep)
        assert report["scanned"] == 1500
        assert report["removed"] == 200
        assert col.count() == 1300

    def test_prune_blocked_above_threshold(self, prune_env):
        repo, col = prune_env
        rows = [(f"g{i}", _meta("w", repo / f"g{i}.md")) for i in range(250)]
        rows += [(f"k{i}", _meta("w", repo / f"k{i}.md")) for i in range(50)]
        _drawers(col, rows)
        keep = {str(repo / f"k{i}.md") for i in range(50)}
        report = prune_wing(col, "w", str(repo), keep)
        assert report["status"] == "blocked"
        assert report["removed"] == 0
        assert "250" in report["reason"]
        assert "mems sync --allow-large-prune" in report["reason"]
        assert col.count() == 300

    def test_prune_below_threshold_applies(self, prune_env):
        repo, col = prune_env
        rows = [(f"g{i}", _meta("w", repo / f"g{i}.md")) for i in range(150)]
        rows += [(f"k{i}", _meta("w", repo / f"k{i}.md")) for i in range(50)]
        _drawers(col, rows)
        keep = {str(repo / f"k{i}.md") for i in range(50)}
        report = prune_wing(col, "w", str(repo), keep)
        assert report["status"] == "ok"
        assert col.count() == 50

    def test_prune_blocked_when_keep_empty(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("a", _meta("w", repo / "a.md"))])
        report = prune_wing(col, "w", str(repo), set())
        assert report["status"] == "blocked"
        assert "mems sync --allow-large-prune" in report["reason"]
        assert _ids(col) == ["a"]

    def test_prune_allow_large_applies(self, prune_env, tmp_palace):
        repo, col = prune_env
        closets = get_closets_collection(str(tmp_palace))
        rows = [(f"g{i}", _meta("w", repo / f"g{i}.md")) for i in range(250)]
        rows += [(f"k{i}", _meta("w", repo / f"k{i}.md")) for i in range(50)]
        _drawers(col, rows)
        _drawers(
            closets,
            [
                ("c-gone", _meta("w", repo / "g0.md")),
                ("c-keep", _meta("w", repo / "k0.md")),
                ("c-other", _meta("user", repo / "g0.md")),
            ],
        )
        keep = {str(repo / f"k{i}.md") for i in range(50)}
        report = prune_wing(col, "w", str(repo), keep, allow_large=True, closets=closets)
        assert report["status"] == "ok"
        assert report["removed"] == 250
        assert col.count() == 50
        assert _ids(closets) == ["c-keep", "c-other"]

    def test_prune_skipped_when_repo_missing(self, prune_env, tmp_path):
        _, col = prune_env
        _drawers(col, [("a", _meta("w", tmp_path / "nope" / "a.md"))])
        report = prune_wing(col, "w", str(tmp_path / "nope"), {"x"})
        assert report["status"] == "skipped"
        assert _ids(col) == ["a"]

    def test_prune_error_never_raises(self, prune_env):
        repo, _ = prune_env

        class Broken:
            def get(self, **kwargs):
                raise RuntimeError("boom")

        report = prune_wing(Broken(), "w", str(repo), {"x"})
        assert report["status"] == "error"
        assert "boom" in report["reason"]

    def test_prune_normalises_dotdot_repo_path(self, prune_env, tmp_path):
        repo, col = prune_env
        (tmp_path / "b").mkdir()
        dotted = str(tmp_path / "b" / ".." / "repo")
        _drawers(col, [("a", _meta("w", repo / "a.md")), ("b", _meta("w", f"{dotted}/b.md"))])
        keep = {f"{dotted}/a.md", f"{dotted}/b.md"}
        report = prune_wing(col, "w", dotted, keep)
        assert report["status"] == "ok"
        assert report["removed"] == 0
        assert report["would_remove"] == 0
        assert _ids(col) == ["a", "b"]

    def test_prune_reports_would_remove(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("a", _meta("w", repo / "a.md")), ("b", _meta("w", repo / "b.md"))])
        blocked = prune_wing(col, "w", str(repo), set())
        assert blocked["status"] == "blocked"
        assert blocked["would_remove"] == 2
        assert blocked["removed"] == 0
        ok = prune_wing(col, "w", str(repo), {str(repo / "a.md")})
        assert ok["would_remove"] == 1
        assert ok["removed"] == 1

    def test_prune_partial_delete_failure_reports_removed(self, prune_env):
        repo, col = prune_env
        rows = [(f"g{i}", _meta("w", repo / f"g{i}.md")) for i in range(1500)]
        rows += [("k", _meta("w", repo / "k.md"))]
        _drawers(col, rows)

        class FailSecondDelete:
            def __init__(self, inner):
                self.inner = inner
                self.deletes = 0

            def get(self, **kwargs):
                return self.inner.get(**kwargs)

            def delete(self, **kwargs):
                self.deletes += 1
                if self.deletes == 2:
                    raise RuntimeError("disk full")
                return self.inner.delete(**kwargs)

        report = prune_wing(
            FailSecondDelete(col), "w", str(repo), {str(repo / "k.md")}, allow_large=True
        )
        assert report["status"] == "error"
        assert report["removed"] == 1000
        assert report["scanned"] == 1501
        assert report["would_remove"] == 1500
        assert "disk full" in report["reason"]
        assert col.count() == 501

    def test_prune_closet_failure_deletes_no_drawers(self, prune_env):
        repo, col = prune_env
        _drawers(col, [("a", _meta("w", repo / "a.md")), ("b", _meta("w", repo / "b.md"))])

        class BrokenClosets:
            def delete(self, **kwargs):
                raise RuntimeError("closets down")

        report = prune_wing(col, "w", str(repo), {str(repo / "a.md")}, closets=BrokenClosets())
        assert report["status"] == "error"
        assert report["removed"] == 0
        assert report["scanned"] == 2
        assert _ids(col) == ["a", "b"]


def _fake_process_file(filepath, project_path, collection, wing, **kwargs):
    """Stand-in for upstream process_file that files one drawer per file with fixed embeddings."""
    source = str(filepath)
    if collection.get(where={"source_file": source}, include=[])["ids"]:
        return 0, "general", None
    collection.add(
        ids=[f"{wing}:{source}"],
        documents=[Path(filepath).read_text()],
        metadatas=[{"wing": wing, "room": "general", "source_file": source}],
        embeddings=[[0.1, 0.2, 0.3]],
    )
    return 1, "general", None


def _sources(tmp_palace, wing="w"):
    metas = get_collection(str(tmp_palace)).get(where={"wing": wing}, include=["metadatas"])
    return sorted(Path(m["source_file"]).name for m in metas["metadatas"])


@pytest.fixture
def reconcile_env(tmp_path, tmp_palace, monkeypatch):
    """A git repo registered as wing `w`, with process_file replaced by a fast fake."""
    repo = _init_repo(tmp_path / "repo")
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "repos.json").write_text(json.dumps({"w": {"path": str(repo)}}))
    (config / "mempalace.yaml").write_text("wings: {}\n")
    monkeypatch.setattr("src.sync_engine.process_file", _fake_process_file)

    def engine():
        return SyncEngine(config_path=str(config), data_path=str(tmp_palace))

    return repo, config, engine


class TestReconcile:
    def test_full_sync_records_prune_in_ledger(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        _drawers(get_collection(str(tmp_palace)), [("old", _meta("w", repo / "gone.md"))])

        eng = engine()
        assert eng.full_sync() == ["w"]

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "synced"
        assert entry["prune"]["status"] == "ok"
        assert entry["prune"]["removed"] == 1
        assert entry["prune"]["ts"]
        assert entry["last_run"] == {
            "indexed": 1,
            "skipped": 0,
            "removed": 1,
            "failed": 0,
            "failed_files": [],
        }
        assert _sources(tmp_palace) == ["a.md"]

    def test_sync_never_invokes_mempalace_cli(self, reconcile_env, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        calls = []
        real_run = subprocess.run

        def recording_run(cmd, *args, **kwargs):
            calls.append(cmd)
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr("src.sync_engine.subprocess.run", recording_run)
        eng = engine()
        eng.full_sync()
        (repo / "b.md").write_text("beta")
        eng.incremental_sync()

        assert calls
        assert all(c[0] == "git" for c in calls)

    def test_reconcile_rename_purges_old_and_indexes_new(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "old.md").write_text("same content " * 20)
        _commit_all(repo)
        engine().full_sync()
        _git(repo, "mv", "old.md", "new.md")
        _git(repo, "commit", "-qm", "rename")

        assert engine().incremental_sync() == ["w"]
        assert _sources(tmp_palace) == ["new.md"]

    def test_reconcile_unrelated_delete_and_add(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        body = "describe('utils', () => {\n" + "  it('works', () => expect(1).toBe(1));\n" * 20
        (repo / "manageUtils.test.ts").write_text(body + "});\n")
        _commit_all(repo)
        engine().full_sync()
        (repo / "manageUtils.test.ts").unlink()
        (repo / "collectionEditUtils.test.ts").write_text(body + "  it('edits');\n});\n")
        _commit_all(repo)

        engine().incremental_sync()
        assert _sources(tmp_palace) == ["collectionEditUtils.test.ts"]

    def test_reconcile_skips_non_indexable(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        (repo / "package-lock.json").write_text("{}")
        _commit_all(repo)
        _drawers(
            get_collection(str(tmp_palace)), [("lock", _meta("w", repo / "package-lock.json"))]
        )
        seen = []

        def spy(filepath, **kwargs):
            seen.append(Path(filepath).name)
            return _fake_process_file(filepath, **kwargs)

        monkeypatch.setattr("src.sync_engine.process_file", spy)
        engine().full_sync()

        assert seen == ["a.md"]
        assert _sources(tmp_palace) == ["a.md"]

    def test_reconcile_modified_to_symlink_purges_drawers(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        (repo / "b.md").write_text("beta")
        _commit_all(repo)
        engine().full_sync()
        (repo / "a.md").unlink()
        (repo / "a.md").symlink_to("b.md")
        _commit_all(repo)

        engine().incremental_sync()
        assert _sources(tmp_palace) == ["b.md"]

    def test_incremental_skips_wing_when_clean_and_unchanged(
        self, reconcile_env, tmp_palace, monkeypatch
    ):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        engine().full_sync()
        before = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        monkeypatch.setattr(
            "src.sync_engine.list_indexable_files",
            lambda *a, **k: pytest.fail("clean wing should be skipped"),
        )

        assert engine().incremental_sync() == []
        assert SyncLedger(tmp_palace / "sync_ledger.json").get("w") == before

    def test_incremental_runs_when_untracked_file_added(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        engine().full_sync()
        (repo / "notes.md").write_text("untracked notes")

        assert engine().incremental_sync() == ["w"]
        assert _sources(tmp_palace) == ["a.md", "notes.md"]
        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["last_run"] == {
            "indexed": 1,
            "skipped": 1,
            "removed": 0,
            "failed": 0,
            "failed_files": [],
        }

    def test_incremental_runs_when_last_prune_not_ok(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        eng = engine()
        eng.full_sync()
        eng.ledger.entries["w"]["prune"]["status"] = "blocked"
        eng.ledger.save()

        assert engine().incremental_sync() == ["w"]
        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["prune"]["status"] == "ok"

    def test_files_indexed_counts_kept_files(self, reconcile_env, tmp_palace):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        (repo / "b.py").write_text("x = 1")
        (repo / "package-lock.json").write_text("{}")
        (repo / "image.png").write_bytes(b"\x89PNG")
        _commit_all(repo)

        engine().full_sync()
        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["files_indexed"] == 2

    def test_sync_source_error_marks_only_that_wing(self, reconcile_env, tmp_path, tmp_palace):
        repo, config, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        not_git = tmp_path / "plain"
        not_git.mkdir()
        (not_git / "c.md").write_text("gamma")
        _drawers(get_collection(str(tmp_palace)), [("c", _meta("bad", not_git / "c.md"))])
        (config / "repos.json").write_text(
            json.dumps({"bad": {"path": str(not_git)}, "w": {"path": str(repo)}})
        )

        assert sorted(engine().full_sync()) == ["bad", "w"]
        ledger = SyncLedger(tmp_palace / "sync_ledger.json")
        assert ledger.get("bad")["status"] == "error"
        assert ledger.get("w")["status"] == "synced"
        assert _sources(tmp_palace, "bad") == ["c.md"]
        assert _sources(tmp_palace) == ["a.md"]

    def test_collection_opened_once_per_run(self, reconcile_env, tmp_path, monkeypatch):
        repo, config, engine = reconcile_env
        other = _init_repo(tmp_path / "other")
        (other / "o.md").write_text("other")
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        _commit_all(other)
        (config / "repos.json").write_text(
            json.dumps({"w": {"path": str(repo)}, "x": {"path": str(other)}})
        )
        opened = []
        real_get_collection = get_collection

        def counting(*args, **kwargs):
            opened.append(args)
            return real_get_collection(*args, **kwargs)

        monkeypatch.setattr("src.sync_engine.get_collection", counting)
        engine().full_sync()
        assert len(opened) == 1

    def test_ledger_records_head_read_before_listing(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        before = get_head_sha(str(repo))
        real_list = list_indexable_files

        def list_then_commit(repo_path, sync_cfg):
            files = real_list(repo_path, sync_cfg)
            (repo / "late.md").write_text("late")
            _commit_all(repo)
            return files

        monkeypatch.setattr("src.sync_engine.list_indexable_files", list_then_commit)
        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["last_commit_sha"] == before
        assert get_head_sha(str(repo)) != before

    def test_sync_passes_closets_to_process_file(self, reconcile_env, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        _commit_all(repo)
        seen = []

        def spy(filepath, **kwargs):
            seen.append(kwargs.get("closets_col"))
            return _fake_process_file(filepath, **kwargs)

        monkeypatch.setattr("src.sync_engine.process_file", spy)
        engine().full_sync()

        assert len(seen) == 1
        assert seen[0] is not None

    def test_one_bad_file_does_not_fail_wing(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        (repo / "sub").mkdir()
        (repo / "sub" / "bad.md").write_text("bad")
        (repo / "c.md").write_text("gamma")
        _commit_all(repo)

        def flaky(filepath, **kwargs):
            if Path(filepath).name == "bad.md":
                raise ValueError("x" * 500)
            return _fake_process_file(filepath, **kwargs)

        monkeypatch.setattr("src.sync_engine.process_file", flaky)
        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "synced"
        assert entry["last_commit_sha"] == get_head_sha(str(repo))
        assert entry["last_run"]["indexed"] == 2
        assert entry["last_run"]["failed"] == 1
        [failure] = entry["last_run"]["failed_files"]
        assert failure["file"] == "sub/bad.md"
        assert failure["error"].startswith("ValueError: xxx")
        assert len(failure["error"]) == 200
        assert _sources(tmp_palace) == ["a.md", "c.md"]

    def test_failed_files_list_is_capped(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "ok.md").write_text("fine")
        for i in range(30):
            (repo / f"bad{i:02}.md").write_text("bad")
        _commit_all(repo)

        def flaky(filepath, **kwargs):
            if Path(filepath).name.startswith("bad"):
                raise RuntimeError("nope")
            return _fake_process_file(filepath, **kwargs)

        monkeypatch.setattr("src.sync_engine.list_indexable_files", _ok_first(list_indexable_files))
        monkeypatch.setattr("src.sync_engine.process_file", flaky)
        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "synced"
        assert entry["last_run"]["failed"] == 30
        assert len(entry["last_run"]["failed_files"]) == 20
        assert _sources(tmp_palace) == ["ok.md"]

    def test_all_files_failing_marks_wing_error(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        for i in range(30):
            (repo / f"f{i:02}.md").write_text("x")
        _commit_all(repo)
        attempts = []

        def broken(filepath, **kwargs):
            attempts.append(filepath)
            raise ConnectionError("collection is gone")

        monkeypatch.setattr("src.sync_engine.process_file", broken)
        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "error"
        assert "ConnectionError: collection is gone" in entry["error"]
        assert len(attempts) == 25

    def test_few_files_all_failing_keeps_wing_synced(self, reconcile_env, tmp_palace, monkeypatch):
        repo, _, engine = reconcile_env
        (repo / "only.md").write_text("x")
        _commit_all(repo)

        def broken(filepath, **kwargs):
            raise ValueError("bad file")

        monkeypatch.setattr("src.sync_engine.process_file", broken)
        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "synced"
        assert entry["last_run"]["failed"] == 1

    def test_incremental_retries_wing_with_failed_files(
        self, reconcile_env, tmp_palace, monkeypatch
    ):
        repo, _, engine = reconcile_env
        (repo / "a.md").write_text("alpha")
        (repo / "b.md").write_text("beta")
        _commit_all(repo)

        def flaky(filepath, **kwargs):
            if Path(filepath).name == "b.md":
                raise ValueError("transient")
            return _fake_process_file(filepath, **kwargs)

        monkeypatch.setattr("src.sync_engine.process_file", flaky)
        engine().full_sync()
        monkeypatch.setattr("src.sync_engine.process_file", _fake_process_file)

        assert engine().incremental_sync() == ["w"]
        assert _sources(tmp_palace) == ["a.md", "b.md"]
        assert SyncLedger(tmp_palace / "sync_ledger.json").get("w")["last_run"]["failed"] == 0

    def test_dockerfile_gets_drawers(self, reconcile_env, tmp_palace, monkeypatch):
        repo, config, engine = reconcile_env
        (config / "mempalace.yaml").write_text(
            "sync:\n  extra_filenames: [Dockerfile]\nwings: {}\n"
        )
        (repo / "Dockerfile").write_text(
            "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            'CMD ["python", "-m", "src.mcp_http_server"]\n'
        )
        _commit_all(repo)
        monkeypatch.setattr("src.sync_engine.process_file", real_process_file)

        engine().full_sync()

        entry = SyncLedger(tmp_palace / "sync_ledger.json").get("w")
        assert entry["status"] == "synced"
        assert entry["last_run"]["indexed"] == 1
        assert _sources(tmp_palace) == ["Dockerfile"]


def _ok_first(real_list):
    """Wrap list_indexable_files so `ok.md` is processed first."""

    def ordered(repo_path, sync_cfg):
        return sorted(real_list(repo_path, sync_cfg), key=lambda p: p.name != "ok.md")

    return ordered


@pytest.fixture
def prune_cli_env(tmp_path, tmp_palace, monkeypatch):
    """Wing `w` with one kept and one stale drawer, plus a wing outside repos.json."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "a.md").write_text("alpha")
    _commit_all(repo)
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "repos.json").write_text(json.dumps({"w": {"path": str(repo)}}))
    (config / "mempalace.yaml").write_text("wings: {}\n")
    _drawers(
        get_collection(str(tmp_palace)),
        [
            ("keep", _meta("w", repo / "a.md")),
            ("stale", _meta("w", repo / "gone.md")),
            ("foreign", _meta("unlisted", repo / "gone.md")),
        ],
    )
    monkeypatch.setenv("PALACE_PATH", str(tmp_palace))
    monkeypatch.setenv("CONFIG_PATH", str(config))
    return repo, config


def _json_lines(out):
    return [json.loads(line) for line in out.splitlines() if line.strip()]


class TestPruneCli:
    def test_prune_cli_dry_run_by_default(self, prune_cli_env, tmp_palace, capsys):
        repo, _ = prune_cli_env

        assert main(["prune"]) == 0

        [line] = _json_lines(capsys.readouterr().out)
        assert line["wing"] == "w"
        assert line["status"] == "ok"
        assert line["dry_run"] is True
        assert line["would_remove"] == 1
        assert line["removed"] == 0
        assert line["top_sources"] == [{"source_file": str(repo / "gone.md"), "drawers": 1}]
        assert _ids(get_collection(str(tmp_palace))) == ["foreign", "keep", "stale"]

    def test_prune_cli_apply_force(self, prune_cli_env, tmp_palace, capsys):
        repo, _ = prune_cli_env
        (repo / "a.md").unlink()
        _commit_all(repo)

        assert main(["prune", "--apply"]) == 1
        [blocked] = _json_lines(capsys.readouterr().out)
        assert blocked["status"] == "blocked"
        assert "python -m src.sync_engine prune --apply --force" in blocked["reason"]
        assert "mems sync" not in blocked["reason"]
        assert _ids(get_collection(str(tmp_palace))) == ["foreign", "keep", "stale"]

        assert main(["prune", "--wing", "w", "--apply", "--force"]) == 0
        [applied] = _json_lines(capsys.readouterr().out)
        assert applied["status"] == "ok"
        assert applied["removed"] == 2
        assert _ids(get_collection(str(tmp_palace))) == ["foreign"]

    def test_prune_cli_unknown_wing(self, prune_cli_env, tmp_palace, capsys):
        assert main(["prune", "--wing", "unlisted", "--apply", "--force"]) == 2
        assert "unlisted" in capsys.readouterr().err
        assert _ids(get_collection(str(tmp_palace))) == ["foreign", "keep", "stale"]

    def test_prune_cli_source_error_reports_wing(self, prune_cli_env, tmp_path, capsys):
        _, config = prune_cli_env
        plain = tmp_path / "plain"
        plain.mkdir()
        (config / "repos.json").write_text(json.dumps({"bad": {"path": str(plain)}}))

        assert main(["prune"]) == 1
        [line] = _json_lines(capsys.readouterr().out)
        assert line["wing"] == "bad"
        assert line["status"] == "error"

    def test_prune_cli_runs_as_module(self, prune_cli_env):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "src.sync_engine", "prune"],
            cwd=root,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr
        [line] = _json_lines(result.stdout)
        assert line["would_remove"] == 1
