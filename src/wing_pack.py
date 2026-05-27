"""Wingpack bundle author — produces portable .wingpack zips."""

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

WINGPACK_SCHEMA_VERSION = "1.0"


class WingpackBuilder:
    """Builds a .wingpack zip in memory then writes to disk."""

    def __init__(self, wing_meta: dict[str, Any]):
        self.meta = wing_meta
        self._members: dict[str, bytes] = {}

    def add_manifest(self) -> None:
        manifest = {
            "schema_version": WINGPACK_SCHEMA_VERSION,
            "wing": self.meta["name"],
            "drawer_count": self.meta.get("drawer_count", 0),
            "embedding_model": self.meta["embedding_model"],
            "embedding_dim": self.meta["embedding_dim"],
            "source_digest": self._digest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._members["manifest.json"] = json.dumps(manifest, indent=2).encode()

    def add_wingpack_yaml(self) -> None:
        body = {
            "wing": self.meta["name"],
            "rooms": self.meta.get("rooms", []),
        }
        self._members["wingpack.yaml"] = yaml.safe_dump(body).encode()

    def add_keywords(self) -> None:
        kw = {r["name"]: r.get("keywords", []) for r in self.meta.get("rooms", [])}
        self._members["keywords.json"] = json.dumps(kw, indent=2).encode()

    def add_rooms(self) -> None:
        body = [
            {"name": r["name"], "tags": r.get("tags", []), "keywords": r.get("keywords", [])}
            for r in self.meta.get("rooms", [])
        ]
        self._members["rooms.json"] = json.dumps(body, indent=2).encode()

    def add_sync_manifest(self, sync_manifest: dict) -> None:
        self._members["sync_manifest.json"] = json.dumps(sync_manifest, indent=2).encode()

    def write(self, output_path: Path) -> Path:
        self.add_manifest()
        self.add_wingpack_yaml()
        self.add_keywords()
        self.add_rooms()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in self._members.items():
                zf.writestr(name, data)
        return output_path

    def _digest(self) -> str:
        blob = json.dumps(self.meta.get("rooms", []), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def write_wingpack(wing_meta: dict[str, Any], output_dir: Path) -> Path:
    """Convenience: timestamped filename, default location."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = Path(output_dir) / f"{ts}.wingpack"
    return WingpackBuilder(wing_meta).write(output_path)
