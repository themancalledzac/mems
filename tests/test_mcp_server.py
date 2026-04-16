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
