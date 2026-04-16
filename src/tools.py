"""MCP tool handlers for sync operations."""

from src.sync_engine import SyncEngine, SyncLedger


def handle_sync(
    config_path: str,
    data_path: str,
    wing: str | None = None,
    full: bool = False,
) -> dict:
    """Handle memory_sync tool call."""
    engine = SyncEngine(config_path=config_path, data_path=data_path)

    if wing and wing not in engine.repos:
        return {"status": "error", "message": f"Unknown wing: {wing}"}

    if full or not SyncLedger(f"{data_path}/sync_ledger.json").entries:
        engine.full_sync(wing_name=wing)
    else:
        engine.incremental_sync(wing_name=wing)

    synced = []
    errors = []
    for name, entry in engine.ledger.entries.items():
        if entry["status"] == "synced":
            synced.append(name)
        elif entry["status"] == "error":
            errors.append({"wing": name, "error": entry.get("error", "unknown")})

    return {"status": "ok", "synced": synced, "errors": errors}


def handle_sync_status(config_path: str, data_path: str) -> dict:
    """Handle memory_sync_status tool call."""
    ledger = SyncLedger(f"{data_path}/sync_ledger.json")
    return {"wings": ledger.entries}
