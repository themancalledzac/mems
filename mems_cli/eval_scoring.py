"""Scoring for the retrieval eval: hit normalising, per-question metrics, run comparison."""

from __future__ import annotations

import re
from typing import Any

CONTAINER_PREFIX = re.compile(r"^/repos/[^/]+/")
GATED_METRICS = ("hit1", "rr", "recall3")
MEAN_METRICS = ("hit1", "recall3", "recall5", "rr", "file_precision", "chunk_precision")
MIN_TOLERANCE = 0.03
P95_WARN_FACTOR = 2.0


def normalize_hit(hit: dict) -> tuple[str, str]:
    """Return (repo-relative path, text) for a search hit, tolerating both hit layouts."""
    meta = hit.get("metadata") or {}
    raw = hit.get("source_path") or meta.get("source_path") or ""
    text = hit.get("text") or hit.get("document") or hit.get("content") or ""
    return CONTAINER_PREFIX.sub("", raw), text


def served_files(hits: list[dict]) -> list[str]:
    """Distinct file paths of `hits`, in the order they first appear."""
    seen: dict[str, None] = {}
    for hit in hits:
        path, _ = normalize_hit(hit)
        if path:
            seen.setdefault(path, None)
    return list(seen)


def _rank(served: list[str], group: list[str]) -> int | None:
    ranks = [i for i, path in enumerate(served, start=1) if path in group]
    return min(ranks) if ranks else None


def _fraction(count: int, total: int) -> float:
    return count / total if total else 0.0


def score_question(
    served: list[str], gold_groups: list[list[str]], chunk_paths: list[str]
) -> dict[str, Any]:
    """Score one question. Only exact path matches count as gold."""
    ranks = [_rank(served, group) for group in gold_groups]
    found = [r for r in ranks if r is not None]
    gold_files = {path for group in gold_groups for path in group}
    n_groups = len(gold_groups)

    def recall(k: int) -> float:
        return _fraction(sum(1 for r in found if r <= k), min(k, n_groups))

    return {
        "ranks": ranks,
        "hit1": bool(served) and served[0] in gold_files,
        "recall3": recall(3),
        "recall5": recall(5),
        "rr": 1.0 / min(found) if found else 0.0,
        "file_precision": _fraction(sum(1 for p in served if p in gold_files), len(served)),
        "chunk_precision": _fraction(
            sum(1 for p in chunk_paths if p in gold_files), len(chunk_paths)
        ),
    }


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(pct * (len(ordered) - 1)))))
    return ordered[index]


def aggregate(rows: list[dict]) -> dict:
    """Mean of each metric over scored rows, plus latency percentiles."""
    result: dict[str, Any] = {"n_scored": len(rows)}
    for metric in MEAN_METRICS:
        values = [float(row[metric]) for row in rows]
        result[metric] = sum(values) / len(values) if values else 0.0
    latencies = [row["latency_ms"] for row in rows if "latency_ms" in row]
    result["p50_ms"] = _percentile(latencies, 0.5)
    result["p95_ms"] = _percentile(latencies, 0.95)
    return result


def compare(run: dict, base: dict, tol: float | None = None) -> dict:
    """Gate hit1, rr and recall3 against `base`. Latency only warns."""
    n = run.get("n_scored") or 0
    if tol is None:
        tol = max(MIN_TOLERANCE, 1.5 / n) if n else MIN_TOLERANCE
    regressions = [
        metric
        for metric in GATED_METRICS
        if base.get(metric, 0.0) - run.get(metric, 0.0) > tol + 1e-9
    ]
    warnings = []
    base_p95 = base.get("p95_ms") or 0.0
    if base_p95 and run.get("p95_ms", 0.0) >= base_p95 * P95_WARN_FACTOR:
        warnings.append(f"p95 latency {base_p95:.0f} ms -> {run['p95_ms']:.0f} ms")
    return {"ok": not regressions, "tol": tol, "regressions": regressions, "warnings": warnings}
