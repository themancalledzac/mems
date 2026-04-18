"""MCP tool handlers for sync, navigation, search, and wing ops.

# mempalace public API map (verified 2026-04-17 against installed mempalace):
# - mempalace.palace.get_collection(palace_path, collection_name="mempalace_drawers",
#       create=True) -> chroma Collection
# - mempalace.palace.get_closets_collection(palace_path, create=False) -> Collection
# - mempalace.searcher.search_memories(query, palace_path, wing=None, room=None,
#       n_results=5, max_distance=0.0) -> dict    (hybrid drawers+closets search)
# - mempalace.searcher.build_where_filter(wing=None, room=None) -> dict
# - mempalace.exporter.export_palace(...)         (palace-wide export, not wing-scoped)
# - mempalace.mcp_server.tool_status / tool_list_wings / tool_list_rooms /
#       tool_check_duplicate / tool_search / ...  — these exist but bind to a
#       module-level _config singleton initialized from MEMPALACE_PALACE_PATH at
#       import time. They cannot be safely retargeted to an arbitrary palace_path
#       at call time, so we re-implement the Phase 4A handlers locally against the
#       shared `mempalace_drawers` collection with the palace_path argument we own.
#
# Per-tool wiring (Phase 4A):
#   mempalace_status          -> local (uses get_collection + paged metadata)
#   mempalace_list_wings      -> local (distinct `wing` metadata values)
#   mempalace_list_rooms      -> local (distinct `room` metadata values, wing filter)
#   mempalace_check_logs      -> local (collection.query over check content)
#   mempalace_get_logs_recent -> local (collection.get sorted by timestamp desc)
#   mempalace_search          -> wraps mempalace.searcher.search_memories
#   mempalace_search_all      -> wraps mempalace.searcher.search_memories (no filters)
#   mempalace_resync          -> delegates to handle_sync (full=full_refresh)
#   mempalace_export_wing     -> local: assembles wing_meta, calls wing_pack.write_wingpack
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mempalace.palace import get_collection
from mempalace.searcher import search_memories

from src.sync_engine import SyncEngine, SyncLedger
from src.wing_pack import write_wingpack

# Default embedding model/dim for wingpack export — matches mempalace defaults.
# Flagged in the Phase 4A report: introspecting model/dim from a live chroma
# Collection is not reliable across versions, so we hardcode these.
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384

# Keep metadata fetches paged; chroma silently truncates large .get() calls.
_FETCH_PAGE = 1000


# --- existing sync handlers --------------------------------------------------


def handle_sync(
    config_path: str,
    data_path: str,
    wing: str | None = None,
    full: bool = False,
) -> dict:
    """Handle memory_sync tool call."""
    engine = SyncEngine(config_path=config_path, data_path=data_path)

    if wing and wing not in engine.repos:
        return {"status": "error", "message": f"Unknown wing: {wing}"}

    if full or not SyncLedger(f"{data_path}/sync_ledger.json").entries:
        engine.full_sync(wing_name=wing)
    else:
        engine.incremental_sync(wing_name=wing)

    synced = []
    errors = []
    for name, entry in engine.ledger.entries.items():
        if entry["status"] == "synced":
            synced.append(name)
        elif entry["status"] == "error":
            errors.append({"wing": name, "error": entry.get("error", "unknown")})

    return {"status": "ok", "synced": synced, "errors": errors}


def handle_sync_status(config_path: str, data_path: str) -> dict:
    """Handle memory_sync_status tool call."""
    ledger = SyncLedger(f"{data_path}/sync_ledger.json")
    return {"wings": ledger.entries}


# --- internal helpers --------------------------------------------------------


def _drawers_collection(palace_path: str):
    """Open the shared drawers collection, creating it if missing.

    Matches the pattern in src.user_wing.UserWing — both write to the same
    `mempalace_drawers` collection, distinguished by metadata.
    """
    return get_collection(
        palace_path, collection_name="mempalace_drawers", create=True
    )


def _fetch_all_metadata(col, where: dict | None = None) -> list[dict]:
    """Paginate col.get() to avoid chroma's 10K silent truncation."""
    try:
        total = col.count()
    except Exception:
        return []
    all_meta: list[dict] = []
    offset = 0
    while offset < total:
        kwargs: dict[str, Any] = {
            "include": ["metadatas"],
            "limit": _FETCH_PAGE,
            "offset": offset,
        }
        if where:
            kwargs["where"] = where
        try:
            batch = col.get(**kwargs)
        except Exception:
            break
        metas = batch.get("metadatas") or []
        if not metas:
            break
        all_meta.extend(metas)
        offset += len(metas)
    return all_meta


def _ts_of(meta: dict) -> str:
    """Pick the best timestamp-ish field we have. Empty string if absent."""
    return (
        meta.get("timestamp")
        or meta.get("created_at")
        or meta.get("ts")
        or ""
    )


# --- navigation handlers -----------------------------------------------------


def handle_status(palace_path: str) -> dict:
    """Palace overview — total drawers plus counts by wing and room."""
    col = _drawers_collection(palace_path)
    try:
        total = col.count()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "palace_path": palace_path}

    wings: dict[str, int] = {}
    rooms: dict[str, int] = {}
    for meta in _fetch_all_metadata(col):
        wings[meta.get("wing", "unknown")] = wings.get(meta.get("wing", "unknown"), 0) + 1
        rooms[meta.get("room", "unknown")] = rooms.get(meta.get("room", "unknown"), 0) + 1
    return {
        "ok": True,
        "palace_path": palace_path,
        "total_drawers": total,
        "wings": wings,
        "rooms": rooms,
    }


def handle_list_wings(palace_path: str) -> list[dict]:
    """Distinct wings with drawer counts. Returns a list for stable ordering."""
    col = _drawers_collection(palace_path)
    counts: dict[str, int] = {}
    for meta in _fetch_all_metadata(col):
        name = meta.get("wing", "unknown")
        counts[name] = counts.get(name, 0) + 1
    return [{"wing": w, "drawers": n} for w, n in sorted(counts.items())]


def handle_list_rooms(palace_path: str, wing: str | None = None) -> list[dict]:
    """Distinct rooms (optionally filtered to one wing) with drawer counts."""
    col = _drawers_collection(palace_path)
    where = {"wing": wing} if wing else None
    counts: dict[str, int] = {}
    for meta in _fetch_all_metadata(col, where=where):
        name = meta.get("room", "unknown")
        counts[name] = counts.get(name, 0) + 1
    return [{"room": r, "drawers": n} for r, n in sorted(counts.items())]


def handle_check_logs(
    palace_path: str,
    content: str,
    threshold: float = 0.9,
) -> dict:
    """Check whether similar content already exists in the palace.

    Returns the top hit and a `duplicate` flag computed from cosine similarity
    (1 - distance). Duplicate is True iff similarity >= threshold.
    """
    col = _drawers_collection(palace_path)
    try:
        res = col.query(
            query_texts=[content],
            n_results=1,
            include=["metadatas", "documents", "distances"],
        )
    except Exception as exc:
        return {"duplicate": False, "top": None, "error": str(exc)}

    if not res.get("ids") or not res["ids"][0]:
        return {"duplicate": False, "top": None}

    distance = res["distances"][0][0]
    similarity = round(1.0 - distance, 4)
    top_doc = res["documents"][0][0]
    top = {
        "id": res["ids"][0][0],
        "similarity": similarity,
        "distance": distance,
        "metadata": res["metadatas"][0][0] if res.get("metadatas") else {},
        "content": top_doc[:300] + ("..." if len(top_doc) > 300 else ""),
    }
    return {"duplicate": similarity >= threshold, "threshold": threshold, "top": top}


def handle_get_logs_recent(palace_path: str, n: int = 10) -> list[dict]:
    """Return the N most recently timestamped drawers."""
    col = _drawers_collection(palace_path)
    try:
        total = col.count()
    except Exception:
        return []
    if total == 0:
        return []

    # Fetch everything paged — chroma can't sort server-side on metadata.
    entries: list[dict] = []
    offset = 0
    while offset < total:
        try:
            batch = col.get(
                include=["metadatas", "documents"],
                limit=_FETCH_PAGE,
                offset=offset,
            )
        except Exception:
            break
        ids = batch.get("ids") or []
        metas = batch.get("metadatas") or []
        docs = batch.get("documents") or []
        if not ids:
            break
        for i, drawer_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            entries.append(
                {
                    "id": drawer_id,
                    "metadata": meta,
                    "content": docs[i] if i < len(docs) else "",
                    "_ts": _ts_of(meta),
                }
            )
        offset += len(ids)

    entries.sort(key=lambda e: e["_ts"], reverse=True)
    out = []
    for e in entries[: max(0, n)]:
        e.pop("_ts", None)
        out.append(e)
    return out


# --- search handlers ---------------------------------------------------------


def handle_search(
    palace_path: str,
    query: str,
    slug: str | None = None,
    wing: str | None = None,
    room: str | None = None,
    n: int = 10,
) -> dict:
    """Semantic search over the palace. `slug` is accepted as a wing alias.

    Delegates to mempalace.searcher.search_memories which does hybrid
    (drawers + closets) retrieval.
    """
    effective_wing = wing or slug
    return search_memories(
        query,
        palace_path=palace_path,
        wing=effective_wing,
        room=room,
        n_results=n,
    )


def handle_search_all(palace_path: str, query: str, n: int = 10) -> dict:
    """Unfiltered semantic search across every wing."""
    return search_memories(query, palace_path=palace_path, n_results=n)


# --- ops ---------------------------------------------------------------------


def handle_resync(
    config_path: str,
    data_path: str,
    full_refresh: bool = False,
    output_dir: str | None = None,  # noqa: ARG001 — accepted for API symmetry
) -> dict:
    """Ops-level resync. Delegates to handle_sync with full=full_refresh."""
    result = handle_sync(
        config_path=config_path,
        data_path=data_path,
        wing=None,
        full=full_refresh,
    )
    result["full_refresh"] = full_refresh
    return result


# --- wing sharing ------------------------------------------------------------


def handle_export_wing(
    palace_path: str,
    slug: str,
    output_dir: str | Path | None = None,
) -> dict:
    """Assemble wing metadata from the live collection and write a .wingpack.

    Uses the default exports dir (`<palace_path>/exports`) when output_dir
    isn't supplied.
    """
    col = _drawers_collection(palace_path)
    metas = _fetch_all_metadata(col, where={"wing": slug})

    rooms: dict[str, dict] = {}
    for meta in metas:
        room_name = meta.get("room", "unknown")
        entry = rooms.setdefault(room_name, {"name": room_name, "keywords": set(), "tags": set()})
        for kw in meta.get("keywords", []) if isinstance(meta.get("keywords"), list) else []:
            entry["keywords"].add(kw)
        for tag in meta.get("tags", []) if isinstance(meta.get("tags"), list) else []:
            entry["tags"].add(tag)

    rooms_list = [
        {
            "name": r["name"],
            "keywords": sorted(r["keywords"]),
            "tags": sorted(r["tags"]),
        }
        for r in sorted(rooms.values(), key=lambda x: x["name"])
    ]

    wing_meta = {
        "name": slug,
        "drawer_count": len(metas),
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "embedding_dim": DEFAULT_EMBEDDING_DIM,
        "rooms": rooms_list,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    target_dir = Path(output_dir) if output_dir else Path(palace_path) / "exports"
    bundle_path = write_wingpack(wing_meta, target_dir)
    return {
        "path": str(bundle_path),
        "slug": slug,
        "drawer_count": wing_meta["drawer_count"],
        "room_count": len(rooms_list),
    }
