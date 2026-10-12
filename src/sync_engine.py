"""Multi-repo sync: list each wing's files, prune the rest, index what is kept."""

import argparse
import json
import os
import subprocess
import sys
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
    should_skip_dir,
)
from mempalace.palace import get_closets_collection, get_collection

GIT_TIMEOUT_S = 30
PRUNE_BATCH = 1000
LARGE_PRUNE_FRACTION = 0.5
LARGE_PRUNE_MIN = 200
LARGE_PRUNE_OVERRIDE = "mems sync --allow-large-prune"
CLI_PRUNE_OVERRIDE = "python -m src.sync_engine prune --apply --force"


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
    override_hint: str = LARGE_PRUNE_OVERRIDE,
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
                    "blocked", f"{reason}; run `{override_hint}` to apply it", **counts
                )

        if dry_run:
            counts["kept"] = scanned - len(doomed)
            return _prune_report("ok", dry_run=True, **counts)

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
    """HEAD commit SHA for a repo, or None when git fails or there are no commits."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def worktree_is_clean(repo_path: str) -> bool:
    """True when `git status --porcelain` reports no modified or untracked files."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and not result.stdout.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncEngine:
    """Syncs the repos in repos.json into the palace. The repos.json key is the wing name."""

    def __init__(self, config_path: str, data_path: str):
        self.config_path = Path(config_path)
        self.data_path = Path(data_path)
        self.ledger = SyncLedger(self.data_path / "sync_ledger.json")

        with open(self.config_path / "repos.json") as f:
            self.repos: dict = json.load(f)

        with open(self.config_path / "mempalace.yaml") as f:
            self.taxonomy: dict = yaml.safe_load(f) or {}

    def full_sync(self, wing_name: str | None = None, allow_large_prune: bool = False) -> list[str]:
        """Reconcile every wing (or one) with its repo and return the wing names processed.

        Indexes committed and untracked-but-not-ignored files as they are on disk, and
        prunes drawers for files the repo no longer has. A wing whose repo cannot be
        listed is marked as an error and left untouched.
        """
        return self._run(self._targets(wing_name), allow_large_prune)

    def incremental_sync(
        self, wing_name: str | None = None, allow_large_prune: bool = False
    ) -> list[str]:
        """Like `full_sync`, but skips wings with nothing new and returns only the wings run.

        A wing is skipped only when HEAD matches the ledger, its last prune was `ok`, and
        `git status --porcelain` is empty. Unchanged files are cheap: `process_file` skips
        them by mtime.
        """
        targets = {
            name: cfg
            for name, cfg in self._targets(wing_name).items()
            if not self._is_current(name, cfg)
        }
        return self._run(targets, allow_large_prune)

    def _targets(self, wing_name: str | None) -> dict:
        return {wing_name: self.repos[wing_name]} if wing_name else dict(self.repos)

    def _is_current(self, name: str, repo_config: dict) -> bool:
        entry = self.ledger.get(name)
        if not entry or entry.get("status") != "synced":
            return False
        if (entry.get("prune") or {}).get("status") != "ok":
            return False
        repo_path = repo_config["path"]
        head = get_head_sha(repo_path)
        return (
            head is not None
            and head == entry.get("last_commit_sha")
            and worktree_is_clean(repo_path)
        )

    def _run(self, targets: dict, allow_large_prune: bool) -> list[str]:
        if not targets:
            return []
        try:
            collection = get_collection(str(self.data_path))
        except Exception as exc:
            for name, repo_config in targets.items():
                self.ledger.mark_error(name, repo_config["path"], f"palace unavailable: {exc}")
            self.ledger.save()
            return list(targets)
        try:
            closets = get_closets_collection(str(self.data_path))
        except Exception:
            closets = None

        for name, repo_config in targets.items():
            self._sync_one(name, repo_config, collection, allow_large_prune, closets=closets)
        self.ledger.save()
        return list(targets)

    def _sync_one(
        self, name: str, repo_config: dict, collection, allow_large_prune: bool, *, closets=None
    ) -> dict:
        """List the wing's files, prune drawers for the rest, index the kept files.

        Returns the new ledger entry. Any failure marks only this wing as an error.
        """
        repo_path = repo_config["path"]
        try:
            head = get_head_sha(repo_path)
            keep = list_indexable_files(repo_path, self.taxonomy.get("sync") or {})
            prune = prune_wing(
                collection,
                name,
                repo_path,
                {str(p) for p in keep},
                allow_large=allow_large_prune,
                closets=closets,
            )
            rooms = _flatten_rooms(self.taxonomy.get("wings", {}).get(name, {}) or {})
            indexed = skipped = 0
            for filepath in keep:
                drawers, _room, _skip = process_file(
                    filepath=filepath,
                    project_path=Path(repo_path),
                    collection=collection,
                    wing=name,
                    rooms=rooms,
                    agent="memory-sync",
                    dry_run=False,
                    closets_col=closets,
                )
                if drawers:
                    indexed += 1
                else:
                    skipped += 1
            entry = {
                "repo_path": repo_path,
                "last_commit_sha": head,
                "last_sync_ts": _now(),
                "files_indexed": len(keep),
                "status": "synced",
                "prune": {**prune, "ts": _now()},
                "last_run": {"indexed": indexed, "skipped": skipped, "removed": prune["removed"]},
            }
            self.ledger.update(name, entry)
            return entry
        except Exception as exc:
            self.ledger.mark_error(name, repo_path, str(exc))
            return self.ledger.get(name)


def prune_registered_wings(
    config_path: str,
    palace_path: str,
    wing_name: str | None = None,
    *,
    apply: bool = False,
    force: bool = False,
) -> list[dict]:
    """Run `prune_wing` for each wing in repos.json (or one) and return one report per wing.

    A dry run unless `apply`. `force` passes `allow_large`. Wings not in repos.json are
    never touched; an unknown `wing_name` raises ValueError.
    """
    config = Path(config_path)
    repos = json.loads((config / "repos.json").read_text())
    if wing_name and wing_name not in repos:
        raise ValueError(f"wing not in repos.json: {wing_name}")
    taxonomy = yaml.safe_load((config / "mempalace.yaml").read_text()) or {}
    targets = {wing_name: repos[wing_name]} if wing_name else repos
    collection = get_collection(palace_path, create=False)
    closets = None
    if apply:
        try:
            closets = get_closets_collection(palace_path, create=False)
        except Exception:
            closets = None

    reports = []
    for name, repo_config in targets.items():
        repo_path = repo_config["path"]
        try:
            keep = list_indexable_files(repo_path, taxonomy.get("sync") or {})
        except SyncSourceError as exc:
            report = _prune_report("error", str(exc))
        else:
            report = prune_wing(
                collection,
                name,
                repo_path,
                {str(p) for p in keep},
                dry_run=not apply,
                allow_large=force,
                closets=closets,
                override_hint=CLI_PRUNE_OVERRIDE,
            )
        reports.append({"wing": name, "repo_path": repo_path, **report})
    return reports


def main(argv: list[str] | None = None) -> int:
    """`python -m src.sync_engine prune`: print one JSON line per wing. Exit 1 on error or block.

    Reads PALACE_PATH and CONFIG_PATH like the server. Stop the server before `--apply`, so
    the palace has one writer.
    """
    parser = argparse.ArgumentParser(prog="python -m src.sync_engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    prune_p = sub.add_parser("prune", help="Remove drawers for files a repo no longer has.")
    prune_p.add_argument("--wing", default=None, help="Only this wing from repos.json.")
    prune_p.add_argument("--apply", action="store_true", help="Delete. Default is a dry run.")
    prune_p.add_argument("--force", action="store_true", help="Allow large prunes.")
    prune_p.add_argument("--palace", default=os.environ.get("PALACE_PATH", "/data/palace"))
    prune_p.add_argument("--config", default=os.environ.get("CONFIG_PATH", "/config"))
    args = parser.parse_args(argv)

    try:
        reports = prune_registered_wings(
            args.config, args.palace, args.wing, apply=args.apply, force=args.force
        )
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for report in reports:
        print(json.dumps(report))
    return 1 if any(r["status"] in ("error", "blocked") for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
