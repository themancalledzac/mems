from src.mcp_http_server import create_server

EXPECTED_PHASE_4A_TOOLS = {
    "mempalace_status",
    "mempalace_list_wings",
    "mempalace_list_rooms",
    "mempalace_check_logs",
    "mempalace_get_logs_recent",
    "mempalace_search",
    "mempalace_search_all",
    "mempalace_resync",
    "mempalace_export_wing",
}

# Phase 4B: 4 KG + 2 graph + 3 drawer + 4 tunnel + 2 diary = 15 tools.
# Skipped (no upstream support): kg_time_kv, kg_drawer, diary_read_time.
EXPECTED_PHASE_4B_TOOLS = {
    # KG (4)
    "mempalace_kg_query",
    "mempalace_kg_add",
    "mempalace_kg_time",
    "mempalace_kg_stats",
    # Graph (2)
    "mempalace_traverse",
    "mempalace_find_tunnels",
    # Drawers (3)
    "mempalace_list_drawers",
    "mempalace_update_drawer",
    "mempalace_delete_drawer",
    # Tunnels (4)
    "mempalace_create_tunnel",
    "mempalace_delete_tunnel",
    "mempalace_list_tunnels",
    "mempalace_tunnel_read",
    # Diary (2)
    "mempalace_diary_write",
    "mempalace_diary_read",
}


class TestCreateServer:
    def test_server_has_custom_tools(self, tmp_palace, tmp_config):
        """The server should register the original 8 custom tools."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        tool_names = {t.name for t in tools}

        assert "memory_sync" in tool_names
        assert "memory_sync_status" in tool_names
        assert "mempalace_user_write" in tool_names
        assert "mempalace_user_search" in tool_names
        assert "mempalace_user_summary" in tool_names
        assert "mempalace_user_status" in tool_names
        assert "mempalace_user_merge_topics" in tool_names
        assert "mempalace_user_prune" in tool_names

    def test_extended_tools_registered(self, tmp_palace, tmp_config):
        """Phase 4A tools are registered on the server."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        missing = EXPECTED_PHASE_4A_TOOLS - names
        assert not missing, f"missing tools: {missing}"

    def test_server_tool_count(self, tmp_palace, tmp_config):
        """8 original + 9 Phase 4A + 15 Phase 4B = 32 total custom tools."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        assert len(tools) == 32

    def test_phase_4b_tools_registered(self, tmp_palace, tmp_config):
        """Phase 4B tools (KG, graph, drawers, tunnels, diary) are registered."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        missing = EXPECTED_PHASE_4B_TOOLS - names
        assert not missing, f"missing Phase 4B tools: {missing}"


class TestToolSchemas:
    def test_user_write_has_required_params(self, tmp_palace, tmp_config):
        """mempalace_user_write should have hall, content, topic params."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        write_tool = tools["mempalace_user_write"]
        schema = write_tool.parameters
        assert "hall" in schema.get("properties", {})
        assert "content" in schema.get("properties", {})
        assert "topic" in schema.get("properties", {})

    def test_memory_sync_has_optional_wing(self, tmp_palace, tmp_config):
        """memory_sync should have optional wing param."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        sync_tool = tools["memory_sync"]
        schema = sync_tool.parameters
        assert "wing" in schema.get("properties", {})

    def test_search_has_slug_and_wing(self, tmp_palace, tmp_config):
        """mempalace_search should expose slug, wing, room, n."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        search_tool = tools["mempalace_search"]
        props = search_tool.parameters.get("properties", {})
        assert "query" in props
        assert "slug" in props
        assert "wing" in props
        assert "room" in props


class TestExtendedHandlers:
    """Smoke tests on handler functions against an empty tmp_palace."""

    def test_handle_list_wings_empty_palace(self, tmp_palace):
        from src.tools import handle_list_wings

        wings = handle_list_wings(str(tmp_palace))
        assert isinstance(wings, list)

    def test_handle_list_rooms_empty_palace(self, tmp_palace):
        from src.tools import handle_list_rooms

        rooms = handle_list_rooms(str(tmp_palace))
        assert isinstance(rooms, list)

    def test_handle_status_empty_palace(self, tmp_palace):
        from src.tools import handle_status

        status = handle_status(str(tmp_palace))
        assert status["ok"] is True
        assert status["total_drawers"] == 0
        assert status["wings"] == {}

    def test_handle_get_logs_recent_empty_palace(self, tmp_palace):
        from src.tools import handle_get_logs_recent

        logs = handle_get_logs_recent(str(tmp_palace), n=5)
        assert logs == []


class TestHealthRoute:
    def test_attach_health_route_adds_route(self, tmp_palace, tmp_config):
        """_attach_health_route should add a /health route to the app."""
        from src.mcp_http_server import _attach_health_route

        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        _attach_health_route(server, palace_path=str(tmp_palace))
        app = server.streamable_http_app()
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/health" in paths
