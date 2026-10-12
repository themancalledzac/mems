"""Sample real `mempalace_search` queries per wing from Claude Code transcripts.

Walks `<projects-dir>/*/*.jsonl` and `*/*/subagents/*.jsonl` with the walker in
`mems_cli.protocol_audit`. Only the query string and wing name of each call are kept.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mems_cli.protocol_audit import DEFAULT_PROJECTS_DIR, _iter_tool_calls

SEARCH_TOOL = "mempalace_search"


def _is_search(name: str) -> bool:
    return name == SEARCH_TOOL or name.endswith(f"__{SEARCH_TOOL}")


def _transcripts(root: Path):
    yield from root.glob("*/*.jsonl")
    yield from root.glob("*/*/subagents/*.jsonl")


def sample(projects_dir: Path, per_wing: int = 30) -> dict[str, list[dict]]:
    """Return `{wing: [{"query", "count"}]}`, most frequent first, capped at `per_wing`."""
    counts: dict[str, Counter] = {}
    for path in _transcripts(Path(projects_dir)):
        try:
            for name, tool_input in _iter_tool_calls(path):
                if not _is_search(name):
                    continue
                query, wing = tool_input.get("query"), tool_input.get("wing")
                if isinstance(query, str) and query.strip() and isinstance(wing, str) and wing:
                    counts.setdefault(wing, Counter())[query.strip()] += 1
        except OSError:
            continue
    return {
        wing: [{"query": q, "count": c} for q, c in counter.most_common(per_wing)]
        for wing, counter in sorted(counts.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projects-dir", default=str(DEFAULT_PROJECTS_DIR))
    parser.add_argument("--per-wing", type=int, default=30)
    parser.add_argument("--out", default=None, help="Write JSON here instead of stdout.")
    args = parser.parse_args(argv)
    text = json.dumps(sample(Path(args.projects_dir), args.per_wing), indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
