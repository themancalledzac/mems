"""User Wing — persistent user context organized by thought type."""

import uuid
from datetime import datetime, timezone

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
