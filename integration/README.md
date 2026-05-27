# IDE Integrations

| File | Consumer | What it does |
|---|---|---|
| `claude_code/pretooluse_agent_orientation.py` | Claude Code | Injects mempalace orientation before Agent tool calls |
| `claude_code/hooks_install.py` | Claude Code | Helper for `scripts/install_claude_code.sh` |
| `mempalace_codex_append.toml` | Codex CLI | Append-block for Codex's hooks.toml |
| `mempalace_mcp_cursor.json` | Cursor | MCP server registration for Cursor |
| `mempalace-discovery.mdc` | Cursor | Cursor rule — search palace at session start (invisible to Claude Code) |
| `user-wing.mdc` | Cursor | Cursor rule — write user thoughts during session (invisible to Claude Code) |

Files ending in `.mdc` are Cursor-specific. Claude Code does not read them; for
Claude Code, the equivalent guidance lives in `~/.claude/CLAUDE.md` (Memory Palace
Protocol section).
