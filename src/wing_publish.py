"""Publish .wingpack bundles into source repos."""

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


class PublishRefused(RuntimeError):
    """Raised when a compatibility gate blocks a publish."""


@dataclass
class PublishResult:
    path: Path
    mode: str
    dry_run: bool


PUBLISH_MODES = {"default", "force", "keep"}
BLOCKED_WING_NAMES = {"wing_user"}  # never re-publish user-private data


def _read_manifest(bundle: Path) -> dict:
    with zipfile.ZipFile(bundle) as zf:
        return json.loads(zf.read("manifest.json"))


def _existing_manifest(dest_dir: Path) -> dict | None:
    if not dest_dir.exists():
        return None
    candidates = sorted(dest_dir.glob("*.wingpack"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return _read_manifest(candidates[0])


def _check_compat(new_m: dict, old_m: dict | None) -> None:
    if new_m["wing"] in BLOCKED_WING_NAMES:
        raise PublishRefused(f"wing {new_m['wing']!r} is blocked from publish")
    if old_m is None:
        return
    if new_m["embedding_dim"] != old_m["embedding_dim"]:
        raise PublishRefused(
            f"embedding dim mismatch: new={new_m['embedding_dim']} "
            f"vs existing={old_m['embedding_dim']}"
        )
    if new_m["embedding_model"] != old_m["embedding_model"]:
        raise PublishRefused(
            f"embedding model mismatch: new={new_m['embedding_model']!r} "
            f"vs {old_m['embedding_model']!r}"
        )


def publish_to_repo(
    bundle: Path,
    repo_root: Path,
    mode: str = "default",
    dry_run: bool = False,
) -> PublishResult:
    """Stage a .wingpack at <repo>/.mempalace/wings/<bundle>.

    Raises PublishRefused on compatibility gate failure.
    """
    if mode not in PUBLISH_MODES:
        raise ValueError(f"mode must be one of {PUBLISH_MODES}, got {mode!r}")

    bundle = Path(bundle)
    repo_root = Path(repo_root)
    dest_dir = repo_root / ".mempalace" / "wings"

    new_m = _read_manifest(bundle)
    old_m = _existing_manifest(dest_dir)
    _check_compat(new_m, old_m)

    if mode == "keep" and old_m is not None:
        return PublishResult(path=dest_dir / bundle.name, mode=mode, dry_run=False)

    dest = dest_dir / bundle.name
    if dry_run:
        return PublishResult(path=dest, mode=mode, dry_run=True)

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, dest)
    return PublishResult(path=dest, mode=mode, dry_run=False)
