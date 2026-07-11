"""Window isolation tests for deferred Codex tool discovery."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

import codex_rosetta.gateway.proxy as proxy_module
from codex_rosetta.gateway.proxy import (
    ToolSearchCapacityError,
    WindowToolSearchStore,
)
from codex_rosetta.gateway.state_scope import GatewayStateScope


def _namespace(name: str, tool_name: str, description: str) -> dict[str, Any]:
    return {
        "type": "namespace",
        "name": name,
        "description": f"Tools for {name}",
        "tools": [
            {
                "type": "function",
                "name": tool_name,
                "description": description,
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    }


def _function(name: str, description: str = "tool") -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": {}},
    }


def _search_body(query: str) -> dict[str, Any]:
    return {
        "input": [
            {
                "type": "tool_search_call",
                "id": "tsc_1",
                "call_id": "call_search_1",
                "execution": "client",
                "arguments": {"query": query, "limit": 8},
            },
            {
                "type": "tool_search_output",
                "call_id": "call_search_1",
                "tools": [],
            },
        ]
    }


def _result_tools(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["input"][1]["tools"]


def test_deferred_tool_search_is_isolated_between_codex_windows():
    store = WindowToolSearchStore()
    github = _namespace("github", "list_pull_requests", "List GitHub pull requests")
    gmail = _namespace("gmail", "search_mail", "Search Gmail messages")
    store.remember_deferred_tools("thread-a:0", [github])
    store.remember_deferred_tools("thread-b:0", [gmail])

    a_github = _search_body("github pull requests")
    a_gmail = _search_body("gmail messages")
    b_github = _search_body("github pull requests")
    b_gmail = _search_body("gmail messages")

    store.enrich_tool_search_outputs("thread-a:0", a_github)
    store.enrich_tool_search_outputs("thread-a:0", a_gmail)
    store.enrich_tool_search_outputs("thread-b:0", b_github)
    store.enrich_tool_search_outputs("thread-b:0", b_gmail)

    assert _result_tools(a_github)[0]["name"] == "github"
    assert _result_tools(a_gmail) == []
    assert _result_tools(b_github) == []
    assert _result_tools(b_gmail)[0]["name"] == "gmail"


def test_same_window_is_isolated_between_principals():
    root = WindowToolSearchStore()
    scope_a = GatewayStateScope("client-a", "provider", "model", "same-window", True)
    scope_b = GatewayStateScope("client-b", "provider", "model", "same-window", True)
    store_a = root.scoped(scope_a)
    store_b = root.scoped(scope_b)
    store_a.remember_deferred_tools(
        "same-window", [_namespace("github", "list_pull_requests", "List PRs")]
    )
    store_b.remember_deferred_tools(
        "same-window", [_namespace("gmail", "search_mail", "Search mail")]
    )

    a_body = _search_body("github pull requests")
    b_body = _search_body("github pull requests")
    store_a.enrich_tool_search_outputs("same-window", a_body)
    store_b.enrich_tool_search_outputs("same-window", b_body)

    assert _result_tools(a_body)[0]["name"] == "github"
    assert _result_tools(b_body) == []


def test_scoped_clear_preserves_other_principal():
    root = WindowToolSearchStore()
    scope_a = GatewayStateScope("client-a", "provider", "model", "same-window", True)
    scope_b = GatewayStateScope("client-b", "provider", "model", "same-window", True)
    store_a = root.scoped(scope_a)
    store_b = root.scoped(scope_b)
    store_a.remember_deferred_tools(
        "same-window", [_namespace("github", "list_pull_requests", "List PRs")]
    )
    store_b.remember_deferred_tools(
        "same-window", [_namespace("gmail", "search_mail", "Search mail")]
    )

    store_a.clear()

    body_a = _search_body("github pull requests")
    body_b = _search_body("gmail messages")
    store_a.enrich_tool_search_outputs("same-window", body_a)
    store_b.enrich_tool_search_outputs("same-window", body_b)
    assert _result_tools(body_a) == []
    assert _result_tools(body_b)[0]["name"] == "gmail"
    assert root._state.global_bytes == root._state.scope_bytes[scope_b]


def test_scope_tool_budget_rejects_before_partial_mutation_across_requests():
    store = WindowToolSearchStore(max_tools_per_scope=3)
    store.remember_deferred_tools("window", [_function("one"), _function("two")])
    before = copy.deepcopy(store._deferred_store)
    before_bytes = store._state.global_bytes

    with pytest.raises(ToolSearchCapacityError, match="scope tool limit is 3"):
        store.remember_deferred_tools("window", [_function("three"), _function("four")])

    assert store._deferred_store == before
    assert store._state.global_bytes == before_bytes


def test_same_name_replace_updates_cached_byte_accounting():
    store = WindowToolSearchStore(max_bytes_per_scope=4096)
    store.remember_deferred_tools("window", [_function("same", "short")])
    short_bytes = store._state.global_bytes

    store.remember_deferred_tools("window", [_function("same", "longer text")])

    assert store._state.global_bytes > short_bytes
    entry = next(iter(store._deferred_store.values()))
    assert entry.data["function:same"]["description"] == "longer text"
    accounting = next(iter(store._state.accounting.values()))
    assert accounting.byte_size == store._state.global_bytes


def test_unicode_budget_uses_canonical_utf8_bytes():
    tool = _function("unicode", "😀" * 20)
    probe = WindowToolSearchStore()
    probe.remember_deferred_tools("window", [tool])
    exact_bytes = probe._state.global_bytes
    assert exact_bytes > len(str(tool))

    store = WindowToolSearchStore(max_bytes_per_scope=exact_bytes - 1)
    with pytest.raises(ToolSearchCapacityError, match="scope byte limit"):
        store.remember_deferred_tools("window", [tool])

    assert store._deferred_store == {}
    assert store._state.global_bytes == 0


def test_global_budget_is_shared_across_scopes_without_evicting_existing_state():
    scope_a = GatewayStateScope("client", "provider", "model", "a", True)
    scope_b = GatewayStateScope("client", "provider", "model", "b", True)
    probe = WindowToolSearchStore()
    probe.scoped(scope_a).remember_deferred_tools("a", [_function("one")])
    one_scope_bytes = probe._state.global_bytes
    root = WindowToolSearchStore(max_bytes_global=one_scope_bytes * 2 - 1)
    store_a = root.scoped(scope_a)
    store_b = root.scoped(scope_b)
    store_a.remember_deferred_tools("a", [_function("one")])
    before = copy.deepcopy(root._deferred_store)

    with pytest.raises(ToolSearchCapacityError, match="global byte limit"):
        store_b.remember_deferred_tools("b", [_function("two")])

    assert root._deferred_store == before
    assert scope_a in root._deferred_store
    assert scope_b not in root._deferred_store


def test_concurrent_writers_cannot_oversubscribe_scope_tool_budget():
    store = WindowToolSearchStore(max_tools_per_scope=10)

    def _remember(index: int) -> bool:
        try:
            store.remember_deferred_tools("window", [_function(f"tool-{index}")])
        except ToolSearchCapacityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = list(executor.map(_remember, range(20)))

    assert sum(accepted) == 10
    entry = next(iter(store._deferred_store.values()))
    assert len(entry.data) == 10
    assert sum(store._state.scope_tools.values()) == 10


def test_ttl_and_scope_count_eviction_return_all_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    root = WindowToolSearchStore(ttl=10, max_size=1)
    root.remember_deferred_tools("old", [_function("old")])
    old_scope = next(iter(root._deferred_store))
    old_bytes = root._state.global_bytes
    root.remember_deferred_tools("new", [_function("new")])

    assert old_scope not in root._deferred_store
    assert len(root._deferred_store) == 1
    assert root._state.global_bytes == old_bytes

    entry = next(iter(root._deferred_store.values()))
    entry.created = 0
    monkeypatch.setattr(proxy_module.time, "monotonic", lambda: 11)
    body = _search_body("anything")
    root.enrich_tool_search_outputs("new", body)

    assert root._deferred_store == {}
    assert root._state.global_bytes == 0
    assert root._state.scope_bytes == {}
    assert root._state.scope_tools == {}


def test_prepare_request_rejects_combined_batches_atomically():
    store = WindowToolSearchStore(max_tools_per_scope=3)
    deferred = [_namespace("github", "list_prs", "List PRs")]
    body = {
        "input": [
            {
                "type": "tool_search_output",
                "call_id": "call-search",
                "tools": [_namespace("gmail", "search_mail", "Search mail")],
            }
        ]
    }

    with pytest.raises(ToolSearchCapacityError, match="scope tool limit is 3"):
        store.prepare_request("window", deferred, body)

    assert store._store == {}
    assert store._deferred_store == {}
    assert store._state.global_bytes == 0


def test_principal_scope_limit_counts_loaded_and_deferred_scope_once():
    scope = GatewayStateScope("client", "provider", "model", "window", True)
    root = WindowToolSearchStore(max_scopes_per_principal=1)
    store = root.scoped(scope)
    body = _search_body("github")
    body["input"][1]["tools"] = [_function("discovered")]

    store.prepare_request(
        "window",
        [_namespace("github", "list_prs", "List PRs")],
        body,
    )

    assert root._state.scope_refs[scope] == 2
    assert root._state.principal_scopes == {"client": 1}
    with pytest.raises(ToolSearchCapacityError, match="principal scope limit is 1"):
        root.scoped(
            GatewayStateScope("client", "provider", "model", "other", True)
        ).remember_deferred_tools("other", [_function("other")])
    assert root._state.principal_scopes == {"client": 1}


def test_principal_scope_limit_does_not_reserve_other_principals_capacity():
    root = WindowToolSearchStore(max_size=4, max_scopes_per_principal=1)
    scope_a = GatewayStateScope("client-a", "provider", "model", "a", True)
    scope_b = GatewayStateScope("client-b", "provider", "model", "b", True)
    root.scoped(scope_a).remember_deferred_tools("a", [_function("a")])

    with pytest.raises(ToolSearchCapacityError, match="principal scope limit is 1"):
        root.scoped(
            GatewayStateScope("client-a", "provider", "model", "a-2", True)
        ).remember_deferred_tools("a-2", [_function("a-2")])
    root.scoped(scope_b).remember_deferred_tools("b", [_function("b")])

    assert set(root._deferred_store) == {scope_a, scope_b}
    assert root._state.principal_scopes == {"client-a": 1, "client-b": 1}


def test_global_scope_eviction_uses_current_principals_oldest_scope_only():
    root = WindowToolSearchStore(max_size=2, max_scopes_per_principal=3)
    a_old = GatewayStateScope("client-a", "provider", "model", "a-old", True)
    b_only = GatewayStateScope("client-b", "provider", "model", "b", True)
    a_new = GatewayStateScope("client-a", "provider", "model", "a-new", True)
    root.scoped(a_old).remember_deferred_tools("a-old", [_function("a-old")])
    root.scoped(b_only).remember_deferred_tools("b", [_function("b")])

    root.scoped(a_new).remember_deferred_tools("a-new", [_function("a-new")])

    assert set(root._deferred_store) == {b_only, a_new}
    assert root._state.principal_scopes == {"client-a": 1, "client-b": 1}


def test_global_scope_limit_never_evicts_another_principal():
    root = WindowToolSearchStore(max_size=1, max_scopes_per_principal=2)
    scope_a = GatewayStateScope("client-a", "provider", "model", "a", True)
    scope_b = GatewayStateScope("client-b", "provider", "model", "b", True)
    root.scoped(scope_a).remember_deferred_tools("a", [_function("a")])

    with pytest.raises(ToolSearchCapacityError, match="global scope limit is 1"):
        root.scoped(scope_b).remember_deferred_tools("b", [_function("b")])

    assert set(root._deferred_store) == {scope_a}
    assert root._state.principal_scopes == {"client-a": 1}


def test_concurrent_new_scopes_cannot_oversubscribe_principal_limit():
    root = WindowToolSearchStore(max_size=20, max_scopes_per_principal=2)
    barrier = threading.Barrier(8)

    def remember(index: int) -> bool:
        scope = GatewayStateScope(
            "client", "provider", "model", f"window-{index}", True
        )
        barrier.wait(timeout=2)
        try:
            root.scoped(scope).remember_deferred_tools(
                f"window-{index}", [_function(f"tool-{index}")]
            )
        except ToolSearchCapacityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = list(executor.map(remember, range(8)))

    assert sum(accepted) == 2
    assert root._state.principal_scopes == {"client": 2}


def test_clear_returns_unique_scope_accounting_for_both_maps():
    scope = GatewayStateScope("client", "provider", "model", "window", True)
    root = WindowToolSearchStore(max_scopes_per_principal=1)
    store = root.scoped(scope)
    body = _search_body("loaded")
    body["input"][1]["tools"] = [_function("loaded")]
    store.prepare_request("window", [_function("deferred")], body)
    assert root._state.scope_refs == {scope: 2}

    store.clear()

    assert root._store == {}
    assert root._deferred_store == {}
    assert root._state.scope_refs == {}
    assert root._state.principal_scopes == {}
    assert root._state.global_bytes == 0
