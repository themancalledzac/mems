"""`mems todo` — list my open Jira tickets.

Thin convenience wrapper over the Jira client in `tickets.py`: runs a
fixed "assigned to me and not Done" JQL, optionally scoped to a project.
"""

from __future__ import annotations

import argparse
import sys

from mems_cli.commands.tickets import JiraClientError, load_client
from mems_cli.common import print_json, print_table

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    todo_p = subparsers.add_parser(
        "todo",
        help="List my open Jira tickets (assigned to me, not Done).",
    )
    todo_p.add_argument("--limit", "-n", type=int, default=20)
    todo_p.add_argument("--project", default=None, help='Scope to a project key, e.g. "ABC".')
    todo_p.add_argument("--json", action="store_true")
    todo_p.set_defaults(func=cmd_todo)


def _build_jql(project: str | None) -> str:
    jql = "assignee = currentUser() AND statusCategory != Done"
    if project:
        jql += f' AND project = "{project}"'
    jql += " ORDER BY updated DESC"
    return jql


def _row_from_issue(issue: dict) -> tuple:
    key = issue.get("key", "?")
    fields = issue.get("fields", {}) or {}
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "-") if isinstance(status_obj, dict) else "-"
    summary = (fields.get("summary") or "").strip()[:70]
    return (key, status, summary)


def cmd_todo(args: argparse.Namespace) -> int:
    client = load_client()
    if client is None:
        return EXIT_USER_ERROR

    jql = _build_jql(getattr(args, "project", None))
    try:
        data = client.search(jql, limit=args.limit)
    except JiraClientError as exc:
        print(f"jira error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    issues = data.get("issues") or []
    if getattr(args, "json", False):
        print_json(issues)
        return EXIT_OK

    rows = [_row_from_issue(i) for i in issues]
    print_table(rows, headers=("key", "status", "summary"))
    return EXIT_OK
