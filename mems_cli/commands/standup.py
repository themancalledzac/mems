"""`mems standup` — a quick "what have I been up to" report.

Stitches together three independent sources, each degrading gracefully
(a note is printed and the section is skipped on failure, never crashing):

    1. Jira  — issues assigned to me, updated in the last N days.
    2. Palace — recent decisions / discoveries / goals from the user wing.
    3. Commits — `git log` from the current working directory.

With `--json` the same data is emitted as a single dict instead of a
human-readable sectioned report.
"""

from __future__ import annotations

import argparse
import subprocess

from mems_cli.commands.tickets import JiraClientError, load_client
from mems_cli.common import extract_tool_result, print_json
from mems_cli.palace_client import PalaceClient, PalaceClientError

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_SERVER_ERROR = 2


def register(subparsers: argparse._SubParsersAction) -> None:
    standup_p = subparsers.add_parser(
        "standup",
        help="Daily standup: recent Jira updates, palace notes, and git commits.",
    )
    standup_p.add_argument("--days", "-d", type=int, default=1)
    standup_p.add_argument("--json", action="store_true")
    standup_p.set_defaults(func=cmd_standup)


# --- section collectors -------------------------------------------------------
#
# Each returns a (data, note) pair: `data` is the structured payload for JSON
# mode, `note` is a human string explaining a skip/empty (or None on success).


def _collect_jira(days: int) -> tuple[list, str | None]:
    client = load_client()
    if client is None:
        # load_client already printed the env error to stderr.
        return [], "(no Jira creds — skipping)"

    jql = f"assignee = currentUser() AND updated >= -{days}d ORDER BY updated DESC"
    try:
        data = client.search(jql)
    except JiraClientError as exc:
        return [], f"(jira error: {exc})"

    issues = data.get("issues") or []
    rows = []
    for issue in issues:
        fields = issue.get("fields", {}) or {}
        status_obj = fields.get("status") or {}
        status = status_obj.get("name", "-") if isinstance(status_obj, dict) else "-"
        rows.append(
            {
                "key": issue.get("key", "?"),
                "status": status,
                "summary": (fields.get("summary") or "").strip(),
            }
        )
    return rows, None


def _collect_palace() -> tuple[dict, str | None]:
    try:
        with PalaceClient() as palace:
            raw = palace.call("mempalace_user_summary", {})
    except PalaceClientError as exc:
        return {}, f"(palace unavailable: {exc})"

    summary = extract_tool_result(raw)
    if not isinstance(summary, dict):
        # Some tools return the summary as a bare string.
        return ({"text": summary} if summary else {}), None
    return summary, None


def _collect_commits(days: int) -> tuple[list, str | None]:
    try:
        proc = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--oneline"],
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001 — git may be missing entirely
        return [], f"(git unavailable: {exc})"

    if proc.returncode != 0:
        note = (proc.stderr or "git log failed").strip()
        return [], f"(git error: {note})"

    commits = [line for line in proc.stdout.splitlines() if line.strip()]
    return commits, None


# --- rendering ----------------------------------------------------------------


def _print_jira(rows: list, note: str | None) -> None:
    print("## Jira updates")
    if note:
        print(note)
    if rows:
        for row in rows:
            print(f"  {row['key']}  [{row['status']}]  {row['summary']}")
    elif not note:
        print("(nothing updated)")
    print()


def _print_palace(summary: dict, note: str | None) -> None:
    print("## Palace (recent)")
    if note:
        print(note)
        print()
        return
    text = summary.get("text") if isinstance(summary, dict) else None
    if text:
        print(text)
    elif summary:
        print_json(summary)
    else:
        print("(no recent palace context)")
    print()


def _print_commits(commits: list, note: str | None) -> None:
    print("## Commits")
    if note:
        print(note)
    if commits:
        for line in commits:
            print(f"  {line}")
    elif not note:
        print("(no commits)")
    print()


def cmd_standup(args: argparse.Namespace) -> int:
    days = getattr(args, "days", 1)

    jira_rows, jira_note = _collect_jira(days)
    palace_summary, palace_note = _collect_palace()
    commits, commit_note = _collect_commits(days)

    if getattr(args, "json", False):
        print_json(
            {
                "days": days,
                "jira": {"issues": jira_rows, "note": jira_note},
                "palace": {"summary": palace_summary, "note": palace_note},
                "commits": {"entries": commits, "note": commit_note},
            }
        )
        return EXIT_OK

    _print_jira(jira_rows, jira_note)
    _print_palace(palace_summary, palace_note)
    _print_commits(commits, commit_note)
    return EXIT_OK
