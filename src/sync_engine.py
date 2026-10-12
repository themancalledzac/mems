"""Multi-repo git-diff sync orchestrator."""

import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from mempalace.miner import (
    MAX_FILE_SIZE,
    READABLE_EXTENSIONS,
    SKIP_FILENAMES,
    GitignoreMatcher,
    process_file,
    scan_project,
    should_skip_dir,
)
from mempalace.palace import get_collection

GIT_TIMEOUT_S = 30
PRUNE_BATCH = 1000
LARGE_PRUNE_FRACTION = 0.5
LARGE_PRUNE_MIN = 200
LARGE_PRUNE_OVERRIDE = "mems sync --allow-large-prune"


class SyncSourceError(Exception):
    """A wing's repo could not be listed, so nothing should be pruned from it."""


def _flatten_rooms(wing_def: dict) -> list:
    """Flatten halls.<hall>.rooms into a single list for process_file."""
    halls = wing_def.get("halls", {}) or {}
    flat = []
    for hall_def in halls.values():
        for room in hall_def.get("rooms", []) or []:
            flat.append(room)
    return flat


def list_indexable_files(repo_path: str, sync_cfg: dict) -> list[Path]:
    """Files to keep for a wing: git ls-files -z --cached --others --exclude-standard, filtered.

    Raises SyncSourceError when git fails, is missing or times out. A None `sync_cfg`
    means no `sync:` block in the config. Paths are `Path(repo_path) / rel` and are
    never resolved, so they match stored `source_file` values.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncSourceError(f"git ls-files failed for {repo_path}: {exc}") from exc
    if result.returncode != 0:
        raise SyncSourceError(result.stderr.decode("utf-8", errors="replace").strip())

    sync_cfg = sync_cfg or {}
    root = Path(repo_path)
    exclude = sync_cfg.get("exclude") or []
    exclude_matcher = GitignoreMatcher.from_patterns(root, exclude) if exclude else None
    data_cap = sync_cfg.get("max_data_file_bytes")
    data_exts = {e.lower() for e in sync_cfg.get("data_extensions") or []}

    rels = dict.fromkeys(
        r for r in result.stdout.decode("utf-8", errors="surrogateescape").split("\0") if r
    )
    files = []
    for rel in rels:
        if rel.endswith("/"):
            continue
        parts = rel.split("/")
        if parts[-1] in SKIP_FILENAMES or any(should_skip_dir(d) for d in parts[:-1]):
            continue
        path = root / rel
        suffix = path.suffix.lower()
        if suffix not in READABLE_EXTENSIONS:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_SIZE:
            continue
        if data_cap is not None and suffix in data_exts and size > data_cap:
            continue
        if exclude_matcher and exclude_matcher.matches(path, is_dir=False):
            continue
        files.append(path)
    return files


def _prune_report(status: str, reason: str = "", **counts) -> dict:
    report = {
        "status": status,
        "scanned": 0,
        "removed": 0,
        "would_remove": 0,
        "kept": 0,
        "no_source": 0,
        "out_of_scope": 0,
        "top_sources": [],
        "reason": reason,
    }
    report.update(counts)
    return report


def _norm_path(path: str) -> str:
    return os.path.normpath(path)


def prune_wing(
    collection,
    wing: str,
    repo_path: str,
    keep: set[str],
    *,
    dry_run: bool = False,
    allow_large: bool = False,
    closets=None,
) -> dict:
    """Delete this wing's drawers whose `source_file` is under `repo_path` but not in `keep`.

    Drawers with no source, sources outside the repo, and registry rows are kept. Refuses
    (status `blocked`) when `keep` is empty or the removal is large, unless `allow_large`.
    Never raises; on failure it returns status `error` with `removed` set to what was
    actually deleted. Closets for removed files in this wing are purged first, when given.
    """
    counts: dict = {}
    removed = 0
    try:
        if not os.path.isdir(repo_path):
            return _prune_report("skipped", f"repo path not found: {repo_path}")

        prefix = _norm_path(repo_path) + "/"
        norm_keep = {_norm_path(k) for k in keep}
        scanned = no_source = out_of_scope = 0
        doomed: list[str] = []
        doomed_sources: Counter = Counter()
        offset = 0
        while True:
            page = collection.get(
                where={"wing": wing}, include=["metadatas"], limit=PRUNE_BATCH, offset=offset
            )
            ids = page["ids"] or []
            if not ids:
                break
            for drawer_id, meta in zip(ids, page["metadatas"] or [{}] * len(ids)):
                scanned += 1
                meta = meta or {}
                source = meta.get("source_file")
                norm_source = _norm_path(source) if source else ""
                if not source:
                    no_source += 1
                elif not norm_source.startswith(prefix):
                    out_of_scope += 1
                elif meta.get("room") == "_registry" or drawer_id.startswith("_reg_"):
                    continue
                elif norm_source not in norm_keep:
                    doomed.append(drawer_id)
                    doomed_sources[source] += 1
            if len(ids) < PRUNE_BATCH:
                break
            offset += PRUNE_BATCH

        counts = {
            "scanned": scanned,
            "would_remove": len(doomed),
            "kept": scanned,
            "no_source": no_source,
            "out_of_scope": out_of_scope,
            "top_sources": [
                {"source_file": src, "drawers": n} for src, n in doomed_sources.most_common(10)
            ],
        }
        if not allow_large:
            reason = ""
            if not keep and scanned:
                reason = f"keep list is empty; {len(doomed)} of {scanned} drawers would be removed"
            elif len(doomed) > LARGE_PRUNE_MIN and len(doomed) > scanned * LARGE_PRUNE_FRACTION:
                reason = f"prune would remove {len(doomed)} of {scanned} drawers"
            if reason:
                return _prune_report(
                    "blocked", f"{reason}; run `{LARGE_PRUNE_OVERRIDE}` to apply it", **counts
                )

        if dry_run:
            counts["kept"] = scanned - len(doomed)
            return _prune_report("ok", removed=len(doomed), dry_run=True, **counts)

        sources = list(doomed_sources)
        if closets is not None:
            for start in range(0, len(sources), PRUNE_BATCH):
                closets.delete(
                    where={
                        "$and": [
                            {"wing": wing},
                            {"source_file": {"$in": sources[start : start + PRUNE_BATCH]}},
                        ]
                    }
                )
        for start in range(0, len(doomed), PRUNE_BATCH):
            batch = doomed[start : start + PRUNE_BATCH]
            collection.delete(ids=batch)
            removed += len(batch)
        counts["kept"] = scanned - removed
        return _prune_report("ok", removed=removed, dry_run=False, **counts)
    except Exception as exc:
        if counts:
            counts["kept"] = counts["scanned"] - removed
        return _prune_report("error", f"{type(exc).__name__}: {exc}", removed=removed, **counts)


class SyncLedger:
    """Manages sync_ledger.json — tracks per-repo sync state."""

    def __init__(self, ledger_path: str | Path):
        self.ledger_path = Path(ledger_path)
        self.entries: dict = {}
        if self.ledger_path.exists():
            self.entries = json.loads(self.ledger_path.read_text())

    def get(self, wing_name: str) -> dict | None:
        return self.entries.get(wing_name)

    def update(self, wing_name: str, entry: dict):
        self.entries[wing_name] = entry

    def mark_error(self, wing_name: str, repo_path: str, error_msg: str):
        self.entries[wing_name] = {
            "repo_path": repo_path,
            "last_commit_sha": None,
            "last_sync_ts": datetime.now(timezone.utc).isoformat(),
            "files_indexed": 0,
            "status": "error",
            "error": error_msg,
        }

    def save(self):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(self.entries, indent=2))


def get_head_sha(repo_path: str) -> str | None:
    """Get HEAD commit SHA for a repo. Returns None if repo is invalid."""
    result = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_changed_files(repo_path: str, since_sha: str) -> dict:
    """Get files changed since a commit SHA. Returns {added, modified, deleted} lists."""
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-status", since_sha, "HEAD"],
        capture_output=True,
        text=True,
    )
    changes = {"added": [], "modified": [], "deleted": []}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, filepath = parts[0], parts[1]
        if status.startswith("A"):
            changes["added"].append(filepath)
        elif status.startswith("M"):
            changes["modified"].append(filepath)
        elif status.startswith("D"):
            changes["deleted"].append(filepath)
    return changes


class SyncEngine:
    """Orchestrates multi-repo sync using mempalace mining."""

    def __init__(self, config_path: str, data_path: str):
        self.config_path = Path(config_path)
        self.data_path = Path(data_path)
        self.ledger = SyncLedger(self.data_path / "sync_ledger.json")

        with open(self.config_path / "repos.json") as f:
            self.repos: dict = json.load(f)

        with open(self.config_path / "mempalace.yaml") as f:
            self.taxonomy: dict = yaml.safe_load(f)

    def full_sync(self, wing_name: str | None = None):
        """Run full mine on all repos (or a specific wing).

        Uses scan_project + process_file instead of mine() because repos
        are mounted read-only and mine() expects a mempalace.yaml in each repo.
        """
        targets = {wing_name: self.repos[wing_name]} if wing_name else self.repos

        for name, repo_config in targets.items():
            repo_path = repo_config["path"]
            try:
                files = scan_project(repo_path)
                collection = get_collection(str(self.data_path))
                wing_def = self.taxonomy.get("wings", {}).get(name, {})
                wing_rooms = _flatten_rooms(wing_def)

                for filepath in files:
                    process_file(
                        filepath=Path(filepath),
                        project_path=Path(repo_path),
                        collection=collection,
                        wing=name,
                        rooms=wing_rooms,
                        agent="memory-sync",
                        dry_run=False,
                    )

                head_sha = get_head_sha(repo_path)
                self.ledger.update(
                    name,
                    {
                        "repo_path": repo_path,
                        "last_commit_sha": head_sha,
                        "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                        "files_indexed": len(files),
                        "status": "synced",
                    },
                )
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self._post_ingest_prune()
        self.ledger.save()

    def incremental_sync(self, wing_name: str | None = None):
        """Sync only files changed since last sync."""
        targets = {wing_name: self.repos[wing_name]} if wing_name else self.repos

        for name, repo_config in targets.items():
            entry = self.ledger.get(name)
            if not entry or entry.get("status") == "error" or not entry.get("last_commit_sha"):
                self.full_sync(wing_name=name)
                continue

            repo_path = repo_config["path"]
            try:
                head_sha = get_head_sha(repo_path)
                if head_sha == entry["last_commit_sha"]:
                    continue

                changes = get_changed_files(repo_path, entry["last_commit_sha"])
                collection = get_collection(str(self.data_path))
                wing_def = self.taxonomy.get("wings", {}).get(name, {})
                wing_rooms = _flatten_rooms(wing_def)

                for filepath in changes["deleted"]:
                    full_path = str(Path(repo_path) / filepath)
                    self._delete_drawers_for_file(collection, full_path)

                for filepath in changes["added"] + changes["modified"]:
                    full_path = Path(repo_path) / filepath
                    if full_path.exists():
                        process_file(
                            filepath=full_path,
                            project_path=Path(repo_path),
                            collection=collection,
                            wing=name,
                            rooms=wing_rooms,
                            agent="memory-sync",
                            dry_run=False,
                        )

                prev_count = entry.get("files_indexed", 0)
                self.ledger.update(
                    name,
                    {
                        "repo_path": repo_path,
                        "last_commit_sha": head_sha,
                        "last_sync_ts": datetime.now(timezone.utc).isoformat(),
                        "files_indexed": prev_count
                        + len(changes["added"])
                        - len(changes["deleted"]),
                        "status": "synced",
                    },
                )
            except Exception as e:
                self.ledger.mark_error(name, repo_path, str(e))

        self._post_ingest_prune()
        self.ledger.save()

    def _post_ingest_prune(self) -> None:
        """Prune drawers whose source files were gitignored/deleted/moved.

        Upstream cmd_sync handles this — runs against the same palace_path the
        wrapper just wrote to (MEMPALACE_PALACE_PATH already set via _bind_palace).
        Non-fatal: ingest already succeeded. Log + continue on failure.
        """
        try:
            subprocess.run(
                ["mempalace", "sync", "--apply"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            print(f"warning: post-ingest mempalace sync skipped: {exc}", flush=True)

    def _delete_drawers_for_file(self, collection, source_file: str):
        """Remove all drawers originating from a deleted file."""
        try:
            results = collection.get(where={"source_file": source_file})
            if results and results.get("ids"):
                collection.delete(ids=results["ids"])
        except Exception:
            pass
