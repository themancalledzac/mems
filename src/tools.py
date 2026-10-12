"""MCP tool handlers for sync, navigation, search, and wing ops.

# mempalace public API map (verified 2026-04-17 against installed mempalace):
# - mempalace.palace.get_collection(palace_path, collection_name="mempalace_drawers",
#       create=True) -> chroma Collection
# - mempalace.palace.get_closets_collection(palace_path, create=True) -> Collection
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
#
# Phase 4B wiring (all upstream-wrapped via mempalace.mcp_server.tool_*):
#   All 4B handlers call _bind_palace(palace_path) first to set
#   MEMPALACE_PALACE_PATH. `_config.palace_path` is a property that re-reads
#   the env on every access, so chroma-backed tools (drawers, tunnels, search,
#   diary) respect the current target.
#
#   kg_query        -> wraps tool_kg_query (entity, as_of, direction)
#   kg_add          -> wraps tool_kg_add   (subject, predicate, object_, ...)
#   kg_time         -> wraps tool_kg_timeline (entity)
#   kg_stats        -> wraps tool_kg_stats ()
#   traverse        -> wraps tool_traverse_graph (start_room, max_hops)
#   find_tunnels    -> wraps tool_find_tunnels (wing_a, wing_b)
#   list_drawers    -> wraps tool_list_drawers (wing, room, limit, offset)
#   update_drawer   -> wraps tool_update_drawer (drawer_id, content, wing, room)
#   delete_drawer   -> wraps tool_delete_drawer (drawer_id)
#   create_tunnel   -> wraps tool_create_tunnel (source_wing, source_room, ...)
#   delete_tunnel   -> wraps tool_delete_tunnel (tunnel_id)
#   list_tunnels    -> wraps tool_list_tunnels (wing)
#   tunnel_read     -> wraps tool_follow_tunnels (wing, room) — plan name
#                      "tunnel_read" maps to upstream "follow_tunnels"
#   diary_write     -> wraps tool_diary_write (agent_name, entry, topic)
#   diary_read      -> wraps tool_diary_read (agent_name, last_n)
#
# Plan item kg_time_kv was not wirable — there is no upstream tool_kg_time_kv
# and no obvious KG method for timeline-with-key-value filtering. Skipped.
# Plan item "kg_drawer" likewise had no upstream analog and no clear semantics
# distinct from kg_add; skipped.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mempalace.palace import get_collection
from mempalace.searcher import search_memories

from src.sync_engine import SyncEngine, SyncLedger
from src.wing_pack import write_wingpack

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIM = 384

_FETCH_PAGE = 1000
_SYNC_LOCK = threading.Lock()


def handle_sync(
    config_path: str,
    data_path: str,
    wing: str | None = None,
    full: bool = False,
    allow_large_prune: bool = False,
) -> dict:
    """Sync repos into the palace and report only the wings this run touched.

    Status is `partial` when a wing errored, a file failed to index (listed per wing under
    `failed`), or a prune was `error` or `blocked`.
    Runs one at a time per process, since each run rewrites the ledger and the collection.
    """
    with _SYNC_LOCK:
        return _sync_locked(config_path, data_path, wing, full, allow_large_prune)


def _sync_locked(
    config_path: str, data_path: str, wing: str | None, full: bool, allow_large_prune: bool
) -> dict:
    engine = SyncEngine(config_path=config_path, data_path=data_path)

    if wing and wing not in engine.repos:
        return {"status": "error", "message": f"Unknown wing: {wing}"}

    if full or not engine.ledger.entries:
        touched = engine.full_sync(wing_name=wing, allow_large_prune=allow_large_prune)
    else:
        touched = engine.incremental_sync(wing_name=wing, allow_large_prune=allow_large_prune)

    synced: list[str] = []
    errors: list[dict] = []
    prune: dict[str, dict] = {}
    failed: dict[str, dict] = {}
    for name in touched:
        entry = engine.ledger.get(name) or {}
        if entry.get("status") == "synced":
            synced.append(name)
        else:
            errors.append({"wing": name, "error": entry.get("error", "unknown")})
        if entry.get("prune"):
            prune[name] = entry["prune"]
        run = entry.get("last_run") or {}
        if run.get("failed"):
            failed[name] = {"count": run["failed"], "files": run.get("failed_files") or []}

    bad_prune = any(r.get("status") in ("error", "blocked") for r in prune.values())
    status = "partial" if errors or bad_prune or failed else "ok"
    return {
        "status": status,
        "synced": synced,
        "errors": errors,
        "prune": prune,
        "failed": failed,
    }


def handle_sync_status(config_path: str, data_path: str) -> dict:
    """Handle memory_sync_status tool call."""
    ledger = SyncLedger(f"{data_path}/sync_ledger.json")
    return {"wings": ledger.entries}


def _drawers_collection(palace_path: str):
    """Open the shared drawers collection, creating it if missing.

    Matches the pattern in src.user_wing.UserWing — both write to the same
    `mempalace_drawers` collection, distinguished by metadata.
    """
    return get_collection(palace_path, collection_name="mempalace_drawers", create=True)


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
    return meta.get("timestamp") or meta.get("created_at") or meta.get("ts") or ""


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


def handle_resync(
    config_path: str,
    data_path: str,
    full_refresh: bool = False,
    allow_large_prune: bool = False,
) -> dict:
    """Ops-level resync. Delegates to handle_sync with full=full_refresh."""
    result = handle_sync(
        config_path=config_path,
        data_path=data_path,
        wing=None,
        full=full_refresh,
        allow_large_prune=allow_large_prune,
    )
    result["full_refresh"] = full_refresh
    return result


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


def _bind_palace(palace_path: str) -> None:
    """Set MEMPALACE_PALACE_PATH so subsequent mempalace tool calls hit the right palace.

    Both chroma collections and the knowledge graph are resolved per-call from
    the env var (upstream 3.3.5 #1136 + #1383), so this is sufficient for
    multi-tenant hosts that rotate palaces between tool invocations.
    """
    os.environ["MEMPALACE_PALACE_PATH"] = palace_path


def handle_kg_query(
    palace_path: str,
    entity: str,
    as_of: str | None = None,
    direction: str = "both",
) -> dict:
    """Query KG for relationships involving an entity."""
    from mempalace.mcp_server import tool_kg_query

    _bind_palace(palace_path)
    return tool_kg_query(entity=entity, as_of=as_of, direction=direction)


def handle_kg_add(
    palace_path: str,
    subject: str,
    predicate: str,
    object_: str,
    valid_from: str | None = None,
    source_closet: str | None = None,
) -> dict:
    """Add a triple to the KG.

    ``object_`` is renamed internally to dodge the Python builtin; upstream
    expects ``object``.
    """
    from mempalace.mcp_server import tool_kg_add

    _bind_palace(palace_path)
    return tool_kg_add(
        subject=subject,
        predicate=predicate,
        object=object_,
        valid_from=valid_from,
        source_closet=source_closet,
    )


def handle_kg_time(palace_path: str, entity: str | None = None) -> dict:
    """Chronological KG timeline, optionally scoped to one entity."""
    from mempalace.mcp_server import tool_kg_timeline

    _bind_palace(palace_path)
    return tool_kg_timeline(entity=entity)


def handle_kg_stats(palace_path: str) -> dict:
    """KG overview: entity/triple/relation counts."""
    from mempalace.mcp_server import tool_kg_stats

    _bind_palace(palace_path)
    return tool_kg_stats()


def handle_traverse(palace_path: str, start_room: str, max_hops: int = 2) -> dict:
    """Walk the palace graph from a starting room."""
    from mempalace.mcp_server import tool_traverse_graph

    _bind_palace(palace_path)
    return tool_traverse_graph(start_room=start_room, max_hops=max_hops)


def handle_find_tunnels(
    palace_path: str,
    wing_a: str | None = None,
    wing_b: str | None = None,
) -> dict:
    """Find bridge-rooms between two wings."""
    from mempalace.mcp_server import tool_find_tunnels

    _bind_palace(palace_path)
    return tool_find_tunnels(wing_a=wing_a, wing_b=wing_b)


def handle_list_drawers(
    palace_path: str,
    wing: str | None = None,
    room: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List drawers with pagination, optional wing/room filter."""
    from mempalace.mcp_server import tool_list_drawers

    _bind_palace(palace_path)
    return tool_list_drawers(wing=wing, room=room, limit=limit, offset=offset)


def handle_update_drawer(
    palace_path: str,
    drawer_id: str,
    content: str | None = None,
    wing: str | None = None,
    room: str | None = None,
) -> dict:
    """Update an existing drawer's content and/or metadata."""
    from mempalace.mcp_server import tool_update_drawer

    _bind_palace(palace_path)
    return tool_update_drawer(drawer_id=drawer_id, content=content, wing=wing, room=room)


def handle_delete_drawer(palace_path: str, drawer_id: str) -> dict:
    """Delete a drawer by id."""
    from mempalace.mcp_server import tool_delete_drawer

    _bind_palace(palace_path)
    return tool_delete_drawer(drawer_id=drawer_id)


def handle_create_tunnel(
    palace_path: str,
    source_wing: str,
    source_room: str,
    target_wing: str,
    target_room: str,
    label: str = "",
    source_drawer_id: str | None = None,
    target_drawer_id: str | None = None,
) -> dict:
    """Create an explicit cross-wing tunnel."""
    from mempalace.mcp_server import tool_create_tunnel

    _bind_palace(palace_path)
    return tool_create_tunnel(
        source_wing=source_wing,
        source_room=source_room,
        target_wing=target_wing,
        target_room=target_room,
        label=label,
        source_drawer_id=source_drawer_id,
        target_drawer_id=target_drawer_id,
    )


def handle_delete_tunnel(palace_path: str, tunnel_id: str) -> dict:
    """Delete an explicit tunnel by id."""
    from mempalace.mcp_server import tool_delete_tunnel

    _bind_palace(palace_path)
    return tool_delete_tunnel(tunnel_id=tunnel_id)


def handle_list_tunnels(palace_path: str, wing: str | None = None) -> dict:
    """List explicit cross-wing tunnels."""
    from mempalace.mcp_server import tool_list_tunnels

    _bind_palace(palace_path)
    return tool_list_tunnels(wing=wing)


def handle_tunnel_read(palace_path: str, wing: str, room: str) -> dict:
    """Follow tunnels from a room to see connected drawers in other wings.

    Wraps upstream ``tool_follow_tunnels``. The plan's ``tunnel_read`` name
    matches the "read what's on the other side of the tunnel" semantics.
    """
    from mempalace.mcp_server import tool_follow_tunnels

    _bind_palace(palace_path)
    return tool_follow_tunnels(wing=wing, room=room)


def handle_diary_write(
    palace_path: str,
    agent_name: str,
    entry: str,
    topic: str = "general",
    wing: str = "",
) -> dict:
    """Append a diary entry for an agent. Optionally scope to a specific wing."""
    from mempalace.mcp_server import tool_diary_write

    _bind_palace(palace_path)
    return tool_diary_write(agent_name=agent_name, entry=entry, topic=topic, wing=wing)


def handle_diary_read(
    palace_path: str,
    agent_name: str,
    last_n: int = 10,
    wing: str = "",
) -> dict:
    """Read an agent's recent diary entries. Empty wing returns entries from every wing."""
    from mempalace.mcp_server import tool_diary_read

    _bind_palace(palace_path)
    return tool_diary_read(agent_name=agent_name, last_n=last_n, wing=wing)
