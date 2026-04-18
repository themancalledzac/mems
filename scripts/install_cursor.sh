#!/bin/bash
# Install Memory Palace MCP entry into ~/.cursor/mcp.json and copy the
# mempalace.mdc rule into ~/.cursor/rules/. Idempotent.
set -e
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CURSOR_DIR="$HOME/.cursor"
MCP_JSON="$CURSOR_DIR/mcp.json"
RULES_DIR="$CURSOR_DIR/rules"

SOURCE_JSON="$REPO_ROOT/integration/mempalace_mcp_cursor.json"
SOURCE_MDC="$REPO_ROOT/scripts/cursor_rules/mempalace.mdc"

if [[ ! -f "$SOURCE_JSON" ]]; then
    echo "error: missing $SOURCE_JSON" >&2
    exit 1
fi
if [[ ! -f "$SOURCE_MDC" ]]; then
    echo "error: missing $SOURCE_MDC" >&2
    exit 1
fi

mkdir -p "$CURSOR_DIR" "$RULES_DIR"

if [[ ! -f "$MCP_JSON" ]]; then
    printf '{"mcpServers": {}}\n' > "$MCP_JSON"
    echo "created $MCP_JSON"
fi

python3 - "$MCP_JSON" "$SOURCE_JSON" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
source = Path(sys.argv[2])

try:
    current = json.loads(target.read_text()) if target.read_text().strip() else {}
except json.JSONDecodeError as exc:
    print(f"error: {target} is not valid JSON: {exc}", file=sys.stderr)
    sys.exit(1)

snippet = json.loads(source.read_text())
current.setdefault("mcpServers", {})

added = []
updated = []
for name, config in snippet.get("mcpServers", {}).items():
    if name in current["mcpServers"]:
        if current["mcpServers"][name] != config:
            updated.append(name)
        else:
            continue
    else:
        added.append(name)
    current["mcpServers"][name] = config

target.write_text(json.dumps(current, indent=2) + "\n")

if added:
    print(f"added MCP servers: {', '.join(added)}")
if updated:
    print(f"updated MCP servers: {', '.join(updated)}")
if not added and not updated:
    print("no changes — mempalace entry already up to date")
print(f"wrote {target}")
PY

cp "$SOURCE_MDC" "$RULES_DIR/mempalace.mdc"
echo "copied rule to $RULES_DIR/mempalace.mdc"
