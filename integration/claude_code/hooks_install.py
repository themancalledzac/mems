"""Idempotent merge of Memory wrapper hooks into ~/.claude/settings.json.

Adds three entries:
  - PreToolUse: Agent → wrapper's pretooluse_agent_orientation.py
  - Stop → upstream mempalace's mempal_save_hook.sh
  - PreCompact → upstream mempalace's mempal_precompact_hook.sh

Designed to be invoked from scripts/install_claude_code.sh. Reads:
  HOOK_PRETOOLUSE_CMD, HOOK_STOP_CMD, HOOK_PRECOMPACT_CMD
  SETTINGS_PATH
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _already_present(entries, command):
    return any(
        h.get("command") == command
        for entry in entries
        if isinstance(entry, dict)
        for h in (entry.get("hooks") or [])
    )


def main() -> int:
    settings_path = Path(os.environ["SETTINGS_PATH"])
    pretool = os.environ["HOOK_PRETOOLUSE_CMD"]
    stop = os.environ["HOOK_STOP_CMD"]
    precompact = os.environ["HOOK_PRECOMPACT_CMD"]

    if settings_path.exists():
        original = settings_path.read_text()
        settings = json.loads(original) if original.strip() else {}
    else:
        original = ""
        settings = {}

    if not isinstance(settings, dict):
        print(f"error: {settings_path} is not a JSON object")
        return 1

    hooks = settings.setdefault("hooks", {})

    plan = [
        (
            "PreToolUse",
            pretool,
            {
                "matcher": "Agent",
                "hooks": [{"type": "command", "command": pretool}],
            },
        ),
        (
            "Stop",
            stop,
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": stop, "timeout": 30}],
            },
        ),
        (
            "PreCompact",
            precompact,
            {
                "hooks": [{"type": "command", "command": precompact, "timeout": 30}],
            },
        ),
    ]

    any_change = False
    for key, cmd, entry in plan:
        entries = hooks.setdefault(key, [])
        if not isinstance(entries, list):
            entries = []
            hooks[key] = entries
        if _already_present(entries, cmd):
            print(f"skip - {key} hook already present: {cmd}")
            continue
        entries.append(entry)
        any_change = True
        print(f"installed {key} hook -> {cmd}")

    if any_change and original:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = settings_path.with_suffix(settings_path.suffix + f".bak.{ts}")
        backup.write_text(original)
        print(f"backup: {backup}")

    if any_change:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
