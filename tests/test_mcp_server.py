import os
from unittest.mock import patch

from src.mcp_http_server import create_server


class TestCreateServer:
    def test_server_has_custom_tools(self, tmp_palace, tmp_config):
        """The server should register our 8 custom tools."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        # FastMCP stores tools internally — get their names via _tool_manager
        tools = server._tool_manager.list_tools()
        tool_names = [t.name for t in tools]

        assert "memory_sync" in tool_names
        assert "memory_sync_status" in tool_names
        assert "mempalace_user_write" in tool_names
        assert "mempalace_user_search" in tool_names
        assert "mempalace_user_summary" in tool_names
        assert "mempalace_user_status" in tool_names
        assert "mempalace_user_merge_topics" in tool_names
        assert "mempalace_user_prune" in tool_names

    def test_server_tool_count(self, tmp_palace, tmp_config):
        """Should have exactly 8 custom tools."""
        server = create_server(
            palace_path=str(tmp_palace),
            config_path=str(tmp_config),
        )
        tools = server._tool_manager.list_tools()
        assert len(tools) == 8


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
