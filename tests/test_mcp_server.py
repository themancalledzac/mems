from src.mcp_http_server import create_server
from src.user_wing import UserWing

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

EXPECTED_PHASE_4B_TOOLS = {
    "mempalace_kg_query",
    "mempalace_kg_add",
    "mempalace_kg_time",
    "mempalace_kg_stats",
    "mempalace_traverse",
    "mempalace_find_tunnels",
    "mempalace_list_drawers",
    "mempalace_update_drawer",
    "mempalace_delete_drawer",
    "mempalace_create_tunnel",
    "mempalace_delete_tunnel",
    "mempalace_list_tunnels",
    "mempalace_tunnel_read",
    "mempalace_diary_write",
    "mempalace_diary_read",
}


class TestCreateServer:
    def test_server_has_custom_tools(self, tmp_palace, tmp_config):
        """The server registers the sync and User Wing tools."""
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
        assert "mempalace_user_recent" in tool_names
        assert "mempalace_user_set_status" in tool_names

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
        """10 sync and User Wing + 9 Phase 4A + 15 Phase 4B = 34 tools."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        assert len(tools) == 34

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

    def test_user_tools_expose_recency_params(self, tmp_palace, tmp_config):
        server = create_server(palace_path=str(tmp_palace), config_path=str(tmp_config))
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        expected = {
            "mempalace_user_write": {"origin", "status", "personal", "session_id"},
            "mempalace_user_search": {
                "since_days",
                "source_wing",
                "include_unscoped",
                "status",
                "include_personal",
                "recency_weight",
            },
            "mempalace_user_summary": {"source_wing", "max_item_chars"},
            "mempalace_user_recent": {
                "days",
                "source_wing",
                "include_unscoped",
                "hall",
                "status",
                "include_personal",
                "n",
            },
            "mempalace_user_set_status": {"drawer_id", "status"},
        }
        for name, params in expected.items():
            schema = tools[name].parameters
            assert params <= set(schema.get("properties", {})), name
        assert set(tools["mempalace_user_write"].parameters["required"]) == {
            "hall",
            "content",
            "topic",
        }
        assert set(tools["mempalace_user_set_status"].parameters["required"]) == {
            "drawer_id",
            "status",
        }

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


class TestUserWingTools:
    async def test_write_recent_set_status_round_trip(self, tmp_palace, tmp_config):
        server = create_server(palace_path=str(tmp_palace), config_path=str(tmp_config))
        call = server._tool_manager.call_tool
        legacy = await call(
            "mempalace_user_write",
            {"hall": "goals", "content": "Ship recency", "topic": "mems"},
        )
        assert legacy["status"] == "created"
        await call(
            "mempalace_user_write",
            {
                "hall": "decisions",
                "content": "Keep it private",
                "topic": "me",
                "personal": True,
                "origin": "prompt",
            },
        )
        recent = await call("mempalace_user_recent", {"include_personal": False})
        assert [r["id"] for r in recent["results"]] == [legacy["id"]]
        assert recent["results"][0]["status"] == "open"

        done = await call(
            "mempalace_user_set_status", {"drawer_id": legacy["id"], "status": "done"}
        )
        assert done == {"status": "updated", "id": legacy["id"], "entry_status": "done"}

        hits = await call("mempalace_user_search", {"query": "Ship recency", "status": "done"})
        assert [r["id"] for r in hits["results"]] == [legacy["id"]]
        summary = await call("mempalace_user_summary", {})
        assert "Keep it private" not in summary["text"]

    async def test_write_passes_new_params_to_metadata(self, tmp_palace, tmp_config):
        server = create_server(palace_path=str(tmp_palace), config_path=str(tmp_config))
        created = await server._tool_manager.call_tool(
            "mempalace_user_write",
            {
                "hall": "observations",
                "content": "Orchestrator saw a stale branch",
                "topic": "orch",
                "source_wing": "memory",
                "origin": "orch",
                "status": "active",
                "personal": True,
                "session_id": "sess-123",
            },
        )
        meta = UserWing(str(tmp_palace)).collection.get(ids=[created["id"]]).get("metadatas")[0]
        assert meta["origin"] == "orch"
        assert meta["status"] == "active"
        assert meta["personal"] is True
        assert meta["session_id"] == "sess-123"
        assert meta["source_wing"] == "memory"


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
