"""StreamableHTTP MCP server composing mempalace + custom tools."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.tools import (
    handle_check_logs,
    handle_create_tunnel,
    handle_delete_drawer,
    handle_delete_tunnel,
    handle_diary_read,
    handle_diary_write,
    handle_export_wing,
    handle_find_tunnels,
    handle_get_logs_recent,
    handle_kg_add,
    handle_kg_query,
    handle_kg_stats,
    handle_kg_time,
    handle_list_drawers,
    handle_list_rooms,
    handle_list_tunnels,
    handle_list_wings,
    handle_resync,
    handle_search,
    handle_search_all,
    handle_status,
    handle_sync,
    handle_sync_status,
    handle_traverse,
    handle_tunnel_read,
    handle_update_drawer,
)
from src.user_wing import UserWing


def palace_path_default() -> str:
    """Resolve the default palace path from env with a safe fallback."""
    return os.environ.get("PALACE_PATH", "/data")


def config_path_default() -> str:
    """Resolve the default config path from env with a safe fallback."""
    return os.environ.get("CONFIG_PATH", "/config")


def create_server(
    palace_path: str | None = None,
    config_path: str | None = None,
) -> FastMCP:
    """Create and configure the FastMCP server with all tools.

    Tools are registered by hand, so new upstream tools never appear on their own.
    Upstream tool_mine, tool_list_hallways and tool_delete_hallway are left out on purpose:
    syncing goes through memory_sync, and cross-wing links use tunnels.
    """
    palace_path = palace_path or palace_path_default()
    config_path = config_path or config_path_default()

    mcp = FastMCP(
        "Memory Palace",
        host="0.0.0.0",
        port=int(os.environ.get("MEMORY_PORT", "8787")),
    )

    user_wing = UserWing(palace_path=palace_path)

    @mcp.tool()
    def mempalace_user_write(
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
        origin: str = "agent",
        status: str | None = None,
        personal: bool = False,
        session_id: str | None = None,
    ) -> dict:
        """File a user thought into a hall. A near-duplicate keeps its text and gains a revision.

        Halls: questions, discoveries, frustrations, goals, decisions, observations.
        origin: agent|prompt|orch. status: open|active|parked|done|superseded (goals and
        questions default to open).
        """
        return user_wing.write(
            hall=hall,
            content=content,
            topic=topic,
            source_wing=source_wing,
            origin=origin,
            status=status,
            personal=personal,
            session_id=session_id,
        )

    @mcp.tool()
    def mempalace_user_search(
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
        since_days: float | None = None,
        source_wing: str | None = None,
        include_unscoped: bool = True,
        status: str | None = None,
        include_personal: bool = True,
        recency_weight: float = 0.1,
    ) -> dict:
        """Semantic search across the User Wing, re-ranked so recently touched entries win ties."""
        return user_wing.search(
            query=query,
            hall=hall,
            topic=topic,
            n_results=n_results,
            since_days=since_days,
            source_wing=source_wing,
            include_unscoped=include_unscoped,
            status=status,
            include_personal=include_personal,
            recency_weight=recency_weight,
        )

    @mcp.tool()
    def mempalace_user_recent(
        days: float = 7,
        source_wing: str | None = None,
        include_unscoped: bool = True,
        hall: str | None = None,
        status: str | None = None,
        include_personal: bool = True,
        n: int = 20,
    ) -> dict:
        """User Wing entries touched in the last `days`, newest first."""
        return user_wing.recent(
            days=days,
            source_wing=source_wing,
            include_unscoped=include_unscoped,
            hall=hall,
            status=status,
            include_personal=include_personal,
            n=n,
        )

    @mcp.tool()
    def mempalace_user_set_status(drawer_id: str, status: str) -> dict:
        """Set a User Wing entry's status: open|active|parked|done|superseded."""
        return user_wing.set_status(drawer_id=drawer_id, status=status)

    @mcp.tool()
    def mempalace_user_summary(
        source_wing: str | None = None,
        max_item_chars: int = 300,
    ) -> dict:
        """Compact user context for agent wake-up: open ideas, then the newest entries per hall."""
        return user_wing.summary(source_wing=source_wing, max_item_chars=max_item_chars)

    @mcp.tool()
    def mempalace_user_status() -> dict:
        """Hall counts, recent topics, and protocol guidance for agents."""
        return user_wing.status()

    @mcp.tool()
    def mempalace_user_merge_topics(
        source_topic: str,
        target_topic: str,
        hall: str | None = None,
    ) -> dict:
        """Merge drifted topics — rewrite metadata, deduplicate."""
        return user_wing.merge_topics(
            source_topic=source_topic,
            target_topic=target_topic,
            hall=hall,
        )

    @mcp.tool()
    def mempalace_user_prune(
        hall: str | None = None,
        topic: str | None = None,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> dict:
        """Remove stale/low-value thoughts by age, similarity, or cluster."""
        return user_wing.prune(
            hall=hall,
            topic=topic,
            older_than_days=older_than_days,
            dry_run=dry_run,
        )

    @mcp.tool()
    def memory_sync(
        wing: str | None = None,
        full: bool = False,
    ) -> dict:
        """Sync repos into the palace. Incremental by default, full if requested."""
        return handle_sync(
            config_path=config_path,
            data_path=palace_path,
            wing=wing,
            full=full,
        )

    @mcp.tool()
    def memory_sync_status() -> dict:
        """Show sync status for all registered repos."""
        return handle_sync_status(
            config_path=config_path,
            data_path=palace_path,
        )

    @mcp.tool()
    def mempalace_status() -> dict:
        """Palace overview — total drawers plus counts by wing and room."""
        return handle_status(palace_path)

    @mcp.tool()
    def mempalace_list_wings() -> list[dict]:
        """List every wing in the palace with its drawer count."""
        return handle_list_wings(palace_path)

    @mcp.tool()
    def mempalace_list_rooms(wing: str | None = None) -> list[dict]:
        """List rooms. If `wing` is given, limit to that wing."""
        return handle_list_rooms(palace_path, wing=wing)

    @mcp.tool()
    def mempalace_check_logs(content: str, threshold: float = 0.9) -> dict:
        """Check whether content is a near-duplicate of an existing drawer."""
        return handle_check_logs(palace_path, content=content, threshold=threshold)

    @mcp.tool()
    def mempalace_get_logs_recent(n: int = 10) -> list[dict]:
        """Return the N most recently timestamped drawers (newest first)."""
        return handle_get_logs_recent(palace_path, n=n)

    @mcp.tool()
    def mempalace_search(
        query: str,
        slug: str | None = None,
        wing: str | None = None,
        room: str | None = None,
        n: int = 10,
    ) -> dict:
        """Semantic search. `slug` is an alias for `wing`."""
        return handle_search(
            palace_path,
            query=query,
            slug=slug,
            wing=wing,
            room=room,
            n=n,
        )

    @mcp.tool()
    def mempalace_search_all(query: str, n: int = 10) -> dict:
        """Unfiltered semantic search across every wing."""
        return handle_search_all(palace_path, query=query, n=n)

    @mcp.tool()
    def mempalace_resync(
        full_refresh: bool = False,
        output_dir: str | None = None,
    ) -> dict:
        """Resync all registered wings. Pass full_refresh=True to ignore the ledger."""
        return handle_resync(
            config_path=config_path,
            data_path=palace_path,
            full_refresh=full_refresh,
            output_dir=output_dir,
        )

    @mcp.tool()
    def mempalace_export_wing(slug: str) -> dict:
        """Export a wing as a portable .wingpack bundle."""
        return handle_export_wing(palace_path, slug=slug)

    @mcp.tool()
    def mempalace_kg_query(
        entity: str,
        as_of: str | None = None,
        direction: str = "both",
    ) -> dict:
        """Query the knowledge graph for relationships involving an entity."""
        return handle_kg_query(palace_path, entity=entity, as_of=as_of, direction=direction)

    @mcp.tool()
    def mempalace_kg_add(
        subject: str,
        predicate: str,
        object: str,
        valid_from: str | None = None,
        source_closet: str | None = None,
    ) -> dict:
        """Add a (subject, predicate, object) triple to the knowledge graph."""
        return handle_kg_add(
            palace_path,
            subject=subject,
            predicate=predicate,
            object_=object,
            valid_from=valid_from,
            source_closet=source_closet,
        )

    @mcp.tool()
    def mempalace_kg_time(entity: str | None = None) -> dict:
        """Chronological timeline of KG facts, optionally for a single entity."""
        return handle_kg_time(palace_path, entity=entity)

    @mcp.tool()
    def mempalace_kg_stats() -> dict:
        """Knowledge graph overview: entities, triples, relation types."""
        return handle_kg_stats(palace_path)

    @mcp.tool()
    def mempalace_traverse(start_room: str, max_hops: int = 2) -> dict:
        """Walk the palace graph from a starting room."""
        return handle_traverse(palace_path, start_room=start_room, max_hops=max_hops)

    @mcp.tool()
    def mempalace_find_tunnels(
        wing_a: str | None = None,
        wing_b: str | None = None,
    ) -> dict:
        """Find rooms that bridge two wings."""
        return handle_find_tunnels(palace_path, wing_a=wing_a, wing_b=wing_b)

    @mcp.tool()
    def mempalace_list_drawers(
        wing: str | None = None,
        room: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """List drawers with pagination. Optional wing/room filter."""
        return handle_list_drawers(
            palace_path,
            wing=wing,
            room=room,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def mempalace_update_drawer(
        drawer_id: str,
        content: str | None = None,
        wing: str | None = None,
        room: str | None = None,
    ) -> dict:
        """Update an existing drawer's content and/or metadata."""
        return handle_update_drawer(
            palace_path,
            drawer_id=drawer_id,
            content=content,
            wing=wing,
            room=room,
        )

    @mcp.tool()
    def mempalace_delete_drawer(drawer_id: str) -> dict:
        """Delete a single drawer by ID."""
        return handle_delete_drawer(palace_path, drawer_id=drawer_id)

    @mcp.tool()
    def mempalace_create_tunnel(
        source_wing: str,
        source_room: str,
        target_wing: str,
        target_room: str,
        label: str = "",
        source_drawer_id: str | None = None,
        target_drawer_id: str | None = None,
    ) -> dict:
        """Create an explicit cross-wing tunnel between two rooms."""
        return handle_create_tunnel(
            palace_path,
            source_wing=source_wing,
            source_room=source_room,
            target_wing=target_wing,
            target_room=target_room,
            label=label,
            source_drawer_id=source_drawer_id,
            target_drawer_id=target_drawer_id,
        )

    @mcp.tool()
    def mempalace_delete_tunnel(tunnel_id: str) -> dict:
        """Delete an explicit tunnel by its ID."""
        return handle_delete_tunnel(palace_path, tunnel_id=tunnel_id)

    @mcp.tool()
    def mempalace_list_tunnels(wing: str | None = None) -> dict:
        """List explicit cross-wing tunnels, optionally filtered by wing."""
        return handle_list_tunnels(palace_path, wing=wing)

    @mcp.tool()
    def mempalace_tunnel_read(wing: str, room: str) -> dict:
        """Follow tunnels from a room to see connected drawers in other wings."""
        return handle_tunnel_read(palace_path, wing=wing, room=room)

    @mcp.tool()
    def mempalace_diary_write(
        agent_name: str,
        entry: str,
        topic: str = "general",
        wing: str = "",
    ) -> dict:
        """Append a diary entry for an agent. Optionally scope to a specific wing."""
        return handle_diary_write(
            palace_path,
            agent_name=agent_name,
            entry=entry,
            topic=topic,
            wing=wing,
        )

    @mcp.tool()
    def mempalace_diary_read(agent_name: str, last_n: int = 10, wing: str = "") -> dict:
        """Read an agent's recent diary entries. Empty wing returns entries from every wing."""
        return handle_diary_read(
            palace_path,
            agent_name=agent_name,
            last_n=last_n,
            wing=wing,
        )

    return mcp


def _attach_health_route(server: FastMCP, palace_path: str | None = None) -> None:
    """Mount GET /health on the streamable-http Starlette app.

    FastMCP doesn't expose /health natively. Using its `custom_route`
    decorator registers the route on `_custom_starlette_routes`, which
    `streamable_http_app()` picks up every time the app is built.
    Returns 200 with wing summary on success, 503 on any error — the
    Docker healthcheck and K8s probes can both key off the status code.
    """
    from datetime import datetime, timezone

    from starlette.responses import JSONResponse

    resolved = palace_path or palace_path_default()

    @server.custom_route("/health", methods=["GET"])
    async def health(_request):  # noqa: ARG001 — Starlette requires the arg
        try:
            wings = handle_list_wings(resolved)
            return JSONResponse(
                {
                    "ok": True,
                    "wings": wings,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


def _snapshot_cycle(palace_path: str, exports_dir: str, retention_days: int):
    """Run one wing_user snapshot + prune pass. Best-effort — never raises.

    Returns the snapshot path on success, or None if the cycle failed (a failed
    snapshot must never take down the timer thread that calls it).
    """
    from src.wing_user_snapshot import prune_snapshots, snapshot_wing_user

    try:
        path = snapshot_wing_user(Path(palace_path), Path(exports_dir))
        prune_snapshots(Path(exports_dir), retention_days)
        return path
    except Exception:
        return None


def _start_daily_snapshot(
    palace_path: str,
    exports_dir: str,
    retention_days: int,
    interval_seconds: int = 86_400,
):
    """Spawn a daemon thread that snapshots wing_user once per ``interval_seconds``.

    Closes the boot-only-snapshot gap (observed: the DR floor went 15 days stale
    on a container that had been up two weeks). Daemon + best-effort so it never
    blocks shutdown and a snapshot failure never crashes serving.
    """
    import threading
    import time

    def _loop() -> None:
        while True:
            time.sleep(interval_seconds)
            _snapshot_cycle(palace_path, exports_dir, retention_days)

    thread = threading.Thread(target=_loop, name="wing-user-snapshot", daemon=True)
    thread.start()
    return thread


def main():
    """Entry point: create server and run with StreamableHTTP transport."""
    server = create_server()
    _attach_health_route(server)

    # Keep the wing_user disaster-recovery floor fresh on long-lived containers:
    # the entrypoint only snapshots at boot, so a container up for weeks lets the
    # newest backup go stale. Best-effort daemon — never blocks serving.
    exports = os.environ.get("EXPORTS_PATH") or os.environ.get(
        "MEMPALACE_EXPORTS_DIR", "/data/exports"
    )
    retention = int(os.environ.get("WING_USER_RETENTION_DAYS", "7"))
    _start_daily_snapshot(palace_path_default(), exports, retention)

    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
