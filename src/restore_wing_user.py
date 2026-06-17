"""Auto-restore the user_wing slice from the most recent JSON backup on cold boot.

This module is intentionally narrow. For general palace recovery (HNSW corruption,
chromadb segment quarantine, drawer loss from source-file deletion), use upstream's
``mempalace repair --mode from-sqlite`` instead — added in 3.3.5 #1308. That mode
reads (id, document, metadata) directly from chroma.sqlite3 and re-upserts into a
fresh palace, which is a strict superset of what we used to do here.

What this module owns:
  - Loading ``exports/wing_user_backup.YYYYMMDD.json`` (written by wing_user_snapshot.py)
  - Re-inserting user-wing drawers with deterministic IDs (idempotent)
  - The empty-wing-user precondition check that gates restoration

wing_user is a wrapper-unique concept (halls: questions / discoveries / frustrations /
goals / decisions / observations) with no source repo to re-mine from — that's why
this module exists separately from ``mempalace repair``.
"""

import json
from pathlib import Path

from mempalace.palace import get_collection


def _newest_backup(exports_dir: Path) -> Path | None:
    exports_dir = Path(exports_dir)
    if not exports_dir.exists():
        return None
    backups = sorted(
        exports_dir.glob("wing_user_backup_*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    return backups[0] if backups else None


def _wing_user_count(palace_path: Path) -> int:
    """Number of drawers currently in wing_user.

    Unlike the snapshot reader, this deliberately does NOT swallow read errors.
    The restore guard must distinguish a genuinely empty wing (count 0) from a
    transient read failure (exception) so it can fail CLOSED on the latter —
    treating an unreadable wing as "empty" would replay a backup over live data.
    ``create=True`` means a fresh palace yields an empty collection (count 0)
    rather than an error, so real cold-boot restores still fire.
    """
    collection = get_collection(str(palace_path), collection_name="mempalace_drawers", create=True)
    raw = collection.get(where={"wing": "user"})
    return len(raw.get("ids") or [])


def _reinsert_drawers(palace_path: Path, drawers: list[dict]) -> None:
    """Re-insert drawers into wing_user via the same collection abstraction."""
    collection = get_collection(str(palace_path), collection_name="mempalace_drawers", create=True)
    collection.upsert(
        ids=[d["id"] for d in drawers],
        documents=[d["content"] for d in drawers],
        metadatas=[d["metadata"] for d in drawers],
    )


def restore_if_empty(palace_path: Path, exports_dir: Path) -> dict:
    """Re-insert wing_user drawers from newest backup if wing_user is empty.

    Fails CLOSED: if wing_user's state cannot be read, restore is skipped rather
    than assuming the wing is empty — a transient read error must never trigger
    a replay over a live, non-empty wing_user.
    """
    try:
        count = _wing_user_count(palace_path)
    except Exception as exc:  # noqa: BLE001 — any read failure → skip (fail-closed)
        return {
            "action": "skipped",
            "reason": f"wing_user state unreadable; skipping restore (fail-closed): {exc}",
        }

    if count > 0:
        return {"action": "skipped", "reason": "wing_user not empty"}

    backup = _newest_backup(exports_dir)
    if backup is None:
        return {"action": "skipped", "reason": "no backup available"}

    try:
        data = json.loads(backup.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"action": "skipped", "reason": f"backup unreadable: {exc}"}

    drawers = data.get("drawers") or []
    if not drawers:
        return {"action": "skipped", "reason": "backup empty"}

    _reinsert_drawers(palace_path, drawers)
    return {
        "action": "restored",
        "drawers_restored": len(drawers),
        "source": str(backup),
    }


def main() -> None:
    import os

    palace = Path(os.environ.get("PALACE_PATH", "/data"))
    exports = Path(os.environ.get("MEMPALACE_EXPORTS_DIR", "/exports"))
    print(restore_if_empty(palace, exports))


if __name__ == "__main__":
    main()
