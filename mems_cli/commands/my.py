"""`mems my <action>` — personal User Wing shortcuts.

A thin, friendly wrapper over the User Wing MCP tools so common personal
lookups read like sentences:

    mems my questions [QUERY]        # search the `questions` hall
    mems my discoveries [QUERY]      # search the `discoveries` hall
    mems my frustrations [QUERY]     # ...
    mems my goals [QUERY]
    mems my decisions [QUERY]
    mems my observations [QUERY]
    mems my recent [--days N] [-n N] # entries touched recently, newest first
    mems my note "<text>" --hall <hall> --topic <topic>

The six hall subcommands all map to `mempalace_user_search`; `recent`
maps to `mempalace_user_recent`; `note` maps to `mempalace_user_write`.

Conventions (tool call, result unwrapping, error handling, output) follow
`mems_cli.commands.search`.
"""

from __future__ import annotations

import argparse
import sys

from mems_cli.common import extract_tool_result, print_json, print_table
from mems_cli.palace_client import PalaceClient, PalaceClientError

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2

VALID_HALLS = ("questions", "discoveries", "frustrations", "goals", "decisions", "observations")


def register(subparsers: argparse._SubParsersAction) -> None:
    my_p = subparsers.add_parser("my", help="Personal User Wing shortcuts.")
    my_sub = my_p.add_subparsers(dest="my_cmd", metavar="ACTION")

    for hall in VALID_HALLS:
        hall_p = my_sub.add_parser(hall, help=f"Search the {hall} hall of your User Wing.")
        hall_p.add_argument("query", nargs="?", default="", help="Optional search text.")
        hall_p.add_argument("--limit", "-n", type=int, default=10)
        hall_p.add_argument("--json", dest="as_json", action="store_true")
        hall_p.set_defaults(func=_make_hall_handler(hall), hall=hall)

    recent_p = my_sub.add_parser(
        "recent", help="Show User Wing entries touched recently, newest first."
    )
    recent_p.add_argument("--days", type=float, default=7)
    recent_p.add_argument("--limit", "-n", type=int, default=20)
    recent_p.add_argument("--json", dest="as_json", action="store_true")
    recent_p.set_defaults(func=cmd_my_recent)

    note_p = my_sub.add_parser("note", help="File a thought into a User Wing hall.")
    note_p.add_argument("text", help="The thought to record.")
    note_p.add_argument("--hall", default="observations", help="|".join(VALID_HALLS))
    note_p.add_argument("--topic", default="general")
    note_p.add_argument("--source-wing", default=None)
    note_p.set_defaults(func=cmd_my_note)

    my_p.set_defaults(func=_no_action)


def _no_action(args: argparse.Namespace) -> int:
    actions = "|".join((*VALID_HALLS, "recent", "note"))
    print(f"usage: mems my {{{actions}}} ...")
    return EXIT_USER_ERROR


def _call(tool: str, args: dict | None = None):
    """Call an MCP tool; return (payload, exit_code). Mirrors search._call."""
    try:
        with PalaceClient() as client:
            result = client.call(tool, args or {})
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return None, EXIT_SERVER_ERROR
    return extract_tool_result(result), EXIT_OK


def _hits_from(data) -> list:
    """Pull the list of thought entries out of a user-search payload.

    `mempalace_user_search` may return a bare list, or a dict keyed by
    `results` / `drawers` / `closets`. Be liberal about the shape.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "drawers", "closets"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _row_from_hit(hit, time_key: str = "timestamp") -> tuple:
    """(topic, snippet, time) row for one thought entry, falling back to `timestamp`."""
    if not isinstance(hit, dict):
        return ("?", str(hit)[:120].replace("\n", " "), "-")
    meta = hit.get("metadata") or {}
    topic = hit.get("topic") or meta.get("topic") or "-"
    timestamp = hit.get(time_key) or hit.get("timestamp") or meta.get("timestamp") or "-"
    content = (hit.get("document") or hit.get("content") or hit.get("text") or "").strip()
    snippet = content[:120].replace("\n", " ")
    return (str(topic), snippet, str(timestamp))


def _print_hall_results(data, as_json: bool, time_key: str = "timestamp") -> None:
    if as_json:
        print_json(data)
        return
    hits = _hits_from(data)
    if not hits:
        print("(no matching thoughts)")
        return
    rows = [_row_from_hit(h, time_key) for h in hits]
    print_table(rows, headers=("topic", "snippet", "timestamp"))


def _make_hall_handler(hall: str):
    """Build a `cmd_my_<hall>` handler bound to one hall name."""

    def handler(args: argparse.Namespace) -> int:
        payload = {
            "query": getattr(args, "query", "") or "",
            "hall": hall,
            "n_results": getattr(args, "limit", 10),
        }
        data, code = _call("mempalace_user_search", payload)
        if code != EXIT_OK:
            return code
        _print_hall_results(data, getattr(args, "as_json", False))
        return EXIT_OK

    handler.__name__ = f"cmd_my_{hall}"
    handler.__qualname__ = f"cmd_my_{hall}"
    return handler


cmd_my_questions = _make_hall_handler("questions")
cmd_my_discoveries = _make_hall_handler("discoveries")
cmd_my_frustrations = _make_hall_handler("frustrations")
cmd_my_goals = _make_hall_handler("goals")
cmd_my_decisions = _make_hall_handler("decisions")
cmd_my_observations = _make_hall_handler("observations")


def cmd_my_recent(args: argparse.Namespace) -> int:
    """Table of entries touched in the last `--days`, with the time column showing last_seen."""
    payload = {"days": getattr(args, "days", 7), "n": getattr(args, "limit", 20)}
    data, code = _call("mempalace_user_recent", payload)
    if code != EXIT_OK:
        return code
    _print_hall_results(data, getattr(args, "as_json", False), time_key="last_seen")
    return EXIT_OK


def cmd_my_note(args: argparse.Namespace) -> int:
    if args.hall not in VALID_HALLS:
        print(
            f"error: hall must be one of {list(VALID_HALLS)}, got {args.hall!r}",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR
    payload = {
        "hall": args.hall,
        "content": args.text,
        "topic": args.topic,
    }
    source_wing = getattr(args, "source_wing", None)
    if source_wing:
        payload["source_wing"] = source_wing
    data, code = _call("mempalace_user_write", payload)
    if code != EXIT_OK:
        return code
    print_json(data)
    return EXIT_OK
