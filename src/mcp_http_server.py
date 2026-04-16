"""StreamableHTTP MCP server composing mempalace + custom tools."""

import os

from mcp.server.fastmcp import FastMCP

from src.user_wing import UserWing
from src.tools import handle_sync, handle_sync_status


def create_server(
    palace_path: str | None = None,
    config_path: str | None = None,
) -> FastMCP:
    """Create and configure the FastMCP server with all tools."""
    palace_path = palace_path or os.environ.get("PALACE_PATH", "/data")
    config_path = config_path or os.environ.get("CONFIG_PATH", "/config")

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

    return mcp


def main():
    """Entry point: create server and run with StreamableHTTP transport."""
    server = create_server()
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
