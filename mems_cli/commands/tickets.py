"""`mems ticket ...` — minimal Jira API v3 client (stdlib only).

Config via env vars:
    JIRA_URL        e.g. "https://example.atlassian.net"
    JIRA_EMAIL      atlassian account email
    JIRA_API_TOKEN  token from id.atlassian.com
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from mems_cli.common import print_json, print_table

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    ticket_p = subparsers.add_parser("ticket", help="Jira ticket commands.")
    ticket_sub = ticket_p.add_subparsers(dest="ticket_cmd", metavar="ACTION")

    list_p = ticket_sub.add_parser("list", help="List tickets (optionally filtered).")
    list_p.add_argument("--assignee", default=None, help="'ME' for current user.")
    list_p.add_argument("--status", default=None)
    list_p.add_argument("--limit", "-n", type=int, default=20)
    list_p.add_argument("--json", dest="as_json", action="store_true")
    list_p.set_defaults(func=cmd_list)

    show_p = ticket_sub.add_parser("show", help="Show one ticket.")
    show_p.add_argument("ticket_id")
    show_p.add_argument("--json", dest="as_json", action="store_true")
    show_p.set_defaults(func=cmd_show)

    search_p = ticket_sub.add_parser("search", help="Search tickets by JQL.")
    search_p.add_argument("jql")
    search_p.add_argument("--limit", "-n", type=int, default=20)
    search_p.add_argument("--json", dest="as_json", action="store_true")
    search_p.set_defaults(func=cmd_search)

    ticket_p.set_defaults(func=_no_action)


def _no_action(args: argparse.Namespace) -> int:
    print("usage: mems ticket {list|show|search} ...")
    return 1


# --- Jira client --------------------------------------------------------------


class JiraClientError(RuntimeError):
    pass


class JiraClient:
    """Tiny Jira REST v3 client. urllib + base64 basic auth."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self._auth}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise JiraClientError(f"HTTP {exc.code} {exc.reason} from {url}") from exc
        except urllib.error.URLError as exc:
            raise JiraClientError(f"connection failed to {url}: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise JiraClientError(f"request failed: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JiraClientError(f"non-JSON response from Jira: {exc}") from exc

    def search(self, jql: str, limit: int = 20) -> dict:
        return self._get(
            "/rest/api/3/search",
            params={"jql": jql, "maxResults": limit},
        )

    def issue(self, key: str) -> dict:
        return self._get(f"/rest/api/3/issue/{urllib.parse.quote(key)}")


def load_client() -> JiraClient | None:
    """Return a JiraClient or None. Prints a clear error + returns None on miss."""
    url = os.environ.get("JIRA_URL")
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not (url and email and token):
        print(
            "error: Jira not configured. Set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN",
            file=sys.stderr,
        )
        return None
    return JiraClient(url, email, token)


# --- rendering ----------------------------------------------------------------


def _row_from_issue(issue: dict) -> tuple:
    key = issue.get("key", "?")
    fields = issue.get("fields", {}) or {}
    summary = (fields.get("summary") or "").strip()[:70]
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "-") if isinstance(status_obj, dict) else "-"
    assignee_obj = fields.get("assignee") or {}
    assignee = assignee_obj.get("displayName", "-") if isinstance(assignee_obj, dict) else "-"
    return (key, summary, status, assignee)


def _render_list(issues: list, as_json: bool) -> None:
    if as_json:
        print_json(issues)
        return
    rows = [_row_from_issue(i) for i in issues]
    print_table(rows, headers=("key", "summary", "status", "assignee"))


def _render_issue(issue: dict, as_json: bool) -> None:
    if as_json:
        print_json(issue)
        return
    key = issue.get("key", "?")
    fields = issue.get("fields", {}) or {}
    summary = fields.get("summary", "")
    status_obj = fields.get("status") or {}
    status = status_obj.get("name", "-") if isinstance(status_obj, dict) else "-"
    assignee_obj = fields.get("assignee") or {}
    assignee = assignee_obj.get("displayName", "-") if isinstance(assignee_obj, dict) else "-"
    description = fields.get("description") or ""
    if isinstance(description, dict):
        # Atlassian Document Format — fall back to JSON dump.
        description = json.dumps(description)

    print(f"{key}  {summary}")
    print(f"status: {status}    assignee: {assignee}")
    print()
    if description:
        print(description)


# --- handlers -----------------------------------------------------------------


def _build_list_jql(args: argparse.Namespace) -> str:
    clauses = []
    if args.assignee:
        clauses.append(
            "assignee = currentUser()"
            if args.assignee.upper() == "ME"
            else f'assignee = "{args.assignee}"'
        )
    if args.status:
        clauses.append(f'status = "{args.status}"')
    jql = " AND ".join(clauses) if clauses else "order by updated DESC"
    if clauses:
        jql += " ORDER BY updated DESC"
    return jql


def cmd_list(args: argparse.Namespace) -> int:
    client = load_client()
    if client is None:
        return EXIT_USER_ERROR

    jql = _build_list_jql(args)
    try:
        data = client.search(jql, limit=args.limit)
    except JiraClientError as exc:
        print(f"jira error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    issues = data.get("issues") or []
    _render_list(issues, getattr(args, "as_json", False))
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    client = load_client()
    if client is None:
        return EXIT_USER_ERROR
    try:
        issue = client.issue(args.ticket_id)
    except JiraClientError as exc:
        print(f"jira error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR
    _render_issue(issue, getattr(args, "as_json", False))
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    client = load_client()
    if client is None:
        return EXIT_USER_ERROR
    try:
        data = client.search(args.jql, limit=args.limit)
    except JiraClientError as exc:
        print(f"jira error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR
    issues = data.get("issues") or []
    _render_list(issues, getattr(args, "as_json", False))
    return EXIT_OK
