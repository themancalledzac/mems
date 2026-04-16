#!/bin/bash
set -e

echo "Memory Palace starting..."

if [ ! -f /data/sync_ledger.json ]; then
    echo "First boot — running full sync across all repos..."
    python -c "
from src.tools import handle_sync
import os
result = handle_sync(
    config_path=os.environ.get('CONFIG_PATH', '/config'),
    data_path=os.environ.get('PALACE_PATH', '/data'),
    full=True,
)
print(f'Sync complete: {result}')
"
else
    echo "Existing ledger found — validating..."
    python -c "
from src.sync_engine import SyncLedger
import os
ledger = SyncLedger(os.path.join(os.environ.get('PALACE_PATH', '/data'), 'sync_ledger.json'))
wings = list(ledger.entries.keys())
print(f'Ledger OK — {len(wings)} wings: {wings}')
"
fi

echo "Starting MCP server on port ${MEMORY_PORT:-8787}..."
exec python -m src.mcp_http_server
