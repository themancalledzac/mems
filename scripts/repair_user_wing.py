"""Strip leaked tool-call markup from User Wing entries.

Run inside the container: `python repair_user_wing.py [--apply]`. It is a dry run unless
`--apply` is passed. A leaked `<parameter name="source_wing">X` fills in a missing source_wing.
"""

import argparse
import os
import re
import sys

MARKUP_MARKERS = ("</content>", "<parameter", "</parameter>", "<invoke")
SOURCE_WING_TAG = re.compile(r'<parameter name="source_wing">\s*([^<\s]+)')
SAMPLE_LIMIT = 5
SAMPLE_CHARS = 160


def open_collection(palace_path: str):
    from mempalace.palace import get_collection

    return get_collection(palace_path, collection_name="mempalace_drawers", create=False)


def _first_marker(document: str) -> int:
    hits = [document.find(m) for m in MARKUP_MARKERS if m in document]
    return min(hits) if hits else -1


def plan_repairs(collection) -> dict:
    """List the user entries holding markup, each with its stripped text and metadata fix.

    Entries that would be empty after stripping are listed in `skipped_empty` and left alone.
    """
    results = collection.get(where={"wing": "user"}, include=["documents", "metadatas"])
    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    repairs = []
    skipped_empty = []
    for drawer_id, document, meta in zip(ids, documents, metadatas):
        cut = _first_marker(document or "")
        if cut < 0:
            continue
        cleaned = document[:cut].rstrip()
        if not cleaned:
            skipped_empty.append(drawer_id)
            continue
        updates = {}
        tag = SOURCE_WING_TAG.search(document[cut:])
        if tag and not (meta or {}).get("source_wing"):
            updates["source_wing"] = tag.group(1)
        repairs.append(
            {"id": drawer_id, "before": document, "after": cleaned, "metadata_updates": updates}
        )
    return {"scanned": len(ids), "repairs": repairs, "skipped_empty": skipped_empty}


def apply_repairs(collection, repairs: list[dict]) -> int:
    for repair in repairs:
        if repair["metadata_updates"]:
            collection.update(
                ids=[repair["id"]],
                documents=[repair["after"]],
                metadatas=[repair["metadata_updates"]],
            )
        else:
            collection.update(ids=[repair["id"]], documents=[repair["after"]])
    return len(repairs)


def _tail(text: str) -> str:
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= SAMPLE_CHARS else "..." + flat[-SAMPLE_CHARS:]


def run(collection, apply: bool) -> dict:
    """Plan, print a report with up to SAMPLE_LIMIT before/after samples, and apply if asked."""
    plan = plan_repairs(collection)
    repairs = plan["repairs"]
    fills = sum(1 for r in repairs if r["metadata_updates"])
    mode = "apply" if apply else "dry run"
    print(f"[{mode}] scanned {plan['scanned']} user entries")
    print(f"[{mode}] {len(repairs)} entries hold tool-call markup")
    print(f"[{mode}] {fills} would get source_wing from the leaked tag")
    print(f"[{mode}] {len(plan['skipped_empty'])} skipped (nothing left after stripping)")
    for repair in repairs[:SAMPLE_LIMIT]:
        print(f"- {repair['id']} {repair['metadata_updates'] or ''}")
        print(f"  before: {_tail(repair['before'])}")
        print(f"  after:  {_tail(repair['after'])}")
    applied = apply_repairs(collection, repairs) if apply else 0
    if apply:
        print(f"[apply] updated {applied} entries")
    return {
        "scanned": plan["scanned"],
        "would_repair": len(repairs),
        "source_wing_fills": fills,
        "skipped_empty": len(plan["skipped_empty"]),
        "applied": applied,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", default=False)
    mode.add_argument("--apply", dest="apply", action="store_true")
    parser.add_argument("--palace-path", default=None)
    args = parser.parse_args(argv)
    palace_path = args.palace_path or os.environ.get("PALACE_PATH", "/data/palace")
    run(open_collection(palace_path), apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
