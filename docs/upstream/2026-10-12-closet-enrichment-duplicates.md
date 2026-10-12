# Upstream draft: closet enrichment replaces drawer text

Draft issue and PR text for https://github.com/milla-jovovich/mempalace. Not posted. The owner decides whether to post it.

The fix is committed locally as `a938e3c` on branch `fix/closet-enrichment-keeps-drawer-text` in `~/Code/mempalace`, based on `origin/develop` at `643134b`. It is not pushed.

## Issue

### Title

Closet-boosted search hits return their file's best passage instead of their own drawer text

### Body

`search_memories` runs a closet enrichment step on every hit with `matched_via == "drawer+closet"`. It fetches all drawers of the hit's source file and picks the chunk with the most query terms. It then sets the hit's `text` to that chunk joined with its two neighbours. This is `_enrich_closet_hits` in `mempalace/searcher/candidates.py` on develop, and the "Drawer-grep enrichment" block in `searcher.py` in 3.6.0.

That text depends only on the source file and the query. So when several drawers of one file are closet-boosted, they all come back with the same `text`. Each hit's `drawer_id` then points at a drawer whose content is not the `text` returned with it.

3.9.0 added `_dedupe_rendered_hits` and a 4x candidate pool to hide the repeats. That removes the duplicates, but it also collapses a file to one hit. A file with six relevant drawers now returns one, and the text of that one hit is still not its own drawer.

Expected: every hit returns its own drawer's text. Closets change ranking only.

### Minimal repro

Against develop, with a real Chroma palace:

```python
from mempalace.palace import get_closets_collection, get_collection
from mempalace.searcher import search_memories

palace = "/tmp/repro-palace"
query = "quasar authentication token rotation"
source = "/project/auth-notes.md"
docs = [f"SECTION_{i:02d} {query} variant {i:02d}." for i in range(6)]
get_collection(palace).upsert(
    ids=[f"d{i}" for i in range(6)],
    documents=docs,
    metadatas=[{"wing": "code", "room": "docs", "source_file": source, "chunk_index": i} for i in range(6)],
)
get_closets_collection(palace).upsert(
    ids=["c0"],
    documents=[f"{query}|;|→d0"],
    metadatas=[{"wing": "code", "room": "docs", "source_file": source}],
)
hits = search_memories(query, palace, wing="code", n_results=5)["results"]
print(len(hits), [h["text"][:30] for h in hits])
```

On develop this prints one hit, whose text is three chunks stitched together. On 3.6.0 it prints five hits with identical text.

## Pull request

### Title

fix(search): keep each closet-boosted hit on its own drawer text

### Description

Closet enrichment no longer rewrites `text`. Each hit keeps its own drawer's text, and the closet boost to ranking is unchanged.

`_enrich_closet_hits` still annotates closet hits, so the hit fields stay the same:

- `drawer_index` is now the hit's own `chunk_index`. Before, it was the index of the keyword-best chunk.
- `total_drawers` is the drawer count of the hit's source, or of its parent group when `parent_drawer_id` is set.

The source fetch now asks for metadatas only and still runs once per source group. The keyword scoring, neighbour stitching and `_MAX_HYDRATION_CHARS` are removed because nothing uses them. The function no longer takes `query` or `stop_words`.

`_dedupe_rendered_hits` and the widened candidate pool are left in place. With this change they only drop exact repeated chunk text, so they could be removed in a follow-up. I kept this PR to the one behaviour change.

### Tests

- New: `test_closet_enrichment_keeps_each_hit_on_its_own_drawer_text` (unit, mocked collection).
- New: `test_real_chromadb_closet_boosted_hits_return_their_own_drawer_text` (real Chroma; six drawers in one file, one closet). It asserts five hits, five distinct texts, and each hit's text equals the document stored under its `drawer_id`. It fails on develop with one hit.
- Changed: `test_closet_enrichment_memoises_by_source_and_parent_group` asserted that two drawers share one rendered text. It now asserts each keeps its own text.
- Changed: `test_search_promotes_distinct_results_from_wider_pool_and_fetches_source_once` became `test_search_keeps_each_closet_boosted_drawer_and_fetches_source_once`. It asserted one hit per file. It now asserts the five closet-boosted drawers come back in rank order with their own texts.
- Changed: `test_closet_boosted_hits_deduped_by_source_before_hydration` in `tests/test_searcher.py` became `test_closet_boosted_hits_keep_drawer_text_and_fetch_source_once`, for the same reason.

The full suite gives 6722 passed, 62 skipped and 6 failed. The 6 failures are in `tests/test_embeddinggemma2.py` (image and audio embedding). They fail the same way on develop without this change.
