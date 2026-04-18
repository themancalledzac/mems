#!/bin/bash
# Append Memory Palace MCP config to ~/.config/codex/config.toml. Idempotent —
# skips if a [mcp_servers.mempalace] table is already present.
set -e
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CODEX_DIR="$HOME/.config/codex"
CONFIG_TOML="$CODEX_DIR/config.toml"
SOURCE_TOML="$REPO_ROOT/integration/mempalace_codex_append.toml"

if [[ ! -f "$SOURCE_TOML" ]]; then
    echo "error: missing $SOURCE_TOML" >&2
    exit 1
fi

mkdir -p "$CODEX_DIR"

if [[ ! -f "$CONFIG_TOML" ]]; then
    touch "$CONFIG_TOML"
    echo "created $CONFIG_TOML"
fi

if grep -qE '^\[mcp_servers\.mempalace\]' "$CONFIG_TOML"; then
    echo "skip — [mcp_servers.mempalace] already present in $CONFIG_TOML"
    exit 0
fi

# Add a leading newline for clean separation.
if [[ -s "$CONFIG_TOML" ]]; then
    printf '\n' >> "$CONFIG_TOML"
fi
cat "$SOURCE_TOML" >> "$CONFIG_TOML"
echo "appended mempalace block to $CONFIG_TOML"
