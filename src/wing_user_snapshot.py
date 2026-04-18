"""Daily snapshot of wing_user to JSON.

Writes ``exports/wing_user_backup_YYYYMMDD.json`` and prunes backups older than
the retention window. Idempotent per UTC day — re-running overwrites the same
dated file.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mempalace.palace import get_collection

BACKUP_RE = re.compile(r"wing_user_backup_(\d{8})\.json$")


def _read_all_wing_user(palace_path: Path) -> list[dict]:
    """Return every drawer in wing_user as a list of {id, content, metadata}.

    Mirrors the access pattern in ``src.user_wing.UserWing`` — opens the
    shared ``mempalace_drawers`` collection and filters by ``wing == "user"``.
    Keeping this aligned with UserWing is what guarantees restore round-trips.
    """
    collection = get_collection(
        str(palace_path), collection_name="mempalace_drawers", create=True
    )
    try:
        raw = collection.get(where={"wing": "user"})
    except Exception:
        return []

    ids = raw.get("ids") or []
    docs = raw.get("documents") or []
    metas = raw.get("metadatas") or []
    return [
        {"id": rid, "content": doc, "metadata": meta}
        for rid, doc, meta in zip(ids, docs, metas)
    ]


def snapshot_wing_user(palace_path: Path, exports_dir: Path) -> Path:
    """Dump all wing_user drawers to a dated JSON file. Idempotent per day."""
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = exports_dir / f"wing_user_backup_{ts}.json"

    drawers = _read_all_wing_user(palace_path)
    payload = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "drawer_count": len(drawers),
        "drawers": drawers,
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def prune_snapshots(exports_dir: Path, retention_days: int) -> list[Path]:
    """Delete wing_user_backup_*.json files older than retention_days.

    ``retention_days=N`` keeps the last N UTC days (today, today-1, ..., today-(N-1)).
    Returns the list of pruned paths.
    """
    exports_dir = Path(exports_dir)
    if not exports_dir.exists():
        return []

    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=retention_days - 1)

    pruned: list[Path] = []
    for p in exports_dir.glob("wing_user_backup_*.json"):
        m = BACKUP_RE.search(p.name)
        if not m:
            continue
        try:
            dt_date = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if dt_date < cutoff_date:
            p.unlink()
            pruned.append(p)
    return pruned


def main() -> None:
    import os

    palace = Path(os.environ.get("PALACE_PATH", "/data"))
    exports = Path(os.environ.get("MEMPALACE_EXPORTS_DIR", "/exports"))
    retention = int(os.environ.get("MEMPALACE_EXPORTS_RETENTION", "7"))
    out = snapshot_wing_user(palace, exports)
    pruned = prune_snapshots(exports, retention)
    print(f"snapshot: {out} (pruned {len(pruned)} old backups)")


if __name__ == "__main__":
    main()
