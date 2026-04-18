"""Post-sync hook: re-export wings as .wingpack and publish back into source repos."""

import json
from pathlib import Path

from src.wing_pack import write_wingpack
from src.wing_publish import PublishRefused, publish_to_repo


def publish_all_wings(
    repos_json_path: Path,
    exports_dir: Path,
    wing_metas: dict[str, dict],
    mode: str = "default",
) -> list[dict]:
    """For each registered repo, author a fresh wingpack and publish into its repo root."""
    repos = json.loads(Path(repos_json_path).read_text())
    results = []
    for slug, entry in repos.items():
        wing_name = entry.get("wing", slug)
        meta = wing_metas.get(wing_name)
        if meta is None:
            results.append({"slug": slug, "status": "skipped", "reason": "no wing meta"})
            continue
        bundle = write_wingpack(meta, exports_dir)
        try:
            pr = publish_to_repo(bundle, repo_root=Path(entry["path"]), mode=mode)
            results.append({"slug": slug, "status": "published", "path": str(pr.path)})
        except PublishRefused as exc:
            results.append({"slug": slug, "status": "refused", "reason": str(exc)})
    return results
