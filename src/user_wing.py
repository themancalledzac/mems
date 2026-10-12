"""User Wing — persistent user context organized by thought type."""

import re
import uuid
from datetime import datetime, timedelta, timezone

from mempalace.palace import get_collection

VALID_HALLS = frozenset(
    {
        "questions",
        "discoveries",
        "frustrations",
        "goals",
        "decisions",
        "observations",
    }
)
VALID_ORIGINS = frozenset({"agent", "prompt", "orch"})
VALID_STATUSES = frozenset({"open", "active", "parked", "done", "superseded"})
OPEN_BY_DEFAULT_HALLS = frozenset({"goals", "questions"})
MALFORMED_MARKERS = ("<parameter", "</parameter>", "</content>", "<invoke")
"""Substrings that mark leaked tool-call markup; write() rejects content holding any of them."""

DEDUP_THRESHOLD = 0.15
MAX_REVISIONS = 3
REVISION_MARKER = re.compile(r"\n\n\[revised \d{4}-\d{2}-\d{2}\] ")
SECONDS_PER_DAY = 86_400.0
RECENCY_HORIZON_DAYS = 30.0
SUMMARY_CHAR_BUDGET = 2400
SUMMARY_ITEM_CHARS = 220
SUMMARY_OPEN_IDEAS = 4
SUMMARY_HALL_ITEMS = {
    "goals": 2,
    "decisions": 2,
    "frustrations": 2,
    "discoveries": 2,
    "questions": 1,
    "observations": 1,
}
STATUS_TOPIC_WINDOW = 30
HALL_LABELS = {
    "goals": "Goals",
    "decisions": "Recent decisions",
    "frustrations": "Active frustrations",
    "discoveries": "Recent discoveries",
    "questions": "Recent questions",
    "observations": "Observations",
}


def _error(code: str, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}


def _invalid(kind: str, value, allowed: frozenset) -> dict:
    return _error(
        f"invalid_{kind}",
        f"Invalid {kind}: {value}. Must be one of: {', '.join(sorted(allowed))}",
    )


def _parse_iso_epoch(value) -> float | None:
    """Parse an ISO timestamp to epoch seconds, treating naive values as UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _last_seen_epoch(meta: dict) -> float:
    """Epoch of the last touch, falling back to `timestamp` for pre-recency entries."""
    epoch = meta.get("last_seen_epoch")
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
        return float(epoch)
    for key in ("last_seen", "timestamp"):
        parsed = _parse_iso_epoch(meta.get(key))
        if parsed is not None:
            return parsed
    return 0.0


def _effective_status(meta: dict) -> str | None:
    """Stored status, or `open` for a goals/questions entry that has none."""
    status = meta.get("status")
    if status:
        return status
    return "open" if meta.get("hall") in OPEN_BY_DEFAULT_HALLS else None


def _merge_revision(document: str, new_content: str, day: str) -> str:
    """Append `[revised <day>] <new_content>` unless it repeats the original or a revision.

    Only the newest MAX_REVISIONS revision lines are kept.
    """
    markers = list(REVISION_MARKER.finditer(document))
    base = document[: markers[0].start()] if markers else document
    bounds = [m.start() for m in markers[1:]] + [len(document)]
    revisions = [document[m.start() : end] for m, end in zip(markers, bounds)]
    seen = {base} | {document[m.end() : end] for m, end in zip(markers, bounds)}
    if new_content in seen:
        return document
    revisions.append(f"\n\n[revised {day}] {new_content}")
    return base + "".join(revisions[-MAX_REVISIONS:])


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _render_summary(items: list[tuple[str, list[str]]]) -> str:
    lines = ["## User Context"]
    lines.extend(f"**{label}:** " + "; ".join(texts) for label, texts in items)
    return "\n".join(lines)


def _format_entry(drawer_id: str, document: str, meta: dict) -> dict:
    """Shared result shape for search and recent; absent recency keys get their defaults."""
    return {
        "id": drawer_id,
        "content": document,
        "hall": meta.get("hall", ""),
        "topic": meta.get("topic", ""),
        "source_wing": meta.get("source_wing"),
        "timestamp": meta.get("timestamp", ""),
        "last_seen": meta.get("last_seen") or meta.get("timestamp", ""),
        "seen_count": int(meta.get("seen_count", 1)),
        "status": meta.get("status"),
        "origin": meta.get("origin", "agent"),
        "personal": bool(meta.get("personal", False)),
    }


def _keep(
    meta: dict,
    *,
    since_epoch: float | None = None,
    source_wing: str | None = None,
    include_unscoped: bool = True,
    status: str | None = None,
    include_personal: bool = True,
) -> bool:
    """Apply the recency, wing-scope, status and personal filters to one entry."""
    if since_epoch is not None and _last_seen_epoch(meta) < since_epoch:
        return False
    if source_wing is not None:
        entry_wing = meta.get("source_wing")
        if entry_wing != source_wing and not (include_unscoped and not entry_wing):
            return False
    if status is not None and _effective_status(meta) != status:
        return False
    if not include_personal and meta.get("personal", False):
        return False
    return True


def _since_epoch(days: float | None) -> float | None:
    if days is None:
        return None
    return datetime.now(timezone.utc).timestamp() - days * SECONDS_PER_DAY


class UserWing:
    """Manages the User Wing — thoughts organized by hall, not by code area."""

    def __init__(self, palace_path: str):
        self.palace_path = palace_path
        self.collection = get_collection(
            palace_path, collection_name="mempalace_drawers", create=True
        )

    def write(
        self,
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
        session_id: str | None = None,
        confidence: float = 0.9,
        origin: str = "agent",
        status: str | None = None,
        personal: bool = False,
    ) -> dict:
        """File a thought into a hall, or record a repeat of a near-duplicate in the same hall.

        A repeat keeps the original text and metadata, bumps `seen_count` and `last_seen`,
        and appends the new phrasing as a revision line.
        """
        if hall not in VALID_HALLS:
            return _invalid("hall", hall, VALID_HALLS)
        if any(marker in content for marker in MALFORMED_MARKERS):
            return _error("malformed", "malformed: content contains tool-call markup")
        if origin not in VALID_ORIGINS:
            return _invalid("origin", origin, VALID_ORIGINS)
        if status is not None and status not in VALID_STATUSES:
            return _invalid("status", status, VALID_STATUSES)

        now = datetime.now(timezone.utc)
        existing = self._find_duplicate(hall, content)
        if existing:
            return self._record_repeat(existing, hall, content, source_wing, now)

        drawer_id = f"user-{uuid.uuid4().hex[:24]}"
        stamp = now.isoformat()
        metadata = {
            "wing": "user",
            "hall": hall,
            "topic": topic,
            "timestamp": stamp,
            "last_seen": stamp,
            "last_seen_epoch": now.timestamp(),
            "seen_count": 1,
            "origin": origin,
            "personal": personal,
            "confidence": confidence,
            "added_by": "user-wing",
        }
        if status is None and hall in OPEN_BY_DEFAULT_HALLS:
            status = "open"
        if status:
            metadata["status"] = status
        if source_wing:
            metadata["source_wing"] = source_wing
        if session_id:
            metadata["session_id"] = session_id

        self.collection.upsert(
            ids=[drawer_id],
            documents=[content],
            metadatas=[metadata],
        )
        return {"status": "created", "id": drawer_id, "hall": hall}

    def _record_repeat(
        self,
        existing: dict,
        hall: str,
        content: str,
        source_wing: str | None,
        now: datetime,
    ) -> dict:
        drawer_id = existing["id"]
        meta = existing["metadata"]
        seen_count = int(meta.get("seen_count", 1)) + 1
        updates = {
            "last_seen": now.isoformat(),
            "last_seen_epoch": now.timestamp(),
            "seen_count": seen_count,
        }
        if source_wing and not meta.get("source_wing"):
            updates["source_wing"] = source_wing

        document = existing["document"]
        merged = _merge_revision(document, content, now.date().isoformat())
        if merged != document:
            self.collection.update(ids=[drawer_id], documents=[merged], metadatas=[updates])
        else:
            self.collection.update(ids=[drawer_id], metadatas=[updates])
        return {"status": "updated", "id": drawer_id, "hall": hall, "seen_count": seen_count}

    def search(
        self,
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
        since_days: float | None = None,
        source_wing: str | None = None,
        include_unscoped: bool = True,
        status: str | None = None,
        include_personal: bool = True,
        recency_weight: float = 0.1,
    ) -> dict:
        """Semantic search across the user wing, re-ranked by recency.

        `effective_distance = distance + recency_weight * min(age_days / 30, 1)`, with age
        measured from `last_seen`. The `source_wing` scope is applied inside Chroma, so small
        wings are found; the other filters run in Python over an over-fetched candidate set.
        """
        base = [{"wing": "user"}]
        if hall:
            base.append({"hall": hall})
        if topic:
            base.append({"topic": topic})

        scopes: list[dict] = []
        if source_wing is None:
            scopes.append({})
        else:
            scopes.append({"source_wing": source_wing})
            if include_unscoped:
                scopes.append(self._unscoped_clause())

        limit = min(max(n_results * 3, 30), 100)
        now_epoch = datetime.now(timezone.utc).timestamp()
        since = _since_epoch(since_days)
        found: dict[str, dict] = {}
        for scope in scopes:
            conditions = base + ([scope] if scope else [])
            where = {"$and": conditions} if len(conditions) > 1 else conditions[0]
            try:
                results = self.collection.query(query_texts=[query], n_results=limit, where=where)
            except Exception:
                continue
            if not results or not results.get("ids") or not results["ids"][0]:
                continue
            metadatas = results.get("metadatas") or [[]]
            distances = results.get("distances") or [[]]
            for i, doc_id in enumerate(results["ids"][0]):
                meta = (metadatas[0][i] if i < len(metadatas[0]) else {}) or {}
                if not _keep(
                    meta,
                    since_epoch=since,
                    source_wing=source_wing,
                    include_unscoped=include_unscoped,
                    status=status,
                    include_personal=include_personal,
                ):
                    continue
                dist = distances[0][i] if i < len(distances[0]) else None
                age_days = max(now_epoch - _last_seen_epoch(meta), 0.0) / SECONDS_PER_DAY
                effective = (dist or 0.0) + recency_weight * min(
                    age_days / RECENCY_HORIZON_DAYS, 1.0
                )
                entry = _format_entry(doc_id, results["documents"][0][i], meta)
                entry["distance"] = dist
                entry["effective_distance"] = effective
                found[doc_id] = entry

        formatted = sorted(found.values(), key=lambda e: (e["effective_distance"], e["id"]))
        return {"query": query, "results": formatted[:n_results]}

    def _unscoped_clause(self) -> dict:
        """Chroma filter for user entries with no `source_wing` (key missing or empty)."""
        named = sorted(
            {meta["source_wing"] for _, meta in self._user_metadata() if meta.get("source_wing")}
        )
        return {"source_wing": {"$nin": named}} if named else {}

    def recent(
        self,
        days: float = 7,
        source_wing: str | None = None,
        include_unscoped: bool = True,
        hall: str | None = None,
        status: str | None = None,
        include_personal: bool = True,
        n: int = 20,
    ) -> dict:
        """Entries touched within `days`, newest `last_seen` first, in the search result shape.

        Filters and sorts on metadata alone, then reads documents only for the chosen ids.
        """
        since = _since_epoch(days)
        chosen = [
            (drawer_id, meta)
            for drawer_id, meta in self._user_metadata(hall)
            if _keep(
                meta,
                since_epoch=since,
                source_wing=source_wing,
                include_unscoped=include_unscoped,
                status=status,
                include_personal=include_personal,
            )
        ]
        chosen.sort(key=lambda pair: (-_last_seen_epoch(pair[1]), pair[0]))
        chosen = chosen[:n]
        documents = self._documents([drawer_id for drawer_id, _ in chosen])
        return {
            "days": days,
            "results": [
                _format_entry(drawer_id, documents.get(drawer_id, ""), meta)
                for drawer_id, meta in chosen
            ],
        }

    def set_status(self, drawer_id: str, status: str) -> dict:
        """Set the status of one user entry without touching its text or other metadata."""
        if status not in VALID_STATUSES:
            return _invalid("status", status, VALID_STATUSES)
        try:
            found = self.collection.get(ids=[drawer_id], include=["metadatas"])
        except Exception:
            found = None
        if not found or not found.get("ids"):
            return _error("not_found", f"Unknown drawer id: {drawer_id}")
        if (found.get("metadatas") or [{}])[0].get("wing") != "user":
            return _error("not_found", f"Not a user wing entry: {drawer_id}")
        self.collection.update(ids=[drawer_id], metadatas=[{"status": status}])
        return {"status": "updated", "id": drawer_id, "entry_status": status}

    def summary(
        self, source_wing: str | None = None, max_item_chars: int = SUMMARY_ITEM_CHARS
    ) -> dict:
        """Compact user context: open goals and questions first, then the newest entries per hall.

        Personal entries are always excluded, and hall sections skip entries already listed
        under open ideas. Each item is cut to `max_item_chars`, and whole items are dropped
        from the end, observations first, until the text fits SUMMARY_CHAR_BUDGET.
        """
        entries = [
            (drawer_id, meta)
            for drawer_id, meta in self._user_metadata()
            if _keep(meta, source_wing=source_wing, include_personal=False)
        ]
        if not entries:
            return {"text": "", "token_estimate": 0}
        entries.sort(key=lambda pair: (-_last_seen_epoch(pair[1]), pair[0]))

        open_ideas = [
            drawer_id
            for drawer_id, meta in entries
            if meta.get("hall") in OPEN_BY_DEFAULT_HALLS and _effective_status(meta) == "open"
        ][:SUMMARY_OPEN_IDEAS]
        sections = [("Open ideas", open_ideas)] if open_ideas else []
        for hall, label in HALL_LABELS.items():
            newest = [d for d, meta in entries if meta.get("hall") == hall and d not in open_ideas]
            if newest:
                sections.append((label, newest[: SUMMARY_HALL_ITEMS[hall]]))

        documents = self._documents(sorted({d for _, ids in sections for d in ids}))
        items = []
        for label, ids in sections:
            texts = [" ".join(documents.get(d, "").split()) for d in ids]
            items.append((label, [_truncate(t, max_item_chars) for t in texts]))
        text = _render_summary(items)
        while len(text) > SUMMARY_CHAR_BUDGET and items:
            items[-1][1].pop()
            if not items[-1][1]:
                items.pop()
            text = _render_summary(items)
        return {"text": text, "token_estimate": len(text) // 4}

    def status(self) -> dict:
        """Hall counts, the topics of the most recently touched entries, protocol guidance."""
        entries = self._user_metadata()
        halls: dict[str, int] = {}
        for _, meta in entries:
            hall = meta.get("hall")
            if hall in VALID_HALLS:
                halls[hall] = halls.get(hall, 0) + 1

        entries.sort(key=lambda pair: (-_last_seen_epoch(pair[1]), pair[0]))
        recent_topics: list[str] = []
        for _, meta in entries[:STATUS_TOPIC_WINDOW]:
            topic = meta.get("topic")
            if topic and topic not in recent_topics:
                recent_topics.append(topic)

        return {
            "total_thoughts": sum(halls.values()),
            "halls": halls,
            "recent_topics": recent_topics,
            "guidance": (
                "Capture user thoughts continuously via mempalace_user_write — "
                "every substantive response with a decision, discovery, goal, or "
                "observation triggers a write BEFORE the response is delivered. "
                "This is per-turn, not session-end. Announce writes inline "
                '("Capturing X to hall Y") so the user can see what is captured. '
                "Call mempalace_user_summary once per session, cite what is relevant, "
                'or state "no prior context relevant" before proceeding.'
            ),
        }

    def _user_metadata(self, hall: str | None = None) -> list[tuple[str, dict]]:
        """(id, metadata) for every user entry, optionally in one hall. Documents are not read."""
        where = {"$and": [{"wing": "user"}, {"hall": hall}]} if hall else {"wing": "user"}
        try:
            results = self.collection.get(where=where, include=["metadatas"])
        except Exception:
            return []
        if not results or not results.get("ids"):
            return []
        metadatas = results.get("metadatas") or []
        return [
            (drawer_id, (metadatas[i] if i < len(metadatas) else None) or {})
            for i, drawer_id in enumerate(results["ids"])
        ]

    def _documents(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        try:
            results = self.collection.get(ids=ids, include=["documents"])
        except Exception:
            return {}
        return dict(zip(results.get("ids") or [], results.get("documents") or []))

    def merge_topics(
        self,
        source_topic: str,
        target_topic: str,
        hall: str | None = None,
    ) -> dict:
        """Merge drifted topics — rewrite metadata, deduplicate."""
        where_conditions = [{"wing": "user"}, {"topic": source_topic}]
        if hall:
            where_conditions.append({"hall": hall})
        where = {"$and": where_conditions}

        try:
            results = self.collection.get(where=where)
        except Exception:
            return {"merged": 0, "deduped": 0, "remaining": 0}

        if not results or not results.get("ids"):
            return {"merged": 0, "deduped": 0, "remaining": 0}

        merged = 0
        deduped = 0
        for i, drawer_id in enumerate(results["ids"]):
            meta = results["metadatas"][i].copy()
            content = results["documents"][i]

            dup = self._find_duplicate(meta.get("hall"), content, topic=target_topic)
            if dup:
                self.collection.delete(ids=[drawer_id])
                deduped += 1
            else:
                meta["topic"] = target_topic
                self.collection.upsert(
                    ids=[drawer_id],
                    documents=[content],
                    metadatas=[meta],
                )
                merged += 1

        return {"merged": merged, "deduped": deduped, "remaining": merged}

    def prune(
        self,
        hall: str | None = None,
        topic: str | None = None,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> dict:
        """Remove thoughts whose `timestamp` is older than `older_than_days`. Dry run by default."""
        where_conditions = [{"wing": "user"}]
        if hall:
            where_conditions.append({"hall": hall})
        if topic:
            where_conditions.append({"topic": topic})
        where = {"$and": where_conditions} if len(where_conditions) > 1 else where_conditions[0]

        try:
            results = self.collection.get(where=where)
        except Exception:
            return {"candidates": 0, "pruned": 0}

        if not results or not results.get("ids"):
            return {"candidates": 0, "pruned": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        candidates = []
        for i, drawer_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            ts_str = meta.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                candidates.append(drawer_id)

        if dry_run:
            return {"candidates": len(candidates), "pruned": 0}

        if candidates:
            self.collection.delete(ids=candidates)

        return {"candidates": len(candidates), "pruned": len(candidates)}

    def _find_duplicate(
        self, hall: str | None, content: str, topic: str | None = None
    ) -> dict | None:
        """Find a near-duplicate, optionally limited to a hall and topic.

        Returns {id, metadata, document} or None.
        """
        conditions = [{"wing": "user"}]
        if hall:
            conditions.append({"hall": hall})
        if topic:
            conditions.append({"topic": topic})
        try:
            results = self.collection.query(
                query_texts=[content],
                n_results=1,
                where={"$and": conditions} if len(conditions) > 1 else conditions[0],
            )
        except Exception:
            return None

        if (
            not results
            or not results.get("ids")
            or not results["ids"][0]
            or not results.get("distances")
            or not results["distances"][0]
        ):
            return None

        distance = results["distances"][0][0]
        if distance < DEDUP_THRESHOLD:
            return {
                "id": results["ids"][0][0],
                "metadata": results["metadatas"][0][0] if results.get("metadatas") else {},
                "document": results["documents"][0][0] if results.get("documents") else "",
            }
        return None
