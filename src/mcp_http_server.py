"""StreamableHTTP MCP server composing mempalace + custom tools."""

import os

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
    """Create and configure the FastMCP server with all tools."""
    palace_path = palace_path or palace_path_default()
    config_path = config_path or config_path_default()

    mcp = FastMCP(
        "Memory Palace",
        host="0.0.0.0",
        port=int(os.environ.get("MEMORY_PORT", "8787")),
    )

    user_wing = UserWing(palace_path=palace_path)

    # --- User Wing tools (6) ---

    @mcp.tool()
    def mempalace_user_write(
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
    ) -> dict:
        """File a user thought into a hall. Deduplicates near-identical entries.

        Halls: questions, discoveries, frustrations, goals, decisions, observations.
        """
        return user_wing.write(
            hall=hall,
            content=content,
            topic=topic,
            source_wing=source_wing,
        )

    @mcp.tool()
    def mempalace_user_search(
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
    ) -> dict:
        """Semantic search across the User Wing."""
        return user_wing.search(
            query=query,
            hall=hall,
            topic=topic,
            n_results=n_results,
        )

    @mcp.tool()
    def mempalace_user_summary() -> dict:
        """Synthesize compact user context for agent wake-up (~300-500 tokens)."""
        return user_wing.summary()

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

    # --- Sync tools (2) ---

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

    # --- Navigation tools (5) ---

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

    # --- Search tools (2) ---

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

    # --- Ops (1) ---

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

    # --- Wing sharing (1) ---

    @mcp.tool()
    def mempalace_export_wing(slug: str) -> dict:
        """Export a wing as a portable .wingpack bundle."""
        return handle_export_wing(palace_path, slug=slug)

    # --- Phase 4B: KG tools (4) ---
    # Note: upstream mempalace.mcp_server binds `_kg` to a palace path at
    # import time. These tools work correctly in the container (one fixed
    # palace) but cannot be retargeted per-call in tests.

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
        object: str,  # noqa: A002 — matches upstream signature
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

    # TODO: mempalace_kg_time_kv — no upstream tool_kg_time_kv; skipped.
    # See Phase 4B report.

    # --- Phase 4B: Graph traversal (2) ---

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

    # --- Phase 4B: Drawer ops (3) ---

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

    # TODO: mempalace_kg_drawer — plan item has no upstream analog and no
    # clear semantics distinct from kg_add; skipped. See Phase 4B report.

    # --- Phase 4B: Tunnels (4) ---

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

    # --- Phase 4B: Diary (2) ---
    # diary_read_time in plan has no upstream analog (tool_diary_read takes
    # last_n, not a time range). Skipped.

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

    # TODO: mempalace_diary_read_time — no upstream tool takes a time window
    # for diary reads (only last_n); skipped. See Phase 4B report.

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


def main():
    """Entry point: create server and run with StreamableHTTP transport."""
    server = create_server()
    _attach_health_route(server)
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
