"""Search results must not repeat a chunk when closets rewrite several hits to the same text."""

from mempalace.palace import get_closets_collection, get_collection

from src.tools import handle_search, handle_search_all

PRUNE_FILE = "/repos/demo/src/sync_engine.py"


def _seed(palace: str) -> None:
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


def _keys(result: dict) -> list:
    return [(h.get("source_path") or h["source_file"], h["text"]) for h in result["results"]]


def test_handle_search_returns_distinct_chunks(tmp_palace):
    _seed(str(tmp_palace))
    result = handle_search(str(tmp_palace), "prune_wing", wing="demo", n=4)
    keys = _keys(result)
    assert len(keys) == 4
    assert len(set(keys)) == len(keys)


def test_handle_search_all_returns_distinct_chunks(tmp_palace):
    _seed(str(tmp_palace))
    result = handle_search_all(str(tmp_palace), "prune_wing", n=4)
    keys = _keys(result)
    assert len(keys) == 4
    assert len(set(keys)) == len(keys)


def test_handle_search_keeps_best_copy_first(tmp_palace):
    _seed(str(tmp_palace))
    result = handle_search(str(tmp_palace), "prune_wing", wing="demo", n=4)
    assert result["results"][0]["source_file"] == "sync_engine.py"
    assert result["results"][0]["matched_via"] == "drawer+closet"


def test_search_distinct_stops_at_overfetch_cap():
    from src import tools

    calls = []

    def run(k):
        calls.append(k)
        return {"results": [{"source_path": "a.py", "text": "same"}] * k}

    result = tools._search_distinct(2, run)
    assert result["results"] == [{"source_path": "a.py", "text": "same"}]
    assert calls == [2, 6, 18]


def test_search_distinct_passes_errors_through():
    from src import tools

    assert tools._search_distinct(3, lambda k: {"error": "boom"}) == {"error": "boom"}


def test_search_distinct_keeps_first_call_order():
    from src import tools

    a = {"source_path": "a.py", "text": "a"}
    b = {"source_path": "b.py", "text": "b"}
    c = {"source_path": "c.py", "text": "c"}
    pools = {3: [a, a, b], 9: [c, b, a, c, c, c, c, c, c]}

    result = tools._search_distinct(3, lambda k: {"results": pools[k]})
    assert result["results"] == [a, b, c]
