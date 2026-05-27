#!/bin/bash
# Register the Memory Palace Agent-orientation PreToolUse hook in
# ~/.claude/settings.json. Idempotent — skips if our hook command is
# already present. Backs up the original to settings.json.bak.<UTC-ts>
# before any change.
set -e
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SETTINGS="$HOME/.claude/settings.json"
HOOK="$REPO_ROOT/integration/claude_code/pretooluse_agent_orientation.py"

if [[ ! -f "$HOOK" ]]; then
    echo "error: missing $HOOK" >&2
    exit 1
fi

mkdir -p "$(dirname "$SETTINGS")"

# Hand the merge to Python — settings.json is JSON, not line-oriented, and
# bash + sed against nested JSON is a known foot-gun. Idempotency, backup,
# and shape repair all live in one place.
HOOK_CMD="$HOOK" SETTINGS_PATH="$SETTINGS" python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

settings_path = Path(os.environ["SETTINGS_PATH"])
hook_command = os.environ["HOOK_CMD"]

if settings_path.exists():
    original = settings_path.read_text()
    settings = json.loads(original) if original.strip() else {}
else:
    original = ""
    settings = {}

if not isinstance(settings, dict):
    raise SystemExit(f"error: {settings_path} is not a JSON object")

# Already installed? No-op.
pretool = ((settings.get("hooks") or {}).get("PreToolUse")) or []
if isinstance(pretool, list) and any(
    isinstance(h, dict) and h.get("command") == hook_command
    for entry in pretool if isinstance(entry, dict)
    for h in (entry.get("hooks") or [])
):
    print(f"skip — hook already present in {settings_path}")
    raise SystemExit(0)

# Backup before modifying.
if original:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = settings_path.with_suffix(settings_path.suffix + f".bak.{ts}")
    backup.write_text(original)
    print(f"backup: {backup}")

hooks = settings.setdefault("hooks", {})
existing = hooks.get("PreToolUse")
if not isinstance(existing, list):
    existing = []
    hooks["PreToolUse"] = existing
existing.append({
    "matcher": "Agent",
    "hooks": [{"type": "command", "command": hook_command}],
})

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"installed Agent-orientation hook in {settings_path}")
print(f"   command: {hook_command}")
PY
