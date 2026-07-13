"""Bounded-state tests for Codex standalone-search references."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from codex_rosetta.gateway.codex_search_references import (
    CodexSearchReferenceScope,
    CodexSearchReferenceStore,
    SearchQueryDraft,
    SearchResultDraft,
)


def _query(url: str = "https://docs.python.org/3/") -> tuple[SearchQueryDraft, ...]:
    return (
        SearchQueryDraft(
            "python",
            "Python docs",
            (SearchResultDraft("Python", url, "Official docs", 0.99),),
            1,
        ),
    )


def test_reference_session_expires_as_one_unit() -> None:
    current = 10.0
    store = CodexSearchReferenceStore(ttl_seconds=5, clock=lambda: current)
    scope = CodexSearchReferenceScope("client-a", "session-a")
    store.remember_search(scope, "request-a", _query())

    assert store.resolve(scope, "turn0search0") == "https://docs.python.org/3/"
    current = 16.0
    assert store.resolve(scope, "turn0search0") is None
    assert len(store) == 0


def test_session_capacity_evicts_the_oldest_owner_without_cross_lookup() -> None:
    store = CodexSearchReferenceStore(max_sessions=1)
    first = CodexSearchReferenceScope("client-a", "session-a")
    second = CodexSearchReferenceScope("client-b", "session-b")
    store.remember_search(first, "request-a", _query())
    store.remember_search(second, "request-b", _query("https://example.com"))

    assert store.resolve(first, "turn0search0") is None
    assert store.resolve(second, "turn0search0") == "https://example.com"


def test_concurrent_retry_assigns_one_reference_batch() -> None:
    store = CodexSearchReferenceStore()
    scope = CodexSearchReferenceScope("client-a", "session-a")
    barrier = threading.Barrier(2)

    def remember() -> tuple[str | None, bool]:
        barrier.wait()
        batch, cache_hit = store.remember_search(scope, "same-request", _query())
        return batch.queries[0].results[0].ref_id, cache_hit

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: remember(), range(2)))

    assert [ref_id for ref_id, _cache_hit in results] == [
        "turn0search0",
        "turn0search0",
    ]
    assert sorted(cache_hit for _ref_id, cache_hit in results) == [False, True]
    assert len(store) == 1
