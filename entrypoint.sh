#!/bin/bash
# Memory Palace container entrypoint.
# Flow: banner → ensure dirs → restore wing_user (if empty) → sync → snapshot → serve.
# See CONTEXT.md §5 for the canonical order-of-operations.

set -e

PALACE_PATH="${PALACE_PATH:-/data/palace}"
EXPORTS_PATH="${EXPORTS_PATH:-/data/exports}"
CONFIG_PATH="${CONFIG_PATH:-/config}"
MEMORY_PORT="${MEMORY_PORT:-8080}"
WING_USER_RETENTION_DAYS="${WING_USER_RETENTION_DAYS:-7}"

export PALACE_PATH EXPORTS_PATH CONFIG_PATH MEMORY_PORT WING_USER_RETENTION_DAYS
# Keep MEMPALACE_EXPORTS_DIR aligned with EXPORTS_PATH for modules that read it.
export MEMPALACE_EXPORTS_DIR="${MEMPALACE_EXPORTS_DIR:-$EXPORTS_PATH}"

echo "=================================================="
echo "Memory Palace starting..."
echo "  palace   : $PALACE_PATH"
echo "  exports  : $EXPORTS_PATH"
echo "  config   : $CONFIG_PATH"
echo "  port     : $MEMORY_PORT"
echo "=================================================="

# 1. Ensure persistent dirs exist (named volume is bare on first boot).
mkdir -p "$PALACE_PATH" "$EXPORTS_PATH"

# 2. Restore wing_user if empty (disaster-recovery hook — see §7).
echo "  -> restore wing_user if empty"
python <<'PY' || echo "  (restore skipped — non-fatal)"
import json
import os
from pathlib import Path

from src.restore_wing_user import restore_if_empty

result = restore_if_empty(
    Path(os.environ["PALACE_PATH"]),
    Path(os.environ["EXPORTS_PATH"]),
)
print(f"  restore: {json.dumps(result)}")
PY

# 3. Sync — first-boot full sync across all repos, else validate ledger.
LEDGER="$PALACE_PATH/sync_ledger.json"
if [ ! -f "$LEDGER" ]; then
    echo "  -> first-boot: full sync across all repos"
    python <<'PY'
import os
import time

from src.sync_engine import SyncEngine

engine = SyncEngine(
    config_path=os.environ["CONFIG_PATH"],
    data_path=os.environ["PALACE_PATH"],
)

if not engine.repos:
    print("  (no repos registered in config/repos.json — skipping sync)")
else:
    for name in engine.repos:
        start = time.time()
        print(f"  full-sync: {name} ...", flush=True)
        try:
            engine.full_sync(wing_name=name)
            entry = engine.ledger.get(name) or {}
            elapsed = time.time() - start
            status = entry.get("status", "unknown")
            files = entry.get("files_indexed", "?")
            if status == "synced":
                print(f"    ok   {name}: {files} files in {elapsed:.1f}s", flush=True)
            else:
                err = entry.get("error", "unknown error")
                print(f"    fail {name}: {err} ({elapsed:.1f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001 — boot must not die on one bad wing
            print(f"    fail {name}: {exc}", flush=True)

    print("  sync complete.", flush=True)
PY
else
    echo "  -> existing ledger found — validating"
    python <<'PY'
import os
from pathlib import Path

from src.sync_engine import SyncLedger

ledger_path = Path(os.environ["PALACE_PATH"]) / "sync_ledger.json"
ledger = SyncLedger(str(ledger_path))
wings = list(ledger.entries.keys())
print(f"  ledger ok — {len(wings)} wings: {wings}")
PY
fi

# 4. Daily wing_user snapshot — best-effort, never blocks boot.
echo "  -> snapshot wing_user (non-fatal)"
python <<'PY' || true
import os
from pathlib import Path

from src.wing_user_snapshot import prune_snapshots, snapshot_wing_user

palace = Path(os.environ["PALACE_PATH"])
exports = Path(os.environ["EXPORTS_PATH"])
retention = int(os.environ.get("WING_USER_RETENTION_DAYS", "7"))

path = snapshot_wing_user(palace, exports)
print(f"  snapshot: {path}")
pruned = prune_snapshots(exports, retention)
if pruned:
    print(f"  pruned {len(pruned)} snapshot(s) older than {retention}d")
PY

# 5. Serve.
echo "Starting MCP server on port ${MEMORY_PORT}..."
exec python -m src.mcp_http_server
