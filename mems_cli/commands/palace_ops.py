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

from mems_cli import protocol_audit
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
    sync_p.add_argument(
        "--allow-large-prune",
        dest="allow_large_prune",
        action="store_true",
        help="Apply prunes that would remove most of a wing's drawers.",
    )
    sync_p.set_defaults(func=cmd_sync)

    resync_p = subparsers.add_parser("resync", help="Resync (default: full_refresh=False).")
    resync_p.add_argument("--full", action="store_true", help="Full refresh.")
    resync_p.add_argument(
        "--allow-large-prune",
        dest="allow_large_prune",
        action="store_true",
        help="Apply prunes that would remove most of a wing's drawers.",
    )
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
        default=None,
        help="Path to the palace directory. Required unless --protocol is given.",
    )
    doctor_p.add_argument(
        "--protocol",
        action="store_true",
        help="Audit mempalace-before-filesystem compliance across recent sessions.",
    )
    doctor_p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback window for --protocol (default: 30).",
    )
    doctor_p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the --protocol audit as JSON.",
    )
    doctor_p.set_defaults(func=cmd_doctor)


def _call(tool: str, args: dict | None = None):
    try:
        with PalaceClient() as client:
            result = client.call(tool, args or {})
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR
    return extract_tool_result(result), EXIT_OK


def _prune_cell(prune: dict | None) -> str:
    """One status cell for a wing's last prune: `ok -N`, `blocked N`, `error`, `skipped` or `-`."""
    if not prune:
        return "-"
    status = prune.get("status", "-")
    if status == "ok":
        return f"ok -{prune.get('removed', 0)}"
    if status == "blocked":
        return f"blocked {prune.get('would_remove', 0)}"
    return status


def _status_cell(entry: dict) -> str:
    """The wing's status, with `, failed N` added when files failed to index last run."""
    status = entry.get("status", "-")
    failed = (entry.get("last_run") or {}).get("failed") or 0
    return f"{status}, failed {failed}" if failed else status


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
                _status_cell(entry),
                _prune_cell(entry.get("prune")),
            )
        )
    print_table(rows, headers=("wing", "last_sync", "files_indexed", "status", "prune"))
    return EXIT_OK


def _report_sync(data) -> int:
    """Print a sync result and its problems (errors, failed files, bad prunes) on stderr."""
    print_json(data)
    data = data if isinstance(data, dict) else {}
    for err in data.get("errors") or []:
        print(f"error: {err.get('wing')}: {err.get('error')}", file=sys.stderr)
    if data.get("message"):
        print(f"error: {data['message']}", file=sys.stderr)
    for wing, failure in (data.get("failed") or {}).items():
        print(f"failed: {wing}: {failure.get('count', 0)} files", file=sys.stderr)
        for item in failure.get("files") or []:
            print(f"  {wing}: {item.get('file')}: {item.get('error')}", file=sys.stderr)
    for wing, prune in (data.get("prune") or {}).items():
        if prune.get("status") in ("blocked", "error"):
            print(
                f"prune {prune['status']}: {wing}: {prune.get('reason', '')}",
                file=sys.stderr,
            )
    return EXIT_OK if data.get("status") == "ok" else EXIT_USER_ERROR


def cmd_sync(args: argparse.Namespace) -> int:
    payload = {
        "full": bool(args.full),
        "allow_large_prune": bool(getattr(args, "allow_large_prune", False)),
    }
    if args.wing:
        payload["wing"] = args.wing
    data, code = _call("memory_sync", payload)
    if code != EXIT_OK:
        return code
    return _report_sync(data)


def cmd_resync(args: argparse.Namespace) -> int:
    payload = {
        "full_refresh": bool(args.full),
        "allow_large_prune": bool(getattr(args, "allow_large_prune", False)),
    }
    data, code = _call("mempalace_resync", payload)
    if code != EXIT_OK:
        return code
    return _report_sync(data)


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


def cmd_make(args: argparse.Namespace) -> int:
    """Build/initialize a palace from a directory. Delegates to `mempalace init --auto-mine`."""
    cmd = ["mempalace", "init", "--auto-mine", str(args.dir)]
    if getattr(args, "yes", False):
        cmd.insert(2, "--yes")
    result = subprocess.run(cmd, check=False)
    return EXIT_OK if result.returncode == 0 else EXIT_SERVER_ERROR


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore palace from backup.

    Routes the user-wing slice to the wrapper's own restore (no upstream equivalent
    — wing_user has no source repo to re-mine from). General palace recovery goes
    to `mempalace repair --mode from-sqlite` (upstream 3.3.5 #1308).
    """
    if getattr(args, "user_only", False):
        from src.restore_wing_user import restore_if_empty

        palace = Path(args.palace_path)
        exports = palace.parent / "exports"
        result = restore_if_empty(palace, exports)
        print_json(result)
        return EXIT_OK if (result or {}).get("ok", True) else EXIT_SERVER_ERROR

    cmd = ["mempalace", "--palace", args.palace_path, "repair", "--mode", "from-sqlite"]
    if getattr(args, "source", None):
        cmd.extend(["--source", args.source])
    if getattr(args, "archive_existing", False):
        cmd.append("--archive-existing")
    completed = subprocess.run(cmd, check=False)
    return EXIT_OK if completed.returncode == 0 else EXIT_SERVER_ERROR


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnostic: pre-flight hook paths + delegate index health to `mempalace status`.

    With `--protocol`, runs the session-transcript compliance audit instead and
    skips the palace checks (no palace path needed to read transcripts).
    """
    if getattr(args, "protocol", False):
        run_protocol_audit(args)
        return EXIT_OK

    if not getattr(args, "palace_path", None):
        print("error: --palace-path is required (or pass --protocol)", file=sys.stderr)
        return EXIT_USER_ERROR

    issues = []
    save_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_save_hook.sh"
    pc_hook = Path.home() / "Code" / "mempalace" / "hooks" / "mempal_precompact_hook.sh"
    for f in (save_hook, pc_hook):
        if not f.exists():
            issues.append(f"missing hook: {f}")

    if not protocol_audit.gate_installed():
        issues.append(
            "fs-gate hook not registered in ~/.claude/settings.json "
            "(run: bash scripts/install_claude_code.sh)"
        )

    status = subprocess.run(
        ["mempalace", "--palace", args.palace_path, "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        issues.append(f"mempalace status failed: {status.stderr.strip()}")

    for issue in issues:
        print(f"issue: {issue}", file=sys.stderr)
    if status.stdout:
        print(status.stdout)
    return EXIT_OK if not issues else EXIT_SERVER_ERROR


def run_protocol_audit(args: argparse.Namespace) -> dict:
    """`mems doctor --protocol` — measure Hard Rule #1 compliance."""
    data = protocol_audit.audit(days=getattr(args, "days", 30))
    installed = protocol_audit.gate_installed()
    data["gate_installed"] = installed
    data["gate_mode"] = protocol_audit.gate_mode()

    if getattr(args, "as_json", False):
        print_json(data)
        return data

    print(protocol_audit.format_report(data))
    print()
    if installed:
        print(f"  fs-gate hook: installed (mode: {data['gate_mode']})")
    else:
        print("  fs-gate hook: NOT INSTALLED — run: bash scripts/install_claude_code.sh")
    return data
