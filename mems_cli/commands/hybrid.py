"""`mems hybrid <ticket>` — join a Jira ticket with palace search hits."""

from __future__ import annotations

import argparse
import json
import sys

from mems_cli.commands.tickets import JiraClientError, load_client
from mems_cli.common import extract_tool_result
from mems_cli.palace_client import PalaceClient, PalaceClientError

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    h_p = subparsers.add_parser(
        "hybrid",
        help="Look up a Jira ticket then search the palace for related drawers.",
    )
    h_p.add_argument("ticket_id")
    h_p.add_argument("--limit", "-n", type=int, default=5)
    h_p.set_defaults(func=cmd_hybrid)


def _description_text(raw) -> str:
    """Extract plain-ish text from a Jira description (ADF or string)."""
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        # Walk the ADF tree for any `text` leaves.
        texts: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("text"), str):
                    texts.append(node["text"])
                for child in node.get("content") or []:
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(raw)
        return " ".join(texts)
    return json.dumps(raw)


def cmd_hybrid(args: argparse.Namespace) -> int:
    client = load_client()
    if client is None:
        return EXIT_USER_ERROR

    try:
        issue = client.issue(args.ticket_id)
    except JiraClientError as exc:
        print(f"jira error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    fields = issue.get("fields", {}) or {}
    summary = (fields.get("summary") or "").strip()
    description = _description_text(fields.get("description"))[:200]
    query = f"{summary} {description}".strip()
    if not query:
        print(
            f"error: ticket {args.ticket_id} has no summary/description to query on",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "-") if isinstance(status_obj, dict) else "-"

    print(f"{issue.get('key', args.ticket_id)}  {summary}")
    print(f"status: {status}")
    print()

    try:
        with PalaceClient() as palace:
            raw = palace.call(
                "mempalace_search_all",
                {"query": query, "n": args.limit},
            )
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    data = extract_tool_result(raw)
    hits = []
    if isinstance(data, dict):
        for key in ("drawers", "closets", "results"):
            hits.extend(data.get(key) or [])

    if not hits:
        print("no palace matches")
        return EXIT_OK

    print(f"top {min(len(hits), args.limit)} palace matches:")
    for hit in hits[: args.limit]:
        meta = hit.get("metadata") or {}
        path = meta.get("source_path") or meta.get("path") or meta.get("wing", "?")
        distance = hit.get("distance")
        score = f"{1.0 - distance:.3f}" if isinstance(distance, (int, float)) else "?"
        content = (hit.get("document") or hit.get("content") or "").strip()
        snippet = content[:160].replace("\n", " ")
        print(f"  ({score})  {path}")
        print(f"    {snippet}")
    return EXIT_OK
