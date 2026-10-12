"""`mems repo ...` — manage the local repos.json registry.

Operates entirely on local config. No MCP calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mems_cli.common import (
    get_config_dir,
    load_repos_json,
    print_json,
    print_table,
    save_repos_json,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach `mems repo ...` subcommands."""
    repo_p = subparsers.add_parser("repo", help="Manage registered repos.")
    repo_sub = repo_p.add_subparsers(dest="repo_cmd", metavar="ACTION")

    list_p = repo_sub.add_parser("list", help="List registered repos.")
    list_p.set_defaults(func=cmd_list)

    add_p = repo_sub.add_parser("add", help="Register a repo by name + path.")
    add_p.add_argument("name")
    add_p.add_argument("path")
    add_p.set_defaults(func=cmd_add)

    remove_p = repo_sub.add_parser("remove", help="Unregister a repo by name.")
    remove_p.add_argument("name")
    remove_p.set_defaults(func=cmd_remove)

    show_p = repo_sub.add_parser("show", help="Show one repo's entry as JSON.")
    show_p.add_argument("name")
    show_p.set_defaults(func=cmd_show)

    repo_p.set_defaults(func=_no_action)


def _no_action(args: argparse.Namespace) -> int:
    print("usage: mems repo {list|add|remove|show} ...")
    return 1


def _load_ledger(config_dir: Path) -> dict:
    """Load sync_ledger.json if present (for last_sync column)."""
    path = config_dir / "sync_ledger.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def cmd_list(args: argparse.Namespace) -> int:
    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)
    ledger = _load_ledger(config_dir)

    if not repos:
        print("no repos registered. Try: mems repo add <name> <path>")
        return 0

    rows = []
    for name in sorted(repos):
        entry = repos[name] or {}
        path = entry.get("path", "?")
        last_sync = (ledger.get(name) or {}).get("last_sync_ts", "-")
        rows.append((name, path, last_sync))
    print_table(rows, headers=("name", "path", "last_sync"))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"error: path does not exist: {path}", file=_stderr())
        return 1
    if not (path / ".git").exists():
        print(f"error: not a git repo (no .git/): {path}", file=_stderr())
        return 1

    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)

    if args.name in repos:
        existing = repos[args.name].get("path")
        if existing and Path(existing).resolve() == path:
            print(f"{args.name} already registered at {path}")
            return 0
        print(f"warning: overwriting existing entry for {args.name} (was {existing})")

    repos[args.name] = {
        "path": str(path),
        "default_hall": "general",
    }
    save_repos_json(config_dir, repos)
    print(f"added {args.name} -> {path}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)

    if args.name not in repos:
        print(f"warning: {args.name} is not registered", file=_stderr())
        return 0

    del repos[args.name]
    save_repos_json(config_dir, repos)
    print(f"removed {args.name}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config_dir = get_config_dir()
    repos = load_repos_json(config_dir)

    if args.name not in repos:
        print(f"error: {args.name} is not registered", file=_stderr())
        return 1

    print_json({args.name: repos[args.name]})
    return 0


def _stderr():
    import sys

    return sys.stderr
