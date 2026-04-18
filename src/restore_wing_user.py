"""Auto-restore wing_user from newest backup when the collection is empty.

Intended to run at startup (from entrypoint.sh) so that a fresh palace
volume is seeded from the most recent ``wing_user_backup_*.json`` dump.
"""

import json
from pathlib import Path

from mempalace.palace import get_collection

from src.wing_user_snapshot import _read_all_wing_user


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


def _wing_user_is_empty(palace_path: Path) -> bool:
    """True if wing_user has no drawers. Mirrors the snapshot reader."""
    try:
        drawers = _read_all_wing_user(palace_path)
    except Exception:
        return True  # palace not initialized yet
    return len(drawers) == 0


def _reinsert_drawers(palace_path: Path, drawers: list[dict]) -> None:
    """Re-insert drawers into wing_user via the same collection abstraction."""
    collection = get_collection(str(palace_path), collection_name="mempalace_drawers", create=True)
    collection.upsert(
        ids=[d["id"] for d in drawers],
        documents=[d["content"] for d in drawers],
        metadatas=[d["metadata"] for d in drawers],
    )


def restore_if_empty(palace_path: Path, exports_dir: Path) -> dict:
    """Re-insert wing_user drawers from newest backup if wing_user is empty."""
    if not _wing_user_is_empty(palace_path):
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
