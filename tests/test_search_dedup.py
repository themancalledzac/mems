"""Closet-boosted search hits must each carry their own drawer's text.

These fail on an unpatched mempalace 3.6.0. Run scripts/apply_mempalace_patch.sh after `uv sync`.
"""

from mempalace.palace import get_closets_collection, get_collection
from mempalace.searcher import search_memories

from src.tools import handle_search, handle_search_all

PRUNE_FILE = "/repos/demo/src/sync_engine.py"


def _seed(palace: str) -> dict:
    drawers = get_collection(palace, collection_name="mempalace_drawers", create=True)
    prune_chunks = [
        "def prune_wing(wing): delete stale drawers for prune_wing",
        "prune_wing is called after sync to prune_wing old chunks",
        "prune_wing keeps the ledger in step when it prunes a wing",
        "prune_wing logs how many drawers it pruned from the wing",
    ]
    other_files = {
        "/repos/demo/src/ledger.py": "the ledger records when a wing was last pruned",
        "/repos/demo/src/tools.py": "handle_sync calls the sync engine which may prune a wing",
        "/repos/demo/docs/sync.md": "pruning removes drawers whose files were deleted",
        "/repos/demo/src/cli.py": "mems sync prints how many drawers were pruned",
    }
    ids, docs, metas = [], [], []
    for i, text in enumerate(prune_chunks):
        ids.append(f"drawer_prune_{i}")
        docs.append(text)
        metas.append({"wing": "demo", "room": "sync", "source_file": PRUNE_FILE, "chunk_index": i})
    for j, (path, text) in enumerate(other_files.items()):
        ids.append(f"drawer_other_{j}")
        docs.append(text)
        metas.append({"wing": "demo", "room": "sync", "source_file": path, "chunk_index": 0})
    drawers.add(ids=ids, documents=docs, metadatas=metas)

    closets = get_closets_collection(palace, create=True)
    closets.add(
        ids=["closet_prune"],
        documents=["prune_wing -> prunes stale drawers|→drawer_prune_0,drawer_prune_1"],
        metadatas=[{"wing": "demo", "room": "sync", "source_file": PRUNE_FILE}],
    )
    drawer_texts: dict = {}
    for text, meta in zip(docs, metas):
        drawer_texts.setdefault(meta["source_file"], set()).add(text)
    return drawer_texts


def _assert_own_drawer_texts(result: dict, drawer_texts: dict, n: int) -> None:
    hits = result["results"]
    texts = [h["text"] for h in hits]
    assert len(hits) == n
    assert len(set(texts)) == n, f"repeated hit text, is the mempalace patch applied? {texts}"
    for h in hits:
        assert h["text"] in drawer_texts[h["source_path"]], h


def test_installed_mempalace_keeps_drawer_text_on_closet_hits(tmp_palace):
    drawer_texts = _seed(str(tmp_palace))
    result = search_memories("prune_wing", palace_path=str(tmp_palace), wing="demo", n_results=4)
    closet_hits = [h for h in result["results"] if h["matched_via"] == "drawer+closet"]
    assert len(closet_hits) >= 2
    assert len({h["text"] for h in closet_hits}) == len(closet_hits), (
        "mempalace rewrites closet hits to one passage; run scripts/apply_mempalace_patch.sh"
    )
    assert all(h["text"] in drawer_texts[PRUNE_FILE] for h in closet_hits)
    assert all(h["total_drawers"] == 4 for h in closet_hits)


def test_handle_search_hits_carry_their_own_drawer_text(tmp_palace):
    drawer_texts = _seed(str(tmp_palace))
    result = handle_search(str(tmp_palace), "prune_wing", wing="demo", n=4)
    _assert_own_drawer_texts(result, drawer_texts, 4)


def test_handle_search_all_hits_carry_their_own_drawer_text(tmp_palace):
    drawer_texts = _seed(str(tmp_palace))
    result = handle_search_all(str(tmp_palace), "prune_wing", n=4)
    _assert_own_drawer_texts(result, drawer_texts, 4)


def test_handle_search_keeps_best_copy_first(tmp_palace):
    _seed(str(tmp_palace))
    result = handle_search(str(tmp_palace), "prune_wing", wing="demo", n=4)
    assert result["results"][0]["source_file"] == "sync_engine.py"
    assert result["results"][0]["matched_via"] == "drawer+closet"
