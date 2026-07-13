"""Session-scoped references returned by the local Codex Search bridge."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

SEARCH_REFERENCE_RE = re.compile(r"turn[0-9]+search[0-9]+")


@dataclass(frozen=True)
class CodexSearchReferenceScope:
    """Authenticated owner of one Codex ``SearchRequest.id`` namespace."""

    principal_id: str
    session_id: str


@dataclass(frozen=True)
class SearchResultDraft:
    """Bounded Tavily result before a Codex reference ID is assigned."""

    title: str
    url: str
    content: str
    score: int | float | None = None


@dataclass(frozen=True)
class StoredSearchResult:
    """One result with its optional session-local Codex reference ID."""

    title: str
    url: str
    content: str
    score: int | float | None
    ref_id: str | None


@dataclass(frozen=True)
class SearchQueryDraft:
    """One search query and the bounded results returned for it."""

    query: str
    answer: str | None
    results: tuple[SearchResultDraft, ...]
    source_result_count: int


@dataclass(frozen=True)
class StoredSearchQuery:
    """One cached query whose URL results have stable reference IDs."""

    query: str
    answer: str | None
    results: tuple[StoredSearchResult, ...]
    source_result_count: int


@dataclass(frozen=True)
class StoredSearchBatch:
    """Retry-stable result of one Search API request containing queries."""

    turn_index: int
    queries: tuple[StoredSearchQuery, ...]


@dataclass
class _SearchSessionState:
    next_turn_index: int
    references: OrderedDict[str, str]
    batches: OrderedDict[str, StoredSearchBatch]
    last_access: float


class CodexSearchReferenceStore:
    """Bounded in-memory store keyed by principal and ``SearchRequest.id``.

    The store intentionally excludes model and Codex window IDs so references
    remain valid across model changes and context compaction. A synchronous lock
    protects allocation because the gateway may serve concurrent Search calls.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 24 * 60 * 60,
        max_sessions: int = 1_024,
        max_references_per_session: int = 1_024,
        max_batches_per_session: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if min(max_sessions, max_references_per_session, max_batches_per_session) <= 0:
            raise ValueError("search reference capacities must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._max_references_per_session = max_references_per_session
        self._max_batches_per_session = max_batches_per_session
        self._clock = clock
        self._sessions: OrderedDict[CodexSearchReferenceScope, _SearchSessionState] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def remember_search(
        self,
        scope: CodexSearchReferenceScope,
        fingerprint: str,
        queries: tuple[SearchQueryDraft, ...],
    ) -> tuple[StoredSearchBatch, bool]:
        """Return a cached batch or atomically assign one set of references."""

        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            state = self._session(scope, now)
            cached = state.batches.get(fingerprint)
            if cached is not None and self._batch_references_exist(state, cached):
                state.batches.move_to_end(fingerprint)
                return cached, True

            turn_index = state.next_turn_index
            state.next_turn_index += 1
            result_index = 0
            stored_queries: list[StoredSearchQuery] = []
            for query in queries:
                stored_results: list[StoredSearchResult] = []
                for result in query.results:
                    ref_id = None
                    if result.url.lower().startswith(("http://", "https://")):
                        ref_id = f"turn{turn_index}search{result_index}"
                        result_index += 1
                        state.references[ref_id] = result.url
                        state.references.move_to_end(ref_id)
                    stored_results.append(
                        StoredSearchResult(
                            title=result.title,
                            url=result.url,
                            content=result.content,
                            score=result.score,
                            ref_id=ref_id,
                        )
                    )
                stored_queries.append(
                    StoredSearchQuery(
                        query=query.query,
                        answer=query.answer,
                        results=tuple(stored_results),
                        source_result_count=query.source_result_count,
                    )
                )

            batch = StoredSearchBatch(turn_index, tuple(stored_queries))
            state.batches[fingerprint] = batch
            state.batches.move_to_end(fingerprint)
            self._enforce_session_limits(state)
            return batch, False

    def get_search(
        self,
        scope: CodexSearchReferenceScope,
        fingerprint: str,
    ) -> StoredSearchBatch | None:
        """Return a retry-stable search batch without invoking the executor."""

        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            state = self._sessions.get(scope)
            if state is None:
                return None
            self._touch(scope, state, now)
            batch = state.batches.get(fingerprint)
            if batch is None or not self._batch_references_exist(state, batch):
                if batch is not None:
                    del state.batches[fingerprint]
                return None
            state.batches.move_to_end(fingerprint)
            return batch

    def resolve(
        self,
        scope: CodexSearchReferenceScope,
        ref_id: str,
    ) -> str | None:
        """Resolve a reference only inside its authenticated Search session."""

        if SEARCH_REFERENCE_RE.fullmatch(ref_id) is None:
            return None
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            state = self._sessions.get(scope)
            if state is None:
                return None
            self._touch(scope, state, now)
            url = state.references.get(ref_id)
            if url is not None:
                state.references.move_to_end(ref_id)
            return url

    def clear_all(self) -> None:
        """Clear all app-owned Search references."""

        with self._lock:
            self._sessions.clear()

    def __len__(self) -> int:
        with self._lock:
            return sum(len(state.references) for state in self._sessions.values())

    def _session(
        self,
        scope: CodexSearchReferenceScope,
        now: float,
    ) -> _SearchSessionState:
        state = self._sessions.get(scope)
        if state is None:
            state = _SearchSessionState(0, OrderedDict(), OrderedDict(), now)
            self._sessions[scope] = state
        self._touch(scope, state, now)
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)
        return state

    def _touch(
        self,
        scope: CodexSearchReferenceScope,
        state: _SearchSessionState,
        now: float,
    ) -> None:
        state.last_access = now
        self._sessions.move_to_end(scope)

    def _remove_expired(self, now: float) -> None:
        expired = [
            scope
            for scope, state in self._sessions.items()
            if now - state.last_access >= self._ttl_seconds
        ]
        for scope in expired:
            del self._sessions[scope]

    def _enforce_session_limits(self, state: _SearchSessionState) -> None:
        while len(state.references) > self._max_references_per_session:
            state.references.popitem(last=False)
        while len(state.batches) > self._max_batches_per_session:
            state.batches.popitem(last=False)

    @staticmethod
    def _batch_references_exist(
        state: _SearchSessionState,
        batch: StoredSearchBatch,
    ) -> bool:
        return all(
            result.ref_id is None or result.ref_id in state.references
            for query in batch.queries
            for result in query.results
        )
