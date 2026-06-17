"""`mems status|sync|resync|wings|rooms|logs|export|make|restore|doctor` — MCP lifecycle ops.

`make`, `restore`, and `doctor` shell out to the upstream `mempalace` CLI so the
wrapper doesn't duplicate init/repair/status logic. `restore --user-only` falls
back to the wrapper's own user-wing recovery (no upstream equivalent).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mems_cli.common import extract_tool_result, print_json, print_table
from mems_cli.palace_client import PalaceClient, PalaceClientError

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    status_p = subparsers.add_parser("status", help="Show sync ledger status.")
    status_p.add_argument("--json", dest="as_json", action="store_true")
    status_p.set_defaults(func=cmd_status)

    sync_p = subparsers.add_parser("sync", help="Sync repos into the palace.")
    sync_p.add_argument("--wing", default=None, help="Only sync this wing.")
    sync_p.add_argument("--full", action="store_true", help="Force full sync.")
    sync_p.set_defaults(func=cmd_sync)

    resync_p = subparsers.add_parser("resync", help="Resync (default: full_refresh=False).")
    resync_p.add_argument("--wing", default=None)
    resync_p.add_argument("--full", action="store_true", help="Full refresh.")
    resync_p.set_defaults(func=cmd_resync)

    wings_p = subparsers.add_parser("wings", help="List every wing in the palace.")
    wings_p.set_defaults(func=cmd_wings)

    rooms_p = subparsers.add_parser("rooms", help="List rooms in a wing.")
    rooms_p.add_argument("wing")
    rooms_p.set_defaults(func=cmd_rooms)

    logs_p = subparsers.add_parser("logs", help="Show recent palace drawer entries.")
    logs_p.add_argument("--limit", "-n", type=int, default=10)
    logs_p.add_argument("--wing", default=None, help="Only show entries from this wing.")
    logs_p.set_defaults(func=cmd_logs)

    export_p = subparsers.add_parser("export", help="Export a wing as a .wingpack.")
    export_p.add_argument("wing")
    export_p.add_argument("--output", default=None, help="Output path (file).")
    export_p.set_defaults(func=cmd_export)

    make_p = subparsers.add_parser(
        "make",
        help="Build/initialize a palace from a directory (delegates to `mempalace init`).",
    )
    make_p.add_argument("dir", help="Source directory to seed the palace from.")
    make_p.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")
    make_p.set_defaults(func=cmd_make)

    restore_p = subparsers.add_parser(
        "restore",
        help="Restore palace from backup (user_wing slice + delegate to `mempalace repair`).",
    )
    restore_p.add_argument(
        "--palace-path",
        dest="palace_path",
        required=True,
        help="Path to the palace directory.",
    )
    restore_p.add_argument(
        "--user-only",
        dest="user_only",
        action="store_true",
        help="Restore only the wing_user slice from the JSON backup (no general recovery).",
    )
    restore_p.add_argument(
        "--source",
        default=None,
        help="Source sqlite path for general recovery (passed to `mempalace repair`).",
    )
    restore_p.add_argument(
        "--archive-existing",
        dest="archive_existing",
        action="store_true",
        help="Archive any existing palace before restoring.",
    )
    restore_p.set_defaults(func=cmd_restore)

    doctor_p = subparsers.add_parser(
        "doctor",
        help="Diagnostic: pre-flight hook paths + delegate index health to `mempalace status`.",
    )
    doctor_p.add_argument(
        "--palace-path",
        dest="palace_path",
        required=True,
        help="Path to the palace directory.",
    )
    doctor_p.set_defaults(func=cmd_doctor)


# --- helpers ------------------------------------------------------------------


def _call(tool: str, args: dict | None = None):
    try:
        with PalaceClient() as client:
            result = client.call(tool, args or {})
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR
    return extract_tool_result(result), EXIT_OK


# --- handlers -----------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    data, code = _call("memory_sync_status")
    if code != EXIT_OK:
        return code
    if getattr(args, "as_json", False):
        print_json(data)
        return EXIT_OK

    wings = (data or {}).get("wings") or {}
    if not wings:
        print("no wings synced yet. Try: mems sync")
        return EXIT_OK
    rows = []
    for name in sorted(wings):
        entry = wings[name] or {}
        rows.append(
            (
                name,
                entry.get("last_sync_ts", "-"),
                entry.get("files_indexed", "-"),
                entry.get("status", "-"),
            )
        )
    print_table(rows, headers=("wing", "last_sync", "files_indexed", "status"))
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    payload = {"full": bool(args.full)}
    if args.wing:
        payload["wing"] = args.wing
    data, code = _call("memory_sync", payload)
    if code != EXIT_OK:
        return code
    print_json(data)
    return EXIT_OK


def cmd_resync(args: argparse.Namespace) -> int:
    payload = {"full_refresh": bool(args.full)}
    data, code = _call("mempalace_resync", payload)
    if code != EXIT_OK:
        return code
    print_json(data)
    return EXIT_OK


def cmd_wings(args: argparse.Namespace) -> int:
    data, code = _call("mempalace_list_wings")
    if code != EXIT_OK:
        return code
    rows = [(entry.get("wing", "?"), entry.get("drawers", "?")) for entry in (data or [])]
    print_table(rows, headers=("wing", "drawers"))
    return EXIT_OK


def cmd_rooms(args: argparse.Namespace) -> int:
    data, code = _call("mempalace_list_rooms", {"wing": args.wing})
    if code != EXIT_OK:
        return code
    rows = [(entry.get("room", "?"), entry.get("drawers", "?")) for entry in (data or [])]
    print_table(rows, headers=("room", "drawers"))
    return EXIT_OK


def cmd_logs(args: argparse.Namespace) -> int:
    data, code = _call("mempalace_get_logs_recent", {"n": args.limit})
    if code != EXIT_OK:
        return code
    entries = data if isinstance(data, list) else (data or {}).get("result", [])
    if not entries:
        print("no log entries")
        return EXIT_OK
    for entry in entries:
        meta = entry.get("metadata", {}) or {}
        wing = meta.get("wing", "?")
        if args.wing and wing != args.wing:
            continue
        room = meta.get("room", "?")
        ts = meta.get("timestamp") or meta.get("created_at") or "-"
        content = (entry.get("content") or "")[:120].replace("\n", " ")
        print(f"[{ts}] {wing}/{room}  {content}")
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    data, code = _call("mempalace_export_wing", {"slug": args.wing})
    if code != EXIT_OK:
        return code

    # Server wrote the bundle to its own exports/ dir. If the user passed
    # --output, copy it over. This requires the server-side path to be
    # readable from the client — in container setups it might not be, so
    # we surface the server path either way.
    server_path = (data or {}).get("path")
    print_json(data)

    if args.output and server_path:
        target = Path(args.output).expanduser()
        src = Path(server_path)
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(src, target)
            print(f"copied to {target}")
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            print(
                f"note: server bundle at {src} not readable from this host. "
                f"Default name would be ./{args.wing}-{ts}.wingpack",
                file=sys.stderr,
            )
    return EXIT_OK


# --- upstream-CLI shell-outs --------------------------------------------------


def cmd_make(args: argparse.Namespace) -> dict:
    """Build/initialize a palace from a directory. Delegates to `mempalace init --auto-mine`."""
    cmd = ["mempalace", "init", "--auto-mine", str(args.dir)]
    if getattr(args, "yes", False):
        cmd.insert(2, "--yes")
    result = subprocess.run(cmd, check=False)
    return {"ok": result.returncode == 0, "returncode": result.returncode}


def cmd_restore(args: argparse.Namespace) -> dict:
    """Restore palace from backup.

    Routes the user-wing slice to the wrapper's own restore (no upstream equivalent
    — wing_user has no source repo to re-mine from). General palace recovery goes
    to `mempalace repair --mode from-sqlite` (upstream 3.3.5 #1308).
    """
    if getattr(args, "user_only", False):
        from src.restore_wing_user import restore_if_empty

        palace = Path(args.palace_path)
        exports = palace.parent / "exports"
        return restore_if_empty(palace, exports)

    # `--palace` is a global flag on the mempalace CLI, before the subcommand.
    cmd = ["mempalace", "--palace", args.palace_path, "repair", "--mode", "from-sqlite"]
    if getattr(args, "source", None):
        cmd.extend(["--source", args.source])
    if getattr(args, "archive_existing", False):
        cmd.append("--archive-existing")
    result = subprocess.run(cmd, check=False)
    return {"ok": result.returncode == 0, "returncode": result.returncode}


def cmd_doctor(args: argparse.Namespace) -> dict:
    """Diagnostic: pre-flight hook paths + delegate index health to `mempalace status`."""
    issues = []
    save_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_save_hook.sh"
    pc_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_precompact_hook.sh"
    for f in (save_hook, pc_hook):
        if not f.exists():
            issues.append(f"missing hook: {f}")

    # `--palace` is a global flag on the mempalace CLI, before the subcommand.
    status = subprocess.run(
        ["mempalace", "--palace", args.palace_path, "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        issues.append(f"mempalace status failed: {status.stderr.strip()}")

    return {"ok": not issues, "issues": issues, "status_output": status.stdout}
