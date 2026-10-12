"""`mems search|user-search|user-summary|user-write` — query commands."""

from __future__ import annotations

import argparse
import sys

from mems_cli.common import (
    EXIT_OK,
    EXIT_SERVER_ERROR,
    EXIT_USER_ERROR,
    extract_tool_result,
    print_json,
)
from mems_cli.eval_scoring import normalize_hit
from mems_cli.palace_client import PalaceClient, PalaceClientError

VALID_HALLS = {"questions", "discoveries", "frustrations", "goals", "decisions", "observations"}


def register(subparsers: argparse._SubParsersAction) -> None:
    search_p = subparsers.add_parser("search", help="Semantic search across the palace.")
    search_p.add_argument("query")
    search_p.add_argument("--wing", default=None)
    search_p.add_argument("--room", default=None)
    search_p.add_argument("--limit", "-n", type=int, default=10)
    search_p.add_argument("--json", dest="as_json", action="store_true")
    search_p.set_defaults(func=cmd_search)

    us_p = subparsers.add_parser("user-search", help="Search the User Wing.")
    us_p.add_argument("query")
    us_p.add_argument("--hall", default=None)
    us_p.add_argument("--limit", "-n", type=int, default=10)
    us_p.add_argument("--json", dest="as_json", action="store_true")
    us_p.set_defaults(func=cmd_user_search)

    um_p = subparsers.add_parser("user-summary", help="Show synthesized user context.")
    um_p.add_argument("--json", dest="as_json", action="store_true")
    um_p.set_defaults(func=cmd_user_summary)

    uw_p = subparsers.add_parser("user-write", help="File a thought into a User Wing hall.")
    uw_p.add_argument("hall", help="|".join(sorted(VALID_HALLS)))
    uw_p.add_argument("content")
    uw_p.add_argument("--topic", default="general")
    uw_p.add_argument("--source-wing", default=None)
    uw_p.set_defaults(func=cmd_user_write)


def _call(tool: str, args: dict | None = None):
    try:
        with PalaceClient() as client:
            result = client.call(tool, args or {})
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR
    return extract_tool_result(result), EXIT_OK


def _print_search_results(data, as_json: bool) -> None:
    if as_json or not isinstance(data, dict) or not isinstance(data.get("results"), list):
        print_json(data)
        return

    for hit in data["results"]:
        path, text = normalize_hit(hit)
        label = path or hit.get("id") or hit.get("wing") or "?"
        distance = hit.get("distance")
        score = f"{1.0 - distance:.3f}" if isinstance(distance, (int, float)) else "?"
        snippet = text.strip()[:180].replace("\n", " ")
        print(f"({score})  {label}")
        print(f"  {snippet}")
        print()


def cmd_search(args: argparse.Namespace) -> int:
    payload = {"query": args.query, "n": args.limit}
    if args.wing:
        payload["wing"] = args.wing
    if args.room:
        payload["room"] = args.room
    tool = "mempalace_search" if (args.wing or args.room) else "mempalace_search_all"
    data, code = _call(tool, payload)
    if code != EXIT_OK:
        return code
    _print_search_results(data, getattr(args, "as_json", False))
    return EXIT_OK


def cmd_user_search(args: argparse.Namespace) -> int:
    payload = {"query": args.query, "n_results": args.limit}
    if args.hall:
        payload["hall"] = args.hall
    data, code = _call("mempalace_user_search", payload)
    if code != EXIT_OK:
        return code
    _print_search_results(data, getattr(args, "as_json", False))
    return EXIT_OK


def cmd_user_summary(args: argparse.Namespace) -> int:
    data, code = _call("mempalace_user_summary")
    if code != EXIT_OK:
        return code
    if getattr(args, "as_json", False):
        print_json(data)
    else:
        text = (data or {}).get("text") if isinstance(data, dict) else None
        if text:
            print(text)
        else:
            print_json(data)
    return EXIT_OK


def cmd_user_write(args: argparse.Namespace) -> int:
    if args.hall not in VALID_HALLS:
        print(
            f"error: hall must be one of {sorted(VALID_HALLS)}, got {args.hall!r}",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR
    payload = {
        "hall": args.hall,
        "content": args.content,
        "topic": args.topic,
    }
    if args.source_wing:
        payload["source_wing"] = args.source_wing
    data, code = _call("mempalace_user_write", payload)
    if code != EXIT_OK:
        return code
    print_json(data)
    return EXIT_OK
