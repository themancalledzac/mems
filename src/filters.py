"""Priority-ordered room detection layered over mempalace.

Priority (per CONTEXT.md §6):
  1. rooms.json explicit blocks override
  2. Path prefix — wing path segment substring-matches a room name or keyword
  3. Keyword match — bag-of-words against room keywords, highest score wins
  4. Fallback — 'general'
"""

import json
from pathlib import Path


def _load_rooms_json(wing_root: Path) -> dict:
    path = wing_root / "rooms.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _explicit_block(rel_path: str, rooms_json: dict) -> str | None:
    blocks = rooms_json.get("blocks", {})
    for prefix, room_name in blocks.items():
        if rel_path.startswith(prefix):
            return room_name
    return None


def _path_prefix_match(rel_path: str, rooms: list[dict]) -> str | None:
    segments = {s.lower() for s in Path(rel_path).parts}
    for room in rooms:
        if room["name"].lower() in segments:
            return room["name"]
        for kw in room.get("keywords", []):
            if kw.lower() in segments:
                return room["name"]
    return None


def _keyword_score(content: str, rooms: list[dict]) -> str | None:
    lowered = (content or "")[:2000].lower()
    best_name, best_score = None, 0
    for room in rooms:
        score = sum(lowered.count(kw.lower()) for kw in room.get("keywords", []))
        if score > best_score:
            best_name, best_score = room["name"], score
    return best_name


def detect_room_for_wing(
    filepath: Path,
    content: str,
    wing_root: Path,
    rooms: list[dict],
) -> str:
    """Return the room name for a file within a wing. Falls through to 'general'."""
    rel_path = str(Path(filepath).resolve().relative_to(Path(wing_root).resolve()))
    rooms_json = _load_rooms_json(Path(wing_root))

    explicit = _explicit_block(rel_path, rooms_json)
    if explicit:
        return explicit

    prefixed = _path_prefix_match(rel_path, rooms)
    if prefixed:
        return prefixed

    scored = _keyword_score(content, rooms)
    if scored:
        return scored

    return "general"
