"""User Wing — persistent user context organized by thought type."""

import uuid
from datetime import datetime, timezone, timedelta

from mempalace.palace import get_collection


VALID_HALLS = frozenset({
    "questions",
    "discoveries",
    "frustrations",
    "goals",
    "decisions",
    "observations",
})

DEDUP_THRESHOLD = 0.15


class UserWing:
    """Manages the User Wing — thoughts organized by hall, not by code area."""

    def __init__(self, palace_path: str):
        self.palace_path = palace_path
        self.collection = get_collection(palace_path, collection_name="mempalace_drawers", create=True)

    def write(
        self,
        hall: str,
        content: str,
        topic: str,
        source_wing: str | None = None,
        session_id: str | None = None,
        confidence: float = 0.9,
    ) -> dict:
        """File a thought into a hall. Deduplicates against recent entries."""
        if hall not in VALID_HALLS:
            return {
                "status": "error",
                "message": f"Invalid hall: {hall}. Must be one of: {', '.join(sorted(VALID_HALLS))}",
            }

        # Check for near-duplicate in same hall
        existing = self._find_duplicate(hall, content)
        if existing:
            self.collection.upsert(
                ids=[existing["id"]],
                documents=[content],
                metadatas=[{
                    **existing["metadata"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }],
            )
            return {"status": "updated", "id": existing["id"], "hall": hall}

        drawer_id = f"user-{uuid.uuid4().hex[:24]}"
        metadata = {
            "wing": "user",
            "hall": hall,
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
            "added_by": "user-wing",
        }
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

    def search(
        self,
        query: str,
        hall: str | None = None,
        topic: str | None = None,
        n_results: int = 10,
    ) -> dict:
        """Semantic search across user wing."""
        where_conditions = [{"wing": "user"}]
        if hall:
            where_conditions.append({"hall": hall})
        if topic:
            where_conditions.append({"topic": topic})

        if len(where_conditions) > 1:
            where = {"$and": where_conditions}
        else:
            where = where_conditions[0]

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception:
            return {"query": query, "results": []}

        if not results or not results.get("ids") or not results["ids"][0]:
            return {"query": query, "results": []}

        formatted = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            dist = results["distances"][0][i] if results.get("distances") else None
            formatted.append({
                "id": doc_id,
                "content": results["documents"][0][i],
                "hall": meta.get("hall", ""),
                "topic": meta.get("topic", ""),
                "source_wing": meta.get("source_wing"),
                "timestamp": meta.get("timestamp", ""),
                "distance": dist,
            })

        return {"query": query, "results": formatted}

    def summary(self) -> dict:
        """Synthesize a compact user context summary (~300-500 tokens)."""
        sections = {}
        hall_labels = {
            "goals": "Goals",
            "decisions": "Recent decisions",
            "frustrations": "Active frustrations",
            "discoveries": "Recent discoveries",
            "questions": "Open questions",
            "observations": "Observations",
        }

        has_content = False
        for hall, label in hall_labels.items():
            try:
                results = self.collection.get(
                    where={"$and": [{"wing": "user"}, {"hall": hall}]},
                    limit=5,
                )
            except Exception:
                continue

            if results and results.get("documents"):
                items = results["documents"][:3]
                sections[label] = "; ".join(items)
                has_content = True

        if not has_content:
            return {"text": "", "token_estimate": 0}

        lines = ["## User Context"]
        for label, content in sections.items():
            lines.append(f"**{label}:** {content}")

        text = "\n".join(lines)
        token_estimate = len(text) // 4
        return {"text": text, "token_estimate": token_estimate}

    def status(self) -> dict:
        """Hall counts, recent topics, protocol guidance."""
        halls = {}
        topics = set()
        total = 0

        for hall in VALID_HALLS:
            try:
                results = self.collection.get(
                    where={"$and": [{"wing": "user"}, {"hall": hall}]},
                )
            except Exception:
                continue

            count = len(results["ids"]) if results and results.get("ids") else 0
            if count > 0:
                halls[hall] = count
                total += count
                if results.get("metadatas"):
                    for meta in results["metadatas"][:10]:
                        if meta.get("topic"):
                            topics.add(meta["topic"])

        return {
            "total_thoughts": total,
            "halls": halls,
            "recent_topics": sorted(topics),
            "guidance": (
                "Capture user context at session end via mempalace_user_write. "
                "Call mempalace_user_summary at session start for context."
            ),
        }

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

            dup = self._find_duplicate_in_topic(target_topic, content, meta.get("hall"))
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

        remaining = merged
        return {"merged": merged, "deduped": deduped, "remaining": remaining}

    def prune(
        self,
        hall: str | None = None,
        topic: str | None = None,
        older_than_days: int = 90,
        dry_run: bool = True,
    ) -> dict:
        """Remove stale/low-value thoughts by age, similarity, or cluster."""
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

    def _find_duplicate_in_topic(self, topic: str, content: str, hall: str | None = None) -> dict | None:
        """Check if near-duplicate exists in the target topic."""
        where_conditions = [{"wing": "user"}, {"topic": topic}]
        if hall:
            where_conditions.append({"hall": hall})

        try:
            results = self.collection.query(
                query_texts=[content],
                n_results=1,
                where={"$and": where_conditions},
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

        if results["distances"][0][0] < DEDUP_THRESHOLD:
            return {"id": results["ids"][0][0]}
        return None

    def _find_duplicate(self, hall: str, content: str) -> dict | None:
        """Find a near-duplicate in the same hall. Returns {id, metadata} or None."""
        try:
            results = self.collection.query(
                query_texts=[content],
                n_results=1,
                where={"$and": [{"wing": "user"}, {"hall": hall}]},
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
            }
        return None
