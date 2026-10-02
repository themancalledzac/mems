"""Tag personal, non-code User Wing entries with `personal=True`.

Run inside the container: `python tag_personal.py [--apply] [--apply-unscoped]`. It is a dry run
unless a flag is passed. `--apply` tags entries whose source_wing is a personal wing, and
`--apply-unscoped` tags entries with no source_wing that match PERSONAL_KEYWORDS.
"""

import argparse
import os
import re
import sys

DEFAULT_PERSONAL_WINGS = ("job-search", "running")
PERSONAL_KEYWORDS = (
    "integrate",
    "cheat sheet",
    "résumé",
    "cover letter",
    "recruiter",
    "interview",
    "interviews",
    "job posting",
    "job search",
    "hiring manager",
    "salary",
    "offer letter",
    "marathon",
    "half marathon",
    "5k",
    "10k",
    "mileage",
    "strava",
    "garmin",
    "workout",
    "heart rate",
    "injury",
    "doctor",
    "mortgage",
    "taxes",
    "401k",
    "paycheck",
    "savings account",
)
"""Whole-word, case-insensitive matches against an unscoped entry's topic and text.

Built from the live null-source entries: job search and interviews, running and health, money.
Bare "resume" and "savings" are left out because code entries use them ("resume a run").
"""
SAMPLE_LIMIT = 10
PREVIEW_CHARS = 100
KEYWORD_PATTERNS = {
    keyword: re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", re.IGNORECASE)
    for keyword in PERSONAL_KEYWORDS
}


def open_collection(palace_path: str):
    from mempalace.palace import get_collection

    return get_collection(palace_path, collection_name="mempalace_drawers", create=False)


def _keywords_in(text: str) -> list[str]:
    return [keyword for keyword, pattern in KEYWORD_PATTERNS.items() if pattern.search(text)]


def plan_tags(collection, personal_wings: set[str]) -> dict:
    """Sort untagged user entries into wing matches, keyword matches and unscoped non-matches.

    Entries already marked personal are only counted. Scoped entries outside personal_wings
    are ignored.
    """
    results = collection.get(where={"wing": "user"}, include=["documents", "metadatas"])
    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    by_wing, by_keyword, unmatched = [], [], []
    already_personal = 0
    for drawer_id, document, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        if meta.get("personal", False):
            already_personal += 1
            continue
        entry = {
            "id": drawer_id,
            "topic": meta.get("topic", ""),
            "source_wing": meta.get("source_wing"),
            "text": " ".join((document or "").split()),
        }
        if entry["source_wing"] in personal_wings:
            by_wing.append(entry)
        elif not entry["source_wing"]:
            entry["keywords"] = _keywords_in(f"{entry['topic']} {entry['text']}")
            (by_keyword if entry["keywords"] else unmatched).append(entry)
    return {
        "scanned": len(ids),
        "already_personal": already_personal,
        "by_wing": by_wing,
        "by_keyword": by_keyword,
        "unmatched": unmatched,
    }


def apply_tags(collection, entries: list[dict]) -> int:
    ids = [entry["id"] for entry in entries]
    if ids:
        collection.update(ids=ids, metadatas=[{"personal": True} for _ in ids])
    return len(ids)


def _line(entry: dict) -> str:
    return f"- {entry['id']} {entry['topic']} {entry['text'][:PREVIEW_CHARS]}"


def run(collection, personal_wings: set[str], apply: bool, apply_unscoped: bool) -> dict:
    """Print counts, wing samples and every keyword match, then tag what the flags allow."""
    plan = plan_tags(collection, personal_wings)
    mode = "apply" if apply or apply_unscoped else "dry run"
    print(f"[{mode}] scanned {plan['scanned']} user entries")
    print(f"[{mode}] {plan['already_personal']} already personal, left alone")
    print(f"[{mode}] rule 1 (source_wing in {sorted(personal_wings)}): {len(plan['by_wing'])}")
    for entry in plan["by_wing"][:SAMPLE_LIMIT]:
        print(_line(entry))
    print(f"[{mode}] rule 2 (unscoped keyword match): {len(plan['by_keyword'])}")
    for entry in plan["by_keyword"]:
        print(f"{_line(entry)} [{', '.join(entry['keywords'])}]")
    print(f"[{mode}] unscoped entries matching no keyword: {len(plan['unmatched'])}")
    for entry in plan["unmatched"][:SAMPLE_LIMIT]:
        print(f"- {entry['id']} {entry['topic']}")
    applied = 0
    if apply:
        applied += apply_tags(collection, plan["by_wing"])
    if apply_unscoped:
        applied += apply_tags(collection, plan["by_keyword"])
    if applied:
        print(f"[apply] tagged {applied} entries personal")
    return {
        "scanned": plan["scanned"],
        "already_personal": plan["already_personal"],
        "by_wing": len(plan["by_wing"]),
        "by_keyword": len(plan["by_keyword"]),
        "unmatched": len(plan["unmatched"]),
        "applied": applied,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-unscoped", action="store_true")
    parser.add_argument("--wings", default=",".join(DEFAULT_PERSONAL_WINGS))
    parser.add_argument("--palace-path", default=None)
    args = parser.parse_args(argv)
    if args.dry_run and (args.apply or args.apply_unscoped):
        parser.error("--dry-run cannot be combined with --apply or --apply-unscoped")
    wings = {wing.strip() for wing in args.wings.split(",") if wing.strip()}
    palace_path = args.palace_path or os.environ.get("PALACE_PATH", "/data/palace")
    run(
        open_collection(palace_path),
        wings,
        apply=args.apply,
        apply_unscoped=args.apply_unscoped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
