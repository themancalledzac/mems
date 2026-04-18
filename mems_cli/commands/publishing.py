"""`mems publish|publish-all` — wingpack author + stage into source repos.

These commands run entirely in-process via `src.wing_pack` + `src.wing_publish`.
Wing metadata is pulled from the live palace via the MCP `mempalace_export_wing`
tool so the bundle we publish matches what the server sees.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mems_cli.common import (
    extract_tool_result,
    get_config_dir,
    load_repos_json,
    print_json,
    print_table,
)
from mems_cli.palace_client import PalaceClient, PalaceClientError
from src.wing_publish import PublishRefused, publish_to_repo

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    pub_p = subparsers.add_parser(
        "publish",
        help="Export a wing and stage its .wingpack into the source repo.",
    )
    pub_p.add_argument("wing")
    pub_p.add_argument("--mode", choices=["ask", "overwrite", "skip"], default="ask")
    pub_p.add_argument("--dry-run", action="store_true")
    pub_p.add_argument(
        "--exports-dir",
        default=None,
        help="Local dir to download the exported bundle (default: temp).",
    )
    pub_p.set_defaults(func=cmd_publish)

    all_p = subparsers.add_parser(
        "publish-all",
        help="Publish every registered wing into its source repo.",
    )
    all_p.add_argument("--mode", choices=["ask", "overwrite", "skip"], default="ask")
    all_p.add_argument("--dry-run", action="store_true")
    all_p.set_defaults(func=cmd_publish_all)


# --- helpers ------------------------------------------------------------------


# mode alias: user-facing (ask|overwrite|skip) → wing_publish (default|force|keep).
_MODE_MAP = {"ask": "default", "overwrite": "force", "skip": "keep"}


def _export_wing(wing: str) -> tuple[Path | None, int]:
    """Call mempalace_export_wing and return the server-side bundle path."""
    try:
        with PalaceClient() as client:
            raw = client.call("mempalace_export_wing", {"slug": wing})
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR

    data = extract_tool_result(raw)
    path = (data or {}).get("path") if isinstance(data, dict) else None
    if not path:
        print(f"error: export_wing returned no path: {data!r}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR
    return Path(path), EXIT_OK


def _stage_bundle_locally(bundle: Path, exports_dir: Path | None) -> Path:
    """If the server-written path isn't already local, copy it into exports_dir."""
    if bundle.exists():
        return bundle
    # Nothing we can do if the file isn't on our filesystem. Surface clearly.
    raise FileNotFoundError(
        f"bundle {bundle} is not accessible from this host — "
        f"export must run on the same filesystem as the CLI"
    )


def _print_refusal(wing: str, reason: str) -> None:
    print(f"publish refused for {wing}: {reason}", file=sys.stderr)


def _print_result(wing: str, result) -> None:
    print_json(
        {
            "wing": wing,
            "path": str(result.path),
            "mode": result.mode,
            "dry_run": result.dry_run,
        }
    )


# --- handlers -----------------------------------------------------------------


def cmd_publish(args: argparse.Namespace) -> int:
    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)
    if args.wing not in repos:
        print(f"error: wing {args.wing!r} not in repos.json", file=sys.stderr)
        return EXIT_USER_ERROR
    repo_path = Path(repos[args.wing]["path"])

    bundle, code = _export_wing(args.wing)
    if code != EXIT_OK:
        return code

    try:
        bundle = _stage_bundle_locally(bundle, None)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    try:
        result = publish_to_repo(
            bundle=bundle,
            repo_root=repo_path,
            mode=_MODE_MAP[args.mode],
            dry_run=bool(args.dry_run),
        )
    except PublishRefused as exc:
        _print_refusal(args.wing, str(exc))
        return EXIT_USER_ERROR

    _print_result(args.wing, result)
    return EXIT_OK


def cmd_publish_all(args: argparse.Namespace) -> int:
    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)
    if not repos:
        print("no repos registered. Try: mems repo add <name> <path>")
        return EXIT_OK

    rows = []
    for wing in sorted(repos):
        repo_path = Path(repos[wing]["path"])
        bundle, code = _export_wing(wing)
        if code != EXIT_OK:
            rows.append((wing, "error", "export failed"))
            continue

        try:
            bundle = _stage_bundle_locally(bundle, None)
        except FileNotFoundError as exc:
            rows.append((wing, "error", str(exc)[:80]))
            continue

        try:
            result = publish_to_repo(
                bundle=bundle,
                repo_root=repo_path,
                mode=_MODE_MAP[args.mode],
                dry_run=bool(args.dry_run),
            )
        except PublishRefused as exc:
            rows.append((wing, "refused", str(exc)))
            continue

        status = "dry-run" if result.dry_run else "published"
        rows.append((wing, status, str(result.path)))

    print_table(rows, headers=("wing", "status", "detail"))
    return EXIT_OK
