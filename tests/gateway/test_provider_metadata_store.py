"""Tests for ProviderMetadataStore."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from codex_rosetta.gateway.proxy import (
    ProviderMetadataCapacityError,
    ProviderMetadataStore,
)
from codex_rosetta.gateway.state_scope import GatewayStateScope


def _make_ir_response(tool_call_id: str, metadata: dict) -> dict:
    """Build a minimal IR response containing a tool call with provider_metadata."""
    return {
        "choices": [
            {
                "message": {
                    "content": [
                        {
                            "type": "tool_call",
                            "tool_call_id": tool_call_id,
                            "name": "test_fn",
                            "arguments": "{}",
                            "provider_metadata": metadata,
                        }
                    ]
                }
            }
        ]
    }


def _make_ir_request(tool_call_ids: list[str]) -> dict:
    """Build a minimal IR request with tool_call parts (no provider_metadata)."""
    return {
        "messages": [
            {
                "content": [
                    {
                        "type": "tool_call",
                        "tool_call_id": tc_id,
                        "name": "test_fn",
                        "arguments": "{}",
                    }
                    for tc_id in tool_call_ids
                ]
            }
        ]
    }


def _canonical_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _scope(principal: str, conversation: str) -> GatewayStateScope:
    return GatewayStateScope(
        principal,
        "provider",
        "model",
        conversation,
        True,
    )


class TestCacheAndInjectRoundtrip:
    def test_basic_roundtrip(self):
        store = ProviderMetadataStore()
        metadata = {"thought_signature": "abc123"}
        store.cache_from_response(_make_ir_response("call_001", metadata))

        ir_req = _make_ir_request(["call_001"])
        store.inject_into_request(ir_req)

        part = ir_req["messages"][0]["content"][0]
        assert part["provider_metadata"] == {"thought_signature": "abc123"}

    def test_multiple_tool_calls(self):
        store = ProviderMetadataStore()
        store.cache_from_response(_make_ir_response("call_a", {"sig": "A"}))
        store.cache_from_response(_make_ir_response("call_b", {"sig": "B"}))

        ir_req = _make_ir_request(["call_a", "call_b"])
        store.inject_into_request(ir_req)

        parts = ir_req["messages"][0]["content"]
        assert parts[0]["provider_metadata"] == {"sig": "A"}
        assert parts[1]["provider_metadata"] == {"sig": "B"}

    def test_same_call_id_is_isolated_between_principals(self):
        root = ProviderMetadataStore()
        scope_a = GatewayStateScope("client-a", "provider", "model", "window", True)
        scope_b = GatewayStateScope("client-b", "provider", "model", "window", True)
        store_a = root.scoped(scope_a)
        store_b = root.scoped(scope_b)
        store_a.cache_from_response(_make_ir_response("call_1", {"owner": "a"}))
        store_b.cache_from_response(_make_ir_response("call_1", {"owner": "b"}))

        request_a = _make_ir_request(["call_1"])
        request_b = _make_ir_request(["call_1"])
        store_a.inject_into_request(request_a)
        store_b.inject_into_request(request_b)

        assert request_a["messages"][0]["content"][0]["provider_metadata"] == {
            "owner": "a"
        }
        assert request_b["messages"][0]["content"][0]["provider_metadata"] == {
            "owner": "b"
        }


class TestTTLExpiration:
    def test_expired_entries_not_injected(self):
        store = ProviderMetadataStore(ttl=0.05)  # 50ms TTL
        store.cache_from_response(_make_ir_response("call_exp", {"sig": "old"}))
        assert len(store) == 1

        time.sleep(0.06)

        ir_req = _make_ir_request(["call_exp"])
        store.inject_into_request(ir_req)

        part = ir_req["messages"][0]["content"][0]
        assert "provider_metadata" not in part
        assert len(store) == 0

    def test_non_expired_entries_survive(self):
        store = ProviderMetadataStore(ttl=10.0)
        store.cache_from_response(_make_ir_response("call_live", {"sig": "fresh"}))

        ir_req = _make_ir_request(["call_live"])
        store.inject_into_request(ir_req)

        part = ir_req["messages"][0]["content"][0]
        assert part["provider_metadata"] == {"sig": "fresh"}


class TestMaxSizeEviction:
    def test_oldest_evicted_on_overflow(self):
        store = ProviderMetadataStore(max_size=3)

        for i in range(3):
            store.cache_from_response(_make_ir_response(f"call_{i}", {"i": i}))
        assert len(store) == 3

        # Adding a 4th entry should evict the oldest (call_0)
        store.cache_from_response(_make_ir_response("call_3", {"i": 3}))
        assert len(store) == 3

        ir_req = _make_ir_request(["call_0", "call_1", "call_2", "call_3"])
        store.inject_into_request(ir_req)

        parts = ir_req["messages"][0]["content"]
        assert "provider_metadata" not in parts[0]  # call_0 evicted
        assert parts[1]["provider_metadata"] == {"i": 1}
        assert parts[2]["provider_metadata"] == {"i": 2}
        assert parts[3]["provider_metadata"] == {"i": 3}

    def test_count_eviction_never_crosses_principals(self):
        root = ProviderMetadataStore(max_size=2)
        store_a = root.scoped(_scope("a", "window-a"))
        store_b = root.scoped(_scope("b", "window-b"))
        store_a.cache_from_response(_make_ir_response("a-1", {"owner": "a"}))
        store_a.cache_from_response(_make_ir_response("a-2", {"owner": "a"}))

        with pytest.raises(ProviderMetadataCapacityError, match="entry count"):
            store_b.cache_from_response(_make_ir_response("b-1", {"owner": "b"}))

        request_a = _make_ir_request(["a-1", "a-2"])
        store_a.inject_into_request(request_a)
        assert all(
            part["provider_metadata"] == {"owner": "a"}
            for part in request_a["messages"][0]["content"]
        )

    def test_principal_entry_limit_rejects_owner_but_not_other_principals(self):
        root = ProviderMetadataStore(
            max_size=10,
            max_entries_per_principal=2,
        )
        store_a = root.scoped(_scope("a", "window-a"))
        for index in range(2):
            store_a.cache_from_response(
                _make_ir_response(f"a-{index}", {"index": index})
            )

        with pytest.raises(ProviderMetadataCapacityError, match="principal entry"):
            store_a.cache_from_response(_make_ir_response("a-2", {"index": 2}))
        root.scoped(_scope("b", "window-b")).cache_from_response(
            _make_ir_response("b-0", {"owner": "b"})
        )

        assert len(root) == 3
        assert root._state.principal_entries == {"a": 2, "b": 1}

    def test_global_count_eviction_uses_current_principals_oldest_entry(self):
        root = ProviderMetadataStore(
            max_size=2,
            max_entries_per_principal=3,
        )
        store_a = root.scoped(_scope("a", "window-a"))
        store_b = root.scoped(_scope("b", "window-b"))
        store_a.cache_from_response(_make_ir_response("a-old", {"value": "old"}))
        store_b.cache_from_response(_make_ir_response("b-only", {"value": "b"}))

        store_a.cache_from_response(_make_ir_response("a-new", {"value": "new"}))

        request_a = _make_ir_request(["a-old", "a-new"])
        request_b = _make_ir_request(["b-only"])
        store_a.inject_into_request(request_a)
        store_b.inject_into_request(request_b)
        assert "provider_metadata" not in request_a["messages"][0]["content"][0]
        assert request_a["messages"][0]["content"][1]["provider_metadata"] == {
            "value": "new"
        }
        assert request_b["messages"][0]["content"][0]["provider_metadata"] == {
            "value": "b"
        }

    def test_replacement_at_principal_limit_does_not_double_count(self):
        root = ProviderMetadataStore(max_entries_per_principal=1)
        store = root.scoped(_scope("a", "window"))
        store.cache_from_response(_make_ir_response("call", {"version": 1}))

        store.cache_from_response(_make_ir_response("call", {"version": 2}))

        request = _make_ir_request(["call"])
        store.inject_into_request(request)
        assert request["messages"][0]["content"][0]["provider_metadata"] == {
            "version": 2
        }
        assert root._state.principal_entries == {"a": 1}

    def test_principal_entry_batch_rejection_is_atomic(self):
        root = ProviderMetadataStore(max_entries_per_principal=2)
        store = root.scoped(_scope("a", "window"))
        store.cache_from_response(_make_ir_response("existing", {"value": "old"}))
        response = _make_ir_response("new-1", {"value": 1})
        response["choices"][0]["message"]["content"].append(
            {
                "type": "tool_call",
                "tool_call_id": "new-2",
                "provider_metadata": {"value": 2},
            }
        )

        with pytest.raises(ProviderMetadataCapacityError, match="principal entry"):
            store.cache_from_response(response)

        assert len(root) == 1
        assert root._state.principal_entries == {"a": 1}

    def test_concurrent_entries_cannot_oversubscribe_principal_limit(self):
        root = ProviderMetadataStore(
            max_size=20,
            max_entries_per_principal=2,
        )
        store = root.scoped(_scope("a", "window"))
        barrier = threading.Barrier(8)

        def cache(index: int) -> bool:
            barrier.wait(timeout=2)
            try:
                store.cache_from_response(
                    _make_ir_response(f"call-{index}", {"index": index})
                )
            except ProviderMetadataCapacityError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            accepted = list(executor.map(cache, range(8)))

        assert sum(accepted) == 2
        assert root._state.principal_entries == {"a": 2}


class TestByteBudgets:
    def test_entry_budget_counts_canonical_utf8_bytes(self):
        metadata = {"signature": "你好"}
        exact_size = _canonical_size(metadata)
        store = ProviderMetadataStore(max_entry_bytes=exact_size)
        store.cache_from_response(_make_ir_response("exact", metadata))

        rejecting = ProviderMetadataStore(max_entry_bytes=exact_size - 1)
        with pytest.raises(ProviderMetadataCapacityError, match="entry exceeds"):
            rejecting.cache_from_response(_make_ir_response("too-big", metadata))
        assert len(rejecting) == 0

    def test_rejected_replacement_preserves_old_value_and_budget(self):
        old = {"signature": "old"}
        new = {"signature": "x" * 100}
        store = ProviderMetadataStore(max_entry_bytes=_canonical_size(old))
        store.cache_from_response(_make_ir_response("call", old))

        with pytest.raises(ProviderMetadataCapacityError):
            store.cache_from_response(_make_ir_response("call", new))

        request = _make_ir_request(["call"])
        store.inject_into_request(request)
        assert request["messages"][0]["content"][0]["provider_metadata"] == old

    def test_response_batch_rejection_is_atomic(self):
        metadata = {"signature": "same-size"}
        size = _canonical_size(metadata)
        store = ProviderMetadataStore(max_bytes_per_scope=size)
        response = _make_ir_response("call-1", metadata)
        content = response["choices"][0]["message"]["content"]
        content.append(
            {
                "type": "tool_call",
                "tool_call_id": "call-2",
                "provider_metadata": metadata,
            }
        )

        with pytest.raises(ProviderMetadataCapacityError, match="scope exceeds"):
            store.cache_from_response(response)
        assert len(store) == 0

    def test_scope_principal_and_global_budgets_are_independent(self):
        metadata = {"signature": "fixed"}
        size = _canonical_size(metadata)

        root = ProviderMetadataStore(
            max_bytes_per_scope=size,
            max_bytes_per_principal=size * 4,
            max_bytes_global=size * 8,
        )
        scope_store = root.scoped(_scope("p", "one"))
        scope_store.cache_from_response(_make_ir_response("one", metadata))
        with pytest.raises(ProviderMetadataCapacityError, match="scope exceeds"):
            scope_store.cache_from_response(_make_ir_response("two", metadata))

        principal_root = ProviderMetadataStore(
            max_bytes_per_scope=size * 4,
            max_bytes_per_principal=size * 2,
            max_bytes_global=size * 8,
        )
        for index in range(2):
            principal_root.scoped(_scope("p", str(index))).cache_from_response(
                _make_ir_response(str(index), metadata)
            )
        with pytest.raises(ProviderMetadataCapacityError, match="principal exceeds"):
            principal_root.scoped(_scope("p", "third")).cache_from_response(
                _make_ir_response("third", metadata)
            )

        global_root = ProviderMetadataStore(
            max_bytes_per_scope=size * 4,
            max_bytes_per_principal=size * 4,
            max_bytes_global=size * 2,
        )
        global_root.scoped(_scope("a", "one")).cache_from_response(
            _make_ir_response("a", metadata)
        )
        global_root.scoped(_scope("b", "one")).cache_from_response(
            _make_ir_response("b", metadata)
        )
        with pytest.raises(ProviderMetadataCapacityError, match="application exceeds"):
            global_root.scoped(_scope("c", "one")).cache_from_response(
                _make_ir_response("c", metadata)
            )

    def test_ttl_and_clear_release_all_accounting(self):
        metadata = {"signature": "fixed"}
        size = _canonical_size(metadata)
        root = ProviderMetadataStore(ttl=0.01, max_bytes_global=size)
        expired = root.scoped(_scope("a", "old"))
        expired.cache_from_response(_make_ir_response("old", metadata))
        time.sleep(0.02)
        root.scoped(_scope("b", "new")).cache_from_response(
            _make_ir_response("new", metadata)
        )

        root.clear_all()
        root.scoped(_scope("c", "after-clear")).cache_from_response(
            _make_ir_response("after-clear", metadata)
        )
        assert len(root) == 1

    def test_concurrent_global_overflow_allows_only_one_mutation(self):
        metadata = {"signature": "fixed"}
        size = _canonical_size(metadata)
        root = ProviderMetadataStore(max_bytes_global=size)
        barrier = threading.Barrier(2)

        def insert(principal: str) -> str:
            barrier.wait(timeout=2)
            try:
                root.scoped(_scope(principal, "window")).cache_from_response(
                    _make_ir_response(principal, metadata)
                )
            except ProviderMetadataCapacityError:
                return "rejected"
            return "stored"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(insert, ("a", "b")))

        assert sorted(results) == ["rejected", "stored"]
        assert len(root) == 1

    def test_cached_and_injected_values_are_detached(self):
        metadata = {"nested": {"value": "original"}}
        store = ProviderMetadataStore()
        store.cache_from_response(_make_ir_response("call", metadata))
        metadata["nested"]["value"] = "caller-mutated"

        first = _make_ir_request(["call"])
        store.inject_into_request(first)
        injected = first["messages"][0]["content"][0]["provider_metadata"]
        assert injected["nested"]["value"] == "original"
        injected["nested"]["value"] = "request-mutated"

        second = _make_ir_request(["call"])
        store.inject_into_request(second)
        assert second["messages"][0]["content"][0]["provider_metadata"] == {
            "nested": {"value": "original"}
        }


class TestStreamEventCaching:
    def test_cache_from_stream_event(self):
        store = ProviderMetadataStore()
        event = {
            "type": "tool_call_start",
            "tool_call_id": "call_stream",
            "provider_metadata": {"thought_signature": "stream_sig"},
        }
        store.cache_from_stream_event(event)
        assert len(store) == 1

        ir_req = _make_ir_request(["call_stream"])
        store.inject_into_request(ir_req)

        part = ir_req["messages"][0]["content"][0]
        assert part["provider_metadata"] == {"thought_signature": "stream_sig"}

    def test_ignores_non_tool_call_start(self):
        store = ProviderMetadataStore()
        store.cache_from_stream_event(
            {"type": "content_delta", "provider_metadata": {"x": 1}}
        )
        assert len(store) == 0

    def test_ignores_event_without_metadata(self):
        store = ProviderMetadataStore()
        store.cache_from_stream_event(
            {"type": "tool_call_start", "tool_call_id": "call_no_meta"}
        )
        assert len(store) == 0


class TestClear:
    def test_clear_empties_store(self):
        store = ProviderMetadataStore()
        store.cache_from_response(_make_ir_response("call_1", {"a": 1}))
        store.cache_from_response(_make_ir_response("call_2", {"b": 2}))
        assert len(store) == 2

        store.clear()
        assert len(store) == 0

    def test_scoped_clear_preserves_other_principal(self):
        root = ProviderMetadataStore()
        scope_a = GatewayStateScope("client-a", "provider", "model", "window", True)
        scope_b = GatewayStateScope("client-b", "provider", "model", "window", True)
        store_a = root.scoped(scope_a)
        store_b = root.scoped(scope_b)
        store_a.cache_from_response(_make_ir_response("call", {"owner": "a"}))
        store_b.cache_from_response(_make_ir_response("call", {"owner": "b"}))

        store_a.clear()

        assert len(store_a) == 0
        assert len(store_b) == 1
        request_b = _make_ir_request(["call"])
        store_b.inject_into_request(request_b)
        assert request_b["messages"][0]["content"][0]["provider_metadata"] == {
            "owner": "b"
        }


class TestEdgeCases:
    def test_no_injection_when_empty(self):
        store = ProviderMetadataStore()
        ir_req = _make_ir_request(["call_missing"])
        store.inject_into_request(ir_req)

        part = ir_req["messages"][0]["content"][0]
        assert "provider_metadata" not in part

    def test_inject_preserves_existing_metadata(self):
        store = ProviderMetadataStore()
        store.cache_from_response(_make_ir_response("call_x", {"sig": "from_store"}))

        ir_req = {
            "messages": [
                {
                    "content": [
                        {
                            "type": "tool_call",
                            "tool_call_id": "call_x",
                            "name": "fn",
                            "arguments": "{}",
                            "provider_metadata": {"sig": "already_present"},
                        }
                    ]
                }
            ]
        }
        store.inject_into_request(ir_req)

        # Store overwrites — this matches original behavior
        part = ir_req["messages"][0]["content"][0]
        assert part["provider_metadata"] == {"sig": "from_store"}

    def test_entries_kept_across_injections(self):
        """Entries are non-consumptive: same ID can be injected multiple times."""
        store = ProviderMetadataStore()
        store.cache_from_response(_make_ir_response("call_reuse", {"sig": "reused"}))

        for _ in range(3):
            ir_req = _make_ir_request(["call_reuse"])
            store.inject_into_request(ir_req)
            part = ir_req["messages"][0]["content"][0]
            assert part["provider_metadata"] == {"sig": "reused"}

        assert len(store) == 1

    def test_response_without_tool_calls_is_noop(self):
        store = ProviderMetadataStore()
        store.cache_from_response(
            {"choices": [{"message": {"content": [{"type": "text", "text": "hi"}]}}]}
        )
        assert len(store) == 0

    def test_request_without_messages_is_noop(self):
        store = ProviderMetadataStore()
        store.inject_into_request({})  # no crash
