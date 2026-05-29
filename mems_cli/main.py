"""`mems` CLI dispatcher.

Phase 6 wires up the scaffolding plus two real subcommands:
  - `mems health` — hits `/health` on the MCP server
  - `mems tools`  — lists the tools the server advertises

Phase 7 modules will call `register_subcommands` with their own parsers.
The dispatch table is a mutable module-level dict that later modules can
extend via `register_command`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from mems_cli import __version__
from mems_cli.common import get_server_url, print_table
from mems_cli.palace_client import PalaceClient, PalaceClientError

# Exit codes
EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


CommandHandler = Callable[[argparse.Namespace], int]


# Dispatch table — Phase 7 modules extend this via `register_command`.
_COMMANDS: dict[str, CommandHandler] = {}


def register_command(name: str, handler: CommandHandler) -> None:
    """Register a subcommand handler. Later phases call this."""
    _COMMANDS[name] = handler


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser with Phase 6 subcommands."""
    parser = argparse.ArgumentParser(
        prog="mems",
        description="Memory Palace CLI — talk to the MCP server.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mems {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    register_subcommands(subparsers)
    return parser


def register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Wire built-in subcommands + extension point for Phase 7 modules."""
    health_p = subparsers.add_parser("health", help="Check palace server health.")
    health_p.set_defaults(func=cmd_health)
    register_command("health", cmd_health)

    tools_p = subparsers.add_parser("tools", help="List tools the server exposes.")
    tools_p.set_defaults(func=cmd_tools)
    register_command("tools", cmd_tools)

    # Phase 7 command modules.
    from mems_cli.commands import (
        hybrid,
        my,
        palace_ops,
        publishing,
        repo_registry,
        search,
        standup,
        tickets,
        todo,
    )

    for module in (
        repo_registry,
        palace_ops,
        search,
        my,
        publishing,
        tickets,
        todo,
        standup,
        hybrid,
    ):
        module.register(subparsers)


# --- Handlers ----------------------------------------------------------------


def cmd_health(args: argparse.Namespace) -> int:
    """Call /health and print status."""
    try:
        with PalaceClient() as client:
            data = client.health()
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    status = data.get("status") or ("ok" if data.get("ok") else "down")
    url = get_server_url()
    print(f"server: {url}")
    print(f"status: {status}")
    wings = data.get("wings")
    if isinstance(wings, list):
        print(f"wings:  {len(wings)}")
    return EXIT_OK


def cmd_tools(args: argparse.Namespace) -> int:
    """List MCP tools the server advertises."""
    try:
        with PalaceClient() as client:
            tools = client.list_tools()
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    rows = [
        (tool.get("name", "?"), (tool.get("description") or "").splitlines()[0][:70])
        for tool in tools
    ]
    print_table(rows, headers=("name", "description"))
    print()
    print(f"{len(tools)} tool(s)")
    return EXIT_OK


# --- Entry point -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USER_ERROR

    handler = getattr(args, "func", None) or _COMMANDS.get(args.command)
    if handler is None:
        print(f"unknown command: {args.command}", file=sys.stderr)
        return EXIT_USER_ERROR

    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
