"""`mems eval` — score retrieval against the question set and gate on regressions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mems_cli.common import (
    EXIT_OK,
    EXIT_SERVER_ERROR,
    EXIT_USER_ERROR,
    extract_tool_result,
)
from mems_cli.eval_scoring import aggregate, compare, normalize_hit, score_question, served_files
from mems_cli.palace_client import PalaceClient, PalaceClientError

EXIT_REGRESSION = 1
EXIT_DRIFT = 3
USER_WING = "user"
FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
DEFAULT_CORPUS = FIXTURES / "retrieval_corpus.json"
DEFAULT_BASELINE = FIXTURES / "retrieval_baseline.json"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("eval", help="Score retrieval against the question set.")
    p.add_argument("--holdout", action="store_true", help="Run the holdout split only.")
    p.add_argument("--wing", default=None)
    p.add_argument("--n", type=int, default=10, help="Hits requested per query.")
    p.add_argument("--arg", action="append", default=[], metavar="K=V")
    p.add_argument("--out", default=None, help="Write the run to this JSON file.")
    p.add_argument(
        "--compare",
        nargs="?",
        const=str(DEFAULT_BASELINE),
        default=None,
        metavar="BASELINE",
    )
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--allow-drift", action="store_true")
    p.add_argument("--json", dest="as_json", action="store_true")
    p.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    p.set_defaults(func=cmd_eval)


def code_root() -> Path:
    return Path(os.environ.get("MEMS_CODE_ROOT", "~/Code")).expanduser()


def gold_present(repo_dir: str, sha: str, path: str) -> bool:
    """True when `path` exists in the repo at commit `sha`."""
    proc = subprocess.run(
        ["git", "-C", str(code_root() / repo_dir), "cat-file", "-e", f"{sha}:{path}"],
        capture_output=True,
    )
    return proc.returncode == 0


def _parse_extra(pairs: list[str]) -> dict:
    extra = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"--arg expects k=v, got {pair!r}")
        try:
            extra[key] = json.loads(raw)
        except json.JSONDecodeError:
            extra[key] = raw
    return extra


def _groups(question: dict) -> list[list[str]]:
    return [[g] if isinstance(g, str) else list(g) for g in question["gold"]]


def _is_stale(question: dict, corpus: dict, shas: dict) -> bool:
    sha = shas.get(question["wing"])
    if not sha:
        return True
    repo_dir = corpus["wings"][question["wing"]]["repo_dir"]
    return any(
        not any(gold_present(repo_dir, sha, path) for path in group) for group in _groups(question)
    )


def _search(client, question: dict, n: int, extra: dict) -> tuple[list[dict], float]:
    if question["wing"] == USER_WING:
        tool, payload = "mempalace_user_search", {"query": question["query"], "n_results": n}
    else:
        tool = "mempalace_search"
        payload = {"query": question["query"], "wing": question["wing"], "n": n}
    payload.update(extra)
    start = time.perf_counter()
    data = extract_tool_result(client.call(tool, payload))
    elapsed = (time.perf_counter() - start) * 1000
    hits = data.get("results", []) if isinstance(data, dict) else []
    return hits, elapsed


def _score(question: dict, hits: list[dict], elapsed_ms: float) -> dict:
    if question["wing"] == USER_WING:
        served = [h["id"] for h in hits if h.get("id")]
        chunk_paths = list(served)
    else:
        served = served_files(hits)
        chunk_paths = [normalize_hit(h)[0] for h in hits]
    row = score_question(served, _groups(question), chunk_paths)
    row["id"] = question["id"]
    row["latency_ms"] = elapsed_ms
    return row


def _select(corpus: dict, args: argparse.Namespace) -> list[dict]:
    split = "holdout" if args.holdout else "dev"
    return [
        q
        for q in corpus["questions"]
        if q["split"] == split and (not args.wing or q["wing"] == args.wing)
    ]


def run_eval(corpus: dict, args: argparse.Namespace, extra: dict) -> dict:
    """Run every selected question and return the aggregated run."""
    questions = _select(corpus, args)
    with PalaceClient() as client:
        status = extract_tool_result(client.call("memory_sync_status", {}))
        entries = status.get("wings", {}) if isinstance(status, dict) else {}
        shas = {
            q["wing"]: (entries.get(q["wing"]) or {}).get("last_commit_sha")
            for q in questions
            if q["wing"] != USER_WING
        }
        repo_rows, user_rows, stale = [], [], []
        for q in questions:
            if q["wing"] == USER_WING:
                hits, ms = _search(client, q, args.n, extra)
                user_rows.append(_score(q, hits, ms))
            elif _is_stale(q, corpus, shas):
                stale.append(q["id"])
            else:
                hits, ms = _search(client, q, args.n, extra)
                repo_rows.append(_score(q, hits, ms))
    run = aggregate(repo_rows)
    run.update(
        {
            "shas": shas,
            "stale": len(stale),
            "stale_ids": stale,
            "user": dict(aggregate(user_rows), n=len(user_rows)),
            "rows": repo_rows + user_rows,
        }
    )
    return run


def _print_run(run: dict, verdict: dict | None) -> None:
    print(f"scored {run['n_scored']}  stale {run['stale']}  user {run['user']['n']}")
    for metric in ("hit1", "recall3", "recall5", "rr", "file_precision", "chunk_precision"):
        print(f"  {metric:<16}{run[metric]:.3f}")
    print(f"  latency p50 {run['p50_ms']:.0f} ms  p95 {run['p95_ms']:.0f} ms")
    if run["user"]["n"]:
        print(f"  user wing (not gated): hit1 {run['user']['hit1']:.3f} over {run['user']['n']}")
    if verdict:
        print(f"  tolerance {verdict['tol']:.3f}")
        for warning in verdict["warnings"]:
            print(f"  warning: {warning}")
        if verdict["regressions"]:
            print(f"  REGRESSION: {', '.join(verdict['regressions'])}")


def _drifted(run: dict, base: dict) -> bool:
    base_shas = base.get("shas", {})
    return any(base_shas.get(w) != sha for w, sha in run["shas"].items() if w in base_shas)


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        corpus = json.loads(Path(args.corpus).read_text())
        extra = _parse_extra(args.arg)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        run = run_eval(corpus, args, extra)
    except PalaceClientError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR

    verdict = None
    code = EXIT_OK
    if args.compare:
        try:
            base = json.loads(Path(args.compare).read_text())
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USER_ERROR
        if _drifted(run, base) and not args.allow_drift:
            print(
                "error: wing SHAs differ from the baseline; rerun with --allow-drift",
                file=sys.stderr,
            )
            return EXIT_DRIFT
        verdict = compare(run, base)
        run["verdict"] = verdict
        if not verdict["ok"]:
            code = EXIT_REGRESSION

    text = json.dumps(run, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n")
    if args.update_baseline:
        DEFAULT_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_BASELINE.write_text(text + "\n")
    if args.as_json:
        print(text)
    else:
        _print_run(run, verdict)
    return code
